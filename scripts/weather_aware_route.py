import os
import requests
from geopy.geocoders import Nominatim
from geographiclib.geodesic import Geodesic
import folium
import json

NOAA_TOKEN = os.getenv('NOAA_TOKEN')
if not NOAA_TOKEN:
    raise EnvironmentError("NOAA_TOKEN environment variable is required.")

# Geocode locations
geolocator = Nominatim(user_agent="geoapiExercises")
san_diego = geolocator.geocode("San Diego, CA")
san_francisco = geolocator.geocode("San Francisco, CA")

# Build grid graph and query NWS & NOAA
# [Implementation here: Add logic to build grid and fetch data]

# Compute weather anomalies and penalties
# [Implementation here: Logic to calculate anomalies and penalties]

# A* routing implementation
# [A* algorithm implementation]

# Save output files
with open('data/reference_points.geojson', 'w') as f:
    json.dump(reference_points, f)

with open('data/adverse_segments.geojson', 'w') as f:
    json.dump(adverse_segments, f)

map.save('output/map.html')
