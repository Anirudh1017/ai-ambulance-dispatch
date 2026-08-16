/* EMS Dispatch — dashboard client.
 * Vanilla JS + HTML5 Canvas. Consumes engine snapshots over one WebSocket.
 * Button state is rendered purely from server "status" messages. */

"use strict";

// --------------------------------------------------------------------------- //
// State                                                                       //
// --------------------------------------------------------------------------- //

const state = {
  ws: null,
  scenarios: [],
  map: null,
  mapId: null,
  snap: null,
  prevPos: {},
  anim: {},
  nodes: new Map(),
  world: null,
  events: [],
  pendingEvents: [],
  replayQueue: [],
  replayTimer: null,
  t0: performance.now(),
  tps: 8,
  hover: null,
  rotation: 0, // 0, 90, 180, 270 degrees
  strataMode: "sidebar", // "sidebar" or "strata"
  lastDomUpdate: 0,
  isRendering: false,
};

const STATUS_COLOR = {
  idle: "#94a3b8",
  drifting: "#22d3ee",
  enroute: "#34d399",
  on_scene: "#fbbf24",
  transporting: "#a78bfa",
  returning: "#fb923c",
  blocked: "#f43f5e",
};

const STATUS_LABEL = {
  idle: "idle / parked",
  drifting: "drifting (MDP)",
  enroute: "en route to scene",
  on_scene: "on scene",
  transporting: "transporting to hospital",
  returning: "returning to base",
  blocked: "blocked by hazard",
};

const SEVERITY_COLOR = { 3: "#fbbf24", 4: "#fb923c", 5: "#f43f5e" };

const KIND_BADGE = {
  "ambulance.dispatched": "bg-emerald-950/80 text-emerald-300 border border-emerald-800/60",
  "dispatch.auction.award": "bg-teal-950/80 text-teal-300 border border-teal-800/60",
  "dispatch.auction.announce": "bg-teal-950/60 text-teal-300/90 border border-teal-800/50",
  "dispatch.auction.bid": "bg-teal-950/40 text-teal-200/80 border border-teal-800/40",
  "dispatch.auction.reject": "bg-rose-950/40 text-rose-300/80 border border-rose-800/40",
  "dispatch.greedy": "bg-lime-950/80 text-lime-300 border border-lime-800/60",
  "dispatch.renegotiated": "bg-fuchsia-950/80 text-fuchsia-300 border border-fuchsia-800/60",
  "ambulance.replanned": "bg-sky-950/80 text-sky-300 border border-sky-800/60",
  "replan.cost_compare": "bg-sky-950/50 text-sky-300/80 border border-sky-800/40",
  "ambulance.on_scene": "bg-amber-950/80 text-amber-300 border border-amber-800/60",
  "hospital.allocated": "bg-cyan-950/80 text-cyan-300 border border-cyan-800/60",
  "incident.cleared": "bg-indigo-950/80 text-indigo-300 border border-indigo-800/60",
  "mdp.solved": "bg-blue-950/80 text-blue-300 border border-blue-800/60",
  "world.blockage_detected": "bg-orange-950/80 text-orange-300 border border-orange-800/60",
  "dispatch.failed": "bg-rose-950/80 text-rose-300 border border-rose-800/60",
};

// --------------------------------------------------------------------------- //
// WebSocket                                                                   //
// --------------------------------------------------------------------------- //

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${proto}://${location.host}/ws`);
  state.ws.onclose = () => setTimeout(connect, 1500);
  state.ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
}

function send(obj) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(obj));
  }
}

function handleMessage(msg) {
  switch (msg.type) {
    case "init":
      state.scenarios = msg.scenarios;
      populateScenarioSelect();
      break;
    case "status":
      renderControls(msg);
      break;
    case "snapshot": {
      state.snap = msg.data;
      const scenName = msg.data.scenario ? msg.data.scenario.name : null;
      if (!state.map || state.mapId !== scenName) {
        applyMap(msg.data.map);
        state.mapId = scenName;
      } else if (state.map && msg.data.map && msg.data.map.hospitals) {
        state.map.hospitals = msg.data.map.hospitals;
      }
      prepAnimation(msg.data);
      queueEvents(msg.events);
      scheduleDomUpdate(msg.data);

      if (msg.done) {
        renderControls({ running: false, finished: true, has_engine: true });
        const name = document.getElementById("sim-name");
        if (name && !name.textContent.includes("FINISHED")) {
          name.textContent += " · FINISHED";
        }
      }
      break;
    }
    case "replay_chunk":
      state.replayQueue.push(...msg.data);
      if (!state.replayTimer) startReplayPlayback();
      break;
    case "error":
      console.warn(msg.message);
      break;
  }
}

// --------------------------------------------------------------------------- //
// Throttled DOM Updating (Eliminates lag at high TPS)                          //
// --------------------------------------------------------------------------- //

let domUpdateTimer = null;
function scheduleDomUpdate(snap) {
  const now = performance.now();
  if (now - state.lastDomUpdate > 45) {
    state.lastDomUpdate = now;
    renderStats(snap);
    renderExplainability(snap);
    flushPendingEvents();
  } else if (!domUpdateTimer) {
    domUpdateTimer = setTimeout(() => {
      domUpdateTimer = null;
      state.lastDomUpdate = performance.now();
      if (state.snap) {
        renderStats(state.snap);
        renderExplainability(state.snap);
        flushPendingEvents();
      }
    }, 45);
  }
}

// --------------------------------------------------------------------------- //
// Controls (server-driven)                                                    //
// --------------------------------------------------------------------------- //

function populateScenarioSelect() {
  const sel = document.getElementById("scenario");
  sel.innerHTML = "";
  for (const s of state.scenarios) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.title;
    opt.title = s.description;
    sel.appendChild(opt);
  }
  sel.onchange = () => {
    const s = state.scenarios.find((x) => x.id === sel.value);
    document.getElementById("sim-name").textContent = s ? s.title : "—";
    updateFleetSummary(s);
  };
  sel.onchange();
}

function updateFleetSummary(s) {
  const el = document.getElementById("fleet-summary");
  if (!el) return;
  if (!s) { el.innerHTML = ""; return; }
  el.innerHTML =
    `<span class="text-[#38bdf8] font-bold">${s.ambulances ?? "—"}</span> <span class="text-[#8899b5]">units</span> · ` +
    `<span class="text-[#818cf8] font-bold">${s.stations ?? "—"}</span> <span class="text-[#8899b5]">stations</span> · ` +
    `<span class="text-[#06b6d4] font-bold">${s.hospitals ?? "—"}</span> <span class="text-[#06b6d4]">hospitals</span> · ` +
    `<span class="text-[#f43f5e] font-bold">${s.incidents ?? "—"}</span> <span class="text-[#8899b5]">calls</span>`;
}

function renderControls(status) {
  const running = !!status.running;
  const finished = !!status.finished;
  const hasEngine = !!status.has_engine;

  const start = document.getElementById("btn-start");
  const pause = document.getElementById("btn-pause");
  const step = document.getElementById("btn-step");

  const startHidden = running || (hasEngine && !finished);
  const pauseHidden = finished || !hasEngine;
  const stepHidden = running || finished || !hasEngine;

  start.className = "btn px-3.5 py-1.5 text-xs font-bold "
    + (finished ? "btn-ghost" : "btn-primary")
    + (startHidden ? " hidden" : "");
  start.textContent = finished ? "RUN AGAIN" : "START";
  pause.className = "btn px-3.5 py-1.5 text-xs font-bold "
    + (running ? "btn-amber" : "btn-primary")
    + (pauseHidden ? " hidden" : "");
  pause.textContent = running ? "PAUSE" : "RESUME";
  step.className = "btn btn-ghost px-2.5 py-1.5 text-xs"
    + (stepHidden ? " hidden" : "");

  const dot = document.getElementById("status-dot");
  dot.className = "dot " + (finished ? "dot-finished"
    : running ? "dot-running" : "dot-paused");

  const name = document.getElementById("sim-name");
  if (finished && name && !name.textContent.includes("FINISHED")) {
    name.textContent += " · FINISHED";
  }
}

// --------------------------------------------------------------------------- //
// Map geometry & projection math (with Rotation & CSS viewport scaling)      //
// --------------------------------------------------------------------------- //

function applyMap(map) {
  if (!map) return;
  state.map = map;
  state.nodes.clear();
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const n of map.nodes) {
    state.nodes.set(n.id, [n.x, n.y]);
    minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
    minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
  }
  if (map.zones) {
    for (const z of map.zones) {
      if (z.center) {
        minX = Math.min(minX, z.center[0]); maxX = Math.max(maxX, z.center[0]);
        minY = Math.min(minY, z.center[1]); maxY = Math.max(maxY, z.center[1]);
      }
    }
  }
  state.world = { minX, maxX, minY, maxY };
}

const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");

function getViewportCssSize() {
  const shell = document.getElementById("map-shell");
  if (shell) {
    const rect = shell.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      return { w: rect.width, h: rect.height };
    }
  }
  const dpr = window.devicePixelRatio || 1;
  return { w: canvas.width / dpr, h: canvas.height / dpr };
}

function rotatePoint(x, y, cx, cy, rad) {
  if (rad === 0) return { x, y };
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  const dx = x - cx;
  const dy = y - cy;
  return {
    x: cos * dx - sin * dy + cx,
    y: sin * dx + cos * dy + cy,
  };
}

function worldToScreen(x, y) {
  const w = state.world;
  if (!w) return { x: 0, y: 0 };
  const { w: cssW, h: cssH } = getViewportCssSize();

  const cx = (w.minX + w.maxX) / 2;
  const cy = (w.minY + w.maxY) / 2;
  const rad = ((state.rotation || 0) * Math.PI) / 180;

  // Compute rotated world bounding box
  const c1 = rotatePoint(w.minX, w.minY, cx, cy, rad);
  const c2 = rotatePoint(w.maxX, w.minY, cx, cy, rad);
  const c3 = rotatePoint(w.minX, w.maxY, cx, cy, rad);
  const c4 = rotatePoint(w.maxX, w.maxY, cx, cy, rad);

  const rotMinX = Math.min(c1.x, c2.x, c3.x, c4.x);
  const rotMaxX = Math.max(c1.x, c2.x, c3.x, c4.x);
  const rotMinY = Math.min(c1.y, c2.y, c3.y, c4.y);
  const rotMaxY = Math.max(c1.y, c2.y, c3.y, c4.y);

  const spanX = Math.max(0.1, rotMaxX - rotMinX);
  const spanY = Math.max(0.1, rotMaxY - rotMinY);
  const pad = 44;
  const availW = Math.max(20, cssW - pad * 2);
  const availH = Math.max(20, cssH - pad * 2);
  const scale = Math.min(availW / spanX, availH / spanY);

  const ox = (cssW - spanX * scale) / 2;
  const oy = (cssH - spanY * scale) / 2;

  // Rotate target point
  const rp = rotatePoint(x, y, cx, cy, rad);
  return {
    x: ox + (rp.x - rotMinX) * scale,
    y: oy + (rp.y - rotMinY) * scale,
  };
}

function resize() {
  const shell = document.getElementById("map-shell");
  if (!shell) return;
  const rect = shell.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(10, Math.floor(rect.width));
  const h = Math.max(10, Math.floor(rect.height));
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function rr(x, y, w, h, r) {
  ctx.beginPath();
  if (ctx.roundRect) {
    ctx.roundRect(x, y, w, h, r);
  } else {
    ctx.rect(x, y, w, h);
  }
}

// --------------------------------------------------------------------------- //
// Animation (Dynamic duration matching tick rate)                             //
// --------------------------------------------------------------------------- //

function prepAnimation(snap) {
  for (const a of snap.ambulances) {
    const prev = state.prevPos[a.id] || { x: a.x, y: a.y };
    if (prev.x !== a.x || prev.y !== a.y) {
      state.anim[a.id] = { from: { ...prev }, to: { x: a.x, y: a.y },
                           t0: performance.now() };
    }
    state.prevPos[a.id] = { x: a.x, y: a.y };
  }
}

function animPos(a) {
  const anim = state.anim[a.id];
  if (!anim) return { x: a.x, y: a.y };
  // Adaptive animation duration based on active TPS rate
  const dur = Math.max(30, Math.min(300, 900 / Math.max(1, state.tps || 8)));
  const t = Math.min(1, (performance.now() - anim.t0) / dur);
  if (t >= 1) { delete state.anim[a.id]; return { x: a.x, y: a.y }; }
  return {
    x: anim.from.x + (anim.to.x - anim.from.x) * t,
    y: anim.from.y + (anim.to.y - anim.from.y) * t,
  };
}

// --------------------------------------------------------------------------- //
// Single Rendering Loop (Native 60fps, no duplicate loops)                   //
// --------------------------------------------------------------------------- //

function startRenderLoop() {
  if (state.isRendering) return;
  state.isRendering = true;

  function frame() {
    const { w: cssW, h: cssH } = getViewportCssSize();
    if (canvas.width < 10 || canvas.height < 10) resize();

    if (state.map && state.world) {
      const hint = document.getElementById("map-hint");
      if (hint) hint.classList.add("hidden");

      // Deep navy canvas background
      ctx.clearRect(0, 0, cssW, cssH);
      ctx.fillStyle = "#070b16";
      ctx.fillRect(0, 0, cssW, cssH);

      state.hover = null;
      drawZones();
      drawEdges();
      drawBlockages();
      drawStations();
      drawHospitals();
      drawIncidents();
      drawAmbulances();
    }

    requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);
}

function drawZones() {
  const zoneColors = ["#1e293b", "#172544", "#1a2c4e", "#162846",
                      "#132c38", "#2c1e3f", "#33261a"];
  state.map.zones.forEach((z, i) => {
    const c = worldToScreen(z.center[0], z.center[1]);
    const r = 46;
    const g = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, r);
    g.addColorStop(0, (zoneColors[i % zoneColors.length] || "#1e293b") + "66");
    g.addColorStop(1, (zoneColors[i % zoneColors.length] || "#1e293b") + "00");
    ctx.beginPath();
    ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
    ctx.fillStyle = g;
    ctx.fill();
    ctx.fillStyle = "#546682";
    ctx.font = "9px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText(z.label || z.id, c.x, c.y + 3);
  });
}

function drawEdges() {
  ctx.strokeStyle = "#1c2a44";
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  for (const e of state.map.edges) {
    const a = state.nodes.get(e.u), b = state.nodes.get(e.v);
    if (!a || !b) continue;
    const p = worldToScreen(a[0], a[1]);
    const q = worldToScreen(b[0], b[1]);
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(q.x, q.y);
  }
  ctx.stroke();

  // Subtle junction pins
  ctx.fillStyle = "#1e2d4a";
  for (const [nid, pos] of state.nodes) {
    const p = worldToScreen(pos[0], pos[1]);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 1.8, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawBlockages() {
  if (!state.snap) return;
  const mark = (edge, color, dashed) => {
    const a = state.nodes.get(edge[0]), b = state.nodes.get(edge[1]);
    if (!a || !b) return;
    const p = worldToScreen(a[0], a[1]);
    const q = worldToScreen(b[0], b[1]);
    const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.setLineDash(dashed ? [4, 4] : []);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.moveTo(mx - 5, my - 5); ctx.lineTo(mx + 5, my + 5);
    ctx.moveTo(mx + 5, my - 5); ctx.lineTo(mx - 5, my + 5);
    ctx.stroke();
    ctx.restore();
  };
  for (const e of state.snap.blockages.revealed) mark(e, "#fb923c", false);
  for (const e of state.snap.blockages.hidden) mark(e, "#64748b", true);
}

// --------------------------------------------------------------------------- //
// Distinct Stations (Garage Depot) vs Hospitals (Medical Cross)               //
// --------------------------------------------------------------------------- //

function drawStations() {
  const unitsAt = new Map();
  if (state.snap) {
    for (const a of state.snap.ambulances) {
      if (!a.station) continue;
      if (!unitsAt.has(a.station)) unitsAt.set(a.station, []);
      unitsAt.get(a.station).push(a);
    }
  }
  for (const st of state.map.stations || []) {
    const coords = state.nodes.get(st.node);
    if (!coords) continue;
    const c = worldToScreen(...coords);
    const parked = unitsAt.get(st.id) || [];
    const idleAt = parked.filter((a) => a.status === "idle" || a.status === "drifting");

    ctx.save();
    // 1. Pitched roof (indigo/violet garage roof)
    ctx.fillStyle = "#818cf8";
    ctx.strokeStyle = "#4338ca";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(c.x - 11, c.y - 4);
    ctx.lineTo(c.x, c.y - 12);
    ctx.lineTo(c.x + 11, c.y - 4);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // 2. Garage building body
    rr(c.x - 9, c.y - 4, 18, 14, 2);
    ctx.fill();
    ctx.stroke();

    // 3. Roll-up garage door with shutter detail
    ctx.fillStyle = "#312e81";
    ctx.strokeStyle = "#6366f1";
    ctx.lineWidth = 0.8;
    rr(c.x - 5, c.y + 1, 10, 8, 1);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(c.x - 5, c.y + 3.5); ctx.lineTo(c.x + 5, c.y + 3.5);
    ctx.moveTo(c.x - 5, c.y + 6); ctx.lineTo(c.x + 5, c.y + 6);
    ctx.stroke();

    // 4. Clustered idle units parked at the station
    idleAt.forEach((a, i) => {
      const ang = (2 * Math.PI * i) / Math.max(1, idleAt.length) - Math.PI / 2;
      const px = c.x + Math.cos(ang) * 17;
      const py = c.y + Math.sin(ang) * 17;
      ctx.beginPath();
      ctx.arc(px, py, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = STATUS_COLOR[a.status] || "#94a3b8";
      ctx.fill();
      ctx.strokeStyle = "#080d1a";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });

    // 5. Clear Station Label
    ctx.fillStyle = "#c7d2fe";
    ctx.font = "600 9.5px 'Space Grotesk', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(`${st.id} · ${idleAt.length}`, c.x, c.y + 24);
    ctx.restore();
  }
}

function drawHospitals() {
  for (const h of state.map.hospitals) {
    const coords = state.nodes.get(h.node);
    if (!coords) continue;
    const c = worldToScreen(...coords);
    ctx.save();
    // 1. Hospital building (medical cyan rounded square)
    ctx.fillStyle = "#06b6d4";
    ctx.strokeStyle = "#0891b2";
    ctx.lineWidth = 1.5;
    rr(c.x - 9, c.y - 9, 18, 18, 3.5);
    ctx.fill();
    ctx.stroke();

    // 2. Bold white emergency medical cross (+)
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2.6;
    ctx.lineCap = "square";
    ctx.beginPath();
    ctx.moveTo(c.x - 5, c.y); ctx.lineTo(c.x + 5, c.y);
    ctx.moveTo(c.x, c.y - 5); ctx.lineTo(c.x, c.y + 5);
    ctx.stroke();

    // 3. Clear Hospital & Bed Occupancy Label
    ctx.fillStyle = "#67e8f9";
    ctx.font = "600 9px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText(`${h.id} [${h.in_use}/${h.beds}]`, c.x, c.y - 14);
    ctx.restore();
  }
}

function drawIncidents() {
  if (!state.snap) return;
  const t = performance.now();
  for (const inc of state.snap.incidents) {
    if (inc.status === "cleared") continue;
    const coords = state.nodes.get(inc.node);
    if (!coords) continue;
    const c = worldToScreen(...coords);
    const col = SEVERITY_COLOR[inc.severity] || "#f43f5e";
    ctx.save();

    // Pending: expanding pulse ring (time-based, canvas-native)
    if (inc.status === "pending") {
      const ph = ((t - state.t0) / 1400) % 1;
      ctx.beginPath();
      ctx.arc(c.x, c.y, 9 + ph * 14, 0, Math.PI * 2);
      ctx.strokeStyle = col;
      ctx.globalAlpha = 0.55 * (1 - ph);
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // Severity body: S3 triangle, S4 diamond, S5 star
    ctx.save();
    ctx.translate(c.x, c.y);
    ctx.fillStyle = col;
    ctx.strokeStyle = "#080d1a";
    ctx.lineWidth = 2;
    ctx.beginPath();
    if (inc.severity === 3) {
      ctx.moveTo(0, -9);
      ctx.lineTo(8, 6);
      ctx.lineTo(-8, 6);
    } else if (inc.severity === 4) {
      ctx.moveTo(0, -8);
      ctx.lineTo(8, 0);
      ctx.lineTo(0, 8);
      ctx.lineTo(-8, 0);
    } else {
      for (let i = 0; i < 10; i++) {
        const ang = (i * 36 - 90) * Math.PI / 180;
        const rad = i % 2 === 0 ? 10 : 4.5;
        const px = rad * Math.cos(ang);
        const py = rad * Math.sin(ang);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    // Status ring for active incidents
    if (inc.status === "assigned" || inc.status === "enroute") {
      ctx.beginPath();
      ctx.arc(c.x, c.y, 11, 0, Math.PI * 2);
      ctx.strokeStyle = "#34d399";
      ctx.lineWidth = 1.6;
      ctx.stroke();
    } else if (inc.status === "on_scene" || inc.status === "transporting") {
      ctx.beginPath();
      ctx.arc(c.x, c.y, 11, 0, Math.PI * 2);
      ctx.strokeStyle = "#a78bfa";
      ctx.lineWidth = 1.6;
      ctx.stroke();
    }

    ctx.fillStyle = col;
    ctx.font = "bold 9px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText(`S${inc.severity}`, c.x, c.y - 14);
    ctx.restore();
  }
}

function drawAmbulances() {
  if (!state.snap) return;
  for (const a of state.snap.ambulances) {
    if (a.status === "idle" || a.status === "drifting") {
      if (a.station) continue; // Parked units rendered at home station
    }
    const pos = animPos(a);
    const c = worldToScreen(pos.x, pos.y);
    ctx.save();

    // Active route trail
    if (a.route && a.route.length > 1 && (a.status === "enroute"
                                          || a.status === "transporting"
                                          || a.status === "returning")) {
      ctx.strokeStyle = STATUS_COLOR[a.status] || "#94a3b8";
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = 2;
      ctx.setLineDash([3, 4]);
      ctx.beginPath();
      const start = state.nodes.get(a.node);
      if (start) {
        let p = worldToScreen(start[0], start[1]);
        ctx.moveTo(p.x, p.y);
        for (const nid of a.route) {
          const n = state.nodes.get(nid);
          if (!n) continue;
          p = worldToScreen(n[0], n[1]);
          ctx.lineTo(p.x, p.y);
        }
      }
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    const col = STATUS_COLOR[a.status] || "#94a3b8";
    if (a.status !== "idle" && a.status !== "drifting") {
      const glow = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, 14);
      glow.addColorStop(0, col + "66");
      glow.addColorStop(1, col + "00");
      ctx.beginPath();
      ctx.arc(c.x, c.y, 14, 0, Math.PI * 2);
      ctx.fillStyle = glow;
      ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(c.x, c.y, 7, 0, Math.PI * 2);
    ctx.fillStyle = col;
    ctx.fill();
    ctx.strokeStyle = "#080d1a";
    ctx.lineWidth = 2;
    ctx.stroke();

    if (a.status !== "idle" && a.status !== "drifting") {
      ctx.fillStyle = "#e2e8f0";
      ctx.font = "8px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      const tag = a.algorithm === "astar" ? "A*" : a.algorithm;
      ctx.fillText(tag, c.x, c.y - 11);
      ctx.fillStyle = "#8899b5";
      ctx.fillText(a.id, c.x, c.y + 16);
    }
    ctx.restore();
  }
}

// --------------------------------------------------------------------------- //
// Hover Tooltips                                                              //
// --------------------------------------------------------------------------- //

function hitTest(x, y) {
  if (!state.snap) return null;
  const near = (c, r) => (c.x - x) ** 2 + (c.y - y) ** 2 <= r * r;

  // 1. Incidents
  for (const inc of state.snap.incidents) {
    if (inc.status === "cleared") continue;
    const coords = state.nodes.get(inc.node);
    if (!coords) continue;
    const c = worldToScreen(...coords);
    if (near(c, 14)) {
      return {
        title: `INCIDENT: ${inc.id} (Severity ${inc.severity})`,
        headerClass: "text-[#fb923c]",
        lines: [
          `Condition: ${inc.kind}`,
          `Status: ${inc.status}`,
          inc.ambulance_id ? `Assigned Unit: ${inc.ambulance_id}` : `Unit: unassigned`,
          inc.hospital_id ? `Assigned Hospital: ${inc.hospital_id}` : null,
          `Reported: t${inc.reported_tick}`,
        ],
      };
    }
  }

  // 2. Moving Ambulances (not parked at station)
  for (const a of state.snap.ambulances) {
    if (a.station && (a.status === "idle" || a.status === "drifting")) continue;
    const pos = animPos(a);
    const c = worldToScreen(pos.x, pos.y);
    if (near(c, 12)) {
      return {
        title: `AMBULANCE: ${a.id} · ${STATUS_LABEL[a.status] || a.status}`,
        headerClass: "text-[#38bdf8]",
        lines: [
          `Routing Algorithm: ${a.algorithm}`,
          `Zone: ${a.zone}`,
          a.destination ? `Target Destination: ${a.destination}` : null,
          a.station ? `Base Station: ${a.station}` : null,
          `Telemetry: ${a.responses_done} responses · ${a.distance_km.toFixed(1)} km`,
        ],
      };
    }
  }

  // 3. Stations (Garages / Depots)
  for (const st of state.map.stations || []) {
    const coords = state.nodes.get(st.node);
    if (!coords) continue;
    const c = worldToScreen(...coords);
    if (near(c, 16)) {
      const parked = (state.snap.ambulances || []).filter((a) => a.station === st.id && (a.status === "idle" || a.status === "drifting"));
      return {
        title: `GARAGE / STATION: ${st.id}`,
        headerClass: "text-[#818cf8]",
        lines: [
          `Facility Name: ${st.label}`,
          `Type: Ambulance Garage / Base Depot`,
          `Node Location: ${st.node}`,
          `Parked Fleet: ${parked.length} units ready`,
        ],
      };
    }
  }

  // 4. Hospitals (Medical Treatment Facilities)
  for (const h of state.map.hospitals) {
    const coords = state.nodes.get(h.node);
    if (!coords) continue;
    const c = worldToScreen(...coords);
    if (near(c, 16)) {
      return {
        title: `HOSPITAL: ${h.name} (${h.id})`,
        headerClass: "text-[#06b6d4]",
        lines: [
          `Type: Medical Treatment Facility (CSP Allocated)`,
          `Node Location: ${h.node}`,
          `Bed Capacity: ${h.beds - h.in_use} / ${h.beds} beds available`,
          `Occupancy: ${h.in_use} active beds in use`,
        ],
      };
    }
  }

  // 5. Parked Ambulances orbiting the station
  for (const st of state.map.stations || []) {
    const coords = state.nodes.get(st.node);
    if (!coords) continue;
    const c = worldToScreen(...coords);
    const parked = (state.snap.ambulances || []).filter((a) => a.station === st.id && (a.status === "idle" || a.status === "drifting"));
    for (let i = 0; i < parked.length; i++) {
      const a = parked[i];
      const ang = (2 * Math.PI * i) / Math.max(1, parked.length) - Math.PI / 2;
      const px = c.x + Math.cos(ang) * 17;
      const py = c.y + Math.sin(ang) * 17;
      if (near({ x: px, y: py }, 6)) {
        return {
          title: `AMBULANCE: ${a.id} (Parked at ${st.id})`,
          headerClass: "text-[#38bdf8]",
          lines: [
            `Status: ${STATUS_LABEL[a.status] || a.status}`,
            `Routing Algorithm: ${a.algorithm}`,
            `Zone: ${a.zone}`,
            `Telemetry: ${a.responses_done} responses · ${a.distance_km.toFixed(1)} km`,
          ],
        };
      }
    }
  }

  return null;
}

canvas.addEventListener("mousemove", (e) => {
  const rect = canvas.getBoundingClientRect();
  const hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
  const box = document.getElementById("hover-info");
  if (!hit) { box.classList.add("hidden"); return; }
  box.innerHTML = `<div class="${hit.headerClass || 'text-[#38bdf8]'} font-bold mb-1 border-b border-[#1e2d4a]/80 pb-1">${hit.title}</div>` +
    hit.lines.filter(Boolean)
      .map((l) => `<div class="text-[#cbd5e1] text-[10.5px] leading-relaxed">${l}</div>`).join("");
  box.classList.remove("hidden");
});

// --------------------------------------------------------------------------- //
// Panels & Telemetry                                                          //
// --------------------------------------------------------------------------- //

function statCard(label, value, cls) {
  return `<div class="kpi">
      <div class="text-[9px] tracking-widest text-[#8899b5] uppercase font-bold">${label}</div>
      <div class="mono text-lg font-bold ${cls || "text-[#e2e8f0]"}">${value}</div>
    </div>`;
}

function renderStats(snap) {
  const st = snap.stats;
  const sc = state.scenarios.find((x) => x.id === snap.scenario.name);
  updateFleetSummary(sc);
  document.getElementById("clock").textContent =
    `t ${snap.tick} · ${snap.seconds}s`;

  document.getElementById("stats-cards").innerHTML =
    statCard("CALLS REPORTED", st.incidents_reported) +
    statCard("CLEARED", st.incidents_cleared, "text-[#34d399]") +
    statCard("ACTIVE", st.active, st.active ? "text-[#fbbf24]" : "") +
    statCard("QUEUED", st.queue, st.queue ? "text-[#f43f5e]" : "") +
    statCard("RESP AVG", `${st.response_avg.toFixed(1)}s`, "text-[#38bdf8]") +
    statCard("RESP P95", `${st.response_p95.toFixed(1)}s`) +
    statCard("DISTANCE", `${st.total_distance_km.toFixed(0)} km`) +
    statCard("REPLANS", st.replans, "text-[#818cf8]") +
    statCard("EQUITY GINI",
      st.equity?.gini != null ? st.equity.gini.toFixed(3) : "—",
      "text-[#c084fc]") +
    statCard("REPLAN SAVED",
      `${st.replan_savings_expansions ?? 0} exp`, "text-[#38bdf8]") +
    statCard("RENEGOTIATED", st.renegotiations ?? 0, "text-[#e879f9]") +
    statCard("RENEG SAVED",
      `${(st.renegotiation_savings_s ?? 0).toFixed(0)}s`, "text-[#e879f9]");

  renderFairness(snap);

  const ex = st.search_expansions;
  const maxExp = Math.max(1, ...Object.values(ex));
  document.getElementById("expansion-bars").innerHTML =
    Object.entries(ex).map(([k, v]) => `
      <div class="flex items-center gap-2">
        <span class="mono w-14 text-[10px] text-[#8899b5] uppercase">${k}</span>
        <div class="flex-1 h-2 bg-[#131f37] rounded overflow-hidden">
          <div class="h-full bg-[#38bdf8]" style="width:${(v / maxExp * 100).toFixed(1)}%"></div>
        </div>
        <span class="mono w-14 text-right text-[10px] text-[#e2e8f0] font-medium">${v}</span>
      </div>`).join("");

  document.getElementById("module-counters").innerHTML = `
    <div>CSP &nbsp;<b class="text-[#818cf8]">${st.csp_solves}</b> solves ·
      <b class="text-[#818cf8]">${st.csp_backtracks}</b> backtracks ·
      <b class="text-[#818cf8]">${st.csp_nodes}</b> nodes</div>
    <div>MDP <b class="text-[#38bdf8]">${st.mdp_solves}</b> solves</div>
    <div>Arena <b class="text-[#34d399]">${st.arena_runs}</b> runs</div>`;
}

function renderFairness(snap) {
  const box = document.getElementById("fairness-box");
  const eq = snap.stats?.equity;
  if (!eq || !eq.per_zone || !Object.keys(eq.per_zone).length) {
    box.innerHTML =
      `<div class="text-[#546682] text-[10px] py-3 text-center">No zone response data yet…</div>`;
    return;
  }
  const rows = Object.entries(eq.per_zone)
    .map(([z, m]) => ({ z, ...m }))
    .sort((a, b) => (a.mean || 0) - (b.mean || 0));
  const maxMean = Math.max(1, ...rows.map((r) => r.mean || 0));
  const best = eq.best_zone, worst = eq.worst_zone;
  const heatColor = (t) => `hsl(${Math.round(125 * (1 - t))}, 62%, 32%)`;
  const heat = rows.map((r) => `
      <div class="flex-1 h-5 rounded-[4px] flex items-center justify-center text-[8px] mono font-bold"
        style="background:${heatColor((r.mean || 0) / maxMean)}" title="${r.z}: ${r.mean}s mean · ${r.n} calls">
        ${r.z}
      </div>`).join("");
  const list = rows.map((r) => {
    const tag = r.z === best ? `<span class="text-[#34d399] font-bold"> BEST</span>`
      : r.z === worst ? `<span class="text-[#f43f5e] font-bold"> WORST</span>` : "";
    return `<div class="flex justify-between items-center text-[10px] py-0.5 border-b border-[#1e2d4a]/40 last:border-none">
        <span class="text-[#e2e8f0] font-medium">${r.z}${tag}</span>
        <span class="text-[#8899b5]">${r.n} call(s) · ${r.mean}s mean · ${r.p95}s p95</span>
      </div>`;
  }).join("");
  box.innerHTML = `
    <div class="flex items-center justify-between py-0.5">
      <span class="text-[#c084fc] font-bold">Gini ${eq.gini.toFixed(3)}</span>
      <span class="text-[#8899b5]">served ${eq.served_zones}/${eq.zones} zone(s) · max/min ${eq.max_min_ratio != null ? eq.max_min_ratio.toFixed(2) : "—"}×</span>
    </div>
    <div class="flex gap-0.5 py-1">${heat}</div>
    ${list}`;
}

function renderExplainability(snap) {
  const arena = document.getElementById("arena-box");
  if (snap.arena && snap.arena.results && Object.keys(snap.arena.results).length) {
    const q = snap.arena.query || {};
    const rows = Object.entries(snap.arena.results).map(([algo, r]) => `
      <tr class="border-t border-[#1e2d4a]/80">
        <td class="py-1 uppercase text-[10px] text-[#e2e8f0] font-medium">${algo}</td>
        <td class="text-right text-[10px] text-[#8899b5]">${r.cost?.toFixed(1) ?? "—"}</td>
        <td class="text-right text-[10px] text-[#8899b5]">${r.nodes_expanded}</td>
        <td class="text-right text-[10px] text-[#8899b5]">${r.duration_ms?.toFixed(1)}ms</td>
        <td class="text-right text-[10px] text-[#34d399] font-bold">${r.optimal ? "✓" : "—"}</td>
      </tr>`).join("");
    arena.innerHTML = `
      <div class="text-[10px] text-[#8899b5] mb-1.5 font-medium">Run #${snap.arena.run}
        — ${q.from ?? ""} → ${q.to ?? ""} (${q.incident ?? ""})</div>
      <table class="w-full text-[10px]">
        <tr class="text-[#546682] border-b border-[#1e2d4a]/80">
          <td class="py-0.5">ALGO</td><td class="text-right">COST</td>
          <td class="text-right">EXPANDED</td><td class="text-right">TIME</td>
          <td class="text-right">OPT</td></tr>
        ${rows}
      </table>`;
  } else {
    arena.innerHTML = `<div class="text-[#546682] text-[10px] py-4 text-center">Waiting for a dispatch route…</div>`;
  }

  const mdp = document.getElementById("mdp-box");
  if (snap.mdp && snap.mdp.policy && Object.keys(snap.mdp.policy).length) {
    const rows = Object.entries(snap.mdp.policy).map(([z, target]) => `
      <div class="flex justify-between text-[10px] py-0.5 border-b border-[#1e2d4a]/40 last:border-none">
        <span class="text-[#8899b5] font-medium">${z}</span>
        <span class="text-[#e2e8f0]">${z === target ? "stay" : `→ ${target}`}
          <span class="text-[#546682] ml-1">V=${snap.mdp.values[z]?.toFixed(2)}</span></span>
      </div>`).join("");
    mdp.innerHTML = `
      <div class="text-[10px] text-[#8899b5] mb-1.5 font-medium">Value Iteration —
        ${snap.mdp.iterations} sweeps, ε=${snap.mdp.final_residual?.toExponential(1)}
        ${snap.mdp.converged ? "· converged" : ""}</div>
      ${rows}`;
  } else {
    mdp.innerHTML = `<div class="text-[#546682] text-[10px] py-4 text-center">No idle-positioning computed yet…</div>`;
  }

  const dec = document.getElementById("decisions");
  const items = snap.recent_decisions.slice(-12).reverse().map((evt) => {
    const badge = KIND_BADGE[evt.kind] || "bg-slate-800 text-slate-300 border border-slate-700";
    return `<div class="feed-item flex gap-1.5 items-start py-0.5">
      <span class="text-[#546682] w-8 shrink-0 text-[10px]">t${evt.tick}</span>
      <span class="rounded px-1.5 ${badge} text-[8.5px] leading-4 shrink-0 font-medium">${evt.kind}</span>
      <span class="text-[#cbd5e1] text-[10.5px]">${evt.summary}</span>
    </div>`;
  }).join("");
  dec.innerHTML = items || `<div class="text-[#546682] text-center py-4">No decisions recorded yet.</div>`;
  document.getElementById("dec-count").textContent =
    Math.min(snap.recent_decisions.length, 12);
}

function queueEvents(events) {
  if (!events || !events.length) return;
  state.pendingEvents.push(...events);
}

function flushPendingEvents() {
  if (!state.pendingEvents.length) return;
  const events = state.pendingEvents;
  state.pendingEvents = [];
  state.events.push(...events);
  if (state.events.length > 200) state.events = state.events.slice(-200);

  const box = document.getElementById("events");
  const frag = document.createDocumentFragment();
  for (const evt of events) {
    const div = document.createElement("div");
    div.className = "feed-item flex gap-1.5 items-start py-0.5";
    div.innerHTML = `
      <span class="text-[#546682] w-8 shrink-0 text-[10px]">t${evt.tick}</span>
      <span class="rounded px-1.5 ${KIND_BADGE[evt.kind] || "bg-slate-800 text-slate-300 border border-slate-700"} text-[8.5px] leading-4 shrink-0 font-medium">${evt.kind}</span>
      <span class="text-[#cbd5e1] text-[10.5px]">${evt.summary}</span>`;
    frag.appendChild(div);
  }
  box.prepend(frag);
  while (box.children.length > 200) box.removeChild(box.lastChild);
  document.getElementById("evt-count").textContent = state.events.length;
}

// --------------------------------------------------------------------------- //
// Replay                                                                      //
// --------------------------------------------------------------------------- //

function startReplayPlayback() {
  state.replayTimer = setInterval(() => {
    const snap = state.replayQueue.shift();
    if (!snap) {
      clearInterval(state.replayTimer);
      state.replayTimer = null;
      return;
    }
    state.snap = snap;
    prepAnimation(snap);
    scheduleDomUpdate(snap);
  }, 90);
}

// --------------------------------------------------------------------------- //
// Horizontal Strata View Toggle                                              //
// --------------------------------------------------------------------------- //

function initStrataToggle() {
  const btn = document.getElementById("btn-toggle-strata");
  const label = document.getElementById("strata-mode-label");
  const main = document.getElementById("main-layout");
  if (!btn || !label || !main) return;

  const saved = localStorage.getItem("ems_strata_mode");
  const mode = saved === "strata" ? "strata" : "sidebar";

  const applyMode = (m) => {
    state.strataMode = m;
    if (m === "strata") {
      main.classList.remove("xl:grid-cols-[minmax(0,1fr)_380px]");
      main.classList.add("layout-strata");
      label.textContent = "STRATA";
    } else {
      main.classList.add("xl:grid-cols-[minmax(0,1fr)_380px]");
      main.classList.remove("layout-strata");
      label.textContent = "SIDEBAR";
    }
    localStorage.setItem("ems_strata_mode", m);
    resize();
  };

  applyMode(mode);

  btn.onclick = () => {
    applyMode(state.strataMode === "strata" ? "sidebar" : "strata");
  };
}

// --------------------------------------------------------------------------- //
// Map Rotation Control                                                        //
// --------------------------------------------------------------------------- //

function initRotationControl() {
  const btn = document.getElementById("btn-rotate-map");
  const label = document.getElementById("rotation-label");
  if (!btn || !label) return;

  const saved = localStorage.getItem("ems_map_rotation");
  state.rotation = saved ? parseInt(saved, 10) || 0 : 0;
  label.textContent = `${state.rotation}°`;

  btn.onclick = () => {
    state.rotation = (state.rotation + 90) % 360;
    label.textContent = `${state.rotation}°`;
    localStorage.setItem("ems_map_rotation", state.rotation.toString());
  };
}

// --------------------------------------------------------------------------- //
// Legend Hide/Show Persistence                                                //
// --------------------------------------------------------------------------- //

function initLegendToggle() {
  const btn = document.getElementById("btn-toggle-legend");
  const content = document.getElementById("legend-content");
  const label = document.getElementById("legend-toggle-label");
  if (!btn || !content || !label) return;

  const saved = localStorage.getItem("ems_legend_visible");
  const isVisible = saved === null ? true : saved === "true";

  const setVisibility = (vis) => {
    if (vis) {
      content.classList.remove("hidden");
      label.textContent = "HIDE";
    } else {
      content.classList.add("hidden");
      label.textContent = "SHOW";
    }
    localStorage.setItem("ems_legend_visible", vis ? "true" : "false");
  };

  setVisibility(isVisible);

  btn.onclick = (e) => {
    e.stopPropagation();
    const currentlyVisible = !content.classList.contains("hidden");
    setVisibility(!currentlyVisible);
  };
}

// --------------------------------------------------------------------------- //
// Controls Setup                                                              //
// --------------------------------------------------------------------------- //

document.getElementById("btn-start").onclick = () => {
  const sel = document.getElementById("scenario");
  document.getElementById("sim-name").textContent =
    sel.selectedOptions[0]?.textContent || "—";
  send({ action: "start",
         scenario: sel.value,
         seed: Number(document.getElementById("seed").value) });
};
document.getElementById("btn-pause").onclick = () => {
  const running = !document.getElementById("btn-pause").textContent.startsWith("RESUME");
  send({ action: running ? "pause" : "resume" });
};
document.getElementById("btn-step").onclick = () => send({ action: "step" });
document.getElementById("btn-reset").onclick = () => {
  const name = document.getElementById("sim-name");
  name.textContent = name.textContent.replace(" · FINISHED", "");
  send({ action: "reset" });
  document.getElementById("btn-pause").textContent = "PAUSE";
};
document.getElementById("btn-replay").onclick = () => {
  state.replayQueue = [];
  send({ action: "replay" });
};

document.getElementById("btn-benchmark").onclick = async () => {
  const box = document.getElementById("benchmark-box");
  const status = document.getElementById("bench-status");
  const scenario = document.getElementById("scenario").value;
  status.textContent = "RUNNING…";
  box.innerHTML =
    `<div class="text-[#8899b5]">Running ${scenario} × 3 seeds × 2 stacks (6 deterministic runs)…</div>`;
  try {
    const res = await fetch("/benchmark", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario, seeds: 3 }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || res.statusText);
    status.textContent = `${data.n_runs} RUNS · SEEDS 1–3`;
    const rows = data.rows.map((r) => `
      <div class="flex justify-between items-center py-1 border-b border-[#1e2d4a]/40 last:border-none">
        <span class="text-[#e2e8f0] font-medium">${r.combo === "smart" ? "SMART" : "NAIVE"}</span>
        <span class="text-[#8899b5]">resp <b class="text-[#38bdf8]">${r.response_avg.toFixed(1)}s</b>
          · p95 ${r.response_p95.toFixed(1)}s · var ${r.response_variance.toFixed(0)}
          · gini <b class="text-[#c084fc]">${r.equity_gini.toFixed(3)}</b>
          · dist ${r.distance_km.toFixed(0)}km
          · load spread ${r.workload_spread.toFixed(1)}
          · reneg ${r.renegotiations.toFixed(0)}</span>
      </div>`).join("");
    box.innerHTML = `
      <div class="text-[10px] text-[#546682] mb-1">mean over ${data.seeds.length} seed(s), scenario ${data.scenario}</div>
      ${rows}`;
  } catch (err) {
    status.textContent = "FAILED";
    box.innerHTML = `<div class="text-[#f43f5e]">Benchmark failed: ${err.message}</div>`;
  }
};

const speed = document.getElementById("speed");
const paintSpeed = () => {
  const min = +speed.min, max = +speed.max, v = +speed.value;
  state.tps = v;
  speed.style.setProperty("--fill",
    `${((v - min) / (max - min)) * 100}%`);
  document.getElementById("speed-val").textContent = `${v}/s`;
};
speed.oninput = () => {
  paintSpeed();
  send({ action: "set_speed", tps: Number(speed.value) });
};
paintSpeed();

for (const btn of document.querySelectorAll(".speed-preset")) {
  btn.onclick = () => {
    speed.value = btn.dataset.speed;
    paintSpeed();
    send({ action: "set_speed", tps: Number(speed.value) });
  };
}

window.addEventListener("resize", resize);
if (window.ResizeObserver) {
  new ResizeObserver(resize).observe(document.getElementById("map-shell"));
}
resize();
initStrataToggle();
initRotationControl();
initLegendToggle();
connect();
startRenderLoop();