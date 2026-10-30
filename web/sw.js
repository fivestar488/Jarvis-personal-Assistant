// Service worker: lets phones install JARVIS as an app, and shows Jarvis's notifications.
// It caches nothing: Jarvis is live, so every request goes straight to the PC.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});

// A notification from Jarvis (reminder, important email, security alert). Arrives even when the app is closed.
self.addEventListener("push", (event) => {
  const msg = event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(msg.title || "JARVIS", {
    body: msg.body || "",
    icon: "/static/icon-192.png",
    image: msg.image || undefined,  // security photos
    vibrate: [120, 60, 120],
    tag: msg.title,
    renotify: true,
  }));
});

// Tapping a notification opens JARVIS (or brings it to the front).
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const open = windows.find((w) => "focus" in w);
    return open ? open.focus() : self.clients.openWindow("/");
  }));
});
