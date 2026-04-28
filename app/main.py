import math
import time
import xml.etree.ElementTree as ET

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import google.generativeai as genai

app = FastAPI()

# Allow GitHub Pages frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://codesurfing10.github.io"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Gemini if API key is available
_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if _GEMINI_API_KEY:
    genai.configure(api_key=_GEMINI_API_KEY)

_SYSTEM_PROMPT = (
    "You are a maritime safety assistant embedded in a real-time ocean condition aggregator. "
    "Your role is to help mariners interpret weather and sea conditions, evaluate route safety, "
    "and provide concise, actionable guidance. "
    "Always recommend caution when conditions are uncertain. "
    "Respond in plain, clear language suitable for use at sea. "
    "If given specific wind speeds, wave heights, or route details, use them in your answer."
)

# ── Utilities ──────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def interpolate_route(start: dict, end: dict, steps: int = 12) -> list:
    """Return evenly-spaced lat/lon points along a straight-line approximation."""
    return [
        {
            "lat": start["lat"] + (end["lat"] - start["lat"]) * i / steps,
            "lon": start["lon"] + (end["lon"] - start["lon"]) * i / steps,
        }
        for i in range(steps + 1)
    ]

# ── NDBC Station Cache ─────────────────────────────────────────────────────────

_ndbc_stations: list = []
_ndbc_loaded_at: float = 0.0
_NDBC_STATION_TTL = 3600  # refresh station list every hour


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
        return _ndbc_stations  # return stale cache on error

# ── NDBC Conditions Cache ──────────────────────────────────────────────────────

_conditions_cache: dict = {}
_CONDITIONS_TTL = 600  # cache observations for 10 minutes

# Sentinel values used by NDBC to indicate missing / unavailable data
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

# ── API Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/geocode")
def geocode(q: str = Query(..., description="Location name to geocode")):
    """Geocode a location name to lat/lon using Nominatim."""
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
def get_nearby_stations(lat: float, lon: float, radius_km: int = 200):
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
def get_conditions(station_id: str, horizon_minutes: int = 10):
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
    }


@app.post("/api/route")
def get_route(route: dict):
    start = route.get("start", {})
    end = route.get("end", {})

    if not (start.get("lat") and start.get("lon") and end.get("lat") and end.get("lon")):
        raise HTTPException(
            status_code=400, detail="'start' and 'end' with lat/lon are required"
        )

    route_points = interpolate_route(start, end, steps=12)
    stations = load_ndbc_stations()

    seen_ids: set = set()
    sampled = []

    for pt in route_points:
        # Find nearest met station within 400 km
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
        "route_sample_points": sampled,
        "summary": summary,
    }


@app.post("/api/chat")
async def chat(body: dict):
    """
    AI assistant endpoint powered by Gemini 2.0 Flash Lite.
    Accepts: { "message": "...", "context": { optional route/conditions data } }
    Returns: { "reply": "..." }
    """
    if not _GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI assistant is not configured. Set the GEMINI_API_KEY environment variable.",
        )

    user_message = (body.get("message") or "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="'message' field is required.")

    # Optionally inject route/conditions context provided by the frontend
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
        return {"reply": response.text}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI model error: {exc}") from exc
