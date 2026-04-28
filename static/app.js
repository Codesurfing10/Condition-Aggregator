// GitHub Pages static-only implementation (no backend).
// - Draws a stub route polyline between start/end
// - Renders a placeholder Plotly chart (10-minute horizon)
// - Uses La Paz -> Vancouver defaults unless user overrides

(function () {
  const DEFAULTS = {
    start: { lat: 24.1426, lon: -110.3128 }, // La Paz, MX
    end: { lat: 49.2827, lon: -123.1207 },   // Vancouver, BC
    sampleKm: 10,
    horizonMin: 10
  };

  const form = document.getElementById("routeForm");
  const startEl = document.getElementById("start");
  const endEl = document.getElementById("end");
  const mapElId = "map";
  const chartElId = "plotlyChart";

  if (!form || !startEl || !endEl) {
    console.error("Missing expected elements: #routeForm, #start, #end");
    return;
  }

  // Accept input format: "lat,lon" (e.g. "24.1426,-110.3128")
  function parseLatLon(text, fallback) {
    if (!text || !text.trim()) return fallback;
    const parts = text.split(",").map(s => s.trim());
    if (parts.length !== 2) return fallback;
    const lat = parseFloat(parts[0]);
    const lon = parseFloat(parts[1]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return fallback;
    return { lat, lon };
  }

  function formatLatLon(p) {
    return `${p.lat.toFixed(4)},${p.lon.toFixed(4)}`;
  }

  // Initialize input fields with defaults (lat,lon)
  if (!startEl.value) startEl.value = formatLatLon(DEFAULTS.start);
  if (!endEl.value) endEl.value = formatLatLon(DEFAULTS.end);

  // Leaflet map
  const map = L.map(mapElId);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap",
  }).addTo(map);

  let startMarker = null;
  let endMarker = null;
  let routeLine = null;

  function setMarkers(start, end) {
    if (startMarker) startMarker.remove();
    if (endMarker) endMarker.remove();

    startMarker = L.marker([start.lat, start.lon], { draggable: true })
      .addTo(map)
      .bindPopup("Start (drag me)");

    endMarker = L.marker([end.lat, end.lon], { draggable: true })
      .addTo(map)
      .bindPopup("End (drag me)");

    startMarker.on("dragend", () => {
      const p = startMarker.getLatLng();
      startEl.value = formatLatLon({ lat: p.lat, lon: p.lng });
      computeAndRender();
    });

    endMarker.on("dragend", () => {
      const p = endMarker.getLatLng();
      endEl.value = formatLatLon({ lat: p.lat, lon: p.lng });
      computeAndRender();
    });

    const bounds = L.latLngBounds(
      [start.lat, start.lon],
      [end.lat, end.lon]
    );
    map.fitBounds(bounds.pad(0.25));
  }

  function interpolatePolyline(start, end, steps = 80) {
    const pts = [];
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      pts.push([
        start.lat + (end.lat - start.lat) * t,
        start.lon + (end.lon - start.lon) * t,
      ]);
    }
    return pts;
  }

  function drawRoute(latlngs) {
    if (routeLine) routeLine.remove();
    routeLine = L.polyline(latlngs, { color: "#1f77b4", weight: 4 }).addTo(map);
    map.fitBounds(routeLine.getBounds().pad(0.15));
  }

  function renderChart() {
    // Static placeholder: 10-minute horizon, zeros until backend is added
    const x = Array.from({ length: DEFAULTS.horizonMin + 1 }, (_, i) => i); // 0..10
    const windKnots = x.map(() => 0);
    const wavesFeet = x.map(() => 0);

    Plotly.newPlot(
      chartElId,
      [
        { x, y: windKnots, mode: "lines", name: "Wind (knots)" },
        { x, y: wavesFeet, mode: "lines", name: "Waves (ft)" },
      ],
      {
        title: "Anticipated Conditions (static stub, 10-minute horizon)",
        margin: { t: 40, r: 10, b: 40, l: 60 },
        xaxis: { title: "Minutes" },
      },
      { displayModeBar: false }
    );
  }

  function computeAndRender() {
    const start = parseLatLon(startEl.value, DEFAULTS.start);
    const end = parseLatLon(endEl.value, DEFAULTS.end);

    // Create and draw a stub route
    const latlngs = interpolatePolyline(start, end, 80);

    setMarkers(start, end);
    drawRoute(latlngs);
    renderChart();
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    computeAndRender();
  });

  // First render
  computeAndRender();

  // Help text for users
  const hint = document.createElement("p");
  hint.style.fontSize = "12px";
  hint.style.color = "#555";
  hint.textContent =
    'Tip: enter coordinates as "lat,lon" (example: 24.1426,-110.3128). Drag markers to update.';
  form.parentNode.insertBefore(hint, form.nextSibling);
})();
