// Kaoss Offline Service Worker — REAL-IMPLEMENTATION 2026-09-11
// Versioned cache with network-first fallback, stale-while-revalidate for DSP assets.
// Preserves v12 compat (CACHE name) but adds activation cleanup + log rotation.
const CACHE = 'kaoss-offline-v12-dsp-core';
const PRECACHE_TTL_HOURS = 24;
const ASSETS = [
  './index.html',
  './src/styles.css',
  './src/app.js',
  './src/audio-engine.js',
  './src/dsp-core.js',
  './src/action-chain.js',
  './manifest.webmanifest'
];

// Install: pre-cache shell
self.addEventListener('install', (event) => {
  console.info('[sw] install', CACHE);
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

// Activate: delete old caches (keeps only current)
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch: cache-first for shell, network-first for api/dsp with 5s timeout, graceful fallback
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  // API -> network first, 5s timeout, then cache
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/health')) {
    event.respondWith(
      Promise.race([
        fetch(req),
        new Promise((_, rej) => setTimeout(() => rej(new Error('sw timeout 5s')), 5000))
      ]).catch(() => caches.match(req))
    );
    return;
  }
  // Shell assets -> stale-while-revalidate + cache
  event.respondWith(
    caches.match(req).then((cached) => {
      const fetchPromise = fetch(req).then((net) => {
        if (net && net.status === 200 && req.method === 'GET') {
          const clone = net.clone();
          caches.open(CACHE).then((c) => c.put(req, clone));
        }
        return net;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});

// Background periodic cache refresh (if available)
self.addEventListener('periodicsync', (event) => {
  if (event.tag === 'kaoss-refresh') {
    event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
  }
});
