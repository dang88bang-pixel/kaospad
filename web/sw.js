const CACHE = 'kaoss-offline-v9-console-vault';
const ASSETS = ['./index.html', './src/styles.css', './src/app.js', './src/audio-engine.js', './manifest.webmanifest'];
self.addEventListener('install', (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS))));
self.addEventListener('fetch', (event) => event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request))));
