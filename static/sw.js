// Oikotie report — app-shell service worker.
// Bump CACHE_VERSION whenever report.css/report.js/manifest/icons change.
const CACHE_VERSION = '__SW_CACHE_VERSION__';
const CACHE_NAME = `oikotie-shell-${CACHE_VERSION}`;

const SHELL_ASSETS = [
  'report.css',
  'report.js',
  'manifest.json',
  'favicon.svg',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/icon-512-maskable.png',
  'icons/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;

  const isNavigation = req.mode === 'navigate';

  if (isNavigation) {
    // Network-first for the report page itself, so a fresh scrape shows up
    // immediately when online; fall back to the last cached copy offline.
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then((res) => res || caches.match('index.html')))
    );
    return;
  }

  // Cache-first for the static app shell (css/js/icons/manifest).
  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
      return res;
    }))
  );
});
