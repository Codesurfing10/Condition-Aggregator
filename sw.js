/* Condition Aggregator — offline UI shell only (not weather/API data). */
const CACHE_NAME = 'ca-shell-v1';
const SHELL_URLS = [
  '/',
  '/app.js',
  '/manifest.webmanifest',
  '/src/routing/water_pathfinder.js',
  '/static/icons/icon-180.png',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      // Prefetch individually so one miss does not fail the whole install
      await Promise.all(
        SHELL_URLS.map((url) =>
          cache.add(url).catch((err) => console.warn('[sw] skip cache', url, err))
        )
      );
      await self.skipWaiting();
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isApiOrData(url) {
  const p = url.pathname;
  return (
    p.startsWith('/api/') ||
    p === '/health' ||
    p.startsWith('/docs') ||
    p.startsWith('/redoc') ||
    p.startsWith('/openapi')
  );
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  let url;
  try {
    url = new URL(req.url);
  } catch (_) {
    return;
  }

  // Same-origin UI shell only — never cache API / weather / auth responses
  if (url.origin !== self.location.origin) return;
  if (isApiOrData(url)) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.ok && res.type === 'basic') {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone)).catch(() => {});
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
