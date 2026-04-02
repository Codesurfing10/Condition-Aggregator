import json
import folium
import os

# Coordinates for San Diego and San Francisco
coordinates = {
    'San Diego': (32.7157, -117.1611),
    'San Francisco': (37.7749, -122.4194)
}

# Create data and output directories if they don't exist
os.makedirs('data', exist_ok=True)
os.makedirs('output', exist_ok=True)

# Reference points GeoJSON
reference_points = {
    'type': 'FeatureCollection',
    'features': [
        {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': coordinates['San Diego']}, 'properties': {'city': 'San Diego'}},
        {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': coordinates['San Francisco']}, 'properties': {'city': 'San Francisco'}},
    ]
}
# Save reference points
with open('data/reference_points.geojson', 'w') as f:
    json.dump(reference_points, f)

# Adverse segments GeoJSON
adverse_segments = {
    'type': 'FeatureCollection',
    'features': [
        {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [coordinates['San Diego'], coordinates['San Francisco']]}, 'properties': {'adverse': True, 'reason': 'smoke_test'}},
    ]
}
# Save adverse segments
with open('data/adverse_segments.geojson', 'w') as f:
    json.dump(adverse_segments, f)

# Create folium map
m = folium.Map(location=[(coordinates['San Diego'][0] + coordinates['San Francisco'][0]) / 2, (coordinates['San Diego'][1] + coordinates['San Francisco'][1]) / 2], zoom_start=6)

# Add GeoJSON layers to the map
folium.GeoJson('data/reference_points.geojson', name='Reference Points', style_function=lambda x: {'color': 'blue'}).add_to(m)
folium.GeoJson('data/adverse_segments.geojson', name='Adverse Segments', style_function=lambda x: {'color': 'red'}).add_to(m)

# Add markers
for city, coord in coordinates.items():
    folium.Marker(location=coord, popup=city).add_to(m)

# Fit bounds to both cities
m.fit_bounds([coordinates['San Diego'], coordinates['San Francisco']])

# Save output map
m.save('output/map.html')

# Print output paths
print('Generated files:')
print('data/reference_points.geojson')
print('data/adverse_segments.geojson')
print('output/map.html')

exit(0)