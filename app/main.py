from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup

app = FastAPI()

# Allow GitHub Pages frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://codesurfing10.github.io"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/api/stations/near")
async def get_nearby_stations(lat: float, lon: float, radius_km: int = 100):
    # Fetch and extract NDBC station data (placeholder)
    url = "https://www.ndbc.noaa.gov/to_station.shtml"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    # TODO: implement real parsing + distance filtering
    return {
        "query": {"lat": lat, "lon": lon, "radius_km": radius_km},
        "stations": [],
        "note": "TODO: parse NDBC station list and filter by radius",
    }

@app.get("/api/conditions")
async def get_conditions(station_id: str, horizon_minutes: int = 10):
    # TODO: fetch recent observations from NDBC and convert units to knots/feet
    return {
        "station_id": station_id,
        "units": {"wind": "knots", "waves": "feet"},
        "time_horizon_minutes": horizon_minutes,
        "series": [],
        "note": "TODO: implement NDBC observation fetch/parse",
    }

@app.post("/api/route")
async def get_route(route: dict):
    # TODO: implement candidate routes + NDBC sampling + conservative constraints scoring
    return {
        "input": route,
        "units": {"wind": "knots", "waves": "feet"},
        "time_horizon_minutes": 10,
        "sample_interval_km_default": 10,
        "constraints": {"mode": "conservative"},
        "routes": [],
        "best_route": None,
        "vessel_recommendation": {"label": "TBD", "summary": "TODO"},
        "note": "Stub: implement optimum routing",
    }