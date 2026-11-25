// Shared by the popup and the right-click menu: read the tab, and ask Jarvis (running on this PC) about it.

async function settings() {
  const s = await chrome.storage.local.get({ key: "", port: 8765, speak: true });
  return s;
}

// The page's title, address, visible text and whatever is highlighted
async function readTab(tab) {
  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => ({
      title: document.title,
      url: location.href,
      text: (document.body?.innerText || "").replace(/\n{3,}/g, "\n\n").slice(0, 20000),
      selection: String(getSelection() || "").slice(0, 8000),
    }),
  });
  return res.result;
}

async function askJarvis(page, question) {
  const { key, port, speak } = await settings();
  if (!key) throw new Error("Paste your Jarvis key first (open this extension's options).");
  const r = await fetch(`http://127.0.0.1:${port}/api/ask-page?key=${encodeURIComponent(key)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...page, question, speak }),
  }).catch(() => { throw new Error("Jarvis isn't running on this PC. Start it with jarvis.bat."); });
  if (r.status === 403) throw new Error("Jarvis didn't accept the key. Paste it again in the options.");
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Jarvis answered ${r.status}.`);
  return (await r.json()).answer;
}

// "http://192.168.1.5:8765/?key=abc" or just "abc" -> "abc"
function keyFrom(text) {
  const t = (text || "").trim();
  const m = t.match(/[?&]key=([^&#\s]+)/);
  return m ? decodeURIComponent(m[1]) : t;
}
