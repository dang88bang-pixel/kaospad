// Kaoss Studio – Service Worker (offline, zero-cloud).
// Strategie: Netzwerk zuerst (frische Deploys sofort sichtbar), Cache als Fallback.
// Alte Cache-Versionen werden beim Aktivieren gelöscht. Nur Same-Origin-GETs
// werden gecacht; API-Antworten (/api/*) bleiben live und werden nie gecacht.
const CACHE = 'kaoss-offline-v14-netfirst';
const ASSETS = [
  './index.html',
  './src/styles.css',
  './src/app.js',
  './src/audio-engine.js',
  './src/action-chain.js',
  './src/dsp-core.js',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || Response.error())),
  );
});
