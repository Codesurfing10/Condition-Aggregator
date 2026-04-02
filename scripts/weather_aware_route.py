import json
import folium
import os

# Coordinates for San Diego and San Francisco
# Store in (lat, lon) for folium Marker/location usage
coordinates_latlon = {
    'San Diego': (32.7157, -117.1611),
    'San Francisco': (37.7749, -122.4194)
}

# GeoJSON requires [lon, lat]
coordinates_lonlat = {
    city: [lon, lat]
    for city, (lat, lon) in coordinates_latlon.items()
}

# Create data and output directories if they don't exist
os.makedirs('data', exist_ok=True)
os.makedirs('output', exist_ok=True)

# Reference points GeoJSON
reference_points = {
    'type': 'FeatureCollection',
    'features': [
        {
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': coordinates_lonlat['San Diego']},
            'properties': {'city': 'San Diego', 'type': 'city'}
        },
        {
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': coordinates_lonlat['San Francisco']},
            'properties': {'city': 'San Francisco', 'type': 'city'}
        },
        {
            'type': 'Feature',
            'geometry': {
                'type': 'LineString',
                'coordinates': [coordinates_lonlat['San Diego'], coordinates_lonlat['San Francisco']]
            },
            'properties': {'name': 'Route (smoke test)', 'type': 'reference_path'}
        }
    ]
}

# Save reference points
with open('data/reference_points.geojson', 'w', encoding='utf-8') as f:
    json.dump(reference_points, f, indent=2)

# Adverse segments GeoJSON
adverse_segments = {
    'type': 'FeatureCollection',
    'features': [
        {
            'type': 'Feature',
            'geometry': {
                'type': 'LineString',
                'coordinates': [coordinates_lonlat['San Diego'], coordinates_lonlat['San Francisco']]
            },
            'properties': {'adverse': True, 'reason': 'smoke_test'}
        },
    ]
}

# Save adverse segments
with open('data/adverse_segments.geojson', 'w', encoding='utf-8') as f:
    json.dump(adverse_segments, f, indent=2)

# Create folium map
sd_lat, sd_lon = coordinates_latlon['San Diego']
sf_lat, sf_lon = coordinates_latlon['San Francisco']
m = folium.Map(
    location=[(sd_lat + sf_lat) / 2, (sd_lon + sf_lon) / 2],
    zoom_start=6,
    tiles='OpenStreetMap'
)

# Add GeoJSON layers to the map (pass dicts so output HTML is self-contained)
folium.GeoJson(reference_points, name='Reference Points', style_function=lambda _: {'color': 'blue'}).add_to(m)
folium.GeoJson(adverse_segments, name='Adverse Segments', style_function=lambda _: {'color': 'red'}).add_to(m)
folium.LayerControl().add_to(m)

# Add markers
for city, coord in coordinates_latlon.items():
    folium.Marker(location=coord, popup=city).add_to(m)

# Fit bounds to both cities
m.fit_bounds([coordinates_latlon['San Diego'], coordinates_lonlat['San Francisco']])

# Save output map
m.save('output/map.html')

# Print output paths
print('Generated files:')
print('data/reference_points.geojson')
print('data/adverse_segments.geojson')
print('output/map.html')

raise SystemExit(0)
