// The phone app's service worker (served at /sw.js, panel/routes/install.py). It keeps nothing of the panel: the
// queue, the status and the outputs always come from the PC, never from a copy. Only when a page can't be reached at
// all (the PC off, Tailscale down) does it show a page of its own saying so, kept here as it installs.
// A new name when offline.html changes: the new worker keeps the new page, and drops the old.
const CACHE = 'gen-center-offline-2';
const OFFLINE = '/offline';

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.add(new Request(OFFLINE, { cache: 'reload' }))).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys()
    .then(names => Promise.all(names.filter(name => name !== CACHE).map(name => caches.delete(name))))
    .then(() => self.clients.claim()));
});

// Pages only: everything else (the API, the event stream, pictures, videos) goes straight to the network, untouched.
self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
