/* 公文通 · 手机版 Service Worker
   目标：应用外壳离线可用；日报数据网络优先、断网回落缓存。 */
const SHELL = 'nbw-shell-v1';
const DATA = 'nbw-data-v1';
const SHELL_FILES = ['/', '/index.html', '/style.css', '/app.js', '/icon.svg', '/manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // 数据：网络优先，失败回落缓存
  if (url.pathname.startsWith('/api/')) {
    e.respondWith((async () => {
      try {
        const res = await fetch(req);
        if (res.ok) {
          const c = await caches.open(DATA);
          c.put(req, res.clone());
        }
        return res;
      } catch (err) {
        const hit = await caches.match(req);
        if (hit) return hit;
        throw err;
      }
    })());
    return;
  }

  // 外壳：缓存优先，后台更新
  e.respondWith((async () => {
    const hit = await caches.match(req);
    if (hit) {
      fetch(req).then((res) => {
        if (res.ok) caches.open(SHELL).then((c) => c.put(req, res));
      }).catch(() => {});
      return hit;
    }
    const res = await fetch(req);
    if (res.ok) {
      const c = await caches.open(SHELL);
      c.put(req, res.clone());
    }
    return res;
  })());
});
