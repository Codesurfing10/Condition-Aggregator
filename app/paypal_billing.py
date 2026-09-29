"""PayPal Subscriptions REST v2 (sandbox-friendly) + entitlement flips."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Optional

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import config
from app.models import User

log = logging.getLogger("paypal_billing")

# In-process token cache (never log token values)
_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}

PRO_PRICE = config.PAYPAL_PLAN_PRICE_USD or "12.00"


def _ensure_paypal() -> None:
    if not config.paypal_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "paypal_not_configured",
                "message": (
                    "PayPal is not configured. Set PAYPAL_CLIENT_ID and "
                    "PAYPAL_CLIENT_SECRET (sandbox) in .env — see README."
                ),
            },
        )


def api_base() -> str:
    return config.paypal_api_base()


def obtain_access_token(*, force: bool = False) -> str:
    """Client-credentials OAuth. Raises HTTPException on failure. Never logs the token."""
    _ensure_paypal()
    now = time.time()
    if (
        not force
        and _token_cache.get("access_token")
        and float(_token_cache.get("expires_at") or 0) > now + 60
    ):
        return str(_token_cache["access_token"])

    url = f"{api_base()}/v1/oauth2/token"
    try:
        resp = requests.post(
            url,
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            data={"grant_type": "client_credentials"},
            auth=(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET),
            timeout=30,
        )
    except requests.RequestException as exc:
        log.error("PayPal OAuth network error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail={"code": "paypal_oauth_failed", "message": "PayPal OAuth network error."},
        ) from exc

    if resp.status_code != 200:
        log.error("PayPal OAuth failed status=%s", resp.status_code)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "paypal_oauth_failed",
                "message": f"PayPal OAuth failed (HTTP {resp.status_code}). Check sandbox credentials.",
            },
        )

    data = resp.json()
    token = data.get("access_token")
    if not token:
        log.error("PayPal OAuth response missing access_token")
        raise HTTPException(
            status_code=502,
            detail={"code": "paypal_oauth_failed", "message": "PayPal OAuth response incomplete."},
        )
    expires_in = int(data.get("expires_in") or 32400)
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + expires_in
    return str(token)


def oauth_ok() -> bool:
    """Return True/False for health/sanity without raising. Never exposes token."""
    if not config.paypal_configured():
        return False
    try:
        obtain_access_token()
        return True
    except Exception:
        return False


def _auth_headers() -> dict[str, str]:
    token = obtain_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _paypal_request(
    method: str,
    path: str,
    *,
    json_body: Optional[dict] = None,
    prefer: Optional[str] = None,
) -> dict:
    url = f"{api_base()}{path}"
    headers = _auth_headers()
    if prefer:
        headers["Prefer"] = prefer
    try:
        resp = requests.request(
            method, url, headers=headers, json=json_body, timeout=45
        )
    except requests.RequestException as exc:
        log.error("PayPal API network error %s %s: %s", method, path, type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail={"code": "paypal_api_error", "message": "PayPal API network error."},
        ) from exc

    if resp.status_code in (401, 403):
        # Retry once with fresh token
        obtain_access_token(force=True)
        headers = _auth_headers()
        if prefer:
            headers["Prefer"] = prefer
        resp = requests.request(
            method, url, headers=headers, json=json_body, timeout=45
        )

    if resp.status_code >= 400:
        # Do not echo PayPal body (may contain sensitive bits); keep status only
        log.error("PayPal API error %s %s status=%s", method, path, resp.status_code)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "paypal_api_error",
                "message": f"PayPal API error (HTTP {resp.status_code}) on {method} {path}.",
            },
        )

    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}


def persist_plan_id(plan_id: str) -> None:
    """Write PAYPAL_PLAN_ID back into .env and process env (no secret logging)."""
    plan_id = (plan_id or "").strip()
    if not plan_id:
        return
    os.environ["PAYPAL_PLAN_ID"] = plan_id
    config.PAYPAL_PLAN_ID = plan_id

    env_path = config.ROOT / ".env"
    if not env_path.is_file():
        log.warning("No .env file to persist PAYPAL_PLAN_ID")
        return

    text = env_path.read_text(encoding="utf-8")
    line = f"PAYPAL_PLAN_ID={plan_id}"
    if re.search(r"(?m)^PAYPAL_PLAN_ID=", text):
        text = re.sub(r"(?m)^PAYPAL_PLAN_ID=.*$", line, text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    env_path.write_text(text, encoding="utf-8")
    log.info("Persisted PAYPAL_PLAN_ID to .env (id length=%s)", len(plan_id))


def create_product_and_plan() -> str:
    """Create Catalog product + monthly Pro plan (~$12 USD). Returns plan id."""
    _ensure_paypal()
    product = _paypal_request(
        "POST",
        "/v1/catalogs/products",
        json_body={
            "name": config.PAYPAL_PRODUCT_NAME or "Condition Aggregator Pro",
            "description": "Pro entitlements: higher route/chat quotas and forecasts.",
            "type": "SERVICE",
            "category": "SOFTWARE",
        },
        prefer="return=representation",
    )
    product_id = product.get("id")
    if not product_id:
        raise HTTPException(
            status_code=502,
            detail={"code": "paypal_plan_create_failed", "message": "PayPal product create failed."},
        )

    plan = _paypal_request(
        "POST",
        "/v1/billing/plans",
        json_body={
            "product_id": product_id,
            "name": "Condition Aggregator Pro Monthly",
            "description": f"Monthly Pro subscription (${PRO_PRICE} USD).",
            "status": "ACTIVE",
            "billing_cycles": [
                {
                    "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,
                    "pricing_scheme": {
                        "fixed_price": {"value": PRO_PRICE, "currency_code": "USD"}
                    },
                }
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee_failure_action": "CONTINUE",
                "payment_failure_threshold": 3,
            },
        },
        prefer="return=representation",
    )
    plan_id = plan.get("id")
    if not plan_id:
        raise HTTPException(
            status_code=502,
            detail={"code": "paypal_plan_create_failed", "message": "PayPal plan create failed."},
        )
    persist_plan_id(plan_id)
    log.info("Created PayPal plan (length=%s)", len(plan_id))
    return str(plan_id)


def ensure_plan_id() -> str:
    """Return configured plan id, creating product+plan via API when empty."""
    _ensure_paypal()
    if config.PAYPAL_PLAN_ID:
        return config.PAYPAL_PLAN_ID
    return create_product_and_plan()


def set_plan(
    db: Session,
    user: User,
    *,
    plan: str,
    subscription_id: Optional[str] = None,
) -> User:
    user.plan = plan
    user.forecasts_enabled = plan == "pro"
    if plan == "pro":
        if subscription_id:
            user.paypal_subscription_id = subscription_id
    else:
        user.paypal_subscription_id = None
        user.forecasts_enabled = False
    db.commit()
    db.refresh(user)
    return user


def _user_from_custom_id(db: Session, custom_id: Optional[str]) -> Optional[User]:
    if not custom_id:
        return None
    raw = str(custom_id).strip()
    if raw.startswith("user:"):
        raw = raw.split(":", 1)[1]
    try:
        return db.get(User, int(raw))
    except (TypeError, ValueError):
        return None


def create_subscription(db: Session, user: User) -> dict:
    """Create a PayPal subscription; return approval_url + subscription_id."""
    plan_id = ensure_plan_id()
    return_url = f"{config.FRONTEND_ORIGIN}/?billing=success&provider=paypal"
    cancel_url = f"{config.FRONTEND_ORIGIN}/?billing=cancel&provider=paypal"

    body = {
        "plan_id": plan_id,
        "custom_id": f"user:{user.id}",
        "subscriber": {"email_address": user.email},
        "application_context": {
            "brand_name": "Condition Aggregator",
            "locale": "en-US",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    data = _paypal_request(
        "POST",
        "/v1/billing/subscriptions",
        json_body=body,
        prefer="return=representation",
    )
    sub_id = data.get("id")
    approval_url = None
    for link in data.get("links") or []:
        if link.get("rel") == "approve":
            approval_url = link.get("href")
            break
    if not sub_id or not approval_url:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "paypal_subscription_failed",
                "message": "PayPal did not return an approval URL.",
            },
        )

    # Stash pending subscription id so capture/webhook can find the user
    user.paypal_subscription_id = str(sub_id)
    db.commit()

    return {
        "provider": "paypal",
        "subscription_id": str(sub_id),
        "approval_url": approval_url,
        "status": data.get("status"),
        "plan_id": plan_id,
    }


def get_subscription(subscription_id: str) -> dict:
    return _paypal_request("GET", f"/v1/billing/subscriptions/{subscription_id}")


def apply_subscription_status(
    db: Session,
    *,
    subscription_id: str,
    status: Optional[str] = None,
    custom_id: Optional[str] = None,
) -> Optional[User]:
    """Flip entitlements from PayPal subscription status."""
    status_norm = (status or "").upper()
    if not status_norm:
        remote = get_subscription(subscription_id)
        status_norm = str(remote.get("status") or "").upper()
        custom_id = custom_id or remote.get("custom_id")

    user = _user_from_custom_id(db, custom_id)
    if not user:
        user = (
            db.query(User)
            .filter(User.paypal_subscription_id == subscription_id)
            .first()
        )
    if not user:
        log.warning("No user for PayPal subscription (id length=%s)", len(subscription_id or ""))
        return None

    # ACTIVE grants Pro; cancelled/suspended/expired revoke. APPROVED is transitional.
    if status_norm == "ACTIVE":
        return set_plan(db, user, plan="pro", subscription_id=subscription_id)
    if status_norm in ("CANCELLED", "SUSPENDED", "EXPIRED"):
        return set_plan(db, user, plan="free", subscription_id=None)
    # Keep pending id but do not upgrade yet
    user.paypal_subscription_id = subscription_id
    db.commit()
    db.refresh(user)
    return user


def capture_subscription(db: Session, user: User, subscription_id: str) -> dict:
    """After buyer approval: fetch subscription; mark Pro when ACTIVE."""
    subscription_id = (subscription_id or "").strip()
    if not subscription_id:
        raise HTTPException(status_code=400, detail="subscription_id required")

    remote = get_subscription(subscription_id)
    status = str(remote.get("status") or "").upper()
    custom_id = remote.get("custom_id")

    # Ensure this subscription belongs to the signed-in user when custom_id present
    owner = _user_from_custom_id(db, custom_id)
    if owner and owner.id != user.id:
        raise HTTPException(status_code=403, detail="Subscription does not belong to this account.")

    updated = apply_subscription_status(
        db,
        subscription_id=subscription_id,
        status=status,
        custom_id=custom_id or f"user:{user.id}",
    )
    if not updated:
        # Bind to current user if PayPal had no custom_id match
        if status == "ACTIVE":
            updated = set_plan(db, user, plan="pro", subscription_id=subscription_id)
        else:
            user.paypal_subscription_id = subscription_id
            db.commit()
            db.refresh(user)
            updated = user

    return {
        "provider": "paypal",
        "subscription_id": subscription_id,
        "status": status,
        "plan": updated.plan,
        "forecasts_enabled": updated.forecasts_enabled,
    }


def handle_webhook_event(db: Session, event: dict) -> dict:
    """Process PayPal webhook JSON (subscription lifecycle)."""
    etype = str(event.get("event_type") or "")
    resource = event.get("resource") or {}
    sub_id = resource.get("id") or resource.get("billing_agreement_id")
    status = resource.get("status")
    custom_id = resource.get("custom_id")

    if not sub_id:
        return {"handled": False, "reason": "no_subscription_id"}

    if etype in (
        "BILLING.SUBSCRIPTION.ACTIVATED",
        "BILLING.SUBSCRIPTION.UPDATED",
        "BILLING.SUBSCRIPTION.RE-ACTIVATED",
    ):
        apply_subscription_status(
            db, subscription_id=str(sub_id), status=status or "ACTIVE", custom_id=custom_id
        )
        return {"handled": True, "event_type": etype}
    if etype in (
        "BILLING.SUBSCRIPTION.CANCELLED",
        "BILLING.SUBSCRIPTION.SUSPENDED",
        "BILLING.SUBSCRIPTION.EXPIRED",
    ):
        apply_subscription_status(
            db,
            subscription_id=str(sub_id),
            status=status or etype.rsplit(".", 1)[-1],
            custom_id=custom_id,
        )
        return {"handled": True, "event_type": etype}

    return {"handled": False, "event_type": etype}


def verify_webhook_signature(
    *,
    transmission_id: str,
    timestamp: str,
    transmission_sig: str,
    cert_url: str,
    auth_algo: str,
    webhook_event: dict,
) -> bool:
    """Verify via PayPal API when PAYPAL_WEBHOOK_ID is set."""
    if not config.PAYPAL_WEBHOOK_ID:
        return False
    body = {
        "transmission_id": transmission_id,
        "transmission_time": timestamp,
        "cert_url": cert_url,
        "auth_algo": auth_algo,
        "transmission_sig": transmission_sig,
        "webhook_id": config.PAYPAL_WEBHOOK_ID,
        "webhook_event": webhook_event,
    }
    try:
        data = _paypal_request(
            "POST", "/v1/notifications/verify-webhook-signature", json_body=body
        )
    except HTTPException:
        return False
    return str(data.get("verification_status") or "").upper() == "SUCCESS"
