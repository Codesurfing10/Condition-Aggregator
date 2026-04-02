import os
import json
import folium


def main():
    # Create required directories
    os.makedirs('data', exist_ok=True)
    os.makedirs('output', exist_ok=True)

    # Fixed reference points (San Diego/San Francisco) in (lat, lon)
    reference_points = [[-117.1611, 32.7157], [-122.4194, 37.7749]]
    adverse_segments = [[-117.1620, 32.7160], [-122.4200, 37.7750]]

    # Write GeoJSON files
    with open('data/reference_points.geojson', 'w', encoding='utf-8') as ref_file:
        json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": point}, "properties": {}} for point in reference_points]}, ref_file, indent=2)

    with open('data/adverse_segments.geojson', 'w', encoding='utf-8') as adv_file:
        json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": segment}, "properties": {}} for segment in adverse_segments]}, adv_file, indent=2)

    # Create leaflet map
    m = folium.Map(location=[32.7157, -117.1611], zoom_start=7)
    folium.Marker(location=[32.7157, -117.1611], popup='San Diego').add_to(m)
    folium.Marker(location=[37.7749, -122.4194], popup='San Francisco').add_to(m)

    # Load GeoJSON data
    folium.GeoJson('data/reference_points.geojson', name='Reference Points').add_to(m)
    folium.GeoJson('data/adverse_segments.geojson', style_function=lambda x: {'color': 'red'}).add_to(m)

    # Save map to HTML
    m.save('output/map.html')
    
    raise SystemExit(0)


if __name__ == '__main__':
    main()