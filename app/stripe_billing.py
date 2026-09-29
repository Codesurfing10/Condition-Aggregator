"""Stripe Checkout + webhook entitlement flips (test-mode friendly)."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import config
from app.models import User

try:
    import stripe
except ImportError:  # pragma: no cover
    stripe = None


def _ensure_stripe():
    if stripe is None:
        raise HTTPException(
            status_code=503,
            detail="Stripe SDK not installed. pip install stripe.",
        )
    if not config.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stripe_not_configured",
                "message": (
                    "Stripe is not configured. Set STRIPE_SECRET_KEY and "
                    "STRIPE_PRICE_ID_PRO (test mode) in the environment."
                ),
            },
        )
    stripe.api_key = config.STRIPE_SECRET_KEY


def create_checkout_session(db: Session, user: User) -> dict:
    _ensure_stripe()
    if not config.STRIPE_PRICE_ID_PRO:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stripe_not_configured",
                "message": "Set STRIPE_PRICE_ID_PRO to your Stripe test Price ID.",
            },
        )

    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email, metadata={"user_id": str(user.id)})
        user.stripe_customer_id = customer["id"]
        db.commit()

    success = f"{config.FRONTEND_ORIGIN}/?billing=success"
    cancel = f"{config.FRONTEND_ORIGIN}/?billing=cancel"

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=user.stripe_customer_id,
        line_items=[{"price": config.STRIPE_PRICE_ID_PRO, "quantity": 1}],
        success_url=success,
        cancel_url=cancel,
        client_reference_id=str(user.id),
        metadata={"user_id": str(user.id)},
        subscription_data={"metadata": {"user_id": str(user.id)}},
    )
    return {"checkout_url": session.url, "session_id": session.id}


def create_portal_session(db: Session, user: User) -> dict:
    _ensure_stripe()
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer on this account. Subscribe first, or cancel note: contact support.",
        )
    portal = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{config.FRONTEND_ORIGIN}/",
    )
    return {"portal_url": portal.url}


def set_plan(
    db: Session,
    user: User,
    *,
    plan: str,
    subscription_id: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> User:
    user.plan = plan
    user.forecasts_enabled = plan == "pro"
    if subscription_id is not None:
        user.stripe_subscription_id = subscription_id if plan == "pro" else None
    if customer_id:
        user.stripe_customer_id = customer_id
    if plan != "pro":
        user.stripe_subscription_id = None
        user.forecasts_enabled = False
    db.commit()
    db.refresh(user)
    return user


def _user_by_meta(db: Session, obj: Any) -> Optional[User]:
    meta = getattr(obj, "metadata", None) or {}
    if isinstance(obj, dict):
        meta = obj.get("metadata") or {}
    uid = None
    if isinstance(meta, dict):
        uid = meta.get("user_id")
    if not uid and isinstance(obj, dict):
        uid = obj.get("client_reference_id")
    elif not uid:
        uid = getattr(obj, "client_reference_id", None)
    if uid:
        try:
            return db.get(User, int(uid))
        except (TypeError, ValueError):
            pass
    cust = None
    if isinstance(obj, dict):
        cust = obj.get("customer")
    else:
        cust = getattr(obj, "customer", None)
    if cust:
        return db.query(User).filter(User.stripe_customer_id == cust).first()
    return None


def apply_checkout_completed(db: Session, session_obj: Any) -> Optional[User]:
    user = _user_by_meta(db, session_obj)
    if not user:
        return None
    sub_id = None
    cust = None
    if isinstance(session_obj, dict):
        sub_id = session_obj.get("subscription")
        cust = session_obj.get("customer")
    else:
        sub_id = getattr(session_obj, "subscription", None)
        cust = getattr(session_obj, "customer", None)
    return set_plan(
        db, user, plan="pro", subscription_id=str(sub_id) if sub_id else None, customer_id=cust
    )


def apply_subscription_updated(db: Session, sub: Any) -> Optional[User]:
    status = sub.get("status") if isinstance(sub, dict) else getattr(sub, "status", None)
    cust = sub.get("customer") if isinstance(sub, dict) else getattr(sub, "customer", None)
    sub_id = sub.get("id") if isinstance(sub, dict) else getattr(sub, "id", None)
    user = _user_by_meta(db, sub)
    if not user and cust:
        user = db.query(User).filter(User.stripe_customer_id == cust).first()
    if not user:
        return None
    active = status in ("active", "trialing")
    return set_plan(
        db,
        user,
        plan="pro" if active else "free",
        subscription_id=str(sub_id) if active and sub_id else None,
        customer_id=cust,
    )


def apply_subscription_deleted(db: Session, sub: Any) -> Optional[User]:
    cust = sub.get("customer") if isinstance(sub, dict) else getattr(sub, "customer", None)
    user = _user_by_meta(db, sub)
    if not user and cust:
        user = db.query(User).filter(User.stripe_customer_id == cust).first()
    if not user:
        return None
    return set_plan(db, user, plan="free", subscription_id=None, customer_id=cust)


def construct_event(payload: bytes, sig_header: str):
    _ensure_stripe()
    if not config.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stripe_webhook_not_configured",
                "message": "Set STRIPE_WEBHOOK_SECRET (from `stripe listen`).",
            },
        )
    try:
        return stripe.Webhook.construct_event(
            payload, sig_header, config.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Webhook signature error: {exc}") from exc
