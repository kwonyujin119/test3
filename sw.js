// 유진·아름 사진 저장소 서비스 워커 — 홈 화면 설치 조건용 최소 구성.
// 사진·API는 캐시하지 않는다(PC 서버로 바로). 화면(HTML) 한 장만 보관해 두고, 인터넷이 끊겼을 때만 그걸로 연다.
const SHELL = 'album-shell-v1', SHELL_KEY = new URL('./', self.location).href;
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req.url, { cache: 'no-cache', credentials: 'same-origin' })
        .then(r => {
          if (r.redirected) return Response.redirect(r.url, 302);
          if (r.ok && (r.headers.get('content-type') || '').includes('text/html')) { const c = r.clone(); caches.open(SHELL).then(s => s.put(SHELL_KEY, c)).catch(() => {}); }
          return r;
        })
        .catch(() => fetch(req).catch(() => caches.match(SHELL_KEY, { cacheName: SHELL }).then(m => m || Response.error())))
    );
    return;
  }
  e.respondWith(fetch(req));
});
