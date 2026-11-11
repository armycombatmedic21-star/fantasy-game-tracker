/* Game Tracker logo cache (v1.7.2).
   Only team and NFL logo images go through here: they come from this phone's cache, so they show instantly on open
   (CBS doesn't let the app save its logos any other way). Everything else (the app, version check, data) is never
   touched: no respondWith, so the browser loads it normally. */
const CACHE = 'fgt-logos-v1';
const HOSTS = /(^|\.)(cbssports\.com|cbsimg\.net|cbsistatic\.com|espncdn\.com)$/;
const checked = {};   // refresh each cached logo once per run in the background, so a new team logo shows up next open

self.addEventListener('install', function(){ self.skipWaiting(); });
self.addEventListener('activate', function(e){
  e.waitUntil(caches.keys().then(function(ks){
    return Promise.all(ks.filter(function(k){ return /^fgt-logos-/.test(k) && k !== CACHE; }).map(function(k){ return caches.delete(k); }));
  }).then(function(){ return self.clients.claim(); }));
});

function trim(c){
  return c.keys().then(function(ks){ return ks.length > 80 ? Promise.all(ks.slice(0, ks.length - 80).map(function(k){ return c.delete(k); })) : null; });
}

self.addEventListener('fetch', function(e){
  const r = e.request;
  if(r.method !== 'GET' || r.destination !== 'image') return;
  let u; try{ u = new URL(r.url); }catch(x){ return; }
  if(!HOSTS.test(u.hostname)) return;
  e.respondWith(caches.open(CACHE).then(function(c){
    return c.match(r.url, { ignoreVary: true }).then(function(hit){
      const net = function(){
        return fetch(r).then(function(res){
          if(res && (res.ok || res.type === 'opaque')){ const cp = res.clone(); c.delete(r.url).then(function(){ return c.put(r.url, cp); }).then(function(){ return trim(c); }).catch(function(){}); }
          return res;
        });
      };
      if(hit){
        if(!checked[r.url]){ checked[r.url] = 1; e.waitUntil(net().catch(function(){})); }
        return hit;
      }
      return net();
    });
  }).catch(function(){ return fetch(r); }));
});
