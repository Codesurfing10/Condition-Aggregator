"""Route forecast helpers: Open-Meteo (weather/wind/waves) + NOAA CO-OPS (tides).

Public APIs with attribution — advisory only, not for navigation.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MARINE = "https://marine-api.open-meteo.com/v1/marine"
NOAA_STATIONS_URL = (
    "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
    "?type=tidepredictions&units=english"
)
NOAA_PREDICTIONS_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

_ATTRIBUTION = {
    "weather_wind": "Open-Meteo (https://open-meteo.com)",
    "waves": "Open-Meteo Marine API (https://open-meteo.com)",
    "tides": "NOAA CO-OPS (https://tidesandcurrents.noaa.gov)",
}

# WMO weather interpretation codes (subset)
_WMO_LABELS = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm + hail",
    99: "Thunderstorm + heavy hail",
}

_tide_stations: list[dict] = []
_tide_stations_loaded_at = 0.0
_TIDE_STATION_TTL = 86400.0

_forecast_cache: dict[str, tuple[Any, float]] = {}
_FORECAST_TTL = 900.0  # 15 min


def _cache_get(key: str):
    hit = _forecast_cache.get(key)
    if not hit:
        return None
    val, ts = hit
    if time.time() - ts > _FORECAST_TTL:
        return None
    return val


def _cache_set(key: str, val: Any) -> None:
    _forecast_cache[key] = (val, time.time())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def weather_label(code: Optional[int]) -> str:
    if code is None:
        return "Unknown"
    return _WMO_LABELS.get(int(code), f"Code {code}")


def sample_route_points(
    start: dict,
    end: dict,
    path: Optional[list] = None,
    *,
    count: int = 3,
) -> list[dict]:
    """Return evenly spaced points along path (or start→end)."""
    pts: list[dict] = []
    if isinstance(path, list) and len(path) >= 2:
        for p in path:
            try:
                pts.append({"lat": float(p["lat"]), "lon": float(p["lon"])})
            except (KeyError, TypeError, ValueError):
                continue
    if len(pts) < 2:
        pts = [
            {"lat": float(start["lat"]), "lon": float(start["lon"])},
            {"lat": float(end["lat"]), "lon": float(end["lon"])},
        ]
    if count <= 1:
        mid = pts[len(pts) // 2]
        return [{"lat": mid["lat"], "lon": mid["lon"], "label": "mid"}]
    # densify by cumulative distance
    dists = [0.0]
    for i in range(1, len(pts)):
        dists.append(
            dists[-1]
            + haversine_km(pts[i - 1]["lat"], pts[i - 1]["lon"], pts[i]["lat"], pts[i]["lon"])
        )
    total = dists[-1]
    labels = ["start", "mid", "end"] if count == 3 else [f"p{i}" for i in range(count)]
    out = []
    for i in range(count):
        t = 0.0 if total <= 0 else total * i / (count - 1)
        j = 1
        while j < len(dists) and dists[j] < t:
            j += 1
        if j >= len(dists):
            p = pts[-1]
        else:
            seg = dists[j] - dists[j - 1]
            frac = 0.0 if seg <= 0 else (t - dists[j - 1]) / seg
            a, b = pts[j - 1], pts[j]
            p = {
                "lat": a["lat"] + (b["lat"] - a["lat"]) * frac,
                "lon": a["lon"] + (b["lon"] - a["lon"]) * frac,
            }
        label = labels[i] if i < len(labels) else f"p{i}"
        out.append({"lat": round(p["lat"], 5), "lon": round(p["lon"], 5), "label": label})
    return out


def fetch_weather_wind(lat: float, lon: float, hours: int = 48) -> dict:
    """Open-Meteo forecast: temp, precip, conditions, wind."""
    key = f"wx:{lat:.3f},{lon:.3f}:{hours}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    days = max(1, min(7, (hours + 23) // 24))
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(
            [
                "temperature_2m",
                "precipitation_probability",
                "precipitation",
                "weather_code",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ]
        ),
        "forecast_days": days,
        "wind_speed_unit": "kn",
        "timezone": "UTC",
    }
    try:
        resp = requests.get(OPEN_METEO_FORECAST, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"error": str(exc), "hourly": []}

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    n = min(len(times), hours)
    rows = []
    for i in range(n):
        code = hourly.get("weather_code", [None] * n)[i]
        rows.append(
            {
                "time": times[i] if times[i].endswith("Z") else times[i] + "Z",
                "temp_c": _num(hourly.get("temperature_2m"), i),
                "precip_prob_pct": _num(hourly.get("precipitation_probability"), i),
                "precip_mm": _num(hourly.get("precipitation"), i),
                "weather_code": int(code) if code is not None else None,
                "weather": weather_label(code),
                "wind_speed_knots": _num(hourly.get("wind_speed_10m"), i),
                "wind_dir_deg": _num(hourly.get("wind_direction_10m"), i),
                "wind_gust_knots": _num(hourly.get("wind_gusts_10m"), i),
            }
        )
    result = {
        "lat": lat,
        "lon": lon,
        "hourly": rows,
        "units": {"temp": "°C", "wind": "knots", "precip": "mm"},
        "source": _ATTRIBUTION["weather_wind"],
    }
    _cache_set(key, result)
    return result


def fetch_marine_waves(lat: float, lon: float, hours: int = 48) -> dict:
    """Open-Meteo Marine: wave height / period / direction."""
    key = f"wv:{lat:.3f},{lon:.3f}:{hours}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    days = max(1, min(7, (hours + 23) // 24))
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wave_height,wave_direction,wave_period,swell_wave_height",
        "forecast_days": days,
        "length_unit": "imperial",  # feet
        "timezone": "UTC",
    }
    try:
        resp = requests.get(OPEN_METEO_MARINE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"error": str(exc), "hourly": []}

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    n = min(len(times), hours)
    rows = []
    for i in range(n):
        rows.append(
            {
                "time": times[i] if times[i].endswith("Z") else times[i] + "Z",
                "wave_height_ft": _num(hourly.get("wave_height"), i),
                "wave_dir_deg": _num(hourly.get("wave_direction"), i),
                "wave_period_s": _num(hourly.get("wave_period"), i),
                "swell_height_ft": _num(hourly.get("swell_wave_height"), i),
            }
        )
    result = {
        "lat": lat,
        "lon": lon,
        "hourly": rows,
        "units": {"waves": "feet", "period": "s"},
        "source": _ATTRIBUTION["waves"],
    }
    _cache_set(key, result)
    return result


def load_tide_stations(force: bool = False) -> list[dict]:
    global _tide_stations, _tide_stations_loaded_at
    if (
        not force
        and _tide_stations
        and (time.time() - _tide_stations_loaded_at < _TIDE_STATION_TTL)
    ):
        return _tide_stations
    try:
        resp = requests.get(NOAA_STATIONS_URL, timeout=45)
        resp.raise_for_status()
        stations = resp.json().get("stations") or []
        out = []
        for s in stations:
            try:
                out.append(
                    {
                        "id": str(s["id"]),
                        "name": s.get("name") or s["id"],
                        "lat": float(s["lat"]),
                        "lon": float(s["lng"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        _tide_stations = out
        _tide_stations_loaded_at = time.time()
        return out
    except Exception:
        return _tide_stations


def nearest_tide_station(lat: float, lon: float, max_km: float = 250.0) -> Optional[dict]:
    stations = load_tide_stations()
    best = None
    best_d = float("inf")
    for s in stations:
        d = haversine_km(lat, lon, s["lat"], s["lon"])
        if d < best_d:
            best_d = d
            best = {**s, "distance_km": round(d, 1)}
    if best and best_d <= max_km:
        return best
    return None


def fetch_tide_predictions(station_id: str, hours: int = 48) -> dict:
    key = f"td:{station_id}:{hours}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours + 12)
    params = {
        "product": "predictions",
        "application": "ConditionAggregator",
        "begin_date": now.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "datum": "MLLW",
        "station": station_id,
        "time_zone": "gmt",
        "units": "english",
        "interval": "hilo",
        "format": "json",
    }
    try:
        resp = requests.get(NOAA_PREDICTIONS_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"error": str(exc), "events": []}

    preds = data.get("predictions") or []
    events = []
    cutoff = now + timedelta(hours=hours)
    for p in preds:
        try:
            t_raw = p["t"]  # "YYYY-MM-DD HH:MM"
            t = datetime.strptime(t_raw, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            if t < now - timedelta(hours=1) or t > cutoff:
                continue
            typ = (p.get("type") or "").upper()
            label = "High" if typ == "H" else ("Low" if typ == "L" else typ or "Tide")
            events.append(
                {
                    "time": t.strftime("%Y-%m-%dT%H:%MZ"),
                    "height_ft": round(float(p["v"]), 2),
                    "type": label,
                }
            )
        except (KeyError, TypeError, ValueError):
            continue

    result = {
        "station_id": station_id,
        "events": events,
        "units": {"height": "feet (MLLW)"},
        "source": _ATTRIBUTION["tides"],
    }
    _cache_set(key, result)
    return result


def _num(arr: Optional[list], i: int):
    if not arr or i >= len(arr):
        return None
    v = arr[i]
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _summarize_point(wx: dict, wv: dict) -> dict:
    wh = wx.get("hourly") or []
    mh = wv.get("hourly") or []
    winds = [r["wind_speed_knots"] for r in wh if r.get("wind_speed_knots") is not None]
    gusts = [r["wind_gust_knots"] for r in wh if r.get("wind_gust_knots") is not None]
    waves = [r["wave_height_ft"] for r in mh if r.get("wave_height_ft") is not None]
    temps = [r["temp_c"] for r in wh if r.get("temp_c") is not None]
    precip = [r["precip_prob_pct"] for r in wh if r.get("precip_prob_pct") is not None]
    near = wh[0] if wh else {}
    return {
        "next_weather": near.get("weather"),
        "next_temp_c": near.get("temp_c"),
        "max_wind_knots": max(winds) if winds else None,
        "max_gust_knots": max(gusts) if gusts else None,
        "max_wave_ft": max(waves) if waves else None,
        "min_temp_c": min(temps) if temps else None,
        "max_temp_c": max(temps) if temps else None,
        "max_precip_prob_pct": max(precip) if precip else None,
    }


def build_route_forecast(
    start: dict,
    end: dict,
    *,
    path: Optional[list] = None,
    hours: int = 48,
    point_count: int = 3,
    include_tides: bool = True,
    preview: bool = False,
) -> dict:
    """Assemble structured forecast for points along a route."""
    hours = max(1, min(72, int(hours)))
    if preview:
        hours = min(hours, 6)
        point_count = 1

    points = sample_route_points(start, end, path, count=point_count)
    along = []
    for pt in points:
        wx = fetch_weather_wind(pt["lat"], pt["lon"], hours=hours)
        wv = fetch_marine_waves(pt["lat"], pt["lon"], hours=hours)
        entry = {
            "label": pt["label"],
            "lat": pt["lat"],
            "lon": pt["lon"],
            "weather": wx,
            "waves": wv,
            "wind": {
                "hourly": [
                    {
                        "time": r["time"],
                        "wind_speed_knots": r.get("wind_speed_knots"),
                        "wind_dir_deg": r.get("wind_dir_deg"),
                        "wind_gust_knots": r.get("wind_gust_knots"),
                    }
                    for r in (wx.get("hourly") or [])
                ],
                "source": _ATTRIBUTION["weather_wind"],
                "units": {"wind": "knots"},
            },
            "summary": _summarize_point(wx, wv),
        }
        along.append(entry)

    tides = []
    if include_tides:
        # Near start, mid, end (dedupe stations)
        tide_targets = [points[0], points[len(points) // 2], points[-1]]
        seen = set()
        for pt in tide_targets:
            st = nearest_tide_station(pt["lat"], pt["lon"])
            if not st or st["id"] in seen:
                continue
            seen.add(st["id"])
            pred = fetch_tide_predictions(st["id"], hours=hours)
            tides.append(
                {
                    "near_label": pt["label"],
                    "station": st,
                    "predictions": pred,
                }
            )

    # Route-level rollup
    all_wind = []
    all_wave = []
    for e in along:
        s = e.get("summary") or {}
        if s.get("max_wind_knots") is not None:
            all_wind.append(s["max_wind_knots"])
        if s.get("max_wave_ft") is not None:
            all_wave.append(s["max_wave_ft"])

    return {
        "hours": hours,
        "preview": preview,
        "points": along,
        "tides": tides,
        "summary": {
            "max_wind_knots": max(all_wind) if all_wind else None,
            "max_wave_ft": max(all_wave) if all_wave else None,
            "locations": len(along),
            "tide_stations": len(tides),
        },
        "attribution": _ATTRIBUTION,
        "disclaimer": "Advisory forecast only — NOT for navigation. Verify with official sources.",
    }
