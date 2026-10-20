/**
 * The Throne of Nazarick - PWA Service Worker (sw.js)
 * 오프라인 캐싱 및 PWA 백그라운드 서비스 워커
 */

const CACHE_NAME = 'nazarick-cache-v2';
const PRECACHE_ASSETS = [
    '/',
    '/static/style.css',
    '/static/app.js',
    '/static/manifest.json',
    '/static/icons/icon-192x192.png',
    '/static/icons/icon-512x512.png',
    '/static/icons/icon.svg',
    '/static/icons/favicon.png',
    'https://cdn.jsdelivr.net/npm/chart.js',
    'https://cdn.jsdelivr.net/npm/marked/marked.min.js'
];

// 1. 설치 (Install) & 프리캐시
self.addEventListener('install', (event) => {
    console.log('[ServiceWorker] 설치 중 (Pre-caching assets)...');
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(PRECACHE_ASSETS).catch((err) => {
                console.warn('[ServiceWorker] 일부 정적 자산 사전 캐싱 건너뜀:', err);
            });
        }).then(() => self.skipWaiting())
    );
});

// 2. 활성화 (Activate) & 구버전 캐시 정리
self.addEventListener('activate', (event) => {
    console.log('[ServiceWorker] 활성화 완료 (Cleaning old caches)...');
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((name) => {
                    if (name !== CACHE_NAME) {
                        console.log('[ServiceWorker] 구버전 캐시 삭제:', name);
                        return caches.delete(name);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// 3. 네트워크 요청 가로채기 (Fetch)
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // API 통신(/inspect, /run, /suggest, /explain, /chat, /ask, /health)은 항상 네트워크로 직접 통신
    if (url.pathname.startsWith('/inspect') ||
        url.pathname.startsWith('/run') ||
        url.pathname.startsWith('/suggest') ||
        url.pathname.startsWith('/explain') ||
        url.pathname.startsWith('/chat') ||
        url.pathname.startsWith('/ask') ||
        url.pathname.startsWith('/health')) {
        event.respondWith(
            fetch(event.request).catch(() => {
                return new Response(JSON.stringify({
                    error: '네트워크 연결이 끊겼습니다. 오프라인 상태에서는 실시간 AI 분석 API를 호출할 수 없습니다.'
                }), {
                    headers: { 'Content-Type': 'application/json' }
                });
            })
        );
        return;
    }

    // HTML 탐색(Navigation) 요청: 네트워크 시도 후 실패 시 캐시 반환 (Network-first with Cache fallback)
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request).catch(() => {
                return caches.match('/');
            })
        );
        return;
    }

    // 정적 자산(CSS, JS, 이미지, 폰트): 캐시 우선 (Cache-first with Network fallback)
    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                return cachedResponse;
            }
            return fetch(event.request).then((networkResponse) => {
                if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
                    return networkResponse;
                }
                const responseToCache = networkResponse.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, responseToCache);
                });
                return networkResponse;
            });
        })
    );
});
