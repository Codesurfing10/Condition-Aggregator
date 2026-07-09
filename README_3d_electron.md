### Condition Aggregator — 3D + Electron

This branch (feat/3d-electron) contains an experimental Electron desktop wrapper and Cesium-based 3D globe integration plus a coarse water-only routing prototype.

What I added
- electron/ (main.js, preload.js) — Electron app entry and small IPC bridge
- package.json — scripts and electron-builder config for building installers
- src/3d/cesium-view.js — helper to create Cesium viewer, add route & a moving ship model
- src/routing/water_pathfinder.js — coarse grid A* pathfinder that marks land cells (loads local land file or a fallback remote GeoJSON)
- scripts/download_land.sh — helper to download a simplified GeoJSON of land polygons into static/land/land.geojson

Notes & how to run (dev)
1. Install Node (>=16)
2. From repo root:
   - npm install
   - npm run dev
   This will open the Electron app and load the web UI. In dev mode, Cesium assets may be loaded from the `node_modules/cesium` package.

To download land polygons used for routing (recommended):
  ./scripts/download_land.sh
This will save static/land/land.geojson which the pathfinder will attempt to load first.

Build installers
  npm run build
This uses electron-builder to produce platform artifacts (AppImage, dmg, installer). Building requires platform-specific toolchains for macOS notarization, etc.

Limitations & warnings
- The pathfinder uses a coarse grid and a simple point-in-polygon test implemented in src/routing/water_pathfinder.js. It's meant as a prototype to avoid routes crossing land polygons. It is NOT a substitute for nautical charts, bathymetry, or official voyage planning.
- For production-grade routing, integrate chart data (ENC), depth/bathymetry and professional routing services.

If you want, I can now:
- Wire up the front-end UI to call the routing module and the Cesium view (next commit),
- Add a small sample GLTF ship into static/assets or keep using the public sample model URL.

I will proceed to wire the front-end unless you want changes first.
