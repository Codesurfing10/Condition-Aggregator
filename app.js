// app.js

const API_BASE = 'https://condition-aggregator-api.onrender.com';

// Default coordinates
const defaultStart = '24.1426,-110.3128'; // La Paz
const defaultEnd = '49.2827,-123.1207'; // Vancouver

// Bind to the existing form
const form = document.getElementById('routeForm');
const mapDiv = document.getElementById('map');
const plotlyDiv = document.getElementById('plotlyChart');

// Initialize Leaflet map
const map = L.map(mapDiv).setView([24.1426, -110.3128], 4);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
}).addTo(map);

// Track last known route context for AI chat
let currentRouteContext = null;

form.addEventListener('submit', async (event) => {
    event.preventDefault(); // Prevent the default form submission

    // Read inputs
    const startInput = document.getElementById('start').value || defaultStart;
    const endInput = document.getElementById('end').value || defaultEnd;
    const [startLat, startLon] = startInput.split(',').map(Number);
    const [endLat, endLon] = endInput.split(',').map(Number);

    // Prepare the request body
    const requestBody = {
        start: { lat: startLat, lon: startLon },
        end: { lat: endLat, lon: endLon },
        sample_interval_km: 10,
        constraints: { mode: 'conservative' }
    };

    // Save context for AI assistant
    currentRouteContext = {
        start_lat: startLat,
        start_lon: startLon,
        end_lat: endLat,
        end_lon: endLon,
        sample_interval_km: 10,
        constraints: 'conservative',
    };

    // Make the API call
    const response = await fetch(`${API_BASE}/api/route`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
    });
    const data = await response.json();

    // Logic to draw the route or a straight line
    if (data.route) {
        // Draw the returned route
        const route = L.polyline(data.route.map(point => [point.lat, point.lon]), { color: 'blue' }).addTo(map);
        map.fitBounds(route.getBounds());
    } else {
        // Draw straight line
        const line = L.polyline([[startLat, startLon], [endLat, endLon]], { color: 'red' }).addTo(map);
        map.fitBounds(line.getBounds());
    }

    // Prepare Plotly data
    const plotlyData = data.conditions ? data.conditions : Array(11).fill(0);

    // Render Plotly chart
    Plotly.newPlot(plotlyDiv, [{
        x: Array.from({length: 11}, (_, i) => i),
        y: plotlyData,
        type: 'bar'
    }]);
});

// ── AI Chat (Gemini Flash Lite) ──────────────────────────────────────────────

const chatLog   = document.getElementById('chatLog');
const chatInput = document.getElementById('chatInput');
const chatSend  = document.getElementById('chatSend');

function appendChatMessage(role, text) {
    const p = document.createElement('p');
    p.style.margin = '4px 0';
    if (role === 'user') {
        p.innerHTML = `<span class="chat-user">You:</span> ${escapeHtml(text)}`;
    } else if (role === 'ai') {
        p.innerHTML = `<span class="chat-ai">Assistant:</span> ${escapeHtml(text)}`;
    } else {
        p.innerHTML = `<span class="chat-err">Error:</span> ${escapeHtml(text)}`;
    }
    chatLog.appendChild(p);
    chatLog.scrollTop = chatLog.scrollHeight;
}

function escapeHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

async function sendChatMessage() {
    const message = chatInput.value.trim();
    if (!message) return;

    chatInput.value = '';
    chatSend.disabled = true;
    appendChatMessage('user', message);

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
            appendChatMessage('error', err.detail || 'Request failed.');
        } else {
            const data = await res.json();
            appendChatMessage('ai', data.reply || '(no reply)');
        }
    } catch (err) {
        appendChatMessage('error', `Network error: ${err.message}`);
    } finally {
        chatSend.disabled = false;
        chatInput.focus();
    }
}

chatSend.addEventListener('click', sendChatMessage);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendChatMessage();
});
