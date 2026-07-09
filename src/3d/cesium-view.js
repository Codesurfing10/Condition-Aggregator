// src/3d/cesium-view.js
// Lightweight Cesium integration for a globe view and a simple model that follows a route.

// This module expects Cesium to be available via import or global Cesium (installed via npm).

export async function initCesium(containerId) {
  const Cesium = (await import('cesium')).default || (await import('cesium'));

  // Cesium base path setup for static assets when used in Electron
  // If Cesium assets are not served, set the baseUrl to the node_modules path (works in dev)
  if (typeof window !== 'undefined' && Cesium.BuildModuleUrl) {
    // In some builds this function exists; otherwise set manually
  }

  const viewer = new Cesium.Viewer(containerId, {
    timeline: false,
    animation: false,
    sceneModePicker: true,
    baseLayerPicker: false,
    geocoder: false,
  });

  return viewer;
}

export function addRouteToCesium(viewer, routeCoords) {
  if (!viewer || !routeCoords || routeCoords.length === 0) return null;
  const Cesium = window.Cesium;
  const positions = [];
  routeCoords.forEach(p => {
    positions.push(Cesium.Cartesian3.fromDegrees(p.lon, p.lat, 0.0));
  });

  // Add a polyline that represents the route
  const line = viewer.entities.add({
    polyline: {
      positions,
      width: 4,
      material: Cesium.Color.CYAN,
      clampToGround: true,
    }
  });

  // Zoom to route
  viewer.zoomTo(line);
  return line;
}

export async function addShipModel(viewer, routeCoords, modelUrl) {
  const Cesium = window.Cesium;
  if (!routeCoords || routeCoords.length === 0) return null;

  // Use a sample GLTF if none provided
  modelUrl = modelUrl || 'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Models/master/2.0/Cube/glTF/Cube.gltf';

  const start = routeCoords[0];
  const position = Cesium.Cartesian3.fromDegrees(start.lon, start.lat, 0);

  // Create a position property with samples along the path so the model can be animated
  const property = new Cesium.SampledPositionProperty();
  let totalSeconds = 0;
  const speedKts = 12; // default ship speed (~22 km/h)
  for (let i = 0; i < routeCoords.length; i++) {
    const p = routeCoords[i];
    if (i > 0) {
      const prev = routeCoords[i - 1];
      const d = haversine(prev.lat, prev.lon, p.lat, p.lon); // km
      const hrs = d / (speedKts * 1.852);
      totalSeconds += Math.round(hrs * 3600);
    }
    const time = Cesium.JulianDate.addSeconds(Cesium.JulianDate.now(), totalSeconds, new Cesium.JulianDate());
    property.addSample(time, Cesium.Cartesian3.fromDegrees(p.lon, p.lat, 0));
  }

  const entity = viewer.entities.add({
    availability: new Cesium.TimeIntervalCollection([new Cesium.TimeInterval({ start: Cesium.JulianDate.now(), stop: Cesium.JulianDate.addSeconds(Cesium.JulianDate.now(), Math.max(60, totalSeconds), new Cesium.JulianDate()) })]),
    position: property,
    model: { uri: modelUrl, minimumPixelSize: 32, maximumScale: 200 },
    orientation: new Cesium.VelocityOrientationProperty(property),
  });

  // Start clock
  viewer.clock.startTime = Cesium.JulianDate.now();
  viewer.clock.currentTime = Cesium.JulianDate.now();
  viewer.clock.multiplier = 1;
  viewer.clock.shouldAnimate = true;

  viewer.trackedEntity = entity;
  return entity;
}

function haversine(lat1, lon1, lat2, lon2) {
  const toRad = v => (v * Math.PI) / 180;
  const R = 6371; // km
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}
