'use strict';
const CACHE='jabbazi-shell-v1';
const ASSETS=['/vip/terminal.css','/vip/terminal.js','/vip/icon.svg'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
 const url=new URL(e.request.url);
 // No API responses, ticket exchanges, HTML or user data ever enter CacheStorage.
 if(url.origin!==self.location.origin||!ASSETS.includes(url.pathname)||e.request.method!=='GET')return;
 e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));
});
