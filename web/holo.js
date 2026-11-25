"use strict";
// ---------- Holograms: Iron Man-style 3D views you control with your hands ----------
// Opened by voice ("show me a hologram of a jet engine", "expand the weather") or with your hands: point at a
// HUD panel and clap. Three kinds:
//   panel   the weather, news, agenda, system, Spotify or reminders, blown up full-screen
//   object  built-in 3D models (globe, solar system, atom, DNA, jet engine) that come apart into labelled parts
//   topic   anything else: a 3D map whose parts burst into their own parts (the AI works them out)
// Hands (webcam, tracked by MediaPipe inside this browser; no video leaves the device):
//   move your hand      cursor                   pinch thumb + index    click / pick (pinch a picked part again to expand it)
//   pinch and drag      rotate                   pinch with both hands, pull apart / together    zoom
//   clap, or spread both open hands apart    expand / pull apart      flick an open hand sideways    throw it away
// Mouse and touch work too: drag to rotate, wheel or two fingers to zoom, click to pick, double-click to expand.

const Holo = (() => {
  const THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
  const MP = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
  const HAND_MODEL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
  const HINTS = {
    topic: "PINCH a part to pick it · CLAP or SPREAD HANDS to expand it · PINCH + DRAG to rotate · FLICK to dismiss",
    object: "CLAP or SPREAD HANDS to pull it apart · PINCH a part for details · PINCH + DRAG to rotate · FLICK to dismiss",
    panel: "PINCH to press · CLAP to fan the cards out · BOTH HANDS PINCH to zoom · FLICK to dismiss",
    scan: "CLAP or SPREAD HANDS to break it down in 3D · FLICK to dismiss",
  };

  // ---------- page elements (built on first use) ----------
  let el = null;
  function build() {
    if (el) return;
    const box = document.createElement("div");
    box.id = "holo";
    box.hidden = true;
    box.innerHTML = `
      <div class="holo-stage"></div>
      <div class="holo-cards"><div class="holo-sheet"></div></div>
      <div class="holo-head"><span class="holo-kind"></span><h2 class="holo-title"></h2><div class="holo-path"></div></div>
      <div class="holo-busy" hidden><i></i><span></span></div>
      <div class="holo-info" hidden><b></b><p></p></div>
      <div class="holo-hint"></div>
      <button class="holo-close" type="button">CLOSE</button>`;
    document.body.appendChild(box);
    const cursors = document.createElement("div");
    cursors.id = "hand-cursors";
    cursors.innerHTML = `<i class="hand-cursor"></i><i class="hand-cursor second"></i>`;
    document.body.appendChild(cursors);
    const cam = document.createElement("div");
    cam.id = "hand-cam";
    cam.hidden = true;
    cam.innerHTML = `<video playsinline muted></video><canvas width="192" height="144"></canvas><span>HAND TRACKING</span>`;
    document.body.appendChild(cam);
    el = {
      box, stage: box.querySelector(".holo-stage"), cards: box.querySelector(".holo-cards"),
      sheet: box.querySelector(".holo-sheet"), kind: box.querySelector(".holo-kind"),
      title: box.querySelector(".holo-title"), path: box.querySelector(".holo-path"),
      busy: box.querySelector(".holo-busy"), info: box.querySelector(".holo-info"), hint: box.querySelector(".holo-hint"),
      cursors: [...cursors.children], cam, video: cam.querySelector("video"), camCanvas: cam.querySelector("canvas"),
    };
    box.querySelector(".holo-close").onclick = () => close();
    setupPointer();
  }

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#3fc8ff";
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const ease = (k) => 1 - Math.pow(1 - k, 3);
  const easeBack = (k) => 1 + 2.2 * Math.pow(k - 1, 3) + 1.2 * Math.pow(k - 1, 2);
  const beep = (f, d) => { try { blip(f, d, 0.035); } catch {} };

  function showBusy(text) { el.busy.hidden = !text; el.busy.querySelector("span").textContent = text || ""; }
  function showInfo(name, detail) {
    el.info.hidden = !name;
    el.info.querySelector("b").textContent = name || "";
    el.info.querySelector("p").textContent = detail || "";
  }

  // ---------- the 3D engine (three.js, loaded the first time a hologram opens) ----------
  let threeLoading = null;
  function loadThree() {
    if (window.THREE) return Promise.resolve();
    return threeLoading ||= new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = THREE_URL;
      s.onload = ok;
      s.onerror = () => { threeLoading = null; s.remove(); fail(new Error("Couldn't load the 3D engine. Is the internet on?")); };
      document.head.appendChild(s);
    });
  }

  let R = null;  // renderer, scene, camera...
  function setupThree() {
    if (R) return;
    const T = THREE;
    const renderer = new T.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
    el.stage.appendChild(renderer.domElement);
    const scene = new T.Scene();
    const camera = new T.PerspectiveCamera(50, 1, 0.1, 200);
    camera.position.set(0, 0.4, 10);
    const pivot = new T.Group();    // turned and zoomed by your hands
    const content = new T.Group();  // shifted so the picked part sits in the middle
    pivot.add(content);
    scene.add(pivot);
    const deco = new T.Group();     // projector rings and floating dust, always there
    scene.add(deco);
    R = { T, renderer, scene, camera, pivot, content, deco, ray: new T.Raycaster(), clock: new T.Clock(), focus: new T.Vector3() };
    const resize = () => {
      const w = innerWidth, h = innerHeight;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.position.z = w < h ? 14 : 10;  // phones (portrait) need to stand back
      camera.updateProjectionMatrix();
    };
    resize();
    addEventListener("resize", resize);
  }

  const M = {  // glowing hologram materials
    line: (color, opacity = 0.6) => new THREE.LineBasicMaterial({ color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false }),
    glow: (color, opacity = 0.2) => new THREE.MeshBasicMaterial({ color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }),
    wire: (color, opacity = 0.5) => new THREE.MeshBasicMaterial({ color, wireframe: true, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false }),
  };

  // A solid shape drawn the hologram way: faint fill + bright edges (or a wireframe for round things)
  function shape(geometry, color, { fill = 0.1, edges = 0.75, wire = false } = {}) {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(geometry, M.glow(color, fill)));
    g.add(wire ? new THREE.Mesh(geometry, M.wire(color, edges * 0.6))
               : new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), M.line(color, edges)));
    return g;
  }

  function label(text, color, height = 0.36) {
    const c = document.createElement("canvas"), ctx = c.getContext("2d");
    const font = "600 40px Orbitron, Rajdhani, sans-serif";
    text = String(text).toUpperCase();
    ctx.font = font;
    c.width = Math.ceil(ctx.measureText(text).width) + 40;
    c.height = 64;
    ctx.font = font;
    ctx.textBaseline = "middle";
    ctx.shadowColor = color;
    ctx.shadowBlur = 14;
    ctx.fillStyle = color;
    ctx.fillText(text, 20, 34);
    const tex = new THREE.CanvasTexture(c);
    tex.minFilter = THREE.LinearFilter;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    sprite.scale.set(height * c.width / c.height, height, 1);
    return sprite;
  }

  function lineBetween(color, opacity = 0.45) {
    const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
    return new THREE.Line(geo, M.line(color, opacity));
  }
  function setLine(line, a, b) {
    const p = line.geometry.attributes.position;
    p.setXYZ(0, a.x, a.y, a.z);
    p.setXYZ(1, b.x, b.y, b.z);
    p.needsUpdate = true;
    line.geometry.computeBoundingSphere();
  }

  function dispose(obj) {
    obj.traverse((o) => {
      o.geometry?.dispose();
      for (const m of [].concat(o.material || [])) { m.map?.dispose(); m.dispose(); }
    });
    obj.parent?.remove(obj);
  }

  function buildDeco(color) {
    while (R.deco.children.length) dispose(R.deco.children[0]);
    const base = new THREE.Group();
    base.position.y = -3.3;
    base.rotation.x = -Math.PI / 2;
    [[2.6, 2.64, 0.5], [3.4, 3.46, 0.25], [4.4, 4.43, 0.15]].forEach(([a, b, o]) =>
      base.add(new THREE.Mesh(new THREE.RingGeometry(a, b, 96), M.glow(color, o))));
    const ticks = new THREE.Mesh(new THREE.RingGeometry(3.0, 3.25, 64, 1, 0, Math.PI * 2), M.wire(color, 0.18));
    base.add(ticks);
    R.deco.add(base);
    R.decoSpin = ticks;
    const n = 260, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 22;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 12;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 10 - 2;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const dust = new THREE.Points(geo, new THREE.PointsMaterial({ color, size: 0.04, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }));
    R.deco.add(dust);
    R.dust = dust;
  }

  // ---------- view controls (shared by hands, mouse and voice) ----------
  const ctl = { x: 0.25, y: 0, tx: 0.25, ty: 0, z: 1, tz: 1, spin: true, idleUntil: 0 };
  function resetView() { Object.assign(ctl, { tx: 0.25, ty: 0, tz: 1, spin: true }); if (model?.kind === "topic") select(model.root); }
  function rotateBy(dx, dy) {
    ctl.ty += dx;
    ctl.tx = clamp(ctl.tx + dy, -1.3, 1.3);
    ctl.idleUntil = performance.now() + 4000;  // stop the slow spin for a while after you've turned it
  }
  function zoomTo(z) { ctl.tz = clamp(z, 0.3, 3.5); }

  // ---------- open / close ----------
  let isOpen = false, current = null, model = null, raf = 0, tweens = [];
  function tween(ms, fn, done) { tweens.push({ t0: performance.now(), ms, fn, done }); }

  async function open(kind, subject, parts, image, saved = {}) {
    build();
    if (isOpen) clearModel();
    current = { kind, subject };
    isOpen = true;
    el.box.hidden = false;
    el.box.className = "show kind-" + kind;
    el.kind.textContent = { topic: "ANALYSIS", object: "3D MODEL", panel: "EXPANDED VIEW", scan: "DESK SCANNER" }[kind];
    el.title.textContent = subject;
    el.path.textContent = "";
    el.hint.textContent = HINTS[kind];
    showInfo("");
    showBusy("");
    el.sheet.innerHTML = "";
    el.sheet.classList.remove("spread");
    Object.assign(ctl, { x: 0.9, tx: kind === "object" && subject === "solar system" ? 0.55 : 0.25, y: -1.2, ty: 0, z: 0.2, tz: 1, spin: true });
    beep(520, 0.08); setTimeout(() => beep(980, 0.1), 90);
    send({ type: "holo_state", open: true, kind, subject });
    if (!lowPowerOn()) startHands();  // (mouse and touch still work in Low Power Mode)
    syncClapEar();
    const token = ++openCount;
    // A scan is plain page content: show it now, so a result that arrives quickly is never missed while the
    // 3D engine is still loading
    if (kind === "scan") { buildScan(image); if (saved.result) fillScan(saved.result); }
    try {
      await loadThree();
      if (token !== openCount) return;  // another hologram was opened meanwhile
      setupThree();
      buildDeco(css("--cyan"));
      if (!raf) { R.clock.getDelta(); raf = requestAnimationFrame(frame); }
    } catch (e) {
      if (kind !== "panel" && kind !== "scan") { showInfo("3D unavailable", e.message); return; }
    }
    if (token !== openCount) return;
    if (kind === "panel") await buildPanel(subject);
    else if (kind === "object") buildObject(subject);
    else if (kind === "topic") buildTopic(subject, parts, saved.tree);
  }
  let openCount = 0;

  // What's on screen, so it can be saved to the workspace or thrown to the phone and rebuilt exactly
  function spec() {
    if (!isOpen || !current) return null;
    const s = { kind: current.kind, subject: current.subject };
    if (model?.kind === "topic") {
      const ser = (n) => ({ name: n.name, detail: n.detail, children: n.children.map(ser) });
      s.tree = ser(model.root);
    }
    if (model?.kind === "scan") {
      s.image = el.sheet.querySelector(".scan-photo img")?.src;
      s.result = model.result;
    }
    return s;
  }
  const isMainScreen = () => matchMedia("(pointer: fine)").matches;  // the PC, not the phone

  // Workshop looks: wireframe, x-ray, a new colour, or back to normal
  const COLORS = { red: "#ff3b30", blue: "#3fc8ff", green: "#39ff88", gold: "#ffc23d", white: "#ffffff",
                   purple: "#b36bff", orange: "#ff9a1f", cyan: "#3fe8ff", yellow: "#ffe14d", pink: "#ff6bd5" };
  function restyle(mode, color) {
    if (!model?.group) return;
    model.group.traverse((o) => {
      if (o.isSprite) return;  // labels stay readable
      for (const m of [].concat(o.material || [])) {
        m.userData.orig ||= { opacity: m.opacity, color: m.color ? m.color.getHex() : null };
        const orig = m.userData.orig, fill = o.isMesh && !m.wireframe;
        if (mode === "solid") { m.opacity = orig.opacity; if (m.color && orig.color != null) m.color.setHex(orig.color); }
        else if (mode === "wireframe") m.opacity = fill ? 0 : Math.min(1, orig.opacity * 1.4);
        else if (mode === "xray") m.opacity = fill ? 0.04 : orig.opacity * 0.45;
        else if (mode === "color" && m.color) m.color.set(color);
      }
    });
    beep(mode === "solid" ? 520 : 880, 0.06);
  }

  // A video in a floating holographic pane ("play the trailer for...")
  function showVideo(id, title) {
    closeVideo();
    const box = document.createElement("div");
    box.id = "holo-video";
    box.innerHTML = `<div class="hv-head"><span>${esc(title || "VIDEO")}</span><button type="button">CLOSE</button></div>
      <div class="hv-frame"><iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&rel=0&modestbranding=1"
      allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen title="${esc(title || "Video")}"></iframe></div>`;
    box.querySelector("button").onclick = closeVideo;
    document.body.appendChild(box);
    beep(660, 0.06); setTimeout(() => beep(990, 0.08), 80);
  }
  function closeVideo() { document.getElementById("holo-video")?.remove(); }

  function clearModel() {
    if (model?.group) dispose(model.group);
    if (R) while (R.content.children.length) dispose(R.content.children[0]);
    model = null;
    if (R) R.focus.set(0, 0, 0);
  }

  function close(direction = 0) {
    if (!isOpen) return;
    isOpen = false;
    beep(700, 0.06); setTimeout(() => beep(380, 0.1), 70);
    el.box.className = direction < 0 ? "fly-left" : direction > 0 ? "fly-right" : "hide";
    setTimeout(() => {
      if (isOpen) return;  // reopened meanwhile
      el.box.hidden = true;
      clearModel();
      el.sheet.innerHTML = "";
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
    }, 380);
    send({ type: "holo_state", open: false });
    if (!handsWanted()) stopHands();
    syncClapEar();
  }

  // ---------- the animation loop ----------
  function frame() {
    raf = isOpen ? requestAnimationFrame(frame) : 0;
    if (!raf) return;
    const dt = Math.min(R.clock.getDelta(), 0.05), t = R.clock.elapsedTime, now = performance.now();
    if (ctl.spin && now > ctl.idleUntil && !drag && model?.kind !== "panel") ctl.ty += dt * 0.12;
    const k = Math.min(1, dt * 7);
    ctl.x += (ctl.tx - ctl.x) * k;
    ctl.y += (ctl.ty - ctl.y) * k;
    ctl.z += (ctl.tz - ctl.z) * Math.min(1, dt * 5);
    R.pivot.rotation.set(ctl.x, ctl.y, 0);
    R.pivot.scale.setScalar(ctl.z);
    R.content.position.lerp(R.focus.clone().negate(), Math.min(1, dt * 4));
    if (R.decoSpin) R.decoSpin.rotation.z += dt * 0.2;
    if (R.dust) R.dust.rotation.y += dt * 0.01;
    for (const tw of tweens.slice()) {
      const p = Math.min(1, (now - tw.t0) / tw.ms);
      tw.fn(p);
      if (p >= 1) { tweens.splice(tweens.indexOf(tw), 1); tw.done?.(); }
    }
    if (model?.update) model.update(t, dt);
    if (model?.kind === "panel" || model?.kind === "scan") {
      el.sheet.style.transform = `rotateX(${(-ctl.x + 0.25) * 25}deg) rotateY(${ctl.y * 25}deg) scale(${ctl.z})`;
    }
    R.renderer.render(R.scene, R.camera);
  }

  // Which part of the 3D model is under a screen point
  function pick(x, y) {
    if (!R || !model?.pickables) return null;
    R.ray.setFromCamera(new THREE.Vector2((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1), R.camera);
    const hit = R.ray.intersectObjects(model.pickables, true)[0];
    let o = hit?.object;
    while (o && !o.userData.item) o = o.parent;
    return o?.userData.item || null;
  }

  // ================= TOPIC: a 3D map that expands =================
  function growTree(node, tree) {  // rebuild a saved map, part by part, with no AI calls
    if (!tree?.children?.length) return;
    addChildren(node, tree.children.map((c) => ({ name: c.name, detail: c.detail })));
    node.children.forEach((child, i) => growTree(child, tree.children[i]));
  }

  function buildTopic(subject, parts, tree) {
    const color = css("--cyan"), hi = css("--cyan-hi"), accent = css("--amber");
    const group = new THREE.Group();
    R.content.add(group);
    model = { kind: "topic", group, nodes: [], pickables: [], colors: [hi, color, accent] };
    const root = makeNode(subject, "", null);
    model.root = root;
    model.update = (t) => {
      for (const n of model.nodes) {
        n.core.rotation.y = t * (n.depth ? 0.6 : 0.3);
        n.core.rotation.x = t * 0.2;
        const sel = n === model.selected;
        n.ring.visible = sel || n.loading;
        n.ring.rotation.z = t * (n.loading ? 6 : 1.2);
        n.ring.lookAt(R.camera.position);
        n.glow.material.opacity = (sel ? 0.45 : 0.22) + Math.sin(t * 3 + n.depth) * 0.05;
        if (n.line) setLine(n.line, n.parent.group.position, n.group.position);
      }
    };
    select(root);
    if (tree) growTree(root, tree);
    else if (parts?.length) addChildren(root, parts);
    else expandNode(root);
  }

  function makeNode(name, detail, parent) {
    const depth = parent ? parent.depth + 1 : 0;
    const color = model.colors[Math.min(depth, 2)];
    const r = depth ? Math.max(0.24, 0.42 - depth * 0.06) : 0.75;
    const g = new THREE.Group();
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(r, 1), M.wire(color, 0.6));
    const glow = new THREE.Mesh(new THREE.SphereGeometry(r * 0.55, 16, 12), M.glow(color, 0.3));
    const ring = new THREE.Mesh(new THREE.RingGeometry(r * 1.35, r * 1.45, 48, 1, 0, Math.PI * 1.6), M.glow(color, 0.8));
    const tag = label(name, color, depth ? 0.3 : 0.44);
    tag.position.y = -(r + 0.32);
    g.add(core, glow, ring, tag);
    // home: where it ends up (it flies out from its parent, so it isn't there yet while it's animating)
    const node = { name, detail, parent, depth, group: g, core, glow, ring, children: [], expanded: false, loading: false,
                   home: parent ? parent.home.clone() : new THREE.Vector3() };
    g.userData.item = node;
    if (parent) {
      node.line = lineBetween(color, 0.4);
      model.group.add(node.line);
      g.position.copy(parent.group.position);
      g.scale.setScalar(0.01);
    }
    model.group.add(g);
    model.nodes.push(node);
    model.pickables.push(g);
    return node;
  }

  // Where a node's children go: around a ring for the centre, in a cone pointing outwards for the rest
  function childSpots(node, n) {
    const p = node.home, spots = [];
    if (!node.parent) {
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2 + 0.3;
        spots.push(new THREE.Vector3(Math.cos(a) * 3.3, Math.sin(a) * 2.1, Math.sin(a * 2) * 0.9));
      }
      return spots;
    }
    const out = p.clone().sub(node.parent.home).normalize();
    const u = new THREE.Vector3(0, 1, 0).cross(out);
    if (u.lengthSq() < 0.01) u.set(1, 0, 0);
    u.normalize();
    const v = out.clone().cross(u).normalize();
    const dist = Math.max(1.5, 2.3 - node.depth * 0.25);
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      const dir = out.clone().add(u.clone().multiplyScalar(Math.cos(a) * 1.1)).add(v.clone().multiplyScalar(Math.sin(a) * 1.1)).normalize();
      spots.push(p.clone().add(dir.multiplyScalar(dist)));
    }
    return spots;
  }

  function addChildren(node, parts) {
    const spots = childSpots(node, parts.length);
    parts.forEach((part, i) => {
      const child = makeNode(part.name, part.detail, node);
      node.children.push(child);
      const from = node.home.clone(), to = spots[i];
      child.home.copy(to);
      setTimeout(() => {
        beep(700 + i * 90, 0.04);
        tween(750, (k) => {
          child.group.position.lerpVectors(from, to, easeBack(k));
          child.group.scale.setScalar(Math.max(0.01, ease(k)));
        });
      }, i * 70);
    });
    node.expanded = true;
  }

  function pathOf(node) { const p = []; for (let n = node; n; n = n.parent) p.unshift(n.name); return p; }

  function select(node) {
    if (!model || model.kind !== "topic") return;
    model.selected = node;
    R.focus.copy(node.home);  // the view glides over to centre it (see frame())
    el.path.textContent = pathOf(node).join("  ›  ").toUpperCase();
    showInfo(node.name, node.detail || (node.expanded ? "" : "Clap, spread your hands or pinch it again to expand."));
    beep(1100, 0.04);
  }

  async function expandNode(node) {
    if (!node || node.loading) return;
    if (node.expanded) { select(node); return; }
    node.loading = true;
    showBusy(`ANALYSING ${node.name.toUpperCase()}`);
    try {
      const r = await api("/api/holo/expand", { path: pathOf(node) });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Couldn't work that out.");
      if (!model || !model.nodes.includes(node)) return;  // closed meanwhile
      if (!data.parts.length) { showInfo(node.name, "Nothing more to break down here."); return; }
      addChildren(node, data.parts);
      if (model.selected === node) showInfo(node.name, node.detail || "");
    } catch (e) {
      showInfo(node.name, e.message || "Couldn't reach Jarvis.");
    } finally {
      node.loading = false;
      showBusy("");
    }
  }

  function collapseNode(node) {
    if (!node.children.length && node.parent) node = node.parent;
    const drop = (n) => {
      for (const c of n.children) {
        drop(c);
        dispose(c.group);
        if (c.line) dispose(c.line);
        model.nodes.splice(model.nodes.indexOf(c), 1);
        model.pickables.splice(model.pickables.indexOf(c.group), 1);
      }
      n.children = [];
      n.expanded = false;
    };
    drop(node);
    select(node);
  }

  // ================= OBJECTS: built-in 3D models that come apart =================
  const OBJECTS = {
    "globe": buildGlobe, "solar system": buildSolar, "atom": buildAtom, "dna": buildDNA, "jet engine": buildEngine,
  };

  function buildObject(name) {
    const group = new THREE.Group();
    R.content.add(group);
    model = { kind: "object", group, parts: [], pickables: [], explode: 0, explodeTo: 0, spins: [] };
    (OBJECTS[name] || buildGlobe)(group, css("--cyan"), css("--cyan-hi"), css("--amber"));
    model.update = (t, dt) => {
      model.explode += (model.explodeTo - model.explode) * Math.min(1, dt * 3.5);
      const e = ease(model.explode);
      for (const p of model.parts) {
        p.obj.position.copy(p.base).addScaledVector(p.offset, e);
        if (p.tag) p.tag.material.opacity = 0.25 + e * 0.75;
        const sel = p === model.selected;
        p.obj.scale.setScalar(sel ? 1.08 + Math.sin(t * 5) * 0.03 : 1);
      }
      for (const [obj, axis, speed] of model.spins) obj.rotation[axis] += dt * speed;
      model.tick?.(t, dt, e);
    };
  }

  // One named piece of a model. offset: where it moves to when the model is pulled apart.
  function part(group, obj, name, detail, offset, tagColor, tagAt) {
    group.add(obj);
    const p = { obj, name, detail, base: obj.position.clone(), offset: offset || new THREE.Vector3() };
    if (tagColor) {
      p.tag = label(name, tagColor, 0.3);
      p.tag.position.copy(tagAt || new THREE.Vector3(0, 1.2, 0));
      obj.add(p.tag);
    }
    obj.userData.item = p;
    model.parts.push(p);
    model.pickables.push(obj);
    return p;
  }

  function toggleExplode(force) {
    if (!model || model.kind !== "object") return;
    model.explodeTo = force ?? (model.explodeTo > 0.5 ? 0 : 1);
    beep(model.explodeTo ? 880 : 440, 0.08);
    showInfo(model.explodeTo ? "Pulled apart" : "Assembled", model.explodeTo ? "Pinch a part for details. Clap again to put it back together." : "");
  }

  function selectPart(p) {
    model.selected = p;
    showInfo(p.name, p.detail);
    beep(1100, 0.04);
  }

  function buildGlobe(group, c, hi, a) {
    const layers = [
      ["Crust", "The thin rocky shell we live on: 5 to 70 km thick.", 2, c, -3.8],
      ["Mantle", "Hot rock that flows very slowly, about 2,900 km deep.", 1.55, a, 0],
      ["Outer core", "Liquid iron and nickel. Its swirling makes Earth's magnetic field.", 1.0, hi, 2.9],
      ["Inner core", "A solid iron ball about 5,400 °C, as hot as the Sun's surface.", 0.5, a, 4.7],
    ];
    layers.forEach(([name, detail, r, color, x], i) => {  // pulled apart, the layers line up side by side
      const obj = i === 0
        ? shape(new THREE.SphereGeometry(r, 28, 18), color, { fill: 0.05, edges: 0.7, wire: true })
        : shape(new THREE.SphereGeometry(r, 20, 14), color, { fill: 0.18 - i * 0.02, edges: 0.4, wire: true });
      part(group, obj, name, detail, new THREE.Vector3(x, 0, 0), color, new THREE.Vector3(0, -(r + 0.35), 0));
      model.spins.push([obj, "y", 0.15 + i * 0.1]);
    });
    // Where you are, with the current weather (from the HUD's weather feed)
    api("/api/weather").then((r) => r.ok && r.json()).then((w) => {
      if (!w || model?.parts[0]?.obj !== group.children[0]) return;
      const lat = THREE.MathUtils.degToRad(w.location.lat), lon = THREE.MathUtils.degToRad(w.location.lon);
      const pos = new THREE.Vector3(Math.cos(lat) * Math.cos(lon), Math.sin(lat), -Math.cos(lat) * Math.sin(lon)).multiplyScalar(2.02);
      const pin = new THREE.Mesh(new THREE.SphereGeometry(0.07, 10, 8), M.glow(a, 0.95));
      pin.position.copy(pos);
      const beam = lineBetween(a, 0.9);
      setLine(beam, pos, pos.clone().multiplyScalar(1.35));
      const tag = label(`${w.location.name.split(",")[0]} ${w.current.temp}${w.units.temp}`, a, 0.26);
      tag.position.copy(pos.clone().multiplyScalar(1.45));
      group.children[0].add(pin, beam, tag);
    }).catch(() => {});
  }

  function buildSolar(group, c, hi, a) {
    const sun = shape(new THREE.SphereGeometry(0.75, 20, 14), a, { fill: 0.35, edges: 0.6, wire: true });
    part(group, sun, "Sun", "A star 109 times wider than Earth. It holds 99.8% of the solar system's mass.", null, a, new THREE.Vector3(0, -1.1, 0));
    model.spins.push([sun, "y", 0.2]);
    const planets = [
      ["Mercury", 1.4, 0.07, 4.1, "Smallest planet and closest to the Sun. A year lasts 88 days."],
      ["Venus", 1.85, 0.12, 1.6, "Hottest planet: thick clouds trap heat at about 465 °C."],
      ["Earth", 2.35, 0.13, 1.0, "Home. The only planet known to have life."],
      ["Mars", 2.8, 0.09, 0.53, "The red planet, with the solar system's tallest volcano."],
      ["Jupiter", 3.7, 0.32, 0.084, "The giant: more than twice the mass of all the other planets combined."],
      ["Saturn", 4.6, 0.27, 0.034, "Famous for its rings of ice and rock."],
      ["Uranus", 5.3, 0.19, 0.012, "An ice giant that spins on its side."],
      ["Neptune", 5.9, 0.18, 0.006, "Windiest planet, with storms over 2,000 km/h."],
    ];
    const orbits = [];
    planets.forEach(([name, r, size, speed, detail], i) => {
      const ring = new THREE.Mesh(new THREE.RingGeometry(r - 0.006, r + 0.006, 128), M.glow(c, 0.35));
      ring.rotation.x = -Math.PI / 2;
      group.add(ring);
      const planet = shape(new THREE.SphereGeometry(size, 14, 10), i === 2 ? hi : c, { fill: 0.4, edges: 0.6, wire: true });
      if (name === "Saturn") {
        const rings = new THREE.Mesh(new THREE.RingGeometry(size * 1.4, size * 2.1, 48), M.glow(c, 0.45));
        rings.rotation.x = -Math.PI / 2.4;
        planet.add(rings);
      }
      const p = part(group, planet, name, detail, null, c, new THREE.Vector3(0, size + 0.25, 0));
      orbits.push({ p, ring, r, speed, angle: i * 1.7 });
    });
    ctl.tz = 0.8;
    model.tick = (t, dt, e) => {
      const spread = 1 + e * 0.45;  // pulled apart = orbits spread out, so the inner planets are easier to see
      for (const o of orbits) {
        o.angle += dt * o.speed * 0.6;
        o.p.base.set(Math.cos(o.angle) * o.r * spread, 0, Math.sin(o.angle) * o.r * spread);
        o.ring.scale.setScalar(spread);
      }
    };
  }

  function buildAtom(group, c, hi, a) {
    const nucleus = new THREE.Group(), protons = new THREE.Group(), neutrons = new THREE.Group();
    for (let i = 0; i < 12; i++) {
      const ball = new THREE.Mesh(new THREE.SphereGeometry(0.2, 12, 10), M.glow(i % 2 ? c : a, 0.55));
      const d = new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize().multiplyScalar(0.28 * Math.cbrt(Math.random() + 0.2));
      ball.position.copy(d);
      (i % 2 ? neutrons : protons).add(ball);
    }
    nucleus.add(protons, neutrons);
    group.add(nucleus);
    part(nucleus, protons, "Protons", "Positive particles in the nucleus. Their number decides the element: 6 means carbon.", new THREE.Vector3(-1.4, 0, 0), a, new THREE.Vector3(0, 0.7, 0));
    part(nucleus, neutrons, "Neutrons", "Particles with no charge that help hold the nucleus together.", new THREE.Vector3(1.4, 0, 0), c, new THREE.Vector3(0, 0.7, 0));
    const shells = new THREE.Group();
    const electrons = [];
    [[2.0, 0, 2.2], [2.6, 1.0, 1.6], [3.1, -1.0, 1.2]].forEach(([r, tilt, speed], i) => {
      const orbit = new THREE.Group();
      orbit.rotation.set(tilt, i * 0.8, tilt * 0.5);
      orbit.add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.008, 6, 128), M.glow(c, 0.5)));
      for (let k = 0; k < 2; k++) {
        const e = new THREE.Mesh(new THREE.SphereGeometry(0.1, 10, 8), M.glow(hi, 0.95));
        orbit.add(e);
        electrons.push({ e, r, speed, angle: k * Math.PI + i });
      }
      shells.add(orbit);
    });
    part(group, shells, "Electrons", "Tiny negative particles whizzing around the nucleus in shells.", new THREE.Vector3(0, 0, 0), hi, new THREE.Vector3(0, 3.4, 0));
    model.tick = (t, dt, e) => {
      for (const x of electrons) {
        x.angle += dt * x.speed;
        x.e.position.set(Math.cos(x.angle) * x.r, Math.sin(x.angle) * x.r, 0);
      }
      shells.scale.setScalar(1 + e * 0.35);
      nucleus.rotation.y += dt * 0.6;
    };
  }

  function buildDNA(group, c, hi, a) {
    const strandA = new THREE.Group(), strandB = new THREE.Group(), bases = new THREE.Group();
    const steps = 22, colors = [a, hi];
    const ptsA = [], ptsB = [];
    for (let i = 0; i < steps; i++) {
      const y = -3.3 + i * 0.31, ang = i * 0.55;
      const pa = new THREE.Vector3(Math.cos(ang) * 1.1, y, Math.sin(ang) * 1.1);
      const pb = new THREE.Vector3(Math.cos(ang + Math.PI) * 1.1, y, Math.sin(ang + Math.PI) * 1.1);
      ptsA.push(pa); ptsB.push(pb);
      for (const [p, s] of [[pa, strandA], [pb, strandB]]) {
        const ball = new THREE.Mesh(new THREE.SphereGeometry(0.09, 8, 6), M.glow(c, 0.8));
        ball.position.copy(p);
        s.add(ball);
      }
      const rung = lineBetween(colors[i % 2], 0.75);
      setLine(rung, pa.clone().multiplyScalar(0.9), pb.clone().multiplyScalar(0.9));
      bases.add(rung);
    }
    strandA.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(new THREE.CatmullRomCurve3(ptsA).getPoints(200)), M.line(c, 0.8)));
    strandB.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(new THREE.CatmullRomCurve3(ptsB).getPoints(200)), M.line(c, 0.8)));
    part(group, strandA, "Backbone", "A chain of sugar and phosphate that holds the code in order.", new THREE.Vector3(-1.6, 0, 0), c, new THREE.Vector3(0, 3.8, 0));
    part(group, strandB, "Partner strand", "The matching strand. Each base pairs with its partner: A with T, C with G.", new THREE.Vector3(1.6, 0, 0), c, new THREE.Vector3(0, 3.8, 0));
    part(group, bases, "Base pairs", "The letters of the genetic code. About 3 billion pairs in every human cell.", null, a, new THREE.Vector3(0, -3.9, 0));
    model.spins.push([group, "y", 0.35]);
    model.tick = (t, dt, e) => { for (const r of bases.children) r.material.opacity = 0.75 * (1 - e * 0.8); };
  }

  function buildEngine(group, c, hi, a) {
    const along = (geo) => { geo.rotateZ(Math.PI / 2); return geo; };  // turn shapes to lie along the engine
    const blades = (n, r, color, w = 0.1) => {
      const g = new THREE.Group();
      g.add(new THREE.Mesh(along(new THREE.CylinderGeometry(r * 0.25, r * 0.25, 0.25, 20)), M.glow(color, 0.4)));
      for (let i = 0; i < n; i++) {
        const b = new THREE.Mesh(new THREE.BoxGeometry(0.04, r * 0.75, w), M.glow(color, 0.5));
        b.position.y = r * 0.6;
        const holder = new THREE.Group();
        holder.rotation.x = (i / n) * Math.PI * 2;
        b.rotation.y = 0.5;
        holder.add(b);
        g.add(holder);
      }
      return g;
    };
    const fan = blades(18, 1.25, hi, 0.25);
    fan.add(new THREE.Mesh(along(new THREE.ConeGeometry(0.35, 0.6, 20)).rotateZ(Math.PI), M.glow(hi, 0.5)));
    fan.position.x = -2.7;
    part(group, fan, "Fan", "Sucks in huge amounts of air. Most flows around the core and makes most of the thrust.", new THREE.Vector3(-2.2, 0, 0), hi, new THREE.Vector3(0, 1.6, 0));
    const comp = new THREE.Group();
    for (let i = 0; i < 7; i++) {
      const stage = blades(14, 0.95 - i * 0.06, c, 0.12);
      stage.position.x = -1.7 + i * 0.22;
      comp.add(stage);
    }
    part(group, comp, "Compressor", "Rows of spinning blades squeeze the air to about 40 times its pressure.", new THREE.Vector3(-1.1, 0, 0), c, new THREE.Vector3(-1, 1.3, 0));
    const burner = shape(along(new THREE.CylinderGeometry(0.7, 0.7, 1.0, 24, 1, true)), a, { fill: 0.25, edges: 0.6 });
    burner.position.x = 0.4;
    const flame = new THREE.Mesh(along(new THREE.CylinderGeometry(0.45, 0.45, 0.9, 20)), M.glow(a, 0.4));
    burner.add(flame);
    part(group, burner, "Combustion chamber", "Fuel is sprayed into the squeezed air and burns at about 2,000 °C.", new THREE.Vector3(0, 0, 0), a, new THREE.Vector3(0, 1.1, 0));
    const turb = new THREE.Group();
    for (let i = 0; i < 3; i++) {
      const stage = blades(16, 0.8, a, 0.12);
      stage.position.x = 1.2 + i * 0.25;
      turb.add(stage);
    }
    part(group, turb, "Turbine", "The hot gas spins these blades, which turn the fan and compressor through the shaft.", new THREE.Vector3(1.1, 0, 0), a, new THREE.Vector3(1.4, 1.2, 0));
    const nozzle = shape(along(new THREE.CylinderGeometry(0.45, 0.8, 1.1, 24, 1, true)), c, { fill: 0.12, edges: 0.7 });
    nozzle.position.x = 2.5;
    part(group, nozzle, "Exhaust nozzle", "Narrows to speed up the hot gas as it leaves: the core's push.", new THREE.Vector3(2.2, 0, 0), c, new THREE.Vector3(0, 1.1, 0));
    const shaft = new THREE.Mesh(along(new THREE.CylinderGeometry(0.06, 0.06, 5.6, 10)), M.glow(hi, 0.6));
    part(group, shaft, "Shaft", "Links the turbine at the back to the fan and compressor at the front.", new THREE.Vector3(0, -2.1, 0), hi, new THREE.Vector3(0, -0.4, 0));
    const casing = shape(along(new THREE.CylinderGeometry(1.45, 1.35, 6.2, 36, 4, true)), c, { fill: 0.04, edges: 0.3, wire: true });
    casing.position.x = -0.2;
    part(group, casing, "Casing", "The outer shell. It guides the bypass air and contains a broken blade if one snaps.", new THREE.Vector3(0, 2.6, 0), c, new THREE.Vector3(0, 1.8, 0));
    model.spins.push([fan, "x", 6], [comp, "x", 9], [turb, "x", 12]);
    model.tick = (t) => { flame.material.opacity = 0.3 + Math.random() * 0.25; };
    ctl.tz = 0.95;
  }

  // ================= PANELS: HUD panels blown up full-screen =================
  const api = (path, body) => fetch(`${path}${path.includes("?") ? "&" : "?"}key=${encodeURIComponent(KEY)}`,
    body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});

  function card(html, cls = "", say = "") {
    return `<div class="hc ${cls}"${say ? ` data-say="${esc(say)}"` : ""}>${html}</div>`;
  }

  async function buildPanel(name) {
    model = { kind: "panel", update: null };
    el.sheet.innerHTML = `<div class="hc wide"><p class="dim">Loading...</p></div>`;
    let html = "";
    try {
      if (name === "weather") {
        const w = await (await api("/api/weather")).json();
        const u = w.units.temp;
        html = card(`<small>${esc(w.location.name)}</small><div class="big">${w.current.temp}${u}</div><b>${esc(w.current.text)}</b>
          <p>Feels like ${w.current.feels}${u} · Humidity ${w.current.humidity}% · Wind ${w.current.wind} ${w.units.wind}</p>`, "wide hero");
        for (const d of w.daily) {
          html += card(`<small>${DAY(d.date)}</small><div class="mid">${d.high}${u}</div><p>Low ${d.low}${u}</p><b>${esc(d.text)}</b><p>Rain ${d.rain ?? 0}%</p>`);
        }
      } else if (name === "news") {
        const { items } = await (await api("/api/news")).json();
        html = items.slice(0, 12).map((n) => card(`<small>${esc(n.source)}</small><b>${esc(n.title)}</b>`, "news",
          `Tell me more about this news story: "${n.title}"`)).join("") || card("<p>No headlines right now.</p>", "wide");
      } else if (name === "agenda") {
        const data = await (await api("/api/calendar")).json();
        if (!data.connected) html = card(`<b>Google Calendar isn't connected.</b><p>On the PC, run jarvis.bat --connect-google</p>`, "wide");
        else {
          html = data.events.map((e) => {
            const s = e.all_day ? null : new Date(e.start);
            return card(`<small>${e.all_day ? "ALL DAY" : `${s.toLocaleDateString([], { weekday: "short" }).toUpperCase()} ${hhmm(s)}`}</small>
              <b>${esc(e.title)}</b>${e.location ? `<p>${esc(e.location)}</p>` : ""}`);
          }).join("") || card("<b>Nothing scheduled today or tomorrow.</b>", "wide");
        }
      } else if (name === "system") {
        const s = await (await api("/api/stats")).json();
        const g = (label, v) => card(`<small>${label}</small><div class="big">${Math.round(v)}%</div><div class="bar"><i style="width:${v}%"></i></div>`);
        html = g("CPU", s.cpu) + g("MEMORY", s.ram) + g("DISK", s.disk) +
          (s.battery != null ? g(s.charging ? "BATTERY · CHARGING" : "BATTERY", s.battery) : "") +
          card(`<small>UPTIME</small><div class="mid">${esc(String(s.uptime))}</div><p>${s.processes} processes</p>`) +
          card(`<small>API SPEND</small><div class="mid">$${s.spend.today.toFixed(2)}</div><p>today · $${s.spend.month.toFixed(2)} this month</p>`);
      } else if (name === "spotify") {
        const { text } = await (await api("/api/holo/panel?name=spotify")).json();
        html = card(`<small>NOW PLAYING</small><div class="mid">${esc(text.replace(/\s*\(.*\)\.?$/, ""))}</div>`, "wide hero") +
          card(`<div class="mid">⏮</div><p>Previous</p>`, "btn", "previous song") +
          card(`<div class="mid">⏯</div><p>Play / pause</p>`, "btn", "pause") +
          card(`<div class="mid">⏭</div><p>Next</p>`, "btn", "next song");
      } else if (name === "reminders") {
        const { items } = await (await api("/api/holo/panel?name=reminders")).json();
        html = items.map((r) => card(`<small>${new Date(r.due).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }).toUpperCase()}</small>
          <b>${esc(r.message)}</b>${r.important ? "<p>IMPORTANT</p>" : ""}`)).join("") || card("<b>No reminders set.</b>", "wide");
      }
    } catch {
      html = card("<b>Couldn't load this panel.</b><p>Is Jarvis running on the PC?</p>", "wide");
    }
    if (!isOpen || current?.subject !== name) return;
    el.sheet.innerHTML = html;
    const cards = [...el.sheet.children];
    cards.forEach((c, i) => { c.style.setProperty("--i", i); c.style.setProperty("--n", cards.length); c.style.animationDelay = `${i * 45}ms`; });
    for (const c of el.sheet.querySelectorAll("[data-say]")) {
      c.onclick = () => {
        submit(c.dataset.say);
        beep(1000, 0.05);
        if (name === "spotify") setTimeout(() => isOpen && current?.subject === "spotify" && buildPanel("spotify"), 1800);
      };
    }
  }

  // ================= SCAN: what the desk scanner saw =================
  function buildScan(image) {
    model = { kind: "scan", result: null };
    el.title.textContent = "Scanning";
    el.sheet.innerHTML = `<div class="hc wide scan">
      <div class="scan-photo">${image ? `<img alt="Desk camera photo" src="${image}">` : ""}<i class="scan-line"></i>
        <div class="reticle"><i></i><i></i><i></i><i></i><span></span></div></div>
      <div class="scan-result"><small>IDENTIFYING</small><h3>...</h3><p class="what"></p><dl></dl><p class="tip"></p></div></div>`;
    showBusy("SCANNING OBJECT");
    if (typeof sfx !== "undefined") sfx.scan(); else beep(300, 0.3);
  }

  // Target lock: brackets close in on where the object is, with its name and how sure Jarvis is
  function lockOn(r) {
    const ret = el.sheet.querySelector(".reticle");
    if (!ret) return;
    const nothing = /^(nothing|scan failed)/i.test(r.name || "");
    const b = Array.isArray(r.box) && r.box.length === 4 && r.box[2] > r.box[0] && r.box[3] > r.box[1]
      ? r.box.map((v) => Math.max(0, Math.min(1000, v)) / 10) : [30, 25, 70, 75];
    Object.assign(ret.style, { left: `${b[0]}%`, top: `${b[1]}%`, width: `${b[2] - b[0]}%`, height: `${b[3] - b[1]}%` });
    const conf = r.confidence ? ` · ${r.confidence.toUpperCase()} CONFIDENCE` : "";
    ret.querySelector("span").textContent = nothing ? "NO TARGET" : `${r.name}${conf}`;
    ret.classList.add(nothing ? "miss" : "locked");
    if (!nothing && typeof sfx !== "undefined") sfx.lock();
  }

  function fillScan(r) {
    if (!isOpen || model?.kind !== "scan") return;
    model.result = r;
    showBusy("");
    const box = el.sheet.querySelector(".scan");
    box.classList.add("done");
    el.title.textContent = r.name;
    box.querySelector("small").textContent = r.name.toLowerCase().startsWith("nothing") || r.name === "Scan failed" ? "NO MATCH" : "IDENTIFIED";
    box.querySelector("h3").textContent = r.name;
    box.querySelector(".what").textContent = r.what || "";
    box.querySelector("dl").innerHTML = (r.details || []).map((d) => `<div><dt>${esc(d.label)}</dt><dd>${esc(d.value)}</dd></div>`).join("");
    box.querySelector(".tip").textContent = r.tip || "";
    lockOn(r);
    beep(990, 0.08); setTimeout(() => beep(1320, 0.1), 90);
  }

  // ================= actions (from hands, mouse and voice) =================
  function expand(target) {
    if (!isOpen) return false;
    if (model?.kind === "topic") {
      let node = model.selected;
      if (target) {
        const t = target.toLowerCase();
        node = model.nodes.find((n) => n.name.toLowerCase() === t) || model.nodes.find((n) => n.name.toLowerCase().includes(t) || t.includes(n.name.toLowerCase())) || node;
        if (node !== model.selected) select(node);
      }
      expandNode(node);
    } else if (model?.kind === "object") {
      if (target) {
        const t = target.toLowerCase(), p = model.parts.find((x) => x.name.toLowerCase().includes(t) || t.includes(x.name.toLowerCase()));
        if (p) { toggleExplode(1); selectPart(p); return true; }
      }
      toggleExplode();
    } else if (model?.kind === "panel") {
      el.sheet.classList.toggle("spread");
      beep(880, 0.08);
    } else if (model?.kind === "scan") {  // break the scanned object down into a 3D map of its parts
      const name = model.result?.name;
      if (name && !/^(nothing|scan failed)/i.test(name)) open("topic", name);
    }
    return true;
  }

  function collapse() {
    if (model?.kind === "topic") collapseNode(model.selected);
    else if (model?.kind === "object") toggleExplode(0);
    else if (model?.kind === "panel") el.sheet.classList.remove("spread");
  }

  // A pick (pinch or click) at a screen point
  function tap(x, y) {
    const hit = document.elementFromPoint(x, y);
    if (isOpen) {
      const button = hit?.closest?.("#holo button, #holo [data-say]");
      if (button) { button.click(); return; }
      const item = pick(x, y);
      if (!item) return;
      if (model.kind === "topic") {
        if (item === model.selected) expandNode(item);
        else select(item);
      } else if (model.kind === "object") selectPart(item);
      return;
    }
    // On the normal HUD: press buttons, or open a panel as a hologram
    const target = hit?.closest?.("button, a, input, [data-say]");
    if (target) { target.click(); beep(1000, 0.04); return; }
    const panel = panelAt(hit);
    if (panel) openPanel(panel);
  }

  const CARD_PANELS = { weather: "weather", agenda: "agenda", system: "system" };
  function panelAt(node) {
    if (node?.closest?.(".ticker")) return "news";
    const c = node?.closest?.("[data-card]");
    return c ? CARD_PANELS[c.dataset.card] || null : null;
  }

  function openPanel(name) { open("panel", name); }

  // ---------- mouse and touch ----------
  let drag = null;
  function setupPointer() {
    const box = el.box, pts = new Map();
    box.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button, [data-say]")) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pts.size === 2) {
        const [p, q] = [...pts.values()];
        drag = { pinch: Math.hypot(p.x - q.x, p.y - q.y), z: ctl.tz };
      } else drag = { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, moved: false };
      box.setPointerCapture(e.pointerId);
    });
    box.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId) || !drag) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (drag.pinch && pts.size === 2) {
        const [p, q] = [...pts.values()];
        zoomTo(drag.z * Math.hypot(p.x - q.x, p.y - q.y) / drag.pinch);
        return;
      }
      if (drag.pinch) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      if (Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) > 6) drag.moved = true;
      if (drag.moved) rotateBy(dx * 0.008, dy * 0.006);
    });
    const end = (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.delete(e.pointerId);
      if (drag && !drag.pinch && !drag.moved && e.type === "pointerup") tap(e.clientX, e.clientY);
      if (!pts.size) drag = null;
    };
    box.addEventListener("pointerup", end);
    box.addEventListener("pointercancel", end);
    box.addEventListener("dblclick", (e) => { if (!e.target.closest("button, [data-say]")) expand(); });
    box.addEventListener("wheel", (e) => { e.preventDefault(); zoomTo(ctl.tz * Math.exp(-e.deltaY * 0.0012)); }, { passive: false });
    addEventListener("keydown", (e) => {
      if (!isOpen || e.target.closest?.("input, textarea")) return;
      if (e.key === "Escape") close();
      else if (e.key === "e" || e.key === " ") { e.preventDefault(); expand(); }
    });
  }

  // ================= HANDS: webcam hand tracking =================
  const hand = { on: false, starting: false, landmarker: null, stream: null, lastRun: 0, lastTime: -1,
                 slots: [null, null], history: [], cooldown: 0, lastClap: 0, hover: null };
  const handsWanted = () => store.get("jarvis-gestures") === "on";
  const lowPowerOn = () => typeof lowPower !== "undefined" && lowPower;  // Low Power Mode (hud.js)
  const canTrackHands = () => !!navigator.mediaDevices?.getUserMedia && window.isSecureContext;

  async function startHands() {
    build();
    if (hand.on || hand.starting || !canTrackHands()) return;
    hand.starting = true;
    hand.cancelled = false;
    try {
      hand.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: "user" }, audio: false });
      el.video.srcObject = hand.stream;
      await el.video.play();
      el.cam.hidden = false;
      el.cam.classList.add("loading");
      if (!hand.landmarker) {
        const vision = await import(`${MP}/vision_bundle.mjs`);
        const files = await vision.FilesetResolver.forVisionTasks(`${MP}/wasm`);
        const make = (delegate) => vision.HandLandmarker.createFromOptions(files, {
          baseOptions: { modelAssetPath: HAND_MODEL, delegate }, runningMode: "VIDEO", numHands: 2,
          minHandDetectionConfidence: 0.6, minHandPresenceConfidence: 0.5, minTrackingConfidence: 0.5,
        });
        hand.landmarker = await make("GPU").catch(() => make("CPU"));
      }
      if (hand.cancelled) return;  // turned off while loading
      el.cam.classList.remove("loading");
      hand.on = true;
      updateGestureButton();
      requestAnimationFrame(handLoop);
      syncClapEar();
    } catch (e) {
      if (hand.cancelled) return;
      addActivity(`Hand control couldn't start: ${e.name === "NotAllowedError" ? "camera permission was denied" : e.message || e}`, true);
      stopHands();
    } finally {
      hand.starting = false;
    }
  }

  function stopHands() {
    hand.cancelled = hand.starting;
    hand.on = false;
    hand.stream?.getTracks().forEach((t) => t.stop());
    hand.stream = null;
    if (el) {
      el.cam.hidden = true;
      el.video.srcObject = null;
      for (const c of el.cursors) c.classList.remove("show");
    }
    setHover(null);
    hand.slots = [null, null];
    updateGestureButton();
    syncClapEar();
  }

  function handLoop() {
    if (!hand.on) return;
    requestAnimationFrame(handLoop);
    const now = performance.now(), v = el.video;
    if (now - hand.lastRun < 45 || v.readyState < 2 || v.currentTime === hand.lastTime) return;  // ~20 checks a second
    hand.lastRun = now;
    hand.lastTime = v.currentTime;
    let res;
    try { res = hand.landmarker.detectForVideo(v, now); } catch { return; }
    track(res.landmarks || [], now);
    drawCam(res.landmarks || []);
  }

  // Measurements of one hand. Camera x is mirrored so moving your hand right moves the cursor right.
  function measure(lm) {
    const d = (a, b) => Math.hypot(lm[a].x - lm[b].x, lm[a].y - lm[b].y);
    const size = d(0, 9) || 0.1;
    const ext = (tip, pip) => d(0, tip) > d(0, pip) * 1.12;
    return {
      size,
      pinchD: d(4, 8) / size,
      open: ext(8, 6) && ext(12, 10) && ext(16, 14) && ext(20, 18),
      wrist: { x: 1 - lm[0].x, y: lm[0].y },
      palm: { x: 1 - (lm[0].x + lm[5].x + lm[17].x) / 3, y: (lm[0].y + lm[5].y + lm[17].y) / 3 },
      point: { x: 1 - (lm[4].x + lm[8].x) / 2, y: (lm[4].y + lm[8].y) / 2 },
    };
  }

  // Keep each hand in the same slot from frame to frame (the tracker doesn't keep them in order)
  function assign(found) {
    const slots = [null, null], used = new Set();
    for (let s = 0; s < 2; s++) {
      const prev = hand.slots[s];
      if (!prev) continue;
      let best = -1, bestD = 0.25;
      found.forEach((f, i) => {
        if (used.has(i)) return;
        const dd = Math.hypot(f.wrist.x - prev.m.wrist.x, f.wrist.y - prev.m.wrist.y);
        if (dd < bestD) { best = i; bestD = dd; }
      });
      if (best >= 0) { used.add(best); slots[s] = { ...prev, m: found[best] }; }
    }
    found.forEach((f, i) => {
      if (used.has(i)) return;
      const s = slots[0] ? 1 : 0;
      if (!slots[s]) slots[s] = { m: f, since: performance.now(), pinch: false, cx: null, cy: null, trail: [] };
    });
    if (!slots[0] && slots[1]) { slots[0] = slots[1]; slots[1] = null; }
    return slots;
  }

  function toScreen(p) {
    return { x: clamp((p.x - 0.12) / 0.76, 0, 1) * innerWidth, y: clamp((p.y - 0.1) / 0.7, 0, 1) * innerHeight };
  }

  function track(landmarks, now) {
    const found = landmarks.map(measure);
    const before = hand.slots.filter(Boolean).length;
    const slots = hand.slots = assign(found);
    const count = slots.filter(Boolean).length;

    // Cursors, smoothed (more smoothing when the hand is still, less when it moves fast)
    slots.forEach((s, i) => {
      const c = el.cursors[i];
      if (!s) { c.classList.remove("show"); return; }
      const target = toScreen(s.m.point);
      if (s.cx == null) { s.cx = target.x; s.cy = target.y; }
      const speed = Math.hypot(target.x - s.cx, target.y - s.cy) / innerWidth;
      const k = clamp(0.25 + speed * 6, 0.25, 0.85);
      s.cx += (target.x - s.cx) * k;
      s.cy += (target.y - s.cy) * k;
      const wasPinch = s.pinch;
      s.pinch = wasPinch ? s.m.pinchD < 0.5 : s.m.pinchD < 0.32;  // hysteresis, so it doesn't flicker
      if (s.pinch && !wasPinch) { s.pinchStart = { t: now, x: s.cx, y: s.cy, lx: s.cx, ly: s.cy }; s.dragging = false; }
      s.wasPinch = wasPinch;
      c.style.transform = `translate(${s.cx}px, ${s.cy}px)`;
      c.classList.add("show");
      c.classList.toggle("pinch", s.pinch);
      s.trail.push({ t: now, x: s.m.palm.x, open: s.m.open && !s.pinch });
      while (s.trail.length && now - s.trail[0].t > 300) s.trail.shift();
    });

    const a = slots[0], b = slots[1];

    // Two hands
    if (a && b) {
      const size = (a.m.size + b.m.size) / 2;
      const apart = Math.hypot(a.m.palm.x - b.m.palm.x, a.m.palm.y - b.m.palm.y) / size;
      hand.history.push({ t: now, apart, open: a.m.open && b.m.open });
      while (hand.history.length && now - hand.history[0].t > 900) hand.history.shift();
      if (a.pinch && b.pinch) {  // both hands pinching: stretch to zoom
        const d = Math.hypot(a.cx - b.cx, a.cy - b.cy);
        if (!hand.zoom) hand.zoom = { d, z: ctl.tz };
        else if (isOpen) zoomTo(hand.zoom.z * d / Math.max(30, hand.zoom.d));
        return;
      }
      hand.zoom = null;
      // Clap: hands were apart a moment ago and have just met
      const wasApart = hand.history.some((h) => now - h.t < 500 && h.apart > 2.4);
      if (apart < 1.1 && wasApart) return gesture("clap");
      // Spread: both open hands start close together and pull apart
      const wasTogether = hand.history.some((h) => now - h.t < 800 && h.apart < 1.8 && h.open);
      if (apart > 3.8 && a.m.open && b.m.open && wasTogether) return gesture("spread");
      return;
    }
    hand.zoom = null;
    // Two hands that were closing in fast merged into one blob: that was a clap too
    if (before === 2 && count === 1) {
      const recent = hand.history.filter((h) => now - h.t < 250);
      if (recent.length >= 2 && recent[recent.length - 1].apart < 1.7 && recent[0].apart > recent[recent.length - 1].apart + 0.4) return gesture("clap");
    }
    hand.history = [];
    if (!a) { setHover(null); return; }

    // One hand: hover, pinch to tap, pinch and drag to rotate, flick to dismiss
    const hit = document.elementFromPoint(a.cx, a.cy);
    setHover(isOpen ? null : panelAt(hit) ? hit.closest("[data-card], .ticker") : null);
    if (a.pinch && a.pinchStart) {
      const p = a.pinchStart;
      if (!a.dragging && Math.hypot(a.cx - p.x, a.cy - p.y) > innerWidth * 0.03) a.dragging = true;
      if (a.dragging && isOpen) rotateBy((a.cx - p.lx) * 0.009, (a.cy - p.ly) * 0.007);
      p.lx = a.cx; p.ly = a.cy;
    }
    if (!a.pinch && a.wasPinch && a.pinchStart) {
      if (!a.dragging && now - a.pinchStart.t < 700) tap(a.pinchStart.x, a.pinchStart.y);
      a.pinchStart = null;
    }
    const tr = a.trail;
    if (isOpen && tr.length > 3 && now - a.since > 400 && tr.every((p) => p.open)) {
      const vx = (tr[tr.length - 1].x - tr[0].x) / Math.max(0.05, (tr[tr.length - 1].t - tr[0].t) / 1000);
      if (Math.abs(vx) > 2.0 && Math.abs(tr[tr.length - 1].x - tr[0].x) > 0.22) return gesture(vx > 0 ? "flick-right" : "flick-left");
    }
  }

  function gesture(kind) {
    const now = performance.now();
    if (now < hand.cooldown) return;
    hand.cooldown = now + 1100;
    hand.history = [];
    if (kind === "clap" || kind === "spread") {
      if (!isOpen && !hand.hover) return;  // not aimed at anything: a clap stays a clap (e.g. for the music)
      hand.lastClap = Date.now();
      flash();
      if (isOpen) expand();
      else openPanel(panelAt(hand.hover));
    } else if (kind.startsWith("flick") && isOpen) {
      close(kind === "flick-left" ? -1 : 1);
    }
  }

  function flash() {
    for (const c of el.cursors) { c.classList.remove("burst"); void c.offsetWidth; c.classList.add("burst"); }
  }

  function setHover(node) {
    if (hand.hover === node) return;
    hand.hover?.classList.remove("holo-target");
    hand.hover = node;
    node?.classList.add("holo-target");
  }

  // The little camera preview, with your hand's joints drawn on it
  const BONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
                 [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17]];
  function drawCam(landmarks) {
    const cv = el.camCanvas, ctx = cv.getContext("2d"), w = cv.width, h = cv.height;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = css("--cyan");
    ctx.fillStyle = css("--cyan-hi");
    ctx.lineWidth = 1.5;
    for (const lm of landmarks) {
      ctx.beginPath();
      for (const [p, q] of BONES) { ctx.moveTo((1 - lm[p].x) * w, lm[p].y * h); ctx.lineTo((1 - lm[q].x) * w, lm[q].y * h); }
      ctx.stroke();
      for (const p of lm) { ctx.beginPath(); ctx.arc((1 - p.x) * w, p.y * h, 1.8, 0, 7); ctx.fill(); }
    }
  }

  // ---------- the GESTURE button ----------
  function updateGestureButton() {
    const btn = document.getElementById("tg-gesture");
    if (!btn) return;
    btn.classList.toggle("on", hand.on || handsWanted());
    btn.hidden = !canTrackHands();
  }
  function setGestures(on) {
    store.set("jarvis-gestures", on ? "on" : "off");
    if (on) startHands();
    else if (!isOpen) stopHands();
    updateGestureButton();
  }
  document.getElementById("tg-gesture")?.addEventListener("click", () => setGestures(!(hand.on || handsWanted())));
  updateGestureButton();
  if (handsWanted() && !lowPowerOn()) setTimeout(startHands, 1500);

  // ---------- from Jarvis (voice commands) ----------
  function handle(ev) {
    switch (ev.action) {
      case "open":
        if (ev.thrown && isMainScreen()) break;  // thrown from this PC: it's for the phone
        open(ev.kind, ev.subject, ev.parts, ev.image, ev);
        break;
      case "scan_result": fillScan(ev.result || {}); break;
      case "wireframe": case "xray": case "solid": restyle(ev.action); break;
      case "color": restyle("color", COLORS[(ev.target || "").toLowerCase()] || ev.target || "#3fc8ff"); break;
      case "save": { const s = spec(); if (s && isMainScreen()) send({ type: "holo_save", name: ev.target || "", spec: s }); break; }
      case "throw": {
        const s = spec();
        if (s && isMainScreen()) { send({ type: "holo_throw", spec: s }); close(1); }
        break;
      }
      case "video": showVideo(ev.id, ev.title); break;
      case "video_close": closeVideo(); break;
      case "close": close(); break;
      case "expand": expand(ev.target); break;
      case "collapse": collapse(); break;
      case "zoom_in": zoomTo(ctl.tz * 1.4); break;
      case "zoom_out": zoomTo(ctl.tz / 1.4); break;
      case "rotate": rotateBy(Math.PI / 2, 0); break;
      case "reset": resetView(); break;
      case "gestures_on": setGestures(true); break;
      case "gestures_off": setGestures(false); break;
    }
  }

  // A clap heard by the microphone (see heardClap in hud.js). True if the hologram used it.
  function onClap() {
    if (Date.now() - hand.lastClap < 900) return true;  // the camera already saw this clap
    if (isOpen) { expand(); return true; }
    if (hand.on && hand.hover) { openPanel(panelAt(hand.hover)); return true; }
    return false;
  }

  return { handle, onClap, wantsClaps: () => isOpen || hand.on, isOpen: () => isOpen };
})();
