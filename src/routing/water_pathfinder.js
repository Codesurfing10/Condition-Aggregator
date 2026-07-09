// src/routing/water_pathfinder.js
// Coarse grid A* pathfinder that avoids land polygons.

// Very small, dependency-free implementation. For production, replace with a library
// such as turf.js for robust geo operations.

export async function loadLandGeoJSON(localPath) {
  // Attempt to load local static file; fallback to a public Natural Earth raw file
  try {
    const res = await fetch(localPath);
    if (!res.ok) throw new Error('Local land file not found');
    return await res.json();
  } catch (err) {
    // Fallback URL (simplified world land polygons)
    const fallback = 'https://raw.githubusercontent.com/datasets/geo-boundaries-world-110m/master/countries.geojson';
    const r2 = await fetch(fallback);
    if (!r2.ok) throw new Error('Could not fetch fallback land polygons');
    return await r2.json();
  }
}

function pointInPolygon(point, polygon) {
  // Basic ray-casting algorithm for a single polygon (no holes). polygon: [ [lon,lat], ... ]
  const x = point[0], y = point[1];
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1];
    const xj = polygon[j][0], yj = polygon[j][1];

    const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi + 0.0) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function isPointOverLand(lon, lat, landGeo) {
  if (!landGeo || !landGeo.features) return false;
  for (const feat of landGeo.features) {
    const geom = feat.geometry;
    if (!geom) continue;
    if (geom.type === 'Polygon') {
      for (const ring of geom.coordinates) {
        if (pointInPolygon([lon, lat], ring)) return true;
      }
    } else if (geom.type === 'MultiPolygon') {
      for (const poly of geom.coordinates) {
        for (const ring of poly) {
          if (pointInPolygon([lon, lat], ring)) return true;
        }
      }
    }
  }
  return false;
}

export function buildGrid(bounds, stepDeg) {
  // bounds: { minLat, maxLat, minLon, maxLon }
  const grid = [];
  for (let lat = bounds.minLat; lat <= bounds.maxLat; lat += stepDeg) {
    const row = [];
    for (let lon = bounds.minLon; lon <= bounds.maxLon; lon += stepDeg) {
      row.push({ lat: +lat.toFixed(6), lon: +lon.toFixed(6), blocked: false });
    }
    grid.push(row);
  }
  return grid;
}

function coordToIndex(lat, lon, bounds, stepDeg) {
  const i = Math.round((lat - bounds.minLat) / stepDeg);
  const j = Math.round((lon - bounds.minLon) / stepDeg);
  return { i, j };
}

export function markLandOnGrid(grid, bounds, stepDeg, landGeo) {
  for (let i = 0; i < grid.length; i++) {
    for (let j = 0; j < grid[i].length; j++) {
      const cell = grid[i][j];
      // sample center point
      const lon = bounds.minLon + j * stepDeg;
      const lat = bounds.minLat + i * stepDeg;
      cell.blocked = isPointOverLand(lon, lat, landGeo);
    }
  }
}

function neighbors(grid, i, j) {
  const deltas = [
    [-1, 0], [1, 0], [0, -1], [0, 1],
    [-1, -1], [-1, 1], [1, -1], [1, 1]
  ];
  const res = [];
  for (const [di, dj] of deltas) {
    const ni = i + di, nj = j + dj;
    if (ni < 0 || ni >= grid.length) continue;
    if (nj < 0 || nj >= grid[0].length) continue;
    if (grid[ni][nj].blocked) continue;
    res.push({ i: ni, j: nj });
  }
  return res;
}

function heuristic(aLat, aLon, bLat, bLon) {
  // haversine
  const R = 6371;
  const toRad = v => (v * Math.PI) / 180;
  const dLat = toRad(bLat - aLat);
  const dLon = toRad(bLon - aLon);
  const A = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLon / 2) ** 2;
  const C = 2 * Math.atan2(Math.sqrt(A), Math.sqrt(1 - A));
  return R * C;
}

export function findPathAStar(grid, bounds, stepDeg, start, end) {
  const { i: si, j: sj } = coordToIndex(start.lat, start.lon, bounds, stepDeg);
  const { i: ei, j: ej } = coordToIndex(end.lat, end.lon, bounds, stepDeg);
  if (si < 0 || sj < 0 || ei < 0 || ej < 0) return null;
  if (grid[si][sj].blocked || grid[ei][ej].blocked) return null;

  const open = new Map(); // key -> node
  const closed = new Set();
  function key(i, j) { return `${i},${j}`; }

  const startKey = key(si, sj);
  open.set(startKey, { i: si, j: sj, g: 0, f: heuristic(start.lat, start.lon, end.lat, end.lon), parent: null });

  while (open.size > 0) {
    // pick lowest f
    let currentKey = null, current = null;
    for (const [k, node] of open.entries()) {
      if (!current || node.f < current.f) { current = node; currentKey = k; }
    }

    if (current.i === ei && current.j === ej) {
      // reconstruct
      const path = [];
      let cur = current;
      while (cur) {
        const lat = bounds.minLat + cur.i * stepDeg;
        const lon = bounds.minLon + cur.j * stepDeg;
        path.push({ lat, lon });
        cur = cur.parent;
      }
      return path.reverse();
    }

    open.delete(currentKey);
    closed.add(currentKey);

    for (const n of neighbors(grid, current.i, current.j)) {
      const nk = key(n.i, n.j);
      if (closed.has(nk)) continue;
      const lat = bounds.minLat + n.i * stepDeg;
      const lon = bounds.minLon + n.j * stepDeg;
      const gScore = current.g + heuristic(bounds.minLat + current.i * stepDeg, bounds.minLon + current.j * stepDeg, lat, lon);
      const existing = open.get(nk);
      if (!existing || gScore < existing.g) {
        const h = heuristic(lat, lon, bounds.minLat + ei * stepDeg, bounds.minLon + ej * stepDeg);
        open.set(nk, { i: n.i, j: n.j, g: gScore, f: gScore + h, parent: current });
      }
    }
  }

  return null;
}
