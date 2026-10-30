// Minimal service worker so phones offer to install JARVIS as an app.
// It caches nothing: Jarvis is live, so every request goes straight to the PC.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
