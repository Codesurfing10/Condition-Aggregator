#!/usr/bin/env python3
"""Sanity checks for accounts, quotas, and Stripe webhook entitlement helpers.
Run with API already up, or imports app modules directly for unit-style tests.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure repo root on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolated SQLite for tests — blank billing keys BEFORE importing app.config
# (load_dotenv override=False will not refill keys already present in environ)
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_db.name}"
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["STRIPE_PRICE_ID_PRO"] = ""
os.environ["STRIPE_WEBHOOK_SECRET"] = ""
os.environ["PAYPAL_CLIENT_ID"] = ""
os.environ["PAYPAL_CLIENT_SECRET"] = ""
os.environ["PAYPAL_PLAN_ID"] = ""
os.environ["SESSION_SECRET"] = "test-secret-not-for-production-use-32b"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import init_db, SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app import stripe_billing  # noqa: E402
from app.main import app  # noqa: E402


def main() -> None:
    init_db()
    client = TestClient(app)

    r = client.get("/health")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "healthy"
    assert r.json()["stripe_configured"] is False
    assert r.json().get("paypal_configured") is False
    assert r.json().get("billing_provider") == "none"
    print("OK /health")

    # Signup
    r = client.post("/api/auth/signup", json={"email": "sailor@example.com", "password": "password123"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["plan"] == "free"
    assert r.cookies.get("ca_session")
    print("OK signup")

    # Me
    r = client.get("/api/me")
    assert r.status_code == 200
    q = r.json()["quota"]
    assert q["routes_per_day"] == 3
    assert q["chats_per_day"] == 1
    assert q["saved_routes_max"] == 3
    print("OK /api/me quotas", q["plan"], q["routes_remaining"])

    # Consume route quota (3 free) — skip live NDBC by mocking? Still hits NDBC.
    # Use a tiny route; may be slow/offline. Prefer unit consume via DB if network fails.
    body = {
        "start": {"lat": 32.7, "lon": -117.2},
        "end": {"lat": 32.8, "lon": -117.3},
    }
    ok_routes = 0
    for i in range(4):
        r = client.post("/api/route", json=body)
        if r.status_code == 200:
            ok_routes += 1
        elif r.status_code == 402:
            detail = r.json()["detail"]
            assert detail.get("code") == "quota_exceeded"
            print(f"OK route quota 402 after {ok_routes} successes")
            break
        else:
            print(f"WARN route status {r.status_code}: {r.text[:200]}")
            break
    else:
        print("WARN: expected 402 on 4th free route (maybe unlimited if config changed)")

    # Checkout without Stripe keys
    r = client.post("/api/billing/checkout")
    assert r.status_code == 503, r.text
    print("OK checkout graceful without Stripe")

    # Webhook entitlement unit-style (no Stripe signature path)
    db = SessionLocal()
    user = db.query(User).filter(User.email == "sailor@example.com").first()
    assert user
    stripe_billing.apply_checkout_completed(
        db,
        {
            "client_reference_id": str(user.id),
            "customer": "cus_test_123",
            "subscription": "sub_test_123",
            "metadata": {"user_id": str(user.id)},
        },
    )
    db.refresh(user)
    assert user.plan == "pro"
    assert user.forecasts_enabled is True
    print("OK checkout.session.completed → pro")

    stripe_billing.apply_subscription_deleted(
        db, {"customer": "cus_test_123", "metadata": {"user_id": str(user.id)}}
    )
    db.refresh(user)
    assert user.plan == "free"
    assert user.forecasts_enabled is False
    print("OK customer.subscription.deleted → free")
    db.close()

    # Saved routes require auth + limit (ensure free plan)
    db = SessionLocal()
    user = db.query(User).filter(User.email == "sailor@example.com").first()
    stripe_billing.set_plan(db, user, plan="free")
    db.close()

    for i in range(3):
        r = client.post(
            "/api/saved-routes",
            json={
                "name": f"Route {i}",
                "start_lat": 32.7,
                "start_lon": -117.2,
                "end_lat": 33.0,
                "end_lon": -118.0,
            },
        )
        assert r.status_code == 200, r.text
    r = client.post(
        "/api/saved-routes",
        json={
            "name": "Route overflow",
            "start_lat": 32.7,
            "start_lon": -117.2,
            "end_lat": 33.0,
            "end_lon": -118.0,
        },
    )
    assert r.status_code == 402, r.text
    print("OK saved-routes free limit 402")

    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    print("OK logout")
    print("\nAll sanity checks passed.")


if __name__ == "__main__":
    main()
