import os
import json

# Create necessary directories
os.makedirs('data/reference_points.geojson', exist_ok=True)
os.makedirs('data/adverse_segments.geojson', exist_ok=True)
os.makedirs('output', exist_ok=True)

# GeoJSON FeatureCollection for San Diego and San Francisco
reference_points = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [-117.1611, 32.7157]  # San Diego
            },
            "properties": {"name": "San Diego"}
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [-122.4194, 37.7749]  # San Francisco
            },
            "properties": {"name": "San Francisco"}
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [-117.1611, 32.7157],
                    [-122.4194, 37.7749]
                ]
            },
            "properties": {"name": "Line from SD to SF"}
        }
    ]
}

# Write reference points to GeoJSON file
with open('data/reference_points.geojson', 'w') as f:
    json.dump(reference_points, f)

# Empty GeoJSON FeatureCollection for adverse segments
adverse_segments = {"type": "FeatureCollection", "features": []}
with open('data/adverse_segments.geojson', 'w') as f:
    json.dump(adverse_segments, f)

# Create simple HTML file
with open('output/map.html', 'w') as f:
    f.write('<!DOCTYPE html>\n<html>\n<head><title>Smoke Test</title></head>\n<body>\n<h1>Smoke test OK</h1>\n<p>Coordinates:</p>\n<ul>\n<li>San Diego: (-117.1611, 32.7157)</li>\n<li>San Francisco: (-122.4194, 37.7749)</li>\n</ul>\n</body>\n</html>')

# Exit successfully
exit(0)