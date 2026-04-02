import geojson
import folium

# Function to create valid GeoJSON data with points and a LineString route

def create_geojson_route(start_coords, end_coords):
    # Create points for start and end locations
    start_point = geojson.Point((start_coords[0], start_coords[1]))
    end_point = geojson.Point((end_coords[0], end_coords[1]))

    # Create a LineString route
    line = geojson.LineString([(start_coords[0], start_coords[1]), (end_coords[0], end_coords[1])])

    # Create a FeatureCollection
    feature_collection = geojson.FeatureCollection([
        geojson.Feature(geometry=start_point, properties={}),
        geojson.Feature(geometry=end_point, properties={}),
        geojson.Feature(geometry=line, properties={'route': 'valid'})
    ])

    return feature_collection

# Example coordinates
city_a_coords = (-122.4194, 37.7749)  # San Francisco
city_b_coords = (-118.2437, 34.0522)  # Los Angeles

# Create GeoJSON route
geojson_data = create_geojson_route(city_a_coords, city_b_coords)

# Save adverse segments as geojson with properties
adverse_segments = geojson.FeatureCollection([
    geojson.Feature(
        geometry=geojson.LineString([city_a_coords, city_b_coords]),
        properties={'adverse': True}
    )
])

# Add to folium
map = folium.Map(location=[(city_a_coords[1] + city_b_coords[1]) / 2, (city_a_coords[0] + city_b_coords[0]) / 2], zoom_start=6)
folium.GeoJson(geojson_data).add_to(map)
folium.GeoJson(adverse_segments).add_to(map)
map.fit_bounds([(city_a_coords[1], city_a_coords[0]), (city_b_coords[1], city_b_coords[0])])

map.save('smoke_test_map.html')