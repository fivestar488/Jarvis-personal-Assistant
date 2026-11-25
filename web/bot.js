"use strict";
// ---------- The workshop bot: a little robot arm in the corner of the HUD ----------
// Drawn right here as a few SVG shapes (no 3D engine, so it costs next to nothing). It sways while idle, looks up
// when you talk, tilts its head while Jarvis thinks, nods while he speaks, turns toward alerts with its lamp in the
// alert's colour, and slumps when something fails. It stops moving in Low Power Mode and when the window is hidden.
const Bot = (() => {
  const host = document.querySelector(".core");
  if (!host) return { react() {} };
  const box = document.createElement("div");
  box.id = "bot";
  box.setAttribute("aria-hidden", "true");
  box.innerHTML = `
    <svg viewBox="0 0 140 120">
      <ellipse class="bot-shadow" cx="50" cy="110" rx="36" ry="6"/>
      <rect class="bot-part" x="32" y="96" width="36" height="12" rx="3"/>
      <g class="bot-a1">
        <rect class="bot-part" x="45" y="46" width="10" height="52" rx="4"/>
        <circle class="bot-joint" cx="50" cy="96" r="7"/>
        <g class="bot-a2">
          <rect class="bot-part" x="50" y="43.5" width="44" height="9" rx="4"/>
          <circle class="bot-joint" cx="50" cy="48" r="6"/>
          <g class="bot-a3">
            <circle class="bot-joint" cx="93" cy="48" r="5"/>
            <path class="bot-part" d="M95 39 h15 l9 -5 v28 l-9 -5 h-15 z"/>
            <path class="bot-claw" d="M119 36 l9 -6 M119 60 l9 6"/>
            <circle class="bot-eye" cx="106" cy="48" r="3.4"/>
          </g>
        </g>
      </g>
    </svg>
    <span class="bot-name">BOT</span>`;
  host.appendChild(box);
  const [a1, a2, a3] = [".bot-a1", ".bot-a2", ".bot-a3"].map((s) => box.querySelector(s));
  const eye = box.querySelector(".bot-eye");

  // Current angles (degrees) ease toward the pose's angles
  const now = { a: -6, b: 14, c: -12 };
  let mood = null, moodUntil = 0, level = "note", last = 0;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const LEVEL_EYE = { note: "var(--cyan-hi)", caution: "var(--amber)", warning: "#ff7a1a", critical: "var(--red)" };

  function pose(t) {
    const state = document.body.dataset.state || "idle";
    if (mood && performance.now() < moodUntil) {
      if (mood === "alert") return { a: 12, b: -12, c: -22 + Math.sin(t * 9) * (level === "critical" ? 6 : 2), eye: LEVEL_EYE[level], glow: 1 };
      if (mood === "slump") return { a: -24, b: 58, c: 48, eye: "var(--red)", glow: 0.35 };
      if (mood === "happy") return { a: -4, b: 6 - Math.abs(Math.sin(t * 10)) * 10, c: -20, eye: "var(--cyan-hi)", glow: 1 };
      if (mood === "look") return { a: 4, b: -8, c: -34, eye: "var(--cyan-hi)", glow: 1 };
    }
    mood = null;
    if (state === "listening") return { a: -2, b: -6, c: -28, eye: "var(--cyan-hi)", glow: 1 };
    if (state === "thinking") return { a: -10, b: 20, c: -6 + Math.sin(t * 4) * 12, eye: "var(--amber)", glow: Math.sin(t * 8) > 0 ? 1 : 0.4 };
    if (state === "speaking") return { a: -6, b: 10, c: -12 + Math.sin(t * 7) * 7, eye: "var(--cyan-hi)", glow: 1 };
    return { a: -6 + Math.sin(t * 0.6) * 3, b: 14 + Math.sin(t * 0.9) * 4, c: -12 + Math.sin(t * 1.3) * 6, eye: "var(--cyan)", glow: 0.7 };
  }

  function draw(p) {
    a1.setAttribute("transform", `rotate(${now.a.toFixed(2)} 50 96)`);
    a2.setAttribute("transform", `rotate(${now.b.toFixed(2)} 50 48)`);
    a3.setAttribute("transform", `rotate(${now.c.toFixed(2)} 93 48)`);
    eye.style.fill = p.eye;
    eye.style.opacity = p.glow;
  }

  function frame(ms) {
    requestAnimationFrame(frame);
    if (document.hidden || document.body.classList.contains("low-power") || ms - last < 33) return;  // ~30 fps
    const dt = Math.min(0.1, (ms - last) / 1000);
    last = ms;
    const p = pose(ms / 1000), k = reduced ? 1 : Math.min(1, dt * 6);
    now.a += (p.a - now.a) * k; now.b += (p.b - now.b) * k; now.c += (p.c - now.c) * k;
    draw(p);
  }
  requestAnimationFrame(frame);

  function set(m, seconds) { mood = m; moodUntil = performance.now() + seconds * 1000; }
  const FAILED = /\b(couldn'?t|could not|failed|error|unable|can'?t reach|isn'?t connected|no credit)\b/i;
  const DONE = /^(done|captured|saved|added|sent|opened|right away|on it|very good|all \d+ checks passed|everything'?s in order)/i;

  // Called by hud.js for every event from Jarvis
  function react(ev) {
    if (ev.type === "announce") { level = ev.level || "caution"; set("alert", level === "critical" ? 6 : 4); }
    else if (ev.type === "status" && FAILED.test(ev.text || "")) set("slump", 4);
    else if (ev.type === "reply" && FAILED.test((ev.text || "").slice(0, 120))) set("slump", 4);
    else if (ev.type === "reply" && DONE.test(ev.text || "")) set("happy", 1.2);
    else if (ev.type === "holo" && ev.action === "open") set("look", 2.5);
  }
  return { react };
})();
