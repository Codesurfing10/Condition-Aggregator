#!/usr/bin/env bash
# scripts/download_land.sh
# Downloads a small Natural Earth based GeoJSON (110m or 50m) to static/land.geojson

set -e
OUT_DIR="static/land"
mkdir -p "$OUT_DIR"
# Using Natural Earth via GitHub mirror (simplified) - choose a small resolution
URL="https://raw.githubusercontent.com/datasets/geo-boundaries-world-110m/master/countries.geojson"
OUT="$OUT_DIR/land.geojson"

echo "Downloading land polygons from $URL -> $OUT"
curl -L --fail "$URL" -o "$OUT"

echo "Saved to $OUT"
