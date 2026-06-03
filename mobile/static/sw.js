// STM Mobile Service Worker — v1.2
// Minimal SW just for PWA installability (always-online app, no caching)

const CACHE_NAME = 'stm-mobile-v2';

// Static assets to cache for offline fallback page only
const STATIC_ASSETS = [
  '/mobile/static/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Network-first strategy: always fetch from network (online-only app)
self.addEventListener('fetch', (event) => {
  // Only handle same-origin /mobile/* requests
  if (!event.request.url.includes('/mobile/')) return;

  event.respondWith(
    fetch(event.request).catch(() => {
      // If network fails, show offline message
      return new Response(
        `<!DOCTYPE html>
        <html lang="it"><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>STM Mobile — Offline</title>
        <style>
          body{font-family:sans-serif;display:flex;flex-direction:column;align-items:center;
               justify-content:center;min-height:100vh;background:#1e3a8a;color:#fff;text-align:center;padding:2rem}
          h1{font-size:1.5rem;font-weight:700;margin-bottom:.5rem}
          p{opacity:.8;margin-bottom:2rem;font-size:.9rem}
          button{background:#fff;color:#1e3a8a;border:none;padding:.75rem 2rem;border-radius:.75rem;
                 font-weight:700;font-size:1rem;cursor:pointer}
        </style></head>
        <body>
          <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" fill="none" viewBox="0 0 24 24" stroke="currentColor" style="margin-bottom:1rem;opacity:.7">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M18.364 5.636a9 9 0 010 12.728m-3.536-3.536a4 4 0 010-5.657M6.343 6.343a9 9 0 000 12.728m3.536-3.536a4 4 0 000-5.657M12 12h.01"/>
          </svg>
          <h1>Nessuna connessione</h1>
          <p>STM Mobile richiede una connessione internet.<br>Verifica la connessione e riprova.</p>
          <button onclick="location.reload()">Riprova</button>
        </body></html>`,
        { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
      );
    })
  );
});
