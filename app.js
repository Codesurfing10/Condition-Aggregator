// app.js

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

    // Make the API call
    const response = await fetch('https://condition-aggregator-api.onrender.com/api/route', {
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