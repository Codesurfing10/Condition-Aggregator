// app.js — Condition Aggregator
// Geolocation + NOAA/NDBC integration + 3-D conditions chart

const API_BASE    = 'https://condition-aggregator-api.onrender.com';
const NOMINATIM   = 'https://nominatim.openstreetmap.org/search';

const DEFAULTS = {
    start: { lat: 24.1426, lon: -110.3128, label: 'La Paz, MX' },
    end:   { lat: 49.2827, lon: -123.1207, label: 'Vancouver, BC' },
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const form         = document.getElementById('routeForm');
const startEl      = document.getElementById('start');
const endEl        = document.getElementById('end');
const startHint    = document.getElementById('startHint');
const endHint      = document.getElementById('endHint');
const computeBtn   = document.getElementById('computeBtn');
const condDot      = document.getElementById('condDot');
const condSpinner  = document.getElementById('condSpinner');
const maxWindEl    = document.getElementById('maxWind');
const maxWaveEl    = document.getElementById('maxWave');
const avgWindEl    = document.getElementById('avgWind');
const dataPointsEl = document.getElementById('dataPoints');
const stationCountEl = document.getElementById('stationCount');
const noDataMsg    = document.getElementById('noDataMsg');
const condGrid     = document.getElementById('conditionsGrid');

// ── State ─────────────────────────────────────────────────────────────────────
let startCoords = { ...DEFAULTS.start };
let endCoords   = { ...DEFAULTS.end };
let currentRouteContext = null;
let buoyLayer   = null;

// ── Leaflet Map ───────────────────────────────────────────────────────────────
const map = L.map('map').setView([36, -120], 4);

// ESRI Ocean base — much better for maritime use
L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}',
    {
        attribution: 'Tiles &copy; Esri, GEBCO, NOAA, CHS, OSU',
        maxZoom: 13,
    }
).addTo(map);

// ESRI Ocean reference overlay (labels, place names)
L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}',
    { maxZoom: 13, opacity: 0.75 }
).addTo(map);

buoyLayer = L.layerGroup().addTo(map);

let startMarker = null, endMarker = null, routeLine = null;

// ── Marker helpers ────────────────────────────────────────────────────────────
function makeMarker(color, label) {
    return L.divIcon({
        className: '',
        html: `<div style="
            width:13px;height:13px;border-radius:50%;
            background:${color};border:2px solid rgba(255,255,255,0.85);
            box-shadow:0 0 10px ${color},0 2px 8px rgba(0,0,0,0.5);">
        </div>`,
        iconSize: [13, 13],
        iconAnchor: [6, 6],
        tooltipAnchor: [8, 0],
    });
}

function makeBuoyIcon(windKnots) {
    const color = windKnots > 25 ? '#ff5555'
                : windKnots > 15 ? '#ffaa00'
                :                  '#00dd88';
    return L.divIcon({
        className: '',
        html: `<div style="
            width:9px;height:9px;border-radius:50%;
            background:${color};border:1px solid rgba(255,255,255,0.5);
            box-shadow:0 0 7px ${color};cursor:pointer;">
        </div>`,
        iconSize: [9, 9],
        iconAnchor: [4, 4],
    });
}

// ── Geocoding (Nominatim) ─────────────────────────────────────────────────────
function isLatLon(text) {
    const p = text.split(',').map(s => s.trim());
    return p.length === 2 && p.every(s => Number.isFinite(parseFloat(s)));
}

async function geocode(query, hintEl) {
    if (!query.trim()) return null;
    if (isLatLon(query)) {
        const [lat, lon] = query.split(',').map(Number);
        return { lat, lon };
    }
    hintEl.textContent = '🔍 Resolving…';
    hintEl.className = 'geo-hint resolving';
    try {
        const url = `${NOMINATIM}?q=${encodeURIComponent(query)}&format=json&limit=1`;
        const res  = await fetch(url, { headers: { 'Accept-Language': 'en' } });
        const data = await res.json();
        if (!data || !data[0]) {
            hintEl.textContent = '⚠ Location not found';
            hintEl.className = 'geo-hint error';
            return null;
        }
        const r = data[0];
        hintEl.textContent = `✓ ${r.display_name.split(',').slice(0, 2).join(',')}`;
        hintEl.className = 'geo-hint resolved';
        return { lat: parseFloat(r.lat), lon: parseFloat(r.lon) };
    } catch (err) {
        hintEl.textContent = '⚠ Geocoding failed';
        hintEl.className = 'geo-hint error';
        return null;
    }
}

// ── Browser Geolocation ───────────────────────────────────────────────────────
document.getElementById('geoStart').addEventListener('click', () => {
    if (!navigator.geolocation) {
        startHint.textContent = '⚠ Geolocation not supported';
        startHint.className = 'geo-hint error';
        return;
    }
    startHint.textContent = '📡 Getting location…';
    startHint.className = 'geo-hint resolving';
    navigator.geolocation.getCurrentPosition(
        pos => {
            const { latitude: lat, longitude: lon } = pos.coords;
            startEl.value = `${lat.toFixed(4)},${lon.toFixed(4)}`;
            startCoords = { lat, lon };
            startHint.textContent = '✓ Using your GPS location';
            startHint.className = 'geo-hint resolved';
        },
        err => {
            startHint.textContent = `⚠ ${err.message}`;
            startHint.className = 'geo-hint error';
        }
    );
});

// ── Route Drawing ─────────────────────────────────────────────────────────────
function setMarkers(start, end) {
    if (startMarker) startMarker.remove();
    if (endMarker)   endMarker.remove();

    startMarker = L.marker([start.lat, start.lon], {
        icon: makeMarker('#00dd88', 'Start'),
        draggable: true,
    }).addTo(map).bindTooltip('Start', { permanent: false });

    endMarker = L.marker([end.lat, end.lon], {
        icon: makeMarker('#ff5555', 'End'),
        draggable: true,
    }).addTo(map).bindTooltip('End', { permanent: false });

    startMarker.on('dragend', () => {
        const p = startMarker.getLatLng();
        startCoords = { lat: p.lat, lon: p.lng };
        startEl.value = `${p.lat.toFixed(4)},${p.lng.toFixed(4)}`;
        startHint.textContent = '';
        computeAndRender();
    });

    endMarker.on('dragend', () => {
        const p = endMarker.getLatLng();
        endCoords = { lat: p.lat, lon: p.lng };
        endEl.value = `${p.lat.toFixed(4)},${p.lng.toFixed(4)}`;
        endHint.textContent = '';
        computeAndRender();
    });

    map.fitBounds(
        L.latLngBounds([start.lat, start.lon], [end.lat, end.lon]).pad(0.2)
    );
}

function drawRoute(points) {
    if (routeLine) routeLine.remove();
    routeLine = L.polyline(
        points.map(p => [p.lat, p.lon]),
        { color: '#00c8e0', weight: 3, opacity: 0.9 }
    ).addTo(map);
}

// ── NOAA Buoy Markers ─────────────────────────────────────────────────────────
function buildPopupHtml(station, cond) {
    const rows = [
        ['Wind',       cond.wind_speed_knots != null ? `${cond.wind_speed_knots} kts` : '—'],
        ['Gust',       cond.wind_gust_knots  != null ? `${cond.wind_gust_knots} kts`  : '—'],
        ['Waves',      cond.wave_height_ft   != null ? `${cond.wave_height_ft} ft`    : '—'],
        ['Period',     cond.dominant_period_s!= null ? `${cond.dominant_period_s} s`  : '—'],
        ['Air Temp',   cond.air_temp_c       != null ? `${cond.air_temp_c} °C`        : '—'],
        ['Water Temp', cond.water_temp_c     != null ? `${cond.water_temp_c} °C`      : '—'],
        ['Pressure',   cond.pressure_hpa     != null ? `${cond.pressure_hpa} hPa`     : '—'],
    ];
    return `<div class="buoy-popup">
        <h4>🛰 ${station.id} — ${station.name || 'NDBC Buoy'}</h4>
        <table>${rows.map(([l, v]) => `<tr><td>${l}</td><td>${v}</td></tr>`).join('')}</table>
        <p style="margin:5px 0 0;font-size:0.65rem;color:#3a6a8a;">${station.distance_km} km from route</p>
    </div>`;
}

function renderBuoyMarkers(samplePoints) {
    buoyLayer.clearLayers();
    const seen = new Set();
    samplePoints.forEach(pt => {
        if (!pt.nearest_station || !pt.conditions) return;
        const sid = pt.nearest_station.id;
        if (seen.has(sid)) return;
        seen.add(sid);
        const wind = pt.conditions.wind_speed_knots || 0;
        L.marker([pt.lat, pt.lon], { icon: makeBuoyIcon(wind) })
            .addTo(buoyLayer)
            .bindPopup(buildPopupHtml(pt.nearest_station, pt.conditions), { maxWidth: 220 });
    });
    stationCountEl.textContent = `${seen.size} buoy${seen.size !== 1 ? 's' : ''} sampled`;
}

// ── 3-D Plotly Conditions Chart ───────────────────────────────────────────────
function renderChart3D(samplePoints) {
    const pts = (samplePoints || []).filter(
        p => p.conditions && p.conditions.wind_speed_knots != null
    );

    if (pts.length === 0) {
        // Styled stub chart when no NOAA data
        Plotly.newPlot('plotlyChart',
            [{ x: Array.from({length: 11}, (_, i) => i), y: Array(11).fill(0),
               type: 'scatter', mode: 'lines', name: 'Wind (kts)',
               line: { color: '#00c8e0', width: 2 } }],
            {
                title: { text: 'No buoy data for this route', font: { color: '#5a8aaa', size: 13 } },
                paper_bgcolor: 'rgba(4,12,30,0.98)',
                plot_bgcolor:  'rgba(0,0,0,0)',
                font:   { color: '#c8daf5' },
                xaxis:  { title: 'Sample', gridcolor: '#162840', color: '#5a8aaa', zeroline: false },
                yaxis:  { title: 'Wind (kts)', gridcolor: '#162840', color: '#5a8aaa', zeroline: false },
                margin: { t: 40, r: 20, b: 45, l: 55 },
            },
            { displayModeBar: false }
        );
        return;
    }

    // Compute cumulative distances for the X axis
    // 111.12 km ≈ 1 degree of latitude (mean Earth radius conversion)
    const KM_PER_DEG = 111.12;
    const allPts = samplePoints;
    const cumDist = [0];
    for (let i = 1; i < allPts.length; i++) {
        const a = allPts[i - 1], b = allPts[i];
        const dlat = b.lat - a.lat, dlon = b.lon - a.lon;
        cumDist.push(cumDist[i - 1] + Math.sqrt(dlat * dlat + dlon * dlon) * KM_PER_DEG);
    }

    // Build an index map to avoid O(n²) indexOf calls
    const ptIndexMap = new Map(allPts.map((p, i) => [p, i]));
    const x = pts.map(p => Math.round(cumDist[ptIndexMap.get(p) ?? 0]));
    const y = pts.map(p => p.conditions.wind_speed_knots   ?? 0);
    const z = pts.map(p => p.conditions.wave_height_ft     ?? 0);
    const c = pts.map(p => p.conditions.air_temp_c         ?? 20);
    const text = pts.map(p =>
        p.nearest_station
            ? `${p.nearest_station.id}<br>${p.nearest_station.name || ''}`
            : ''
    );

    Plotly.newPlot('plotlyChart',
        [{
            type: 'scatter3d',
            x, y, z, text,
            mode: 'markers+lines',
            marker: {
                size: z.map(h => Math.max(4, (h || 0) * 1.6)),
                color: c,
                colorscale: 'Viridis',
                showscale: true,
                colorbar: {
                    title: 'Air °C',
                    tickfont:  { color: '#c8daf5', size: 10 },
                    titlefont: { color: '#c8daf5', size: 10 },
                    thickness: 12, len: 0.6,
                },
                opacity: 0.9,
            },
            line: { color: '#00c8e0', width: 4 },
            hovertemplate:
                '%{text}<br>Dist: %{x} km<br>Wind: %{y:.1f} kts<br>Wave: %{z:.1f} ft<extra></extra>',
        }],
        {
            scene: {
                xaxis: { title: 'Dist (km)',  gridcolor: '#162840', color: '#5a8aaa', zerolinecolor: '#1e3a5a' },
                yaxis: { title: 'Wind (kts)', gridcolor: '#162840', color: '#5a8aaa', zerolinecolor: '#1e3a5a' },
                zaxis: { title: 'Wave (ft)',  gridcolor: '#162840', color: '#5a8aaa', zerolinecolor: '#1e3a5a' },
                bgcolor: 'rgba(4,12,30,0.98)',
                camera: { eye: { x: 1.7, y: 1.7, z: 0.85 } },
                aspectmode: 'manual',
                aspectratio: { x: 2, y: 1, z: 0.7 },
            },
            paper_bgcolor: 'rgba(4,12,30,0.98)',
            font: { color: '#c8daf5' },
            margin: { t: 10, r: 10, b: 10, l: 10 },
            showlegend: false,
        },
        { displayModeBar: false }
    );
}

// ── Conditions Summary ────────────────────────────────────────────────────────
function setValueColor(el, value, warnAt, dangerAt) {
    el.classList.remove('ok', 'warn', 'danger');
    if (value == null) return;
    el.classList.add(value >= dangerAt ? 'danger' : value >= warnAt ? 'warn' : 'ok');
}

function updateSummary(summary) {
    const hasData = summary && summary.data_points > 0;
    noDataMsg.style.display  = hasData ? 'none'  : 'block';
    condGrid.style.display   = hasData ? 'grid'  : 'none';
    condDot.classList.remove('loading');

    if (!hasData) return;

    maxWindEl.textContent    = summary.max_wind_knots ?? '—';
    maxWaveEl.textContent    = summary.max_wave_ft    ?? '—';
    avgWindEl.textContent    = summary.avg_wind_knots ?? '—';
    dataPointsEl.textContent = summary.data_points    ?? '—';

    setValueColor(maxWindEl, summary.max_wind_knots, 15, 25);
    setValueColor(maxWaveEl, summary.max_wave_ft,     6, 12);

    currentRouteContext = {
        start_lat:          startCoords.lat,
        start_lon:          startCoords.lon,
        end_lat:            endCoords.lat,
        end_lon:            endCoords.lon,
        max_wind_knots:     summary.max_wind_knots,
        avg_wind_knots:     summary.avg_wind_knots,
        max_wave_ft:        summary.max_wave_ft,
        noaa_buoys_sampled: summary.data_points,
    };
}

// ── Main Compute ──────────────────────────────────────────────────────────────
async function computeAndRender() {
    computeBtn.disabled = true;
    condDot.classList.add('loading');
    condSpinner.style.display = 'block';
    noDataMsg.style.display   = 'none';
    condGrid.style.display    = 'none';

    // Resolve locations
    const sCoords = await geocode(startEl.value, startHint);
    if (sCoords) startCoords = sCoords;

    const eCoords = await geocode(endEl.value, endHint);
    if (eCoords) endCoords = eCoords;

    setMarkers(startCoords, endCoords);
    drawRoute([startCoords, endCoords]); // provisional straight line

    try {
        const res = await fetch(`${API_BASE}/api/route`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                start: { lat: startCoords.lat, lon: startCoords.lon },
                end:   { lat: endCoords.lat,   lon: endCoords.lon },
                sample_interval_km: 10,
                constraints: { mode: 'conservative' },
            }),
        });
        if (!res.ok) throw new Error(`API ${res.status}`);
        const data = await res.json();

        if (data.route_sample_points && data.route_sample_points.length > 1) {
            drawRoute(data.route_sample_points);
            renderBuoyMarkers(data.route_sample_points);
            renderChart3D(data.route_sample_points);
        }
        updateSummary(data.summary);
    } catch (err) {
        console.warn('Route API error:', err.message);
        renderChart3D([]);
        updateSummary(null);
    } finally {
        computeBtn.disabled = false;
        condSpinner.style.display = 'none';
    }
}

form.addEventListener('submit', async e => {
    e.preventDefault();
    await computeAndRender();
});

// ── AI Chat ───────────────────────────────────────────────────────────────────
const chatLog   = document.getElementById('chatLog');
const chatInput = document.getElementById('chatInput');
const chatSend  = document.getElementById('chatSend');

function escapeHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function appendChat(role, text) {
    const p = document.createElement('p');
    p.style.margin = '4px 0';
    if (role === 'user')  p.innerHTML = `<span class="chat-user">You:</span> ${escapeHtml(text)}`;
    else if (role === 'ai') p.innerHTML = `<span class="chat-ai">Assistant:</span> ${escapeHtml(text)}`;
    else p.innerHTML = `<span class="chat-err">Error:</span> ${escapeHtml(text)}`;
    chatLog.appendChild(p);
    chatLog.scrollTop = chatLog.scrollHeight;
}

async function sendChat() {
    const message = chatInput.value.trim();
    if (!message) return;
    chatInput.value = '';
    chatSend.disabled = true;
    appendChat('user', message);
    try {
        const body = { message };
        if (currentRouteContext) body.context = currentRouteContext;
        const res = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            appendChat('error', err.detail || 'Request failed.');
        } else {
            const data = await res.json();
            appendChat('ai', data.reply || '(no reply)');
        }
    } catch (err) {
        appendChat('error', `Network error: ${err.message}`);
    } finally {
        chatSend.disabled = false;
        chatInput.focus();
    }
}

chatSend.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });

// ── First render ──────────────────────────────────────────────────────────────
// Use lat,lon strings so the geocode function can parse them directly without
// making unnecessary Nominatim requests on the initial load.
startEl.value = `${DEFAULTS.start.lat},${DEFAULTS.start.lon}`;
endEl.value   = `${DEFAULTS.end.lat},${DEFAULTS.end.lon}`;
computeAndRender();
