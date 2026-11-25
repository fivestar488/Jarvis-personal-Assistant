"use strict";
const $ = (id) => document.getElementById(id);

function show(text, error = false) {
  $("out").textContent = text;
  $("out").classList.toggle("err", error);
}

async function run(question, selectionOnly) {
  for (const b of document.querySelectorAll("button")) b.disabled = true;
  show("Jarvis is reading the page...");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const page = await readTab(tab).catch(() => {
      throw new Error("Browsers don't let extensions read this kind of page (settings, the store, new tabs).");
    });
    if (selectionOnly && !page.selection) throw new Error("Highlight some text on the page first.");
    if (selectionOnly) page.text = "";
    show(await askJarvis(page, question));
  } catch (e) {
    show(e.message || String(e), true);
  } finally {
    for (const b of document.querySelectorAll("button")) b.disabled = false;
  }
}

(async () => {
  const s = await settings();
  $("setup").hidden = !!s.key;
  $("main").hidden = !s.key;
  $("speak").checked = s.speak;
  $("q").focus();
})();

$("save").onclick = async () => {
  const key = keyFrom($("key").value);
  if (!key) return show("Paste the key first.", true);
  await chrome.storage.local.set({ key });
  $("setup").hidden = true;
  $("main").hidden = false;
  show("Saved. Ask away.");
};
$("speak").onchange = () => chrome.storage.local.set({ speak: $("speak").checked });
$("ask").onclick = () => run($("q").value.trim(), false);
$("sum").onclick = () => run("Summarise this page.", false);
$("sel").onclick = () => run("Summarise what I highlighted.", true);
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("ask").click(); } });
