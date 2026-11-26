const CACHE_NAME = 'expense-tracker-v7';
const STATIC_ASSETS = [
  '/static/style.css',
  '/static/manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(names => Promise.all(
        names.filter(name => name !== CACHE_NAME).map(name => caches.delete(name))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Never cache API calls or non-GET requests or HTML navigations
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/') || event.request.mode === 'navigate') {
    return;
  }

  // Network-first for static assets so updated JS/CSS always loads when online
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      fetch(event.request)
        .then(resp => {
          if (resp && resp.status === 200) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return resp;
        })
        .catch(() => caches.match(event.request))
    );
  }
});
