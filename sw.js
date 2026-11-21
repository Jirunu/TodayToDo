// 홈 화면 앱용 서비스 워커: 기록은 항상 최신을 먼저 가져오고, 오프라인이면 마지막으로 본 내용을 보여준다
const CACHE = "todaytodo-v1";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

function remember(req, res) {
  if (res.ok) {
    const copy = res.clone();
    caches.open(CACHE).then((c) => c.put(req, copy));
  }
  return res;
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === location.origin) {
    // 같은 사이트: 네트워크 우선, 실패하면 캐시
    e.respondWith(fetch(req).then((res) => remember(req, res))
      .catch(() => caches.match(req, { ignoreSearch: true }).then((r) => r || caches.match("./index.html"))));
  } else if (url.hostname === "cdn.jsdelivr.net") {
    // 버전이 고정된 라이브러리·폰트: 캐시 우선
    e.respondWith(caches.match(req).then((r) => r || fetch(req).then((res) => remember(req, res))));
  }
});
