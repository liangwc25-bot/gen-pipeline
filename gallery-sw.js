const CACHE = 'gallery-v2';
const ALWAYS_NETWORK = ['/api/'];
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/'])));
});
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
  );
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // API calls — always go to network, never cache
  if (ALWAYS_NETWORK.some(p => url.pathname.startsWith(p))) {
    e.respondWith(fetch(e.request).catch(() => new Response(null, { status: 503 })));
    return;
  }
  // HTML — network-first, fall back to cache
  if (url.pathname === '/') {
    e.respondWith(
      fetch(e.request).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  // Static assets — cache-first
  e.respondWith(caches.match(e.request).then(cached => cached || fetch(e.request)));
});
