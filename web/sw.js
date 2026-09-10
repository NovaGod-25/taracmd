/* TaraCmd service worker — network-first.
 *
 * BUMP THIS ON EVERY DEPLOY. The whole app is one HTML file, so a stale cache
 * entry means returning visitors keep getting the old page, content and all.
 */
const CACHE = "taracmd-2026-09-10e";

const SHELL = [
  "./",
  "./taracmd.html",
  "./manifest.webmanifest",
  "./icon.svg",
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(SHELL))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())   // a missing optional file must not wedge install
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

/* Network-first: the page is the content, so a fresh copy always wins. The
 * cache is the offline fallback, not the primary source — which is why the
 * revision ticks live in localStorage and not in here. */
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== location.origin) return;   // Google Fonts falls back on its own

  e.respondWith(
    fetch(req)
      .then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req).then(hit => hit || caches.match("./taracmd.html")))
  );
});
