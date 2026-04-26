// Service worker — affichage SDIS
// Permet à l'écran de continuer à afficher la dernière version chargée
// (slides, photos, vidéos, icônes, logo) quand le serveur est injoignable.

const CACHE = 'affichage-v1';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    // Pré-cache la page d'affichage tant que le réseau est disponible
    try {
      const cache = await caches.open(CACHE);
      const res = await fetch('/', { credentials: 'same-origin' });
      if (res && res.ok) await cache.put(new Request('/'), res.clone());
    } catch (_) { /* hors-ligne : on ne peut rien faire de plus */ }
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Page d'affichage et endpoints JSON : réseau d'abord, cache en secours
  if (url.pathname === '/' || url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(req, url));
    return;
  }
  // Médias et fichiers statiques : cache d'abord, rafraîchi en arrière-plan
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(req));
    return;
  }
});

async function networkFirst(req, url) {
  const cache = await caches.open(CACHE);
  // Pour la page d'affichage, on cache toujours sous la clé "/"
  // (pour ignorer les paramètres ?lite&token=…).
  const cacheKey = url.pathname === '/' ? new Request('/') : req;
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      cache.put(cacheKey, res.clone()).catch(() => {});
    }
    return res;
  } catch (err) {
    const cached = await cache.match(cacheKey);
    if (cached) return cached;
    throw err;
  }
}

async function cacheFirst(req) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(req);
  if (cached) {
    // Rafraîchit en arrière-plan
    fetch(req).then(res => {
      if (res && res.ok) cache.put(req, res.clone()).catch(() => {});
    }).catch(() => {});
    return cached;
  }
  const res = await fetch(req);
  if (res && res.ok) cache.put(req, res.clone()).catch(() => {});
  return res;
}
