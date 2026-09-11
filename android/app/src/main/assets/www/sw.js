// Kaoss Offline Service Worker — REAL-IMPLEMENTATION 2026-09-11 (Android asset mirror)
// Mirrors web/sw.js v12 but with v11 cache name for WebView compat.
const CACHE = 'kaoss-offline-v11-action-chain';
const ASSETS = ['./index.html', './src/styles.css', './src/app.js', './src/audio-engine.js', './src/action-chain.js', './manifest.webmanifest'];
self.addEventListener('install', (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())));
self.addEventListener('activate', (event) => event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', (event) => event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request))));
