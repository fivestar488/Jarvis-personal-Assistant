"use strict";
const $ = (s) => document.querySelector(s);

// ---------- access key (comes in the link/QR code, then remembered on this device) ----------
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};
const params = new URLSearchParams(location.search);
const KEY = params.get("key") || store.get("jarvis-key") || "";
if (params.get("key")) { store.set("jarvis-key", KEY); history.replaceState(null, "", location.pathname); }

// ---------- elements ----------
const reactor = $("#reactor"), stateLabel = $("#state-label"), subtitle = $("#subtitle");
const logEl = $("#log"), activityEl = $("#activity"), input = $("#input"), micBtn = $("#btn-mic");
const voiceBtn = $("#tg-voice"), handsBtn = $("#tg-hands");

let ws = null, myId = null, retry = 0, greeted = false;
let state = "idle";
let voiceOn = store.get("jarvis-voice") !== "off";
let handsFree = false;
let wakeWords = ["jarvis"];
let userName = "sir";

const LABELS = { idle: "STANDBY", listening: "LISTENING", thinking: "PROCESSING", speaking: "SPEAKING" };
function setState(s) {
  state = s;
  document.body.dataset.state = s;
  stateLabel.textContent = LABELS[s];
}

// ---------- boot sequence ----------
(function boot() {
  const lines = [
    "INITIALIZING J.A.R.V.I.S. ......... OK",
    "NEURAL INTERFACE ................... OK",
    "VOICE SYNTHESIS .................... OK",
    "SYSTEM DIAGNOSTICS ................. OK",
    "SECURE UPLINK ...................... OK",
    "", "ALL SYSTEMS ONLINE",
  ];
  const out = $("#boot-log");
  lines.forEach((l, i) => setTimeout(() => { out.textContent += l + "\n"; }, 140 + i * 160));
  setTimeout(() => $("#boot").classList.add("done"), 140 + lines.length * 160 + 450);
})();

// ---------- clock ----------
function tickClock() {
  const d = new Date();
  $("#clock").textContent = d.toLocaleTimeString([], { hour12: false });
  $("#date").textContent = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}
tickClock(); setInterval(tickClock, 1000);

// ---------- rendering ----------
const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function md(text) {
  const blocks = [];
  let s = esc(text).replace(/```\w*\n?([\s\S]*?)```/g, (_, code) => { blocks.push(code); return `\u0000${blocks.length - 1}\u0000`; });
  s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/^\s*[-*] (.+)$/gm, "&#9656; $1")
    .replace(/^#+ (.+)$/gm, "<b>$1</b>")
    .replace(/\n/g, "<br>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<pre><code>${blocks[i]}</code></pre>`);
}
const plain = (t) => t.replace(/```[\s\S]*?```/g, " [code] ").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*_#`>]/g, "").replace(/\s+/g, " ").trim();
const now = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });

function addMsg(kind, text) {
  const who = { user: "YOU", jarvis: "JARVIS", alert: "ALERT" }[kind];
  const el = document.createElement("div");
  el.className = `msg ${kind}`;
  el.innerHTML = `<div class="who"><span>${who}</span><time>${now()}</time></div><div>${md(text)}</div>`;
  logEl.appendChild(el);
  while (logEl.children.length > 120) logEl.firstChild.remove();
  logEl.scrollTop = logEl.scrollHeight;
}

function addActivity(text, sys = false) {
  const li = document.createElement("li");
  if (sys) li.className = "sys";
  li.innerHTML = `<time>${now()}</time><span>${esc(text)}</span>`;
  activityEl.prepend(li);
  while (activityEl.children.length > 60) activityEl.lastChild.remove();
}

let typeTimer = null;
function showSubtitle(text, dim = false) {
  clearInterval(typeTimer);
  subtitle.classList.toggle("dim", dim);
  let full = plain(text);
  if (full.length > 260) full = full.slice(0, 257) + "...";
  if (dim) { subtitle.textContent = full; return; }
  let i = 0;
  subtitle.textContent = "";
  typeTimer = setInterval(() => {
    i += 2;
    subtitle.textContent = full.slice(0, i);
    if (i >= full.length) clearInterval(typeTimer);
  }, 18);
}

// ---------- audio: Jarvis's voice drives the reactor glow ----------
let actx = null, analyser = null, currentSrc = null, level = 0;
const wave = new Uint8Array(256);

function initAudio() {
  if (!actx) {
    try {
      actx = new (window.AudioContext || window.webkitAudioContext)();
      analyser = actx.createAnalyser();
      analyser.fftSize = 256;
      analyser.connect(actx.destination);
    } catch { return; }
  }
  if (actx.state === "suspended") actx.resume().catch(() => {});
}
document.addEventListener("pointerdown", initAudio);
document.addEventListener("keydown", initAudio);

function stopAudio() {
  if (currentSrc) { const s = currentSrc; currentSrc = null; try { s.stop(); } catch {} }
}

async function play(b64, after) {
  initAudio();
  if (!actx) return after && after();
  try {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const buffer = await actx.decodeAudioData(bytes.buffer);
    stopAudio();
    stopListening();
    const src = actx.createBufferSource();
    src.buffer = buffer;
    src.connect(analyser);
    src.onended = () => { if (currentSrc === src) { currentSrc = null; after && after(); } };
    currentSrc = src;
    src.start();
  } catch { after && after(); }
}

function blip(freq = 880, dur = 0.06, vol = 0.04) {
  if (!actx || actx.state !== "running") return;
  const o = actx.createOscillator(), g = actx.createGain();
  o.frequency.value = freq; o.type = "sine";
  g.gain.setValueAtTime(vol, actx.currentTime);
  g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + dur);
  o.connect(g).connect(actx.destination);
  o.start(); o.stop(actx.currentTime + dur);
}

(function animate() {
  let target = 0;
  if (analyser && currentSrc) {
    analyser.getByteTimeDomainData(wave);
    let sum = 0;
    for (const v of wave) { const d = (v - 128) / 128; sum += d * d; }
    target = Math.min(1, Math.sqrt(sum / wave.length) * 4.5);
  }
  level += (target - level) * 0.35;
  reactor.style.setProperty("--level", level.toFixed(3));
  requestAnimationFrame(animate);
})();

reactor.addEventListener("click", () => {
  if (currentSrc) { stopAudio(); afterSpeaking(); }
});

function afterSpeaking() {
  setState("idle");
  if (handsFree) { followUpUntil = Date.now() + 7000; startListening("hands"); }
}

// ---------- connection ----------
function setLink(online) {
  const el = $("#link");
  el.classList.toggle("online", online);
  el.querySelector("b").textContent = online ? "ONLINE" : "OFFLINE";
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws?key=${encodeURIComponent(KEY)}`);
  ws.onopen = () => { retry = 0; setLink(true); };
  ws.onclose = (e) => {
    setLink(false);
    if (e.code === 4003) { $("#locked").hidden = false; return; }
    addActivity("Uplink lost. Reconnecting...", true);
    setTimeout(connect, Math.min(1000 * 2 ** retry++, 10000));
  };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify(obj)); return true; }
  addActivity("Not connected. Is Jarvis running on the PC?", true);
  return false;
}

function submit(text) {
  text = text.trim();
  if (!text) return;
  initAudio();
  if (send({ type: "message", text })) {
    blip(1200, 0.05);
    stopListening();
    followUpUntil = 0;
    input.value = "";
    setState("thinking");
    showSubtitle("Thinking...", true);
  }
}

function handle(ev) {
  switch (ev.type) {
    case "hello":
      myId = ev.id; wakeWords = ev.wake_words || wakeWords; userName = ev.user || userName;
      addActivity("Secure uplink established.", true);
      if (!greeted) {
        greeted = true;
        const h = new Date().getHours();
        const g = `Good ${h < 12 ? "morning" : h < 18 ? "afternoon" : "evening"}, ${userName}. All systems are online. How can I help?`;
        addMsg("jarvis", g); showSubtitle(g);
      }
      break;
    case "user":
      addMsg("user", ev.text);
      if (ev.origin !== myId) { setState("thinking"); showSubtitle("Thinking...", true); }
      break;
    case "state":
      setState(ev.state);
      if (ev.audio && voiceOn && ev.origin === myId) play(ev.audio);
      break;
    case "status":
      addActivity(ev.text);
      showSubtitle("▸ " + ev.text, true);
      break;
    case "reply":
    case "announce": {
      const alert = ev.type === "announce";
      addMsg(alert ? "alert" : "jarvis", ev.text);
      showSubtitle(ev.text);
      blip(alert ? 660 : 990, 0.08);
      const mine = alert || ev.origin === myId;
      if (voiceOn && mine && ev.audio) { setState("speaking"); play(ev.audio, afterSpeaking); }
      else if (!currentSrc) afterSpeaking();
      break;
    }
    case "confirm":
      showConfirm(ev.id, ev.question);
      break;
    case "confirm_done":
      if (confirmId === ev.id) hideConfirm();
      break;
  }
}

// ---------- permission pop-up ----------
let confirmId = null;
function showConfirm(id, question) {
  confirmId = id;
  $("#confirm-q").textContent = question;
  $("#confirm").hidden = false;
  blip(520, 0.15, 0.06); setTimeout(() => blip(520, 0.15, 0.06), 220);
}
function hideConfirm() { confirmId = null; $("#confirm").hidden = true; }
function answerConfirm(answer) {
  if (confirmId) send({ type: "confirm_reply", id: confirmId, answer });
  addActivity(answer ? "Action authorized." : "Action denied.", true);
  hideConfirm();
}
$("#allow").onclick = () => answerConfirm(true);
$("#deny").onclick = () => answerConfirm(false);

// ---------- speech recognition (browser) ----------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const canListen = !!SR && window.isSecureContext;
let rec = null, followUpUntil = 0;

if (!canListen) {
  micBtn.classList.add("off");
  micBtn.title = "Voice input needs Chrome or Edge on the PC. On a phone, use your keyboard's microphone.";
  handsBtn.hidden = true;
  input.placeholder = /Mobi|Android|iPhone/i.test(navigator.userAgent)
    ? "Type, or tap your keyboard's mic to talk..."
    : "Type a command...";
}

const wakeRe = () => new RegExp(`\\b(?:hey |ok |okay )?(${wakeWords.join("|")})\\b[\\s,.!?]*`, "i");

function startListening(mode) {
  if (!canListen) return;
  stopListening();
  const r = new SR();
  r.lang = navigator.language || "en-GB";
  r.interimResults = true;
  r.continuous = mode === "hands";
  r.mode = mode;
  r.onresult = (e) => {
    let final = "", interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      e.results[i].isFinal ? (final += t) : (interim += t);
    }
    mode === "ptt" ? onPushToTalk(final, interim) : onHandsFree(final, interim);
  };
  r.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      handsFree = false; updateToggles();
      addActivity("Microphone access was blocked.", true);
    }
  };
  r.onend = () => {
    if (rec !== r) return;  // replaced or stopped on purpose
    rec = null;
    micBtn.classList.remove("active");
    if (state === "listening") setState("idle");
    if (handsFree && state === "idle") setTimeout(() => { if (!rec && handsFree && state === "idle") startListening("hands"); }, 300);
  };
  rec = r;
  try { r.start(); } catch { rec = null; return; }
  if (mode === "ptt") { micBtn.classList.add("active"); setState("listening"); showSubtitle("Listening...", true); }
}

function stopListening() {
  if (!rec) return;
  const r = rec; rec = null;
  micBtn.classList.remove("active");
  try { r.abort(); } catch {}
}

function onPushToTalk(final, interim) {
  input.value = final || interim;
  if (final) submit(final);
}

function onHandsFree(final, interim) {
  const text = final || interim;
  const awaiting = Date.now() < followUpUntil;
  if (!final) {
    if (wakeRe().test(text) || awaiting) { setState("listening"); showSubtitle(text, true); }
    return;
  }
  if (wakeRe().test(final)) {
    const command = final.replace(wakeRe(), " ").replace(/^[\s,.!?]+|[\s,.!?]+$/g, "");
    if (command) submit(command);
    else { followUpUntil = Date.now() + 7000; setState("listening"); showSubtitle("Yes?"); blip(1000, 0.06); }
  } else if (awaiting && final.trim()) {
    submit(final);
  } else if (state === "listening") {
    setState("idle");
  }
}

micBtn.onclick = () => {
  initAudio();
  if (!canListen) { input.focus(); return; }
  if (currentSrc) stopAudio();
  if (rec && rec.mode === "ptt") { stopListening(); setState("idle"); return; }
  startListening("ptt");
};

// ---------- controls ----------
function updateToggles() {
  voiceBtn.classList.toggle("on", voiceOn);
  handsBtn.classList.toggle("on", handsFree);
}
voiceBtn.onclick = () => {
  voiceOn = !voiceOn;
  store.set("jarvis-voice", voiceOn ? "on" : "off");
  if (!voiceOn) stopAudio();
  updateToggles();
};
handsBtn.onclick = () => {
  initAudio();
  handsFree = !handsFree;
  updateToggles();
  if (handsFree) {
    addActivity(`Hands-free on. Say "${wakeWords[0][0].toUpperCase() + wakeWords[0].slice(1)}, ..."`, true);
    if (state === "idle") startListening("hands");
  } else {
    stopListening();
    if (state === "listening") setState("idle");
  }
};
$("#form").addEventListener("submit", (e) => { e.preventDefault(); submit(input.value); });
$("#btn-reset").onclick = () => submit("new session");
updateToggles();

// ---------- diagnostics ----------
function setGauge(id, value) {
  const g = $(id);
  if (value == null) return;
  g.querySelector(".val").style.strokeDashoffset = 213.6 * (1 - value / 100);
  g.querySelector("b").textContent = Math.round(value) + "%";
  g.classList.toggle("warn", value >= 75 && value < 90);
  g.classList.toggle("crit", value >= 90);
}

async function pollStats() {
  try {
    const r = await fetch(`/api/stats?key=${encodeURIComponent(KEY)}`);
    if (!r.ok) return;
    const s = await r.json();
    setGauge("#g-cpu", s.cpu); setGauge("#g-ram", s.ram); setGauge("#g-disk", s.disk);
    if (s.battery != null) {
      $("#bat-text").textContent = `${s.battery}%${s.charging ? " ⚡" : ""}`;
      $("#bat-fill").style.width = s.battery + "%";
    } else {
      $("#bat-text").textContent = "AC POWER";
      $("#bat-fill").style.width = "100%";
    }
    $("#uptime").textContent = s.uptime;
    $("#procs").textContent = s.processes;
    $("#mini-stats").textContent = `CPU ${Math.round(s.cpu)}%  ·  RAM ${Math.round(s.ram)}%` + (s.battery != null ? `  ·  PWR ${s.battery}%` : "");
  } catch {}
}
pollStats(); setInterval(pollStats, 3000);

connect();
