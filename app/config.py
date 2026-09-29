"""Central config from environment. Safe defaults for local freemium MVP."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Load .env before reading os.environ (never log secret values)
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:  # pragma: no cover
    pass


def _parse_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


def _bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# ── App ───────────────────────────────────────────────────────────────────────
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://127.0.0.1:5500").rstrip("/")
CORS_ORIGINS = _parse_origins(
    os.environ.get(
        "CORS_ORIGINS",
        f"{FRONTEND_ORIGIN},http://localhost:5500,http://127.0.0.1:5500,"
        f"http://localhost:8000,http://127.0.0.1:8000,https://codesurfing10.github.io",
    )
)
API_KEY = os.environ.get("API_KEY", "").strip()
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Session signing — generate ephemeral secret if unset (dev only; set in prod)
SESSION_SECRET = os.environ.get("SESSION_SECRET", "").strip() or secrets.token_hex(32)
SESSION_COOKIE = os.environ.get("SESSION_COOKIE_NAME", "ca_session")
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "14"))
COOKIE_SECURE = _bool("COOKIE_SECURE", False)
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "lax")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}"
)

# ── Freemium quotas (per calendar day UTC, unless noted) ──────────────────────
FREE_ROUTES_PER_DAY = int(os.environ.get("FREE_ROUTES_PER_DAY", "3"))
FREE_CHATS_PER_DAY = int(os.environ.get("FREE_CHATS_PER_DAY", "1"))
FREE_SAVED_ROUTES = int(os.environ.get("FREE_SAVED_ROUTES", "3"))

PRO_ROUTES_PER_DAY = int(os.environ.get("PRO_ROUTES_PER_DAY", "500"))  # practical unlimited
PRO_CHATS_PER_DAY = int(os.environ.get("PRO_CHATS_PER_DAY", "100"))
PRO_SAVED_ROUTES = int(os.environ.get("PRO_SAVED_ROUTES", "100"))

# Anonymous (no account): routes only, same as free routes; no chat/saves
ANON_ROUTES_PER_DAY = int(os.environ.get("ANON_ROUTES_PER_DAY", str(FREE_ROUTES_PER_DAY)))

# ── Stripe (test mode). Kept for later; PayPal is primary when configured. ────
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_PRICE_ID_PRO = os.environ.get("STRIPE_PRICE_ID_PRO", "").strip()
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "").strip()

# ── PayPal (sandbox / live). Prefer PayPal when client id+secret are set. ─────
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_MODE = (os.environ.get("PAYPAL_MODE", "sandbox") or "sandbox").strip().lower()
PAYPAL_PLAN_ID = os.environ.get("PAYPAL_PLAN_ID", "").strip()
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "").strip()
PAYPAL_PRODUCT_NAME = os.environ.get(
    "PAYPAL_PRODUCT_NAME", "Condition Aggregator Pro"
).strip()
PAYPAL_PLAN_PRICE_USD = os.environ.get("PAYPAL_PLAN_PRICE_USD", "12.00").strip()


def stripe_configured() -> bool:
    return bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID_PRO)


def paypal_configured() -> bool:
    return bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET)


def preferred_billing_provider() -> str:
    """PayPal first when configured; else Stripe; else none."""
    if paypal_configured():
        return "paypal"
    if stripe_configured():
        return "stripe"
    return "none"


def paypal_api_base() -> str:
    if PAYPAL_MODE == "live":
        return "https://api-m.paypal.com"
    return "https://api-m.sandbox.paypal.com"
