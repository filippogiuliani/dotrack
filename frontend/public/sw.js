// doTrack service worker: push notifications, and the app itself kept on the device so it opens offline.
// The page (index.html) always comes from the network when there is one, so a new version shows at once;
// built files have a hash in their name and never change, so they are served from the cache.
// Data is not cached here: the app keeps its own copy (see lib/store.svelte.js).
const CACHE = 'dotrack-app-v1';

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(['/', '/icon.svg', '/manifest.webmanifest'])).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/dav/')) return;
  if (req.mode === 'navigate') {
    // Network first: offline, the last page saved
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        if (fresh.ok) (await caches.open(CACHE)).put('/', fresh.clone());
        return fresh;
      } catch {
        return (await caches.match('/')) ?? Response.error();
      }
    })());
    return;
  }
  if (url.pathname.startsWith('/assets/') || /\.(svg|png|webmanifest|woff2)$/.test(url.pathname)) {
    event.respondWith((async () => {
      const hit = await caches.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) (await caches.open(CACHE)).put(req, res.clone());
      return res;
    })());
  }
});

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data?.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || 'doTrack', {
    body: data.body || '',
    tag: data.tag,
    renotify: !!data.tag,
    data: { url: data.url || '/#/agenda' },
    icon: '/icon-192.png',
    badge: '/badge-96.png',
  }));
});

// Tap on a notification: focus an open doTrack window (and show the item there) or open a new one
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || '/', self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const open = windows.find((w) => new URL(w.url).origin === self.location.origin);
    if (open) {
      await open.focus();
      open.postMessage({ type: 'open', url });
      return;
    }
    await self.clients.openWindow(url);
  })());
});
