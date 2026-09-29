"""Condition Aggregator API — advisory maritime conditions + freemium accounts."""
from __future__ import annotations

import math
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
import requests

from app import config
from app.auth import (
    clear_session_cookie,
    create_session_token,
    get_optional_user,
    hash_password,
    normalize_email,
    require_user,
    set_session_cookie,
    verify_password,
)
from app.database import get_db, init_db
from app.models import SavedRoute, User
from app.quotas import assert_can_save, consume, usage_snapshot
from app import stripe_billing
from app import paypal_billing
from app import forecasts as forecast_svc

# Optional Gemini — app starts fine without the package or key
try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover
    genai = None

app = FastAPI(
    title="Condition Aggregator API",
    description="Advisory maritime route conditions via NOAA/NDBC + forecasts. Not for navigation.",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-API-Key"],
)

if config.GEMINI_API_KEY and genai is not None:
    genai.configure(api_key=config.GEMINI_API_KEY)

_SYSTEM_PROMPT = (
    "You are a maritime safety assistant embedded in a real-time ocean condition aggregator. "
    "Your role is to help mariners interpret weather and sea conditions, evaluate route safety, "
    "and provide concise, actionable guidance. "
    "Always recommend caution when conditions are uncertain. "
    "Remind users that outputs are advisory only and not for navigation. "
    "Respond in plain, clear language suitable for use at sea. "
    "If given specific wind speeds, wave heights, or route details, use them in your answer."
)

# ── Simple in-memory rate limiter (per client IP) ─────────────────────────────

_rate_buckets: dict = defaultdict(list)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> None:
    if config.RATE_LIMIT_PER_MINUTE <= 0:
        return
    ip = _client_ip(request)
    now = time.time()
    window = 60.0
    bucket = _rate_buckets[ip]
    _rate_buckets[ip] = [t for t in bucket if now - t < window]
    if len(_rate_buckets[ip]) >= config.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({config.RATE_LIMIT_PER_MINUTE}/min). Try again shortly.",
        )
    _rate_buckets[ip].append(now)


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    if not config.API_KEY:
        return
    if not x_api_key or x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")


def protect_route(
    request: Request,
    _: None = Depends(require_api_key),
) -> None:
    check_rate_limit(request)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    if config.paypal_configured():
        try:
            ok = paypal_billing.oauth_ok()
            print(f"PayPal OAuth: {'success' if ok else 'fail'}")
            if ok and not config.PAYPAL_PLAN_ID:
                plan_id = paypal_billing.ensure_plan_id()
                print(f"PayPal plan created/ready (id length={len(plan_id)})")
            elif ok and config.PAYPAL_PLAN_ID:
                print(f"PayPal plan configured (id length={len(config.PAYPAL_PLAN_ID)})")
        except Exception as exc:  # pragma: no cover
            print(f"PayPal startup check failed: {type(exc).__name__}")


# ── Utilities ──────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def interpolate_route(start: dict, end: dict, steps: int = 12) -> list:
    return [
        {
            "lat": start["lat"] + (end["lat"] - start["lat"]) * i / steps,
            "lon": start["lon"] + (end["lon"] - start["lon"]) * i / steps,
        }
        for i in range(steps + 1)
    ]


def densify_path(points: list, target_count: int = 13) -> list:
    if not points:
        return []
    if len(points) == 1:
        return points
    dists = [0.0]
    for i in range(1, len(points)):
        dists.append(
            dists[-1]
            + haversine_km(points[i - 1]["lat"], points[i - 1]["lon"], points[i]["lat"], points[i]["lon"])
        )
    total = dists[-1]
    if total <= 0:
        return points[:1]
    out = []
    for i in range(target_count):
        t = total * i / (target_count - 1)
        j = 1
        while j < len(dists) and dists[j] < t:
            j += 1
        if j >= len(dists):
            out.append({"lat": points[-1]["lat"], "lon": points[-1]["lon"]})
            continue
        seg_len = dists[j] - dists[j - 1]
        frac = 0.0 if seg_len <= 0 else (t - dists[j - 1]) / seg_len
        a, b = points[j - 1], points[j]
        out.append({
            "lat": a["lat"] + (b["lat"] - a["lat"]) * frac,
            "lon": a["lon"] + (b["lon"] - a["lon"]) * frac,
        })
    return out


# ── NDBC Station Cache ─────────────────────────────────────────────────────────

_ndbc_stations: list = []
_ndbc_loaded_at: float = 0.0
_NDBC_STATION_TTL = 3600


def load_ndbc_stations(force: bool = False) -> list:
    global _ndbc_stations, _ndbc_loaded_at
    if not force and _ndbc_stations and (time.time() - _ndbc_loaded_at < _NDBC_STATION_TTL):
        return _ndbc_stations
    url = "https://www.ndbc.noaa.gov/activestations.xml"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        stations = []
        for s in root.findall("station"):
            try:
                lat = float(s.get("lat", ""))
                lon = float(s.get("lon", ""))
            except (TypeError, ValueError):
                continue
            stations.append({
                "id": s.get("id", ""),
                "name": s.get("name", ""),
                "lat": lat,
                "lon": lon,
                "type": s.get("type", ""),
                "owner": s.get("owner", ""),
                "has_met": s.get("met", "n") == "y",
            })
        _ndbc_stations = stations
        _ndbc_loaded_at = time.time()
        return stations
    except Exception:
        return _ndbc_stations


_conditions_cache: dict = {}
_CONDITIONS_TTL = 600
_NDBC_MISSING = frozenset({"MM", "999", "9999", "99", "99.0", "9999.0"})


def fetch_ndbc_conditions(station_id: str) -> dict:
    now = time.time()
    if station_id in _conditions_cache:
        cached, ts = _conditions_cache[station_id]
        if now - ts < _CONDITIONS_TTL:
            return cached

    url = f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        if len(lines) < 3:
            return {}
        headers = lines[0].lstrip("#").split()
        data_line = next(
            (l for l in lines[2:] if not l.startswith("#") and l.strip()), None
        )
        if not data_line:
            return {}

        row = dict(zip(headers, data_line.split()))

        def safe(key, mult=1.0):
            v = row.get(key)
            if v is None or v in _NDBC_MISSING:
                return None
            try:
                f = float(v)
                if f in (999.0, 9999.0):
                    return None
                return round(f * mult, 2)
            except ValueError:
                return None

        result = {
            "wind_dir_deg": safe("WDIR"),
            "wind_speed_knots": safe("WSPD", 1.944),
            "wind_gust_knots": safe("GST", 1.944),
            "wave_height_ft": safe("WVHT", 3.281),
            "dominant_period_s": safe("DPD"),
            "air_temp_c": safe("ATMP"),
            "water_temp_c": safe("WTMP"),
            "pressure_hpa": safe("PRES"),
        }
        _conditions_cache[station_id] = (result, now)
        return result
    except Exception:
        return {}


# ── Auth / account schemas ─────────────────────────────────────────────────────

class SignupBody(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email")
        return v


class LoginBody(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email")
        return v


class SavedRouteBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    start_label: Optional[str] = None
    end_label: Optional[str] = None
    notes: Optional[str] = None


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "plan": user.plan,
        "forecasts_enabled": user.forecasts_enabled,
    }


# ── Health + me / auth ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "chat_configured": bool(config.GEMINI_API_KEY and genai is not None),
        "api_key_required": bool(config.API_KEY),
        "stripe_configured": config.stripe_configured(),
        "paypal_configured": config.paypal_configured(),
        "billing_provider": config.preferred_billing_provider(),
        "disclaimer": "Advisory only — not for navigation.",
    }


@app.get("/api/me")
def me(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    anon = f"ip:{_client_ip(request)}"
    snap = usage_snapshot(db, user=user, anon_key=anon if not user else None)
    return {
        "authenticated": user is not None,
        "user": _public_user(user) if user else None,
        "quota": snap,
        "disclaimer": "Advisory only — not for navigation.",
    }


@app.post("/api/auth/signup")
def signup(body: SignupBody, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(body.email)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered.")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        plan="free",
        forecasts_enabled=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_session_token(user.id, user.email)
    set_session_cookie(response, token)
    snap = usage_snapshot(db, user=user)
    return {"user": _public_user(user), "quota": snap}


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(body.email)
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = create_session_token(user.id, user.email)
    set_session_cookie(response, token)
    snap = usage_snapshot(db, user=user)
    return {"user": _public_user(user), "quota": snap}


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}



# ── Billing status + PayPal (primary) ─────────────────────────────────────────

@app.get("/api/billing/status")
def billing_status(
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    provider = config.preferred_billing_provider()
    plan = user.plan if user else "anonymous"
    sub_provider = None
    if user:
        if user.paypal_subscription_id:
            sub_provider = "paypal"
        elif user.stripe_subscription_id:
            sub_provider = "stripe"
        elif plan == "pro":
            sub_provider = provider if provider != "none" else "unknown"
    return {
        "plan": plan,
        "provider": provider,
        "subscription_provider": sub_provider,
        "paypal_configured": config.paypal_configured(),
        "stripe_configured": config.stripe_configured(),
        "paypal_plan_configured": bool(config.PAYPAL_PLAN_ID),
        "forecasts_enabled": bool(user.forecasts_enabled) if user else False,
        "authenticated": user is not None,
    }


class PayPalCaptureBody(BaseModel):
    subscription_id: str = Field(min_length=1, max_length=128)


@app.post("/api/paypal/create-subscription")
def paypal_create_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not config.paypal_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "paypal_not_configured",
                "message": (
                    "PayPal sandbox keys are not set. Add PAYPAL_CLIENT_ID and "
                    "PAYPAL_CLIENT_SECRET to .env (see README)."
                ),
            },
        )
    return paypal_billing.create_subscription(db, user)


@app.post("/api/paypal/capture")
def paypal_capture(
    body: PayPalCaptureBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not config.paypal_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "paypal_not_configured",
                "message": "PayPal is not configured.",
            },
        )
    return paypal_billing.capture_subscription(db, user, body.subscription_id)


@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    """PayPal subscription lifecycle webhook.

    When PAYPAL_WEBHOOK_ID is set, signature is verified via PayPal API.
    For local sandbox without a webhook id, prefer POST /api/paypal/capture
    after the buyer returns from approval.
    """
    try:
        event = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    if config.PAYPAL_WEBHOOK_ID:
        ok = paypal_billing.verify_webhook_signature(
            transmission_id=request.headers.get("paypal-transmission-id", ""),
            timestamp=request.headers.get("paypal-transmission-time", ""),
            transmission_sig=request.headers.get("paypal-transmission-sig", ""),
            cert_url=request.headers.get("paypal-cert-url", ""),
            auth_algo=request.headers.get("paypal-auth-algo", ""),
            webhook_event=event,
        )
        if not ok:
            raise HTTPException(status_code=400, detail="PayPal webhook verification failed")
    result = paypal_billing.handle_webhook_event(db, event)
    return {"received": True, **result}


# ── Stripe billing ─────────────────────────────────────────────────────────────

@app.post("/api/billing/checkout")
def billing_checkout(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not config.stripe_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stripe_not_configured",
                "message": (
                    "Stripe is not configured (PayPal is preferred). "
                    "Use Upgrade which calls PayPal when PAYPAL_CLIENT_ID is set, "
                    "or add STRIPE_SECRET_KEY + STRIPE_PRICE_ID_PRO for Stripe."
                ),
            },
        )
    return stripe_billing.create_checkout_session(db, user)


@app.post("/api/billing/portal")
def billing_portal(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not config.stripe_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stripe_not_configured",
                "message": (
                    "Stripe not configured. To cancel a test subscription, use the "
                    "Stripe Dashboard → Customers, or set keys and use Customer Portal."
                ),
            },
        )
    try:
        return stripe_billing.create_portal_session(db, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Portal unavailable ({exc}). Cancel via Stripe Dashboard for test mode, "
                "or enable Customer Portal in Stripe settings."
            ),
        ) from exc


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    event = stripe_billing.construct_event(payload, sig)
    etype = event["type"] if isinstance(event, dict) else event.type
    data = event["data"]["object"] if isinstance(event, dict) else event.data.object

    if etype == "checkout.session.completed":
        stripe_billing.apply_checkout_completed(db, data)
    elif etype == "customer.subscription.updated":
        stripe_billing.apply_subscription_updated(db, data)
    elif etype == "customer.subscription.deleted":
        stripe_billing.apply_subscription_deleted(db, data)

    return {"received": True}


# ── Saved routes ───────────────────────────────────────────────────────────────

@app.get("/api/saved-routes")
def list_saved_routes(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    rows = (
        db.query(SavedRoute)
        .filter(SavedRoute.user_id == user.id)
        .order_by(SavedRoute.created_at.desc())
        .all()
    )
    return {
        "routes": [
            {
                "id": r.id,
                "name": r.name,
                "start": {"lat": float(r.start_lat), "lon": float(r.start_lon), "label": r.start_label},
                "end": {"lat": float(r.end_lat), "lon": float(r.end_lon), "label": r.end_label},
                "notes": r.notes,
            }
            for r in rows
        ],
        "quota": usage_snapshot(db, user=user),
    }


@app.post("/api/saved-routes")
def create_saved_route(
    body: SavedRouteBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    assert_can_save(db, user)
    row = SavedRoute(
        user_id=user.id,
        name=body.name.strip(),
        start_lat=str(body.start_lat),
        start_lon=str(body.start_lon),
        end_lat=str(body.end_lat),
        end_lon=str(body.end_lon),
        start_label=body.start_label,
        end_label=body.end_label,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "name": row.name,
        "quota": usage_snapshot(db, user=user),
    }


@app.delete("/api/saved-routes/{route_id}")
def delete_saved_route(
    route_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    row = db.query(SavedRoute).filter(SavedRoute.id == route_id, SavedRoute.user_id == user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Saved route not found.")
    db.delete(row)
    db.commit()
    return {"ok": True, "quota": usage_snapshot(db, user=user)}


# ── Existing condition endpoints ───────────────────────────────────────────────

@app.get("/api/geocode")
def geocode(
    request: Request,
    q: str = Query(..., description="Location name to geocode"),
    _: None = Depends(protect_route),
):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": q, "format": "json", "limit": 5}
    headers = {"User-Agent": "ConditionAggregator/1.0 (github.com/Codesurfing10)"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        return {
            "query": q,
            "results": [
                {
                    "display_name": r["display_name"],
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                }
                for r in results
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Geocoding error: {exc}") from exc


@app.get("/api/stations/near")
def get_nearby_stations(
    request: Request,
    lat: float,
    lon: float,
    radius_km: int = 200,
    _: None = Depends(protect_route),
):
    stations = load_ndbc_stations()
    nearby = []
    for s in stations:
        d = haversine_km(lat, lon, s["lat"], s["lon"])
        if d <= radius_km:
            nearby.append({**s, "distance_km": round(d, 1)})
    nearby.sort(key=lambda x: x["distance_km"])
    return {
        "query": {"lat": lat, "lon": lon, "radius_km": radius_km},
        "count": len(nearby),
        "stations": nearby[:50],
    }


@app.get("/api/conditions")
def get_conditions(
    request: Request,
    station_id: str,
    horizon_minutes: int = 10,
    _: None = Depends(protect_route),
):
    conditions = fetch_ndbc_conditions(station_id)
    if not conditions:
        raise HTTPException(
            status_code=404,
            detail=f"No observation data available for station {station_id}",
        )
    return {
        "station_id": station_id,
        "units": {"wind": "knots", "waves": "feet"},
        "time_horizon_minutes": horizon_minutes,
        "observations": conditions,
        "disclaimer": "Advisory only — not for navigation.",
    }


@app.post("/api/route")
def get_route(
    route: dict,
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
    _: None = Depends(protect_route),
):
    """
    Sample NDBC conditions along a route.
    Body: { start: {lat,lon}, end: {lat,lon}, path?: [{lat,lon}, ...] }
    Consumes freemium route quota (anonymous IP or logged-in user).
    """
    anon = f"ip:{_client_ip(request)}"
    quota = consume(db, user=user, anon_key=anon if not user else None, kind="routes")

    start = route.get("start", {})
    end = route.get("end", {})

    if not (start.get("lat") is not None and start.get("lon") is not None
            and end.get("lat") is not None and end.get("lon") is not None):
        raise HTTPException(
            status_code=400, detail="'start' and 'end' with lat/lon are required"
        )

    raw_path = route.get("path") or route.get("waypoints")
    routing_mode = "straight"
    if isinstance(raw_path, list) and len(raw_path) >= 2:
        cleaned = []
        for p in raw_path:
            try:
                cleaned.append({"lat": float(p["lat"]), "lon": float(p["lon"])})
            except (KeyError, TypeError, ValueError):
                continue
        if len(cleaned) >= 2:
            route_points = densify_path(cleaned, target_count=13)
            routing_mode = "water_path"
        else:
            route_points = interpolate_route(start, end, steps=12)
    else:
        route_points = interpolate_route(start, end, steps=12)

    stations = load_ndbc_stations()

    seen_ids: set = set()
    sampled = []

    for pt in route_points:
        best = None
        best_dist = float("inf")
        for s in stations:
            if not s["has_met"]:
                continue
            d = haversine_km(pt["lat"], pt["lon"], s["lat"], s["lon"])
            if d < best_dist:
                best_dist = d
                best = s

        entry: dict = {
            "lat": pt["lat"],
            "lon": pt["lon"],
            "nearest_station": None,
            "conditions": None,
        }

        if best and best_dist <= 400:
            entry["nearest_station"] = {
                "id": best["id"],
                "name": best["name"],
                "distance_km": round(best_dist, 1),
            }
            if best["id"] not in seen_ids:
                seen_ids.add(best["id"])
                cond = fetch_ndbc_conditions(best["id"])
                entry["conditions"] = cond if cond else None
            else:
                cached = _conditions_cache.get(best["id"])
                entry["conditions"] = cached[0] if cached else None

        sampled.append(entry)

    wind_speeds = [
        s["conditions"]["wind_speed_knots"]
        for s in sampled
        if s["conditions"] and s["conditions"].get("wind_speed_knots") is not None
    ]
    wave_heights = [
        s["conditions"]["wave_height_ft"]
        for s in sampled
        if s["conditions"] and s["conditions"].get("wave_height_ft") is not None
    ]

    summary = {
        "max_wind_knots": max(wind_speeds) if wind_speeds else None,
        "avg_wind_knots": round(sum(wind_speeds) / len(wind_speeds), 1) if wind_speeds else None,
        "max_wave_ft": max(wave_heights) if wave_heights else None,
        "avg_wave_ft": round(sum(wave_heights) / len(wave_heights), 1) if wave_heights else None,
        "data_points": len(wind_speeds),
    }

    return {
        "start": start,
        "end": end,
        "units": {"wind": "knots", "waves": "feet"},
        "routing_mode": routing_mode,
        "advisory": True,
        "disclaimer": "Advisory / approximate only — NOT for navigation.",
        "route_sample_points": sampled,
        "summary": summary,
        "quota": quota,
        "forecasts_enabled": bool(user and user.forecasts_enabled),
    }



# ── Route forecasts (Pro: wind / waves / weather / tides) ─────────────────────

class ForecastBody(BaseModel):
    start: dict
    end: dict
    path: Optional[list] = None
    hours: int = Field(default=48, ge=1, le=72)
    points: int = Field(default=3, ge=1, le=5)


def _forecast_upgrade_detail(plan: str) -> dict:
    return {
        "code": "upgrade_required",
        "feature": "forecasts",
        "plan": plan,
        "message": (
            "Anticipated weather, tides, wave height, and wind forecasts are a Pro feature. "
            "Upgrade to unlock full route forecasts (Open-Meteo + NOAA CO-OPS)."
        ),
        "upgrade": True,
        "preview_available": True,
    }


@app.get("/api/forecast")
def get_forecast(
    request: Request,
    start_lat: float = Query(...),
    start_lon: float = Query(...),
    end_lat: float = Query(...),
    end_lon: float = Query(...),
    hours: int = Query(48, ge=1, le=72),
    points: int = Query(3, ge=1, le=5),
    preview: bool = Query(
        False,
        description="Short marketing sample (1 point, ≤6h). Allowed without Pro.",
    ),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
    _: None = Depends(protect_route),
):
    """Forecast wind, waves, weather, and tides along a route.

    Full forecasts require Pro (`forecasts_enabled`). Free/anonymous users may
    request `preview=true` for a short teaser, otherwise receive HTTP 402.
    """
    limits = usage_snapshot(
        db,
        user=user,
        anon_key=f"ip:{_client_ip(request)}" if not user else None,
    )
    pro = bool(user and (user.forecasts_enabled or user.plan == "pro"))
    if not pro and not preview:
        raise HTTPException(status_code=402, detail=_forecast_upgrade_detail(limits["plan"]))

    start = {"lat": start_lat, "lon": start_lon}
    end = {"lat": end_lat, "lon": end_lon}
    data = forecast_svc.build_route_forecast(
        start,
        end,
        hours=hours,
        point_count=1 if preview else points,
        include_tides=True,
        preview=preview or not pro,
    )
    data["quota"] = limits
    data["forecasts_enabled"] = pro
    data["plan"] = limits["plan"]
    if preview and not pro:
        data["teaser"] = True
        data["upgrade_message"] = _forecast_upgrade_detail(limits["plan"])["message"]
    return data


@app.post("/api/forecast")
def post_forecast(
    body: ForecastBody,
    request: Request,
    preview: bool = Query(False),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
    _: None = Depends(protect_route),
):
    """Same as GET /api/forecast but accepts path waypoints in the JSON body."""
    limits = usage_snapshot(
        db,
        user=user,
        anon_key=f"ip:{_client_ip(request)}" if not user else None,
    )
    pro = bool(user and (user.forecasts_enabled or user.plan == "pro"))
    if not pro and not preview:
        raise HTTPException(status_code=402, detail=_forecast_upgrade_detail(limits["plan"]))

    start = body.start or {}
    end = body.end or {}
    if start.get("lat") is None or start.get("lon") is None or end.get("lat") is None or end.get("lon") is None:
        raise HTTPException(status_code=400, detail="'start' and 'end' with lat/lon are required")

    data = forecast_svc.build_route_forecast(
        {"lat": float(start["lat"]), "lon": float(start["lon"])},
        {"lat": float(end["lat"]), "lon": float(end["lon"])},
        path=body.path,
        hours=body.hours,
        point_count=1 if preview else body.points,
        include_tides=True,
        preview=preview or not pro,
    )
    data["quota"] = limits
    data["forecasts_enabled"] = pro
    data["plan"] = limits["plan"]
    if preview and not pro:
        data["teaser"] = True
        data["upgrade_message"] = _forecast_upgrade_detail(limits["plan"])["message"]
    return data


@app.post("/api/chat")
async def chat(
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
    _: None = Depends(protect_route),
):
    """
    AI assistant endpoint powered by Gemini.
    Free: 1/day (account required). Pro: higher daily cap.
    """
    if not config.GEMINI_API_KEY or genai is None:
        raise HTTPException(
            status_code=503,
            detail="AI assistant is not configured. Set the GEMINI_API_KEY environment variable.",
        )

    anon = f"ip:{_client_ip(request)}"
    quota = consume(db, user=user, anon_key=anon if not user else None, kind="chats")

    user_message = (body.get("message") or "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="'message' field is required.")

    context = body.get("context")
    if context:
        context_text = (
            "\n\nCurrent route context:\n"
            + "\n".join(f"  {k}: {v}" for k, v in context.items())
        )
        full_message = user_message + context_text
    else:
        full_message = user_message

    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash-lite",
            system_instruction=_SYSTEM_PROMPT,
        )
        response = model.generate_content(full_message)
        return {
            "reply": response.text,
            "disclaimer": "Advisory only — not for navigation.",
            "quota": quota,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI model error: {exc}") from exc


# ── Static frontend (single-service deploy: UI + API) ─────────────────────────
# Serves repo-root index.html / app.js / src / selected data files from the same
# origin as /api/* and /health. Do NOT mount all of data/ (would expose SQLite).

_ROOT = config.ROOT


@app.get("/")
async def spa_index():
    return FileResponse(_ROOT / "index.html")


@app.get("/app.js")
async def spa_app_js():
    return FileResponse(_ROOT / "app.js", media_type="application/javascript")


@app.get("/data/land_110m.geojson")
async def spa_land_geojson():
    path = _ROOT / "data" / "land_110m.geojson"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="land_110m.geojson not found")
    return FileResponse(path, media_type="application/geo+json")


@app.get("/data/reference_points.geojson")
async def spa_reference_geojson():
    path = _ROOT / "data" / "reference_points.geojson"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="reference_points.geojson not found")
    return FileResponse(path, media_type="application/geo+json")


_src_dir = _ROOT / "src"
if _src_dir.is_dir():
    app.mount("/src", StaticFiles(directory=str(_src_dir)), name="frontend_src")
