"""Freemium quota enforcement (server-side)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import config
from app.models import SavedRoute, UsageDaily, User

UsageKind = Literal["routes", "chats"]


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def subject_key(user: Optional[User], anon_key: Optional[str]) -> str:
    if user:
        return f"user:{user.id}"
    if anon_key:
        return f"anon:{anon_key}"
    raise ValueError("Need user or anon_key")


def plan_limits(user: Optional[User]) -> dict:
    """Return entitlement dict for a user (or anonymous)."""
    if user and user.plan == "pro":
        return {
            "plan": "pro",
            "routes_per_day": config.PRO_ROUTES_PER_DAY,
            "chats_per_day": config.PRO_CHATS_PER_DAY,
            "saved_routes_max": config.PRO_SAVED_ROUTES,
            "forecasts_enabled": True,
            "live_buoys": True,
        }
    if user:
        return {
            "plan": "free",
            "routes_per_day": config.FREE_ROUTES_PER_DAY,
            "chats_per_day": config.FREE_CHATS_PER_DAY,
            "saved_routes_max": config.FREE_SAVED_ROUTES,
            "forecasts_enabled": False,
            "live_buoys": True,
        }
    return {
        "plan": "anonymous",
        "routes_per_day": config.ANON_ROUTES_PER_DAY,
        "chats_per_day": 0,
        "saved_routes_max": 0,
        "forecasts_enabled": False,
        "live_buoys": True,
    }


def _get_or_create_usage(db: Session, *, sk: str, user: Optional[User], day: str) -> UsageDaily:
    row = db.query(UsageDaily).filter(UsageDaily.subject_key == sk, UsageDaily.day == day).first()
    if row:
        return row
    row = UsageDaily(
        subject_key=sk,
        user_id=user.id if user else None,
        day=day,
        routes=0,
        chats=0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def usage_snapshot(
    db: Session, *, user: Optional[User], anon_key: Optional[str] = None
) -> dict:
    limits = plan_limits(user)
    day = utc_day()
    routes_used = 0
    chats_used = 0
    try:
        sk = subject_key(user, anon_key)
        row = _get_or_create_usage(db, sk=sk, user=user, day=day)
        routes_used = row.routes
        chats_used = row.chats
    except ValueError:
        pass
    saved_count = 0
    if user:
        saved_count = db.query(SavedRoute).filter(SavedRoute.user_id == user.id).count()
    return {
        **limits,
        "day": day,
        "routes_used": routes_used,
        "routes_remaining": max(0, limits["routes_per_day"] - routes_used),
        "chats_used": chats_used,
        "chats_remaining": max(0, limits["chats_per_day"] - chats_used),
        "saved_routes_count": saved_count,
        "saved_routes_remaining": max(0, limits["saved_routes_max"] - saved_count),
        "stripe_configured": config.stripe_configured(),
        "paypal_configured": config.paypal_configured(),
        "billing_provider": config.preferred_billing_provider(),
    }


def consume(
    db: Session,
    *,
    user: Optional[User],
    anon_key: Optional[str],
    kind: UsageKind,
) -> dict:
    """Increment usage; raise 429/402 with upgrade messaging when over quota."""
    limits = plan_limits(user)
    day = utc_day()

    if kind == "chats" and limits["chats_per_day"] <= 0:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "upgrade_required",
                "message": "AI chat requires a free account (1/day) or Pro. Sign up or upgrade.",
                "plan": limits["plan"],
            },
        )

    try:
        sk = subject_key(user, anon_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Missing client identity for quota.") from exc

    row = _get_or_create_usage(db, sk=sk, user=user, day=day)
    used = row.routes if kind == "routes" else row.chats
    cap = limits["routes_per_day"] if kind == "routes" else limits["chats_per_day"]

    if used >= cap:
        plan = limits["plan"]
        if plan == "pro":
            msg = f"Daily {kind} limit reached ({cap}/day). Try again tomorrow (UTC)."
            code = 429
        else:
            msg = (
                f"Free-tier {kind} quota reached ({cap}/day). "
                "Upgrade to Pro for higher limits."
            )
            code = 402
        raise HTTPException(
            status_code=code,
            detail={
                "code": "quota_exceeded",
                "kind": kind,
                "limit": cap,
                "used": used,
                "plan": plan,
                "message": msg,
                "upgrade": True,
            },
        )

    if kind == "routes":
        row.routes += 1
    else:
        row.chats += 1
    db.commit()
    return usage_snapshot(db, user=user, anon_key=anon_key)


def assert_can_save(db: Session, user: User) -> None:
    limits = plan_limits(user)
    count = db.query(SavedRoute).filter(SavedRoute.user_id == user.id).count()
    if count >= limits["saved_routes_max"]:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "quota_exceeded",
                "kind": "saved_routes",
                "limit": limits["saved_routes_max"],
                "used": count,
                "plan": limits["plan"],
                "message": (
                    f"Saved-route limit reached ({limits['saved_routes_max']}). "
                    "Upgrade to Pro for more favorites."
                ),
                "upgrade": True,
            },
        )
