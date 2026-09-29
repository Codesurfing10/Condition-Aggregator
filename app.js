// app.js — Condition Aggregator (ES module)
// Geolocation + NOAA/NDBC + water-preferring routes + Plotly chart
// Advisory only — NOT for navigation.

import { computeWaterRoute } from './src/routing/water_pathfinder.js';

// API base: ?api= override, then localStorage, then same-origin when UI+API share a host.
// Local split-dev (e.g. Live Server :5500 + API :8000) still points at localhost:8000.
function resolveApiBase() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('api')) return params.get('api').replace(/\/$/, '');
    try {
        const stored = localStorage.getItem('CA_API_BASE');
        if (stored) return stored.replace(/\/$/, '');
    } catch (_) { /* ignore */ }
    const host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1' || host === '') {
        const port = window.location.port;
        // Served from FastAPI itself (port 8000 or default) → same origin
        if (!port || port === '8000') return '';
        // Split-dev static server (e.g. :5500) → API on 8000
        return 'http://127.0.0.1:8000';
    }
    // Production / Render single-service: same origin
    return '';
}

const API_BASE = resolveApiBase();
const NOMINATIM = 'https://nominatim.openstreetmap.org/search';
// Optional client key when server has API_KEY set (localStorage CA_API_KEY)
function apiHeaders(extra = {}) {
    const headers = { 'Content-Type': 'application/json', ...extra };
    try {
        const key = localStorage.getItem('CA_API_KEY');
        if (key) headers['X-API-Key'] = key;
    } catch (_) { /* ignore */ }
    return headers;
}

/** Fetch with session cookies (credentials) for accounts / quotas */
async function apiFetch(path, options = {}) {
    const opts = {
        credentials: 'include',
        ...options,
        headers: apiHeaders(options.headers || {}),
    };
    if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
        opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(`${API_BASE}${path}`, opts);
    return res;
}

function detailMessage(errBody, fallback) {
    if (!errBody) return fallback;
    const d = errBody.detail;
    if (!d) return fallback;
    if (typeof d === 'string') return d;
    if (d.message) return d.message;
    try { return JSON.stringify(d); } catch (_) { return fallback; }
}

let currentUser = null;
let currentQuota = null;

function renderAccountUI() {
    const planPill = document.getElementById('planPill');
    const quotaChip = document.getElementById('quotaChip');
    const logoutBtn = document.getElementById('logoutBtn');
    const upgradeBtn = document.getElementById('upgradeBtn');
    const authGuest = document.getElementById('authGuest');
    const authUser = document.getElementById('authUser');
    const userEmailLabel = document.getElementById('userEmailLabel');
    const quotaDetail = document.getElementById('quotaDetail');
    const q = currentQuota || {};
    const plan = (currentUser && currentUser.plan) || q.plan || 'anonymous';
    if (planPill) {
        planPill.textContent = plan === 'pro' ? 'Pro' : (plan === 'free' ? 'Free' : 'Guest');
        planPill.classList.toggle('pro', plan === 'pro');
    }
    if (quotaChip) {
        const rr = q.routes_remaining != null ? q.routes_remaining : '—';
        const cr = q.chats_remaining != null ? q.chats_remaining : '—';
        quotaChip.textContent = `Routes left today: ${rr} · Chat: ${cr}`;
    }
    if (quotaDetail) {
        quotaDetail.textContent =
            `Plan: ${plan} · Routes ${q.routes_used || 0}/${q.routes_per_day || 0} · ` +
            `Chat ${q.chats_used || 0}/${q.chats_per_day || 0} · ` +
            `Saved ${q.saved_routes_count || 0}/${q.saved_routes_max || 0}`;
    }
    const loggedIn = !!currentUser;
    if (logoutBtn) logoutBtn.style.display = loggedIn ? '' : 'none';
    if (authGuest) authGuest.style.display = loggedIn ? 'none' : '';
    if (authUser) authUser.style.display = loggedIn ? '' : 'none';
    if (userEmailLabel && currentUser) userEmailLabel.textContent = currentUser.email;
    if (upgradeBtn) {
        upgradeBtn.style.display = plan === 'pro' ? 'none' : '';
        upgradeBtn.disabled = false;
    }
}

async function refreshMe() {
    try {
        const res = await apiFetch('/api/me');
        if (!res.ok) return;
        const data = await res.json();
        currentUser = data.user || null;
        currentQuota = data.quota || null;
        renderAccountUI();
        if (currentUser) await loadSavedRoutes();
    } catch (err) {
        console.warn('me failed', err.message);
    }
}

async function loadSavedRoutes() {
    const list = document.getElementById('savedList');
    if (!list || !currentUser) return;
    try {
        const res = await apiFetch('/api/saved-routes');
        if (!res.ok) return;
        const data = await res.json();
        if (data.quota) { currentQuota = data.quota; renderAccountUI(); }
        list.innerHTML = '';
        (data.routes || []).forEach(r => {
            const li = document.createElement('li');
            const label = document.createElement('span');
            label.textContent = r.name;
            label.style.cursor = 'pointer';
            label.title = 'Load route';
            label.addEventListener('click', () => {
                startCoords = { lat: r.start.lat, lon: r.start.lon };
                endCoords = { lat: r.end.lat, lon: r.end.lon };
                startEl.value = `${r.start.lat},${r.start.lon}`;
                endEl.value = `${r.end.lat},${r.end.lon}`;
                startHint.textContent = `✓ ${r.start.label || r.name}`;
                startHint.className = 'geo-hint resolved';
                endHint.textContent = `✓ ${r.end.label || ''}`;
                endHint.className = 'geo-hint resolved';
                computeAndRender();
            });
            const del = document.createElement('button');
            del.type = 'button';
            del.textContent = '✕';
            del.addEventListener('click', async () => {
                await apiFetch(`/api/saved-routes/${r.id}`, { method: 'DELETE' });
                await loadSavedRoutes();
                await refreshMe();
            });
            li.appendChild(label);
            li.appendChild(del);
            list.appendChild(li);
        });
    } catch (err) {
        console.warn('saved routes', err.message);
    }
}

function initAuthUI() {
    let mode = 'login';
    const tabLogin = document.getElementById('tabLogin');
    const tabSignup = document.getElementById('tabSignup');
    const form = document.getElementById('authForm');
    const submit = document.getElementById('authSubmit');
    const msg = document.getElementById('authMsg');
    const setMode = (m) => {
        mode = m;
        if (tabLogin) tabLogin.classList.toggle('active', m === 'login');
        if (tabSignup) tabSignup.classList.toggle('active', m === 'signup');
        if (submit) submit.textContent = m === 'login' ? 'Log in' : 'Sign up';
        if (msg) { msg.className = 'auth-msg'; msg.textContent = 'Free: 3 routes/day · 1 AI chat/day · 3 saved routes'; }
    };
    tabLogin?.addEventListener('click', () => setMode('login'));
    tabSignup?.addEventListener('click', () => setMode('signup'));
    form?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('authEmail')?.value.trim();
        const password = document.getElementById('authPassword')?.value;
        if (!email || !password) return;
        submit.disabled = true;
        try {
            const path = mode === 'signup' ? '/api/auth/signup' : '/api/auth/login';
            const res = await apiFetch(path, { method: 'POST', body: { email, password } });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (msg) { msg.className = 'auth-msg error'; msg.textContent = detailMessage(data, 'Auth failed'); }
                return;
            }
            currentUser = data.user;
            currentQuota = data.quota;
            renderAccountUI();
            await loadSavedRoutes();
            if (msg) { msg.className = 'auth-msg ok'; msg.textContent = 'Signed in.'; }
        } catch (err) {
            if (msg) { msg.className = 'auth-msg error'; msg.textContent = err.message; }
        } finally {
            submit.disabled = false;
        }
    });
    document.getElementById('logoutBtn')?.addEventListener('click', async () => {
        await apiFetch('/api/auth/logout', { method: 'POST' });
        currentUser = null;
        await refreshMe();
    });
    document.getElementById('upgradeBtn')?.addEventListener('click', async () => {
        if (!currentUser) {
            alert('Sign up or log in first, then upgrade to Pro.');
            document.getElementById('authEmail')?.focus();
            return;
        }
        const btn = document.getElementById('upgradeBtn');
        if (btn) btn.disabled = true;
        try {
            const preferPaypal = (currentQuota && currentQuota.paypal_configured)
                || (currentQuota && currentQuota.billing_provider === 'paypal');
            if (preferPaypal) {
                const res = await apiFetch('/api/paypal/create-subscription', { method: 'POST' });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    alert(detailMessage(data, 'PayPal not configured. See README for sandbox setup.'));
                    return;
                }
                if (data.approval_url) {
                    window.location.href = data.approval_url;
                    return;
                }
                alert('PayPal did not return an approval URL.');
                return;
            }
            // Stripe fallback (hidden/de-emphasized when PayPal is configured)
            const res = await apiFetch('/api/billing/checkout', { method: 'POST' });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                alert(detailMessage(data, 'Billing not configured. See README for PayPal sandbox setup.'));
                return;
            }
            if (data.checkout_url) window.location.href = data.checkout_url;
        } catch (err) {
            alert(err.message);
        } finally {
            if (btn) btn.disabled = false;
        }
    });
    document.getElementById('manageBillingBtn')?.addEventListener('click', async () => {
        try {
            const preferPaypal = (currentQuota && currentQuota.paypal_configured)
                || (currentQuota && currentQuota.billing_provider === 'paypal');
            if (preferPaypal) {
                alert(
                    'PayPal billing: manage or cancel the subscription in your PayPal account ' +
                    '(Sandbox → Sandbox accounts → the buyer account). Entitlements update via webhook or on next capture.'
                );
                return;
            }
            const res = await apiFetch('/api/billing/portal', { method: 'POST' });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                alert(detailMessage(data, 'Billing portal unavailable. Cancel via Stripe Dashboard in test mode.'));
                return;
            }
            if (data.portal_url) window.location.href = data.portal_url;
        } catch (err) {
            alert(err.message);
        }
    });
    document.getElementById('saveRouteBtn')?.addEventListener('click', async () => {
        if (!currentUser) return;
        const name = prompt('Name this route', `${startCoords.lat.toFixed(2)},${startCoords.lon.toFixed(2)} → ${endCoords.lat.toFixed(2)},${endCoords.lon.toFixed(2)}`);
        if (!name) return;
        const res = await apiFetch('/api/saved-routes', {
            method: 'POST',
            body: {
                name,
                start_lat: startCoords.lat,
                start_lon: startCoords.lon,
                end_lat: endCoords.lat,
                end_lon: endCoords.lon,
                start_label: startHint?.textContent || null,
                end_label: endHint?.textContent || null,
            },
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            alert(detailMessage(data, 'Could not save route'));
            return;
        }
        if (data.quota) { currentQuota = data.quota; renderAccountUI(); }
        await loadSavedRoutes();
    });

    // Billing return query (PayPal appends subscription_id on success)
    const params = new URLSearchParams(window.location.search);
    const billing = params.get('billing');
    const provider = params.get('provider');
    if (billing === 'success') {
        const subId = params.get('subscription_id');
        (async () => {
            try {
                if (provider === 'paypal' && subId) {
                    const res = await apiFetch('/api/paypal/capture', {
                        method: 'POST',
                        body: { subscription_id: subId },
                    });
                    const data = await res.json().catch(() => ({}));
                    if (res.ok && data.plan === 'pro') {
                        showAdvisory('PayPal subscription active — Pro unlocked.', false);
                    } else {
                        showAdvisory(
                            detailMessage(data, 'Billing success — refreshing entitlements (activation may take a moment).'),
                            !res.ok
                        );
                    }
                } else {
                    showAdvisory('Billing success — refreshing entitlements (webhook may take a moment).', false);
                }
            } catch (err) {
                showAdvisory(err.message || 'Could not confirm subscription.', true);
            }
            await refreshMe();
            // Clean query string without reload
            try {
                const url = new URL(window.location.href);
                ['billing', 'provider', 'subscription_id', 'ba_token', 'token'].forEach(k => url.searchParams.delete(k));
                window.history.replaceState({}, '', url.pathname + url.search + url.hash);
            } catch (_) { /* ignore */ }
        })();
    } else if (billing === 'cancel') {
        showAdvisory('Checkout canceled. Free tier still available.', true);
    }
}

// West-Coast defaults with good NDBC coverage (San Diego → San Francisco)
const DEFAULTS = {
    start: { lat: 32.7157, lon: -117.1611, label: 'San Diego, CA' },
    end:   { lat: 37.7749, lon: -122.4194, label: 'San Francisco, CA' },
};

const PRESETS = {
    sdSf: {
        start: { lat: 32.7157, lon: -117.1611, label: 'San Diego, CA' },
        end:   { lat: 37.7749, lon: -122.4194, label: 'San Francisco, CA' },
    },
    solana: {
        start: { lat: 32.9912, lon: -117.2714, label: 'Solana Beach, CA' },
        end:   { lat: 33.3872, lon: -118.4160, label: 'Santa Catalina Island, CA' },
    },
};

// ── DOM refs ───────────────────────────────────────────────────────────
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
const routeAdvisory = document.getElementById('routeAdvisory');

// ── State ────────────────────────────────────────────────────────────
let startCoords = { ...DEFAULTS.start };
let endCoords   = { ...DEFAULTS.end };
let currentRouteContext = null;
let buoyLayer   = null;
let cesiumViewer = null;

function showAdvisory(text, isFallback = false) {
    if (!routeAdvisory) return;
    routeAdvisory.textContent = text;
    routeAdvisory.classList.add('visible');
    routeAdvisory.style.color = isFallback ? '#ffaa00' : '#7ec8e0';
    routeAdvisory.style.borderColor = isFallback
        ? 'rgba(255,170,0,0.35)'
        : 'rgba(0,180,220,0.35)';
    routeAdvisory.style.background = isFallback
        ? 'rgba(80,40,0,0.35)'
        : 'rgba(0,40,60,0.4)';
}

// ── Leaflet Map ──────────────────────────────────────────────────────────
const map = L.map('map').setView([34.5, -120.5], 6);

// ESRI Ocean base — much better for maritime use
L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}',
    {
        attribution: 'Tiles &copy; Esri, GEBCO, NOAA, CHS, OSU | Data: NOAA/NDBC · Geocode: Nominatim/OSM',
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

// ── Initialize Cesium (optional; token via window.CESIUM_ION_TOKEN) ─────
async function initCesium() {
    try {
        if (!window.Cesium) return false;
        const Cesium = window.Cesium;
        // Do NOT hardcode Ion JWTs. Set window.CESIUM_ION_TOKEN before load, or leave unset.
        const token = window.CESIUM_ION_TOKEN || '';
        if (token) {
            Cesium.Ion.defaultAccessToken = token;
        } else {
            console.info('Cesium Ion token not set (window.CESIUM_ION_TOKEN). 3D globe may be limited.');
        }

        const container = document.getElementById('cesiumContainer');
        if (!container) return false;

        cesiumViewer = new Cesium.Viewer('cesiumContainer', {
            timeline: false,
            animation: false,
            sceneModePicker: true,
            baseLayerPicker: false,
            geocoder: false,
            homeButton: true,
        });

        cesiumViewer.camera.setView({
            destination: Cesium.Cartesian3.fromDegrees(-120, 34.5, 1800000),
        });

        console.log('Cesium viewer initialized successfully');
        return true;
    } catch (err) {
        console.warn('Cesium initialization failed:', err.message);
    }
    return false;
}

function addRouteToCesium(routeCoords) {
    if (!cesiumViewer || !routeCoords || routeCoords.length === 0) return;

    const Cesium = window.Cesium;
    const positions = [];
    routeCoords.forEach(p => {
        positions.push(Cesium.Cartesian3.fromDegrees(p.lon, p.lat, 0.0));
    });

    cesiumViewer.entities.add({
        polyline: {
            positions,
            width: 4,
            material: Cesium.Color.CYAN,
            clampToGround: true,
        }
    });

    cesiumViewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(
            (routeCoords[0].lon + routeCoords[routeCoords.length - 1].lon) / 2,
            (routeCoords[0].lat + routeCoords[routeCoords.length - 1].lat) / 2,
            1500000
        ),
    });
}

// ── Marker helpers ─────────────────────────────────────────────────────────
function makeMarker(color) {
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

// ── Route Drawing ─────────────────────────────────────────────────────────
function setMarkers(start, end) {
    if (startMarker) startMarker.remove();
    if (endMarker)   endMarker.remove();

    startMarker = L.marker([start.lat, start.lon], {
        icon: makeMarker('#00dd88'),
        draggable: true,
    }).addTo(map).bindTooltip('Start', { permanent: false });

    endMarker = L.marker([end.lat, end.lon], {
        icon: makeMarker('#ff5555'),
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
        { color: '#00c8e0', weight: 3, opacity: 0.9, dashArray: null }
    ).addTo(map);
}

// ── NOAA Buoy Markers ───────────────────────────────────────────────────────
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
        <p style="margin:5px 0 0;font-size:0.65rem;color:#3a6a8a;">${station.distance_km} km from route · advisory only</p>
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
        Plotly.newPlot('plotlyChart',
            [{ x: Array.from({length: 11}, (_, i) => i), y: Array(11).fill(0),
               type: 'scatter', mode: 'lines', name: 'Wind (kts)',
               line: { color: '#00c8e0', width: 2 } }],
            {
                title: { text: 'No buoy data for this route (advisory)', font: { color: '#5a8aaa', size: 13 } },
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

    const KM_PER_DEG = 111.12;
    const allPts = samplePoints;
    const cumDist = [0];
    for (let i = 1; i < allPts.length; i++) {
        const a = allPts[i - 1], b = allPts[i];
        const dlat = b.lat - a.lat, dlon = b.lon - a.lon;
        cumDist.push(cumDist[i - 1] + Math.sqrt(dlat * dlat + dlon * dlon) * KM_PER_DEG);
    }

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

// ── Conditions Summary ───────────────────────────────────────────────────────
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
        advisory:           true,
    };
}

// ── Main Compute ─────────────────────────────────────────────────────────
async function computeAndRender() {
    computeBtn.disabled = true;
    condDot.classList.add('loading');
    condSpinner.style.display = 'block';
    noDataMsg.style.display   = 'none';
    condGrid.style.display    = 'none';

    const sCoords = await geocode(startEl.value, startHint);
    if (sCoords) startCoords = sCoords;

    const eCoords = await geocode(endEl.value, endHint);
    if (eCoords) endCoords = eCoords;

    setMarkers(startCoords, endCoords);

    // Water-preferring path (advisory / approximate)
    let waterResult;
    try {
        showAdvisory('Computing approximate water route…', false);
        waterResult = await computeWaterRoute(startCoords, endCoords, {
            landPath: './data/land_110m.geojson',
            stepDeg: 0.4,
            padDeg: 1.2,
        });
    } catch (err) {
        waterResult = {
            path: [startCoords, endCoords],
            mode: 'straight_fallback',
            message: `Water routing error: ${err.message}. Straight-line estimate — advisory only.`,
        };
    }

    const pathPoints = waterResult.path;
    drawRoute(pathPoints);
    showAdvisory(
        waterResult.message || 'Advisory / approximate route — NOT for navigation.',
        waterResult.mode !== 'water'
    );

    try {
        const body = {
            start: { lat: startCoords.lat, lon: startCoords.lon },
            end:   { lat: endCoords.lat,   lon: endCoords.lon },
            path:  pathPoints,
            sample_interval_km: 10,
            constraints: { mode: 'conservative' },
        };
        const res = await apiFetch('/api/route', { method: 'POST', body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = detailMessage(data, `API ${res.status}`);
            if (res.status === 402 || res.status === 429) {
                showAdvisory(msg, true);
                if (data.quota) { currentQuota = data.quota; renderAccountUI(); }
                else await refreshMe();
                return;
            }
            throw new Error(msg);
        }
        if (data.quota) { currentQuota = data.quota; renderAccountUI(); }

        if (data.disclaimer || data.advisory) {
            const modeNote = data.routing_mode === 'water_path'
                ? 'Water-preferring path sampled.'
                : 'Straight-line sample path.';
            showAdvisory(
                `${data.disclaimer || 'Advisory / approximate only — NOT for navigation.'} ${modeNote}`,
                data.routing_mode !== 'water_path'
            );
        }

        if (data.route_sample_points && data.route_sample_points.length > 1) {
            // Prefer client water geometry for map; overlay sample conditions
            drawRoute(pathPoints.length > 2 ? pathPoints : data.route_sample_points);
            renderBuoyMarkers(data.route_sample_points);
            renderChart3D(data.route_sample_points);

            if (cesiumViewer) {
                addRouteToCesium(pathPoints.length > 2 ? pathPoints : data.route_sample_points);
            }
        }
        updateSummary(data.summary);
    } catch (err) {
        console.warn('Route API error:', err.message);
        renderChart3D([]);
        updateSummary(null);
        showAdvisory(
            `Conditions API unreachable (${err.message}). Route shown is advisory geometry only — NOT for navigation.`,
            true
        );
    } finally {
        computeBtn.disabled = false;
        condSpinner.style.display = 'none';
    }
}

form.addEventListener('submit', async e => {
    e.preventDefault();
    await computeAndRender();
});

function applyPreset(preset) {
    startCoords = { lat: preset.start.lat, lon: preset.start.lon };
    endCoords   = { lat: preset.end.lat,   lon: preset.end.lon };
    startEl.value = `${preset.start.lat},${preset.start.lon}`;
    endEl.value   = `${preset.end.lat},${preset.end.lon}`;
    startHint.textContent = `✓ ${preset.start.label}`;
    startHint.className = 'geo-hint resolved';
    endHint.textContent = `✓ ${preset.end.label}`;
    endHint.className = 'geo-hint resolved';
    computeAndRender();
}

document.getElementById('presetSdSf')?.addEventListener('click', () => applyPreset(PRESETS.sdSf));
document.getElementById('presetSolana')?.addEventListener('click', () => applyPreset(PRESETS.solana));

// ── AI Chat ───────────────────────────────────────────────────────────
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
        const res = await apiFetch('/api/chat', { method: 'POST', body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            appendChat('error', detailMessage(data, 'Request failed.'));
            if (data.quota) { currentQuota = data.quota; renderAccountUI(); }
            else if (res.status === 402) await refreshMe();
        } else {
            appendChat('ai', data.reply || '(no reply)');
            if (data.quota) { currentQuota = data.quota; renderAccountUI(); }
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

// ── First render ─────────────────────────────────────────────────────────
startEl.value = `${DEFAULTS.start.lat},${DEFAULTS.start.lon}`;
endEl.value   = `${DEFAULTS.end.lat},${DEFAULTS.end.lon}`;
startHint.textContent = `✓ ${DEFAULTS.start.label}`;
startHint.className = 'geo-hint resolved';
endHint.textContent = `✓ ${DEFAULTS.end.label}`;
endHint.className = 'geo-hint resolved';

showAdvisory('⚠ Advisory only — NOT for navigation. Compute a route to sample NOAA/NDBC conditions.', true);

initAuthUI();
refreshMe();

window.addEventListener('load', async () => {
    await initCesium();
    computeAndRender();
});
