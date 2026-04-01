import requests
import folium
from geopy.geocoders import Nominatim

# Initialize Nominatim API
geolocator = Nominatim(user_agent="geoapiExercises")

# Function to geocode a city
def geocode_city(city):
    location = geolocator.geocode(city)
    return location.latitude, location.longitude

# Geocode cities
cities = ["San Diego", "San Francisco"]
points = []
for city in cities:
    lat, lon = geocode_city(city)
    points.append((lat, lon))
    
# Create a GeoJSON FeatureCollection
features = []
for i, point in enumerate(points):
    features.append({
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [point[1], point[0]]
        },
        "properties": {
            "name": cities[i]
        }
    })

# Create a LineString route
route = {
    "type": "Feature",
    "geometry": {
        "type": "LineString",
        "coordinates": [
            [points[0][1], points[0][0]],
            [points[1][1], points[1][0]]
        ]
    },
    "properties": {
        "name": "Route from San Diego to San Francisco"
    }
}
features.append(route)

# Create FeatureCollection
geojson = {
    "type": "FeatureCollection",
    "features": features
}

# Save GeoJSON to file
with open('data/reference_points.geojson', 'w') as f:
    import json
    json.dump(geojson, f)

# Create a map
m = folium.Map(location=points[0], zoom_start=6)

# Add points to the map
for point in points:
    folium.Marker(location=point).add_to(m)

# Add route to the map
folium.PolyLine([points], color="blue", weight=2.5, opacity=1).add_to(m)

# Save the map as an HTML file
m.save('output/map.html')
