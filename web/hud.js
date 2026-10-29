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
let spokenText = "";
let activeTab = "comms";
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
let actx = null, analyser = null, suitFilter = null, currentSrc = null, level = 0;
let filterOn = store.get("jarvis-filter") !== "off";
const wave = new Uint8Array(256);

function initAudio() {
  if (!actx) {
    try {
      actx = new (window.AudioContext || window.webkitAudioContext)();
      analyser = actx.createAnalyser();
      analyser.fftSize = 256;
      analyser.connect(actx.destination);
      suitFilter = buildSuitFilter();
    } catch { return; }
  }
  if (actx.state === "suspended") actx.resume().catch(() => {});
}

// The "suit filter": the polished, slightly synthetic sound of the AI in the films.
// Voice -> clean up lows -> presence & air boost -> compressor -> (dry + metallic shimmer + small room echo)
function buildSuitFilter() {
  const input = actx.createGain();
  const lowCut = Object.assign(actx.createBiquadFilter(), { type: "highpass" });
  lowCut.frequency.value = 140;
  const presence = Object.assign(actx.createBiquadFilter(), { type: "peaking" });
  presence.frequency.value = 3200; presence.Q.value = 0.9; presence.gain.value = 4;
  const air = Object.assign(actx.createBiquadFilter(), { type: "highshelf" });
  air.frequency.value = 8000; air.gain.value = 3;
  const comp = actx.createDynamicsCompressor();
  comp.threshold.value = -22; comp.ratio.value = 3;
  input.connect(lowCut).connect(presence).connect(air).connect(comp);

  const dry = actx.createGain();
  dry.gain.value = 0.9;
  comp.connect(dry).connect(analyser);

  // Shimmer: a very short, slowly wobbling delay (a gentle flanger) gives the metallic, digital edge.
  const delay = actx.createDelay(0.05);
  delay.delayTime.value = 0.006;
  const lfo = actx.createOscillator(), depth = actx.createGain();
  lfo.frequency.value = 0.25; depth.gain.value = 0.0015;
  lfo.connect(depth).connect(delay.delayTime);
  lfo.start();
  const feedback = actx.createGain(), shimmer = actx.createGain();
  feedback.gain.value = 0.25; shimmer.gain.value = 0.22;
  comp.connect(delay);
  delay.connect(feedback).connect(delay);
  delay.connect(shimmer).connect(analyser);

  // Room: a short synthetic echo, like a voice coming from all around the lab.
  const room = actx.createConvolver(), wet = actx.createGain();
  const len = Math.floor(actx.sampleRate * 0.6), ir = actx.createBuffer(2, len, actx.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const data = ir.getChannelData(ch);
    for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3.2);
  }
  room.buffer = ir;
  wet.gain.value = 0.16;
  comp.connect(room).connect(wet).connect(analyser);
  return input;
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
    // In hands-free mode keep listening while he talks, so you can cut in with "Jarvis..." or "stop".
    if (!handsFree) stopListening();
    else if (!rec) startListening("hands");
    const src = actx.createBufferSource();
    src.buffer = buffer;
    src.connect(filterOn && suitFilter ? suitFilter : analyser);
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
      if (ev.audio && voiceOn && ev.origin === myId) { spokenText = "thinking"; play(ev.audio); }
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
      if (activeTab !== "comms") document.querySelector('.tabs [data-tab="comms"]').classList.add("ping");
      if (voiceOn && mine && ev.audio) { spokenText = ev.text; setState("speaking"); play(ev.audio, afterSpeaking); }
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
    const resume = () => handsFree && !rec && (state === "idle" || state === "speaking");
    if (resume()) setTimeout(() => { if (resume()) startListening("hands"); }, 300);
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

const STOP_RE = /^\s*(?:ok(?:ay)? )?(stop|wait|hold on|quiet|enough|cancel|shut up|be quiet)\b/i;
const words = (t) => t.toLowerCase().replace(/[^a-z0-9' ]/g, " ").split(/\s+/).filter(Boolean);

// The mic also hears Jarvis through the speakers. Treat a phrase as his own echo if it's mostly words he's saying.
function isEcho(text) {
  if (!currentSrc || !spokenText) return false;
  const heard = words(text);
  if (!heard.length) return true;
  const said = new Set(words(spokenText));
  return heard.filter((w) => said.has(w)).length / heard.length >= 0.7;
}

function onHandsFree(final, interim) {
  const text = final || interim;
  if (currentSrc) {
    // Jarvis is talking: only "Jarvis..." or "stop" interrupts him.
    if (isEcho(text) || !(wakeRe().test(text) || STOP_RE.test(text))) return;
    stopAudio();
    setState("listening");
    addActivity("Interrupted.", true);
    if (!final) { showSubtitle(text, true); return; }
  }
  if (final && STOP_RE.test(final) && !wakeRe().test(final)) {
    followUpUntil = 0;
    setState("idle");
    return;
  }
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
const filterBtn = $("#tg-filter");
function updateToggles() {
  voiceBtn.classList.toggle("on", voiceOn);
  filterBtn.classList.toggle("on", filterOn);
  handsBtn.classList.toggle("on", handsFree);
}
filterBtn.onclick = () => {
  filterOn = !filterOn;
  store.set("jarvis-filter", filterOn ? "on" : "off");
  updateToggles();
};
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

// ---------- tabs (tablet & phone) ----------
function selectTab(name) {
  activeTab = name;
  document.querySelectorAll("[data-card]").forEach((c) => c.classList.toggle("active", c.dataset.card === name));
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.classList.toggle("on", b.dataset.tab === name);
    if (b.dataset.tab === name) b.classList.remove("ping");
  });
  if (name === "weather" && radarMap) setTimeout(() => radarMap.invalidateSize(), 60);
  if (name === "comms") logEl.scrollTop = logEl.scrollHeight;
  store.set("jarvis-tab", name);
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => selectTab(b.dataset.tab)));
window.addEventListener("resize", () => radarMap && radarMap.invalidateSize());

// ---------- weather & radar ----------
const DAY = (iso) => new Date(iso + "T12:00").toLocaleDateString([], { weekday: "short" }).toUpperCase();
let radarMap = null, radarLayers = [], radarTimer = null;

async function loadWeather() {
  try {
    const r = await fetch(`/api/weather?key=${encodeURIComponent(KEY)}`);
    if (!r.ok) throw new Error();
    const w = await r.json(), c = w.current, u = w.units;
    $("#wx-temp").textContent = `${c.temp}°`;
    $("#wx-text").textContent = c.text;
    $("#wx-loc").textContent = w.location.name;
    $("#wx-detail").textContent = `Feels ${c.feels}° · Wind ${c.wind} ${u.wind} · Humidity ${c.humidity}%`;
    $("#wx-days").innerHTML = w.daily.map((d, i) =>
      `<div><em>${i === 0 ? "TODAY" : DAY(d.date)}</em><b>${d.high}° <span>${d.low}°</span></b><span>☂ ${d.rain ?? 0}%</span></div>`
    ).join("");
    if (!radarMap) initRadar(w.location.lat, w.location.lon);
  } catch {
    $("#wx-text").textContent = "Weather offline";
  }
}

function initRadar(lat, lon) {
  if (!window.L) return;  // map library didn't load (no internet)
  radarMap = L.map("radar", { zoomControl: false, scrollWheelZoom: false, attributionControl: true }).setView([lat, lon], 6);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    subdomains: "abcd", maxZoom: 10, className: "basemap",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; CARTO',
  }).addTo(radarMap);
  L.circleMarker([lat, lon], { radius: 4, color: "#ff9a1f", weight: 2, fillColor: "#ff9a1f", fillOpacity: 1 }).addTo(radarMap);
  loadRadar();
  setInterval(loadRadar, 10 * 60 * 1000);
}

async function loadRadar() {
  try {
    const data = await (await fetch("https://api.rainviewer.com/public/weather-maps.json")).json();
    const frames = data.radar.past.slice(-8);
    radarLayers.forEach((l) => radarMap.removeLayer(l));
    radarLayers = frames.map((f) => L.tileLayer(`${data.host}${f.path}/256/{z}/{x}/{y}/2/1_1.png`, {
      opacity: 0, maxNativeZoom: 7, maxZoom: 10, attribution: 'Radar &copy; <a href="https://www.rainviewer.com">RainViewer</a>',
    }).addTo(radarMap));
    let i = 0;
    clearInterval(radarTimer);
    radarTimer = setInterval(() => {
      radarLayers[i].setOpacity(0);
      i = (i + 1) % radarLayers.length;
      radarLayers[i].setOpacity(0.8);
      const t = new Date(frames[i].time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
      $("#radar-time").textContent = `RADAR ${t}`;
    }, 650);
  } catch {
    $("#radar-time").textContent = "RADAR OFFLINE";
  }
}

// ---------- news ticker ----------
async function loadNews() {
  try {
    const { items } = await (await fetch(`/api/news?key=${encodeURIComponent(KEY)}`)).json();
    if (!items.length) return;
    const html = items.map((n) =>
      `<a class="tk" href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}<small>${esc(n.source)}</small></a>`
    ).join("");
    const track = $("#ticker-items");
    track.innerHTML = html + html;  // doubled so the scroll loops seamlessly
    const chars = items.reduce((n, i) => n + i.title.length, 0);
    track.style.setProperty("--dur", `${Math.max(60, chars * 0.2)}s`);
  } catch {}
}

// ---------- agenda timeline ----------
const dayKey = (d) => d.toLocaleDateString("en-CA");  // YYYY-MM-DD in local time
const hhmm = (d) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });

async function loadAgenda() {
  const box = $("#agenda");
  let data;
  try { data = await (await fetch(`/api/calendar?key=${encodeURIComponent(KEY)}`)).json(); }
  catch { return; }
  if (!data.connected) {
    box.innerHTML = `<p class="agenda-empty">Google Calendar isn't connected yet. On the PC, run <code>jarvis.bat --connect-google</code></p>`;
    return;
  }
  const now = new Date(), today = dayKey(now);
  const tomorrow = dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));
  const days = { [today]: [], [tomorrow]: [] };
  for (const e of data.events) {
    const start = e.all_day ? new Date(e.start + "T00:00") : new Date(e.start);
    const end = e.all_day ? new Date(e.end + "T00:00") : new Date(e.end);
    const key = dayKey(start) < today ? today : dayKey(start);  // multi-day events that started earlier show today
    if (days[key]) days[key].push({ ...e, s: start, f: end });
  }
  let html = "";
  for (const [key, events] of Object.entries(days)) {
    html += `<div class="agenda-day">${key === today ? "TODAY" : "TOMORROW"}</div>`;
    if (!events.length) { html += `<p class="agenda-empty">Nothing scheduled.</p>`; continue; }
    let nowShown = key !== today;
    for (const e of events) {
      if (!nowShown && !e.all_day && e.s > now) {
        html += `<div class="now-line"><span>NOW ${hhmm(now)}</span><i></i></div>`;
        nowShown = true;
      }
      const cls = e.all_day ? "" : e.f < now ? "past" : e.s <= now ? "now" : "";
      const sub = [e.all_day ? "All day" : `${hhmm(e.s)}–${hhmm(e.f)}`, e.location].filter(Boolean).join(" · ");
      html += `<div class="ev ${cls}"><time>${e.all_day ? "ALL" : hhmm(e.s)}</time>` +
        `<div class="body"><div class="title">${esc(e.title)}</div><div class="sub">${esc(sub)}</div></div></div>`;
    }
    if (!nowShown) html += `<div class="now-line"><span>NOW ${hhmm(now)}</span><i></i></div>`;
  }
  box.innerHTML = html;
}

selectTab(store.get("jarvis-tab") || "comms");
loadWeather(); setInterval(loadWeather, 10 * 60 * 1000);
loadNews(); setInterval(loadNews, 10 * 60 * 1000);
loadAgenda(); setInterval(loadAgenda, 2 * 60 * 1000);

connect();
