// Offline cache for the BVI Charter Guide.
// The page itself (index.html) is re-checked every time the app opens with a connection and replaced when
// it has changed, so content edits need no change here. Bump VERSION only when this file or FILES changes.
const VERSION = 'bvi-guide-v4';
const PAGE = './index.html';
const FILES = [
  './',
  PAGE,
  './manifest.webmanifest',
  './fonts/barlow-condensed-600.woff2',
  './fonts/barlow-condensed-700.woff2',
  './icons/apple-touch-icon.png',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/maskable-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION)
      .then((cache) => cache.addAll(FILES.map((f) => new Request(f, { cache: 'reload' }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const old = (await caches.keys()).filter((k) => k.startsWith('bvi-guide-') && k !== VERSION);
    await Promise.all(old.map((k) => caches.delete(k)));
    await self.clients.claim();
    // Coming from an older version: reload open copies so they show the new guide straight away.
    if (old.length) {
      (await self.clients.matchAll({ type: 'window' })).forEach((w) => {
        try { const p = w.navigate(w.url); if (p && p.catch) p.catch(() => {}); } catch (e) { /* not supported */ }
      });
    }
  })());
});

// Fetch the newest page, bypassing the browser's own cache. Resolves true if it differs from the saved copy.
async function refreshPage() {
  const cache = await caches.open(VERSION);
  const res = await fetch(PAGE, { cache: 'no-store' });
  if (!res || !res.ok) return false;
  const saved = await cache.match(PAGE);
  const [a, b] = await Promise.all([saved ? saved.text() : '', res.clone().text()]);
  if (a === b) return false;
  await Promise.all([cache.put(PAGE, res.clone()), cache.put('./', res)]);
  return true;
}

let checking = null;
function checkForUpdate() {
  if (!checking) {
    checking = refreshPage()
      .then(async (changed) => {
        if (!changed) return;
        (await self.clients.matchAll({ type: 'window' })).forEach((w) => w.postMessage({ type: 'update-ready' }));
      })
      .catch(() => {})
      .then(() => { checking = null; });
  }
  return checking;
}

self.addEventListener('message', (event) => {
  if (event.data === 'check') event.waitUntil(checkForUpdate());
});

// Everything is served from the saved copy first, so the app opens instantly and works with no signal.
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  if (req.mode === 'navigate') {
    event.respondWith(caches.open(VERSION).then((cache) => cache.match(PAGE)).then((hit) => hit || fetch(req)));
    event.waitUntil(checkForUpdate());
    return;
  }
  event.respondWith(
    caches.open(VERSION).then((cache) =>
      cache.match(req, { ignoreSearch: true }).then((hit) => hit || fetch(req).then((res) => {
        if (res && res.ok && res.type === 'basic') cache.put(req, res.clone());
        return res;
      }))
    )
  );
});
