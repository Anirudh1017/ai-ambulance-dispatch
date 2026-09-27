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
  trail: {},          // unit id -> recent world points (thin 1px motion trail)
  flashes: [],        // one-shot acknowledgement rings, 1.2s max, never repeated
  run: { running: false, finished: false, hasEngine: false }, // last server status
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
  lastDomUpdate: 0,
  lastRenderedTick: -1,
  analyzeDirty: true,
  replayIndex: 0,
  isRendering: false,
  theme: "dark",
  reducedMotion: false,
};

const TAU = Math.PI * 2;

// --------------------------------------------------------------------------- //
// Semantic colour contract                                                     //
// Dual-tone by construction: dark keeps the shipped hues, light uses the       //
// darkened same-hue variant so every swatch clears 3:1 on the light map.       //
// Theme tokens win when present; these are the fallback.                        //
// --------------------------------------------------------------------------- //

const SEMANTIC = {
  idle: { dark: "#94a3b8", light: "#64748b", vars: ["--status-idle", "--st-idle"] },
  drifting: { dark: "#22d3ee", light: "#0e7490", vars: ["--status-drifting", "--st-drifting"] },
  enroute: { dark: "#34d399", light: "#047857", vars: ["--status-enroute", "--st-enroute"] },
  on_scene: { dark: "#fbbf24", light: "#a16207", vars: ["--status-onscene", "--status-on-scene", "--st-onscene"] },
  transporting: { dark: "#a78bfa", light: "#6d28d9", vars: ["--status-transporting", "--st-transporting"] },
  returning: { dark: "#fb923c", light: "#c2410c", vars: ["--status-returning", "--st-returning"] },
  blocked: { dark: "#f43f5e", light: "#be123c", vars: ["--status-blocked", "--st-blocked"] },
};

const SEVERITY_TONE = {
  3: { dark: "#fbbf24", light: "#a16207", vars: ["--sev-3", "--severity-3"] },
  4: { dark: "#fb923c", light: "#c2410c", vars: ["--sev-4", "--severity-4"] },
  5: { dark: "#f43f5e", light: "#be123c", vars: ["--sev-5", "--severity-5"] },
};

const FACILITY_TONE = {
  station: { dark: "#818cf8", light: "#4338ca", vars: ["--station"] },
  hospital: { dark: "#06b6d4", light: "#0e7490", vars: ["--hospital"] },
};

// Panel tones: values keep their semantic hue, words fall back to ink/muted.
const TONES = {
  ink: { vars: ["--ink", "--text"], dark: "#e2e8f0", light: "#0f172a" },
  muted: { vars: ["--muted"], dark: "#8899b5", light: "#475569" },
  dim: { vars: ["--dim", "--faint"], dark: "#546682", light: "#64748b" },
  ok: { vars: ["--ok", "--success"], dark: "#34d399", light: "#047857" },
  warn: { vars: ["--warn"], dark: "#fbbf24", light: "#a16207" },
  orange: { vars: ["--orange"], dark: "#fb923c", light: "#c2410c" },
  alert: { vars: ["--alert", "--danger"], dark: "#f43f5e", light: "#be123c" },
  ops: { vars: ["--ops", "--accent"], dark: "#38bdf8", light: "#0e7490" },
  station: { vars: ["--station"], dark: "#818cf8", light: "#4338ca" },
  hospital: { vars: ["--hospital"], dark: "#06b6d4", light: "#0e7490" },
  violet: { vars: ["--violet"], dark: "#a78bfa", light: "#6d28d9" },
  gini: { vars: ["--gini"], dark: "#c084fc", light: "#7e22ce" },
  reneg: { vars: ["--reneg"], dark: "#e879f9", light: "#86198f" },
};

// Glyph geometry — the single source of truth for canvas and legend swatches.
function starPoints(outer, inner) {
  const pts = [];
  for (let i = 0; i < 10; i++) {
    const ang = ((i * 36) - 90) * Math.PI / 180;
    const r = i % 2 === 0 ? outer : inner;
    pts.push([r * Math.cos(ang), r * Math.sin(ang)]);
  }
  return pts;
}

const SEVERITY_SHAPE = {
  3: [[0, -9], [8, 6], [-8, 6]],
  4: [[0, -8], [8, 0], [0, 8], [-8, 0]],
  5: starPoints(10, 4.5),
};

const STATUS_RING = {
  idle: "solid",
  drifting: "halo",
  enroute: "outer-ring",
  on_scene: "tick",
  transporting: "ring",
  returning: "dashed",
  blocked: "cross",
};

// Ring grammar per status — the shape, not the hue, carries the meaning.
// Radii are fractions of the marker radius so the canvas and the legend swatch
// are the same drawing at two sizes. Every `w` is an absolute hairline in CSS
// pixels: one 1px edge per marker, no scaled halo, no glow layer.
const GLYPH_HAIRLINE = 1;
const UNIT_GLYPH = {
  body: { w: GLYPH_HAIRLINE },
  halo: { r: 1.22, w: GLYPH_HAIRLINE },
  outerRing: { r: 1.66, w: GLYPH_HAIRLINE },
  ring: { r: 1.42, w: GLYPH_HAIRLINE },
  dashed: { r: 1.42, w: GLYPH_HAIRLINE, dash: [0.371, 0.314] },
  tick: { from: 0.77, to: 1.42, w: GLYPH_HAIRLINE },
  cross: { d: 0.52, w: GLYPH_HAIRLINE },
};
const UNIT_RADIUS_RATIO = 0.35; // of the 20-unit nominal box

// Flat-surface constants. A single neutral wash, a single trail alpha and one
// hairline edge keep the map flat; nothing here scales with time or radius.
const ZONE_EDGE_ALPHA = 0.4;
const TRAIL_MAX_POINTS = 18;
const TRAIL_MIN_STEP = 0.6;  // world units — a dense polyline reads as a smear
const TRAIL_HEAD_ALPHA = 0.32;
const ROUTE_ALPHA = 0.45;
const ROUTE_LINE_W = 1;
const FLASH_MS = 1200;        // one static 1px ring, faded once, then gone
const FLASH_RADIUS = 13;
const BLOCKAGE_FLASH_RADIUS = 9;

const STATUS_COLOR = {};
const SEVERITY_COLOR = {};

const STATUS_LABEL = {
  idle: "idle / parked",
  drifting: "drifting (MDP)",
  enroute: "en route to scene",
  on_scene: "on scene",
  transporting: "transporting to hospital",
  returning: "returning to base",
  blocked: "blocked by hazard",
};

// Badge hue encodes the event family only — never the semantic status.
const KIND_BADGE = {
  "ambulance.dispatched": {
    dark: "bg-emerald-950/80 text-emerald-300 border border-emerald-800/60",
    light: "bg-emerald-50 text-emerald-800 border border-emerald-300",
  },
  "dispatch.auction.award": {
    dark: "bg-teal-950/80 text-teal-300 border border-teal-800/60",
    light: "bg-teal-50 text-teal-800 border border-teal-300",
  },
  "dispatch.auction.announce": {
    dark: "bg-teal-950/60 text-teal-300/90 border border-teal-800/50",
    light: "bg-teal-50 text-teal-800 border border-teal-300",
  },
  "dispatch.auction.bid": {
    dark: "bg-teal-950/40 text-teal-200/80 border border-teal-800/40",
    light: "bg-teal-50 text-teal-800 border border-teal-300",
  },
  "dispatch.auction.reject": {
    dark: "bg-rose-950/40 text-rose-300/80 border border-rose-800/40",
    light: "bg-rose-50 text-rose-800 border border-rose-300",
  },
  "dispatch.greedy": {
    dark: "bg-lime-950/80 text-lime-300 border border-lime-800/60",
    light: "bg-lime-50 text-lime-800 border border-lime-300",
  },
  "dispatch.renegotiated": {
    dark: "bg-fuchsia-950/80 text-fuchsia-300 border border-fuchsia-800/60",
    light: "bg-fuchsia-50 text-fuchsia-800 border border-fuchsia-300",
  },
  "ambulance.replanned": {
    dark: "bg-sky-950/80 text-sky-300 border border-sky-800/60",
    light: "bg-sky-50 text-sky-800 border border-sky-300",
  },
  "replan.cost_compare": {
    dark: "bg-sky-950/50 text-sky-300/80 border border-sky-800/40",
    light: "bg-sky-50 text-sky-800 border border-sky-300",
  },
  "ambulance.on_scene": {
    dark: "bg-amber-950/80 text-amber-300 border border-amber-800/60",
    light: "bg-amber-50 text-amber-800 border border-amber-300",
  },
  "hospital.allocated": {
    dark: "bg-cyan-950/80 text-cyan-300 border border-cyan-800/60",
    light: "bg-cyan-50 text-cyan-800 border border-cyan-300",
  },
  "incident.cleared": {
    dark: "bg-indigo-950/80 text-indigo-300 border border-indigo-800/60",
    light: "bg-indigo-50 text-indigo-800 border border-indigo-300",
  },
  "mdp.solved": {
    dark: "bg-blue-950/80 text-blue-300 border border-blue-800/60",
    light: "bg-blue-50 text-blue-800 border border-blue-300",
  },
  "world.blockage_detected": {
    dark: "bg-orange-950/80 text-orange-300 border border-orange-800/60",
    light: "bg-orange-50 text-orange-800 border border-orange-300",
  },
  "dispatch.failed": {
    dark: "bg-rose-950/80 text-rose-300 border border-rose-800/60",
    light: "bg-rose-50 text-rose-800 border border-rose-300",
  },
  "incident.reported": {
    dark: "bg-rose-950/60 text-rose-300/90 border border-rose-800/50",
    light: "bg-rose-50 text-rose-800 border border-rose-300",
  },
  "ambulance.hospital_arrival": {
    dark: "bg-emerald-950/60 text-emerald-300/90 border border-emerald-800/50",
    light: "bg-emerald-50 text-emerald-800 border border-emerald-300",
  },
  "ambulance.transporting": {
    dark: "bg-violet-950/80 text-violet-300 border border-violet-800/60",
    light: "bg-violet-50 text-violet-800 border border-violet-300",
  },
  "ambulance.idle_move": {
    dark: "bg-lime-950/60 text-lime-300/90 border border-lime-800/50",
    light: "bg-lime-50 text-lime-800 border border-lime-300",
  },
  "ambulance.status": {
    dark: "bg-zinc-800 text-zinc-300 border border-zinc-700",
    light: "bg-zinc-50 text-zinc-800 border border-zinc-300",
  },
  "search.run": {
    dark: "bg-blue-950/60 text-blue-300/90 border border-blue-800/50",
    light: "bg-blue-50 text-blue-800 border border-blue-300",
  },
  "sim.start": {
    dark: "bg-stone-800 text-stone-300 border border-stone-700",
    light: "bg-stone-50 text-stone-800 border border-stone-300",
  },
  "sim.incident_scheduled": {
    dark: "bg-stone-800/70 text-stone-300/90 border border-stone-700",
    light: "bg-stone-50 text-stone-800 border border-stone-300",
  },
};

const BADGE_FALLBACK = {
  dark: "bg-slate-800 text-slate-300 border border-slate-700",
  light: "bg-slate-50 text-slate-800 border border-slate-300",
};

function badgeClass(kind) {
  const entry = KIND_BADGE[kind];
  const pair = entry || BADGE_FALLBACK;
  return tokens.badge === "light" ? pair.light : pair.dark;
}

// --------------------------------------------------------------------------- //
// Colour maths — hex/rgb/hsl parsing, WCAG contrast, contrast-safe tuning     //
// --------------------------------------------------------------------------- //

function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

function pct(v) {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (!isFinite(n)) return 0;
  if (typeof v === "string" && v.indexOf("%") >= 0) return n / 100;
  return n > 1 ? n / 100 : n;
}

function parseHex(s) {
  let h = s.slice(1);
  if (h.length === 3 || h.length === 4) h = h.split("").map((c) => c + c).join("");
  if (h.length !== 6 && h.length !== 8) return null;
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
    a: h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1,
  };
}

function hslToRgb(h, s, l) {
  h = ((h % 360) + 360) % 360;
  s = clamp(s, 0, 1);
  l = clamp(l, 0, 1);
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r = 0, g = 0, b = 0;
  if (h < 60) { r = c; g = x; } else if (h < 120) { r = x; g = c; }
  else if (h < 180) { g = c; b = x; } else if (h < 240) { g = x; b = c; }
  else if (h < 300) { r = x; b = c; } else { r = c; b = x; }
  return {
    r: Math.round((r + m) * 255),
    g: Math.round((g + m) * 255),
    b: Math.round((b + m) * 255),
    a: 1,
  };
}

function rgbToHsl(c) {
  const rn = c.r / 255, gn = c.g / 255, bn = c.b / 255;
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  const d = max - min;
  if (!d) return { h: 0, s: 0, l };
  const s = d / (1 - Math.abs(2 * l - 1));
  let h;
  if (max === rn) h = 60 * (((gn - bn) / d) % 6);
  else if (max === gn) h = 60 * ((bn - rn) / d + 2);
  else h = 60 * ((rn - gn) / d + 4);
  return { h: (h + 360) % 360, s, l };
}

function parseColor(c) {
  if (!c) return null;
  const s = String(c).trim();
  if (!s) return null;
  if (s[0] === "#") return parseHex(s);
  const rgb = s.match(/^rgba?\(([^)]+)\)$/i);
  if (rgb) {
    const p = rgb[1].split(/[\s,/]+/).filter(Boolean);
    return { r: +p[0], g: +p[1], b: +p[2], a: p[3] != null ? pct(p[3]) : 1 };
  }
  const hsl = s.match(/^hsla?\(([^)]+)\)$/i);
  if (hsl) {
    const p = hsl[1].split(/[\s,/]+/).filter(Boolean);
    const base = hslToRgb(parseFloat(p[0]), pct(p[1]), pct(p[2]));
    base.a = p[3] != null ? pct(p[3]) : 1;
    return base;
  }
  return null;
}

function rgbToHex(c) {
  const h = (v) => clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0");
  return `#${h(c.r)}${h(c.g)}${h(c.b)}`;
}

function withAlpha(color, a) {
  const p = parseColor(color);
  return p ? `rgba(${p.r},${p.g},${p.b},${a})` : color;
}

// Darkens a hue in place while easing off saturation, so derived details stay
// recognisably the same family instead of turning electric.
function shade(color, amount) {
  const c = parseColor(color);
  if (!c) return color;
  const hsl = rgbToHsl(c);
  const k = clamp(amount, 0, 0.9);
  return rgbToHex(hslToRgb(hsl.h, hsl.s * (1 - k * 0.45), clamp(hsl.l * (1 - k), 0, 1)));
}

function relLum(c) {
  const f = (v) => {
    const n = v / 255;
    return n <= 0.04045 ? n / 12.92 : Math.pow((n + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
}

function contrast(a, b) {
  const la = relLum(a), lb = relLum(b);
  const hi = Math.max(la, lb), lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

// Walks lightness away from the backdrop until the pair clears `target`,
// preserving hue and saturation. Returns the input when already compliant.
function meetContrast(color, bg, target) {
  const c = parseColor(color);
  const b = parseColor(bg);
  if (!c || !b) return color;
  if (contrast(c, b) >= target) return color;
  const hsl = rgbToHsl(c);
  const up = rgbToHsl(b).l < 0.5;
  for (let i = 1; i <= 60; i++) {
    const l = up ? hsl.l + i * 0.015 : hsl.l - i * 0.015;
    if (l > 1 || l < 0) break;
    const cand = hslToRgb(hsl.h, hsl.s, l);
    if (contrast(cand, b) >= target) return rgbToHex(cand);
  }
  return color;
}

// --------------------------------------------------------------------------- //
// Storage — localStorage with a session-only fallback                          //
// --------------------------------------------------------------------------- //

// `foai_app_theme` is the canonical key: the boot script in the markup reads it
// first, so writing it (and mirroring the legacy key) is what keeps a reload in
// the same theme. localStorage can be denied outright — private mode, embedded
// webviews, strict cookie policies — so every access falls back to an in-memory
// map. The dashboard then keeps working for the whole page session instead of
// throwing during boot and taking the toggle down with it.
const THEME_KEY = "foai_app_theme";
const THEME_KEY_LEGACY = "ems_theme";
const memoryStore = new Map();

function storeGet(key) {
  // A value written earlier in this session is the freshest one, and it is
  // also the only one available when the durable store is blocked.
  if (memoryStore.has(key)) return memoryStore.get(key);
  try {
    const v = window.localStorage.getItem(key);
    if (v !== null && v !== undefined) return v;
  } catch (e) { /* denied — fall through to the session-only value */ }
  return null;
}

function storeSet(key, value) {
  memoryStore.set(key, value);
  try { window.localStorage.setItem(key, value); } catch (e) { /* session only */ }
}

function storeRemove(key) {
  memoryStore.delete(key);
  try { window.localStorage.removeItem(key); } catch (e) { /* session only */ }
}

// --------------------------------------------------------------------------- //
// Theme tokens — resolved once per theme change, never per frame               //
// --------------------------------------------------------------------------- //

const INK_ON_DARK = "#ffffff";
const INK_ON_LIGHT = "#0b1220";

const tokens = {
  theme: "dark",
  isLight: false,
  badge: "dark",
  font: { mono: "'JetBrains Mono', monospace", sans: "'Space Grotesk', sans-serif" },
  map: {},
  heat: { s: "62%", l: "32%" },
  tones: {},
  status: {},
  severity: {},
  facility: {},
};

function readTokens() {
  const cs = getComputedStyle(document.documentElement);
  const raw = (name) => {
    const v = cs.getPropertyValue(name);
    const s = (v || "").trim().replace(/\s+/g, " ");
    return s && s !== "inherit" && s !== "initial" && s !== "none" ? s : null;
  };
  const pick = (names, fallback) => {
    for (const n of names) {
      const v = raw(n);
      if (v) return v;
    }
    return fallback;
  };

  const declared = document.documentElement.dataset.theme;
  const bg = pick(["--map-bg", "--bg"], "#070b16");
  const isLight = declared ? declared === "light"
    : (relLum(parseColor(bg) || { r: 7, g: 11, b: 22 }) > 0.5);

  tokens.theme = isLight ? "light" : "dark";
  tokens.badge = tokens.theme;
  tokens.isLight = isLight;

  const fontStack = (v, fb) => (v && v.length < 160 ? v : fb);
  tokens.font = {
    mono: fontStack(pick(["--font-mono", "--font-mono-stack", "--font-mono-family"]),
      "'JetBrains Mono', ui-monospace, monospace"),
    sans: fontStack(pick(["--font-sans", "--font-display"]), "'Space Grotesk', system-ui, sans-serif"),
  };

  const mapBg = bg;
  const road = meetContrast(pick(["--map-road"], isLight ? "#94a3b8" : "#1c2a44"), mapBg, 3);
  tokens.map = {
    bg: mapBg,
    road,
    node: meetContrast(pick(["--map-node"], isLight ? "#64748b" : "#1e2d4a"), mapBg, 2.2),
    zone: pick(["--map-zone"], isLight ? "#94a3b8" : "#1e293b"),
    zoneLabel: meetContrast(pick(["--map-zone-label", "--map-label"], isLight ? "#64748b" : "#546682"), mapBg, 3),
    label: meetContrast(pick(["--map-label"], isLight ? "#475569" : "#c7d2fe"), mapBg, 4.5),
    labelMuted: meetContrast(pick(["--map-label-muted", "--dim"], isLight ? "#64748b" : "#546682"), mapBg, 3),
    halo: pick(["--map-halo"], isLight ? "#ffffff" : "#080d1a"),
    onFill: pick(["--map-onfill"], "#ffffff"),
    border: pick(["--border-strong", "--line-strong"], isLight ? "#94a3b8" : "#2a3e66"),
    surface: pick(["--surface", "--surface-2", "--bg"], mapBg),
    // Mirrored for external consumers only. The canvas paints no glow layer:
    // markers are flat fills with at most one 1px edge.
    glow: pick(["--map-glow"], isLight ? "59" : "66"),
    // One neutral wash for every zone, in both themes — no gradient, no bloom.
    zoneAlpha: 0.16,
  };

  tokens.heat = {
    s: pick(["--heat-s"], "62%"),
    l: pick(["--heat-l"], isLight ? "46%" : "32%"),
  };

  for (const [key, def] of Object.entries(SEMANTIC)) {
    tokens.status[key] = pick(def.vars, def[tokens.theme]);
    STATUS_COLOR[key] = tokens.status[key];
  }
  for (const key of Object.keys(SEVERITY_TONE)) {
    const def = SEVERITY_TONE[key];
    tokens.severity[key] = pick(def.vars, def[tokens.theme]);
    SEVERITY_COLOR[key] = tokens.severity[key];
  }
  for (const [key, def] of Object.entries(FACILITY_TONE)) {
    tokens.facility[key] = pick(def.vars, def[tokens.theme]);
    // The structural edge is the other tone of the same hue: dark ink detail on
    // the light body, light body detail on the dark wash.
    tokens.facility[`${key}Edge`] = pick(
      [`--${key}-edge`, `--map-${key}-edge`], def[tokens.theme === "light" ? "dark" : "light"]);
  }
  for (const [key, def] of Object.entries(TONES)) {
    // Text tones are contrast-guarded against the panel surface so a token
    // that was not flipped still renders legibly; `dim` stays deliberately quiet.
    tokens.tones[key] = meetContrast(
      pick(def.vars, def[tokens.theme]), tokens.map.surface, key === "dim" ? 3 : 4.5);
  }

  return tokens;
}

function getMapPalette() {
  return tokens.map;
}

function statusColor(status) {
  const key = status === "onscene" ? "on_scene" : status;
  return tokens.status[key] || tokens.status.idle;
}

function severityColor(sev) {
  return tokens.severity[sev] || tokens.severity[5];
}

function facilityColor(key) {
  return tokens.facility[key] || tokens.tones.muted;
}

function facilityEdge(key) {
  return tokens.facility[`${key}Edge`] || shade(facilityColor(key), 0.35);
}

function tone(key) {
  return tokens.tones[key] || tokens.tones.ink;
}

function mapFont(weight, size) {
  return `${weight || ""} ${size}px ${tokens.font.mono}`.trim();
}

function mapFontSans(weight, size) {
  return `${weight || ""} ${size}px ${tokens.font.sans}`.trim();
}

// --------------------------------------------------------------------------- //
// Theme — one writer, one repaint, one persistence path                        //
// --------------------------------------------------------------------------- //

// The icon advertises the switch, not the current state: a sun while dark is
// running, a moon while light is.
const THEME_ICON = {
  dark: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>',
  light: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>',
};

function renderThemeToggle() {
  const isDark = state.theme !== "light";
  const btn = document.getElementById("themeToggleBtn");
  if (btn) {
    btn.setAttribute("aria-pressed", isDark ? "true" : "false");
    btn.setAttribute("title", isDark ? "Switch to light theme" : "Switch to dark theme");
    btn.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
  }
  const label = document.getElementById("themeToggleLabel");
  if (label) label.textContent = isDark ? "Light" : "Dark";
  const icon = document.getElementById("themeToggleIcon");
  if (icon) icon.innerHTML = THEME_ICON[isDark ? "dark" : "light"];
}

function persistTheme(theme) {
  storeSet(THEME_KEY, theme);        // canonical: the boot script reads this first
  storeSet(THEME_KEY_LEGACY, theme); // older builds read this; keep them in step
}

// The single place `data-theme` is written. Everything else — the toggle click,
// the 't' shortcut, the `foai:theme` consumers, cross-tab storage sync, a
// `themechange` request, cold boot — comes through here, so one request can
// never produce two competing writes.
function setTheme(theme, opts = {}) {
  const next = theme === "light" ? "light" : "dark";
  const root = document.documentElement;
  const changed = root.getAttribute("data-theme") !== next;
  root.setAttribute("data-theme", next);
  root.classList.toggle("light", next === "light");
  state.theme = next;

  readTokens();          // resolved once per theme change, never per frame
  renderThemeToggle();   // icon, visible label, aria-pressed / aria-label
  if (opts.persist !== false) persistTheme(next);

  rethemePanels();
  renderLegend();
  if (state.snap) {
    try {
      renderStats(state.snap);
      renderExplainability(state.snap);
    } catch (e) { /* a panel re-render must not block the repaint */ }
  }
  forceFrame();          // exactly one forced frame; the loop owns the rest

  if (changed && opts.announce !== false) {
    announce(`${next === "light" ? "Light" : "Dark"} theme.`);
  }
  if (opts.notify !== false) {
    try {
      window.dispatchEvent(new CustomEvent("foai:theme", { detail: { theme: next } }));
    } catch (e) { /* CustomEvent unsupported */ }
  }
  return next;
}

// One user gesture = one theme write. The markup ships its own click handler
// that delegates to window.toggleTheme(), older builds bridged through a
// `foai:toggle-theme` event, and the keyboard shortcut lands here too — so a
// single click could reach setTheme() twice (dark -> light -> dark) and leave
// the attribute exactly where it started: "clicked, but the theme never
// changed". The first writer wins; every other path in the same gesture is a
// no-op that still returns the theme that was applied, so a caller that repaints
// from the return value stays in agreement.
let themeGestureOpen = false;
let themeGestureResult = null;

function requestThemeToggle() {
  if (themeGestureOpen) return themeGestureResult;
  themeGestureOpen = true;
  themeGestureResult = setTheme(currentTheme() === "light" ? "dark" : "light");
  setTimeout(() => { themeGestureOpen = false; themeGestureResult = null; }, 0);
  return themeGestureResult;
}

// An external writer changed the attribute. Adopt it read-only: re-read the
// tokens and repaint the chrome, but never write the attribute back, never
// persist and never re-broadcast. This observer used to call setTheme(), which
// wrote the attribute again and ping-ponged with the click path — the second
// half of the race that swallowed the user's click.
function adoptExternalTheme(theme) {
  if (theme !== "light" && theme !== "dark") return;
  if (theme === state.theme) return;
  state.theme = theme;
  document.documentElement.classList.toggle("light", theme === "light");
  readTokens();
  renderThemeToggle();
  rethemePanels();
  renderLegend();
  if (state.snap) {
    try {
      renderStats(state.snap);
      renderExplainability(state.snap);
    } catch (e) { /* a panel re-render must not block the repaint */ }
  }
  forceFrame();
}

// Cold boot. The inline head script has already written `data-theme` from the
// persisted key, so this only steps in when storage says something different —
// a reload must never flash or revert the choice the user just made.
function restoreTheme() {
  const primary = storeGet(THEME_KEY);
  const legacy = storeGet(THEME_KEY_LEGACY);
  const saved = primary || legacy;
  const declared = document.documentElement.getAttribute("data-theme");
  if (saved === "light" || saved === "dark") {
    if (!primary && legacy) storeSet(THEME_KEY, legacy); // upgrade the key once
    if (declared !== saved) setTheme(saved, { persist: false, notify: false });
    return;
  }
  if (declared !== "light" && declared !== "dark") {
    const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
    setTheme(mq && mq.matches ? "light" : "dark", { persist: false, notify: false });
  }
}

function bindThemeControls() {
  for (const id of ["themeToggleBtn", "btn-theme", "btn-toggle-theme", "theme-toggle"]) {
    const btn = document.getElementById(id);
    if (btn) btn.addEventListener("click", requestThemeToggle);
  }
  // Compatibility bridge for builds that ask for a flip by event instead of
  // calling window.toggleTheme(). Guarded, so it cannot double-apply.
  window.addEventListener("foai:toggle-theme", requestThemeToggle);
}

function watchThemeSources() {
  // Cross-tab sync: an explicit external request, so it may write.
  window.addEventListener("storage", (e) => {
    if (e.key !== THEME_KEY && e.key !== THEME_KEY_LEGACY) return;
    if (e.newValue && e.newValue !== state.theme) {
      setTheme(e.newValue, { persist: false, notify: false });
    }
  });
  const onThemeChange = (e) => {
    const next = (e && e.detail && (e.detail.theme || e.detail.mode)) || null;
    if (next === "light" || next === "dark") setTheme(next, { notify: false });
  };
  window.addEventListener("themechange", onThemeChange);
  document.addEventListener("themechange", onThemeChange);
  if (window.MutationObserver) {
    new MutationObserver(() => {
      adoptExternalTheme(document.documentElement.getAttribute("data-theme"));
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }
}

// --------------------------------------------------------------------------- //
// Motion preference                                                             //
// --------------------------------------------------------------------------- //

const motionStyle = document.createElement("style");
motionStyle.id = "foai-motion";
motionStyle.textContent =
  "[data-motion='reduce'] *{transition:none !important;animation:none !important;scroll-behavior:auto !important}";
document.head.appendChild(motionStyle);

// Flat map chrome: flat fills and hairline edges, no bloom on the overlays, and
// a visible focus ring for the two focusable non-controls (canvas, KPI group).
const flatStyle = document.createElement("style");
flatStyle.id = "foai-flat";
flatStyle.textContent =
  "#hover-info,#legend{box-shadow:none !important}"
  + "#map{filter:none !important}"
  + "#map:focus-visible,#stats-cards:focus-visible{outline:2px solid var(--focus, var(--ink, var(--text)));outline-offset:2px}";
document.head.appendChild(flatStyle);

function syncMotion() {
  const mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  state.reducedMotion = !!(mq && mq.matches);
  document.documentElement.dataset.motion = state.reducedMotion ? "reduce" : "full";
  applyMotionGuards();
  return state.reducedMotion;
}

// The RUNNING blink and the feed-in slide are decoration, never information —
// the dot is already paired with a text label, so both switch off wholesale.
function applyMotionGuards() {
  const dot = document.getElementById("status-dot");
  if (dot) dot.style.animation = state.reducedMotion ? "none" : "";
}

function watchMotion() {
  const mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  if (!mq) return;
  const onChange = () => { syncMotion(); forceFrame(); };
  if (mq.addEventListener) mq.addEventListener("change", onChange);
  else if (mq.addListener) mq.addListener(onChange);
}

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
      state.trail = {};
      state.prevPos = {};
      state.anim = {};
      state.flashes = [];
      state.events = [];
      state.pendingEvents = [];
      state.liveSnap = null;
      resetWowRunState();
      runBenchmark(false);
      break;
    case "status":
      renderControls(msg);
      break;
    case "snapshot": {
      const isFirst = !state.snap;
      if (state.snap && msg.data && msg.data.tick < (state.snap.tick || 0)) {
        state.trail = {};
        state.prevPos = {};
        state.anim = {};
        state.flashes = [];
      }
      state.snap = msg.data;
      state.liveSnap = msg.data; // replay frames borrow state.snap; this stays live
      const scenName = msg.data.scenario ? msg.data.scenario.name : null;
      if (!state.map || state.mapId !== scenName) {
        applyMap(msg.data.map);
        state.mapId = scenName;
      } else if (state.map && msg.data.map && msg.data.map.hospitals) {
        state.map.hospitals = msg.data.map.hospitals;
      }
      if (state.map && state.map.hospitals && state.snap) {
        state.snap.map = state.snap.map || {};
        state.snap.map.hospitals = state.map.hospitals;
      }
      prepAnimation(msg.data);
      if (!isFirst) noteSnapshot(msg.data); // one-shot acknowledgement rings
      queueEvents(msg.events);
      scheduleDomUpdate(msg.data);

      if (msg.done) {
        state.run = state.run || {};
        state.run.finished = true;
        renderControls({ running: false, finished: true, has_engine: true });
        flushPendingEvents();
        if (window.FOAI_WOW && typeof window.FOAI_WOW.renderHospitalLoads === "function") {
          window.FOAI_WOW.renderHospitalLoads(msg.data);
        }
        if (window.FOAI_WOW && typeof window.FOAI_WOW.onRunFinished === "function") {
          window.FOAI_WOW.onRunFinished(msg.data);
        }
        // Pre-fetch replay frames so scrubber is instantly ready
        send({ action: "replay" });
        const name = document.getElementById("sim-name");
        if (name && !name.textContent.includes("FINISHED")) {
          name.textContent += " · FINISHED";
        }
      }
      break;
    }
    case "replay_chunk":
      state.replayQueue.push(...msg.data);
      if (window.FOAI_WOW && typeof window.FOAI_WOW.drainReplayQueue === "function") {
        window.FOAI_WOW.drainReplayQueue();
      }
      break;
    case "replay_end":
      if (window.FOAI_WOW && typeof window.FOAI_WOW.onReplayEnd === "function") {
        window.FOAI_WOW.onReplayEnd(msg.count);
      }
      break;
    case "error":
      console.warn(msg.message);
      break;
  }
}

// --------------------------------------------------------------------------- //
// Throttled DOM Updating (Eliminates lag at high TPS)                          //
// --------------------------------------------------------------------------- //

function isAnalyzeVisible() {
  const ana = document.getElementById("view-analyze");
  return !!(ana && !ana.classList.contains("hidden") && ana.offsetParent !== null);
}

let domUpdateRaf = null;

function performDomUpdate(snap) {
  if (!snap) return;
  state.lastRenderedTick = snap.tick;
  state.lastDomUpdate = performance.now();

  const sc = state.scenarios.find((x) => x.id === snap.scenario?.name);
  updateFleetSummary(sc);
  const clockEl = document.getElementById("clock");
  if (clockEl) {
    clockEl.textContent = `t ${snap.tick} · ${snap.seconds}s`;
  }

  flushPendingEvents();
  refreshMapAlt(snap);

  if (window.FOAI_WOW && typeof window.FOAI_WOW.renderHospitalLoads === "function") {
    window.FOAI_WOW.renderHospitalLoads(snap);
  }

  if (isAnalyzeVisible()) {
    renderStats(snap);
    renderExplainability(snap);
    state.analyzeDirty = false;
  } else {
    state.analyzeDirty = true;
  }
}

function scheduleDomUpdate(snap) {
  if (!snap) return;
  if (snap.tick === state.lastRenderedTick && !state.analyzeDirty) return;

  const now = performance.now();
  if (now - state.lastDomUpdate > 40 && !domUpdateRaf) {
    domUpdateRaf = requestAnimationFrame(() => {
      domUpdateRaf = null;
      performDomUpdate(state.snap || snap);
    });
  } else if (!domUpdateRaf) {
    domUpdateRaf = requestAnimationFrame(() => {
      domUpdateRaf = null;
      performDomUpdate(state.snap || snap);
    });
  }
}

window.addEventListener("foai:view-change", (e) => {
  if (e && e.detail && e.detail.view === "analyze") {
    if (state.snap) {
      renderStats(state.snap);
      renderExplainability(state.snap);
      state.analyzeDirty = false;
    }
  }
});

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
    `<span class="whitespace-nowrap">${val("ops", s.ambulances ?? "—", "font-bold")} ${word("units")}</span> <span class="text-muted font-bold">·</span> ` +
    `<span class="whitespace-nowrap">${val("station", s.stations ?? "—", "font-bold")} ${word("stations")}</span> <span class="text-muted font-bold">·</span> ` +
    `<span class="whitespace-nowrap">${val("hospital", s.hospitals ?? "—", "font-bold")} ${word("hospitals")}</span> <span class="text-muted font-bold">·</span> ` +
    `<span class="whitespace-nowrap">${val("alert", s.incidents ?? "—", "font-bold")} ${word("calls")}</span>`;
}

// Pause / resume reliability --------------------------------------------------
// The server answers `pause` with an authoritative status frame, but `resume`
// can be swallowed entirely: web/main.py's Session.resume early-returns while
// the previous tick task is still inside its sleep window and sends no status,
// so the client would sit on "RESUME" with a frozen sim. The label therefore
// flips optimistically and resume is re-sent until a running status confirms.
let resumeRetryTimer = null;
let resumeRetries = 0;
const RESUME_RETRY_MS = 400;
const RESUME_RETRY_MAX = 8;

function stopResumeRetry() {
  if (resumeRetryTimer) {
    clearTimeout(resumeRetryTimer);
    resumeRetryTimer = null;
  }
  resumeRetries = 0;
}

function scheduleResumeRetry() {
  stopResumeRetry();
  const attempt = () => {
    resumeRetryTimer = null;
    if (state.run && state.run.running) return; // authoritative confirmation
    if (resumeRetries >= RESUME_RETRY_MAX) return;
    resumeRetries += 1;
    send({ action: "resume" });
    resumeRetryTimer = setTimeout(attempt, RESUME_RETRY_MS);
  };
  resumeRetryTimer = setTimeout(attempt, RESUME_RETRY_MS);
}

// Fresh run: trails, ticker and replay buffers belong to the old run.
function resetWowRunState() {
  if (window.FOAI_WOW && typeof window.FOAI_WOW.resetRunState === "function") {
    window.FOAI_WOW.resetRunState();
  }
}

function renderControls(status) {
  const running = !!status.running;
  const finished = !!status.finished;
  const hasEngine = !!status.has_engine;
  const prev = state.run || {};
  state.run = { running, finished, hasEngine };
  if (running) stopResumeRetry();

  const start = document.getElementById("btn-start");
  const pause = document.getElementById("btn-pause");
  const step = document.getElementById("btn-step");

  if (!hasEngine) {
    // Idle state
    start.classList.remove("hidden");
    start.textContent = "START";
    start.className = "btn px-3.5 py-1.5 text-xs font-bold btn-primary";
    start.removeAttribute("disabled");

    pause.classList.add("hidden");
    pause.textContent = "PAUSE";
    pause.setAttribute("disabled", "true");
    pause.className = "btn px-3.5 py-1.5 text-xs font-bold btn-amber hidden";

    if (step) {
      step.classList.add("opacity-40", "cursor-not-allowed");
      step.setAttribute("aria-disabled", "true");
    }
  } else if (finished) {
    // Finished state
    start.classList.remove("hidden");
    start.textContent = "RUN AGAIN";
    start.className = "btn px-3.5 py-1.5 text-xs font-bold btn-primary";
    start.removeAttribute("disabled");

    pause.classList.add("hidden");
    pause.textContent = "PAUSE";
    pause.setAttribute("disabled", "true");
    pause.className = "btn px-3.5 py-1.5 text-xs font-bold btn-amber hidden";

    if (step) {
      step.classList.add("opacity-40", "cursor-not-allowed");
      step.setAttribute("aria-disabled", "true");
    }
  } else if (running) {
    // Running state
    start.classList.add("hidden");

    pause.classList.remove("hidden");
    pause.textContent = "PAUSE";
    pause.className = "btn px-3.5 py-1.5 text-xs font-bold btn-amber";
    pause.removeAttribute("disabled");
    pause.setAttribute("aria-label", "Pause simulation");

    if (step) {
      step.classList.add("opacity-40", "cursor-not-allowed");
      step.setAttribute("aria-disabled", "true");
    }
  } else {
    // Paused state
    start.classList.add("hidden");

    pause.classList.remove("hidden");
    pause.textContent = "RESUME";
    pause.className = "btn px-3.5 py-1.5 text-xs font-bold btn-primary";
    pause.removeAttribute("disabled");
    pause.setAttribute("aria-label", "Resume simulation");

    if (step) {
      step.classList.remove("opacity-40", "cursor-not-allowed");
      step.setAttribute("aria-disabled", "false");
    }
  }

  if (step) {
    if (!step.classList.contains("sidebar-btn")) {
      step.classList.add("sidebar-btn");
    }
    step.classList.remove("btn", "btn-ghost", "px-2.5", "py-1.5");
  }

  const dot = document.getElementById("status-dot");
  if (dot) {
    dot.className = "dot " + (!hasEngine ? "dot-idle" : finished ? "dot-finished"
      : running ? "dot-running" : "dot-paused");
  }
  applyMotionGuards();

  const name = document.getElementById("sim-name");
  if (finished && name && !name.textContent.includes("FINISHED")) {
    name.textContent += " · FINISHED";
  }

  // Announce transitions only. Status frames arrive per tick; the polite
  // region is rate-limited to one message per 10s, so a transition is all it
  // ever needs to carry.
  if (finished && !prev.finished) {
    announce(`Simulation finished at tick ${state.snap ? state.snap.tick : "—"}.`);
  } else if (running && !prev.running) {
    announce("Simulation running.");
  } else if (!running && prev.running) {
    announce("Simulation paused.");
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
  invalidateTransform();
}

const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");

let viewportCache = { w: 0, h: 0 };
let transformCache = {
  valid: false,
  cx: 0, cy: 0,
  cos: 1, sin: 0, rad: 0,
  rotMinX: 0, rotMinY: 0,
  scale: 1,
  ox: 0, oy: 0,
};

function invalidateTransform() {
  transformCache.valid = false;
}

function updateTransformCache() {
  const w = state.world;
  if (!w) return;
  const vp = getViewportCssSize();
  const cssW = vp.w;
  const cssH = vp.h;

  const cx = (w.minX + w.maxX) / 2;
  const cy = (w.minY + w.maxY) / 2;
  const rad = ((state.rotation || 0) * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);

  const rotate = (x, y) => {
    if (rad === 0) return { x, y };
    const dx = x - cx;
    const dy = y - cy;
    return {
      x: cos * dx - sin * dy + cx,
      y: sin * dx + cos * dy + cy,
    };
  };

  const c1 = rotate(w.minX, w.minY);
  const c2 = rotate(w.maxX, w.minY);
  const c3 = rotate(w.minX, w.maxY);
  const c4 = rotate(w.maxX, w.maxY);

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

  transformCache = {
    valid: true,
    cx, cy, cos, sin, rad,
    rotMinX, rotMinY,
    scale, ox, oy,
  };
}

function getViewportCssSize() {
  if (viewportCache.w > 0 && viewportCache.h > 0) {
    return viewportCache;
  }
  const shell = document.getElementById("map-shell");
  if (shell) {
    const rect = shell.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      viewportCache = { w: rect.width, h: rect.height };
      return viewportCache;
    }
  }
  const dpr = window.devicePixelRatio || 1;
  viewportCache = { w: canvas.width / dpr, h: canvas.height / dpr };
  return viewportCache;
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
  if (!transformCache.valid) updateTransformCache();
  if (!transformCache.valid) return { x: 0, y: 0 };

  if (transformCache.rad === 0) {
    return {
      x: transformCache.ox + (x - transformCache.rotMinX) * transformCache.scale,
      y: transformCache.oy + (y - transformCache.rotMinY) * transformCache.scale,
    };
  }

  const dx = x - transformCache.cx;
  const dy = y - transformCache.cy;
  const rx = transformCache.cx + (transformCache.cos * dx - transformCache.sin * dy);
  const ry = transformCache.cy + (transformCache.sin * dx + transformCache.cos * dy);
  return {
    x: transformCache.ox + (rx - transformCache.rotMinX) * transformCache.scale,
    y: transformCache.oy + (ry - transformCache.rotMinY) * transformCache.scale,
  };
}

function resize() {
  const shell = document.getElementById("map-shell");
  if (!shell) return;
  const rect = shell.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(10, Math.floor(rect.width));
  const h = Math.max(10, Math.floor(rect.height));
  viewportCache = { w, h };
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  invalidateTransform();
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
  if (!snap || !snap.ambulances) return;
  state.unitStatus = state.unitStatus || {};
  for (const a of snap.ambulances) {
    if (!a || !Number.isFinite(a.x) || !Number.isFinite(a.y)) continue;
    const prev = state.prevPos[a.id] || { x: a.x, y: a.y };
    const prevStatus = state.unitStatus[a.id];
    state.unitStatus[a.id] = a.status;
    const statusChanged = prevStatus && prevStatus !== a.status;
    const dist = Math.hypot(a.x - prev.x, a.y - prev.y);

    if (state.reducedMotion) {
      delete state.anim[a.id];
      delete state.trail[a.id];
    } else if (dist > 1.25 || statusChanged) {
      // Discontinuous jump / teleport / scenario reset / reassignment: drop stale trail and animation
      delete state.anim[a.id];
      if (state.trail[a.id]) state.trail[a.id] = [];
    } else if (dist > 0.05) {
      state.anim[a.id] = { from: { ...prev }, to: { x: a.x, y: a.y },
                           t0: performance.now() };
      pushTrail(a);
    }
    state.prevPos[a.id] = { x: a.x, y: a.y };
  }
  pruneTrails(snap);
}

// Motion trail: a short world-space polyline behind a moving unit, drawn as a
// thin 1px line that fades toward the tail. It is off entirely under reduced
// motion, where the unit simply jumps from node to node.
function pushTrail(a) {
  if (!a || !Number.isFinite(a.x) || !Number.isFinite(a.y)) return;
  const pts = state.trail[a.id] || (state.trail[a.id] = []);
  const last = pts[pts.length - 1];
  if (last) {
    const dist = Math.hypot(a.x - last.x, a.y - last.y);
    if (dist < TRAIL_MIN_STEP) return;
    if (dist > 1.25) {
      pts.length = 0; // Drop stale jumps (eliminates diagonal lines across map)
    }
  }
  pts.push({ x: a.x, y: a.y });
  while (pts.length > TRAIL_MAX_POINTS) pts.shift();
}

function pruneTrails(snap) {
  const live = new Set();
  for (const a of (snap && snap.ambulances) || []) {
    if (a.status !== "idle" && a.status !== "drifting") {
      live.add(a.id);
    }
  }
  for (const id of Object.keys(state.trail)) {
    if (!live.has(id)) delete state.trail[id];
  }
}

// One-shot acknowledgement. A newly reported incident or a newly revealed
// blockage gets a single static 1px ring that fades once over at most 1.2s —
// not a pulse, not a shockwave, and never under reduced motion.
function pushFlash(key, color, x, y) {
  if (state.reducedMotion) return;
  state.flashes.push({ key, color, x, y, t0: performance.now() });
  if (state.flashes.length > 24) state.flashes.shift();
}

// Returns the live alpha for a key, or null once the ring has expired. Expired
// entries are pruned here, so no timer is needed and nothing accumulates.
function flashFor(key) {
  const now = performance.now();
  for (let i = state.flashes.length - 1; i >= 0; i--) {
    const f = state.flashes[i];
    if (now - f.t0 > FLASH_MS) { state.flashes.splice(i, 1); continue; }
    if (f.key === key) return { alpha: 1 - (now - f.t0) / FLASH_MS, x: f.x, y: f.y, color: f.color };
  }
  return null;
}

function drawFlash(key, c, radius) {
  const f = flashFor(key);
  if (!f) return;
  ctx.save();
  ctx.beginPath();
  ctx.arc(c.x, c.y, radius, 0, TAU);
  ctx.strokeStyle = withAlpha(f.color, f.alpha);
  ctx.lineWidth = GLYPH_HAIRLINE;
  ctx.stroke();
  ctx.restore();
}

// Diffs consecutive snapshots so a fresh incident or a fresh blockage reveal is
// acknowledged once. The first snapshot of a session only seeds the seen sets —
// otherwise every call in the run would flash at once on connect.
function noteSnapshot(snap) {
  if (!snap) return;
  const seenInc = state.seenIncidents || (state.seenIncidents = new Set());
  const seenBlk = state.seenBlockages || (state.seenBlockages = new Set());

  for (const inc of snap.incidents || []) {
    if (seenInc.has(inc.id)) continue;
    seenInc.add(inc.id);
    const node = state.nodes.get(inc.node);
    if (node) pushFlash(`inc:${inc.id}`, severityColor(inc.severity), node[0], node[1]);
  }

  const revealed = (snap.blockages && snap.blockages.revealed) || [];
  for (const edge of revealed) {
    const key = `blk:${edge[0]}|${edge[1]}`;
    if (seenBlk.has(key)) continue;
    seenBlk.add(key);
    const a = state.nodes.get(edge[0]);
    const b = state.nodes.get(edge[1]);
    if (a && b) {
      pushFlash(key, severityColor(4), (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
    }
  }
}

function animPos(a) {
  const anim = state.anim[a.id];
  if (!anim) return { x: a.x, y: a.y };
  if (state.reducedMotion) {
    delete state.anim[a.id];
    return { x: a.x, y: a.y };
  }
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

function paint() {
  const { w: cssW, h: cssH } = getViewportCssSize();
  if (canvas.width < 10 || canvas.height < 10) resize();
  if (!state.map || !state.world) return;

  const hint = document.getElementById("map-hint");
  if (hint) hint.classList.add("hidden");

  const map = getMapPalette();
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = map.bg;
  ctx.fillRect(0, 0, cssW, cssH);

  drawZones();
  drawEdges();
  drawBlockages();
  drawStations();
  drawHospitals();
  drawIncidents();
  drawAmbulances();
}

function forceFrame() {
  try { paint(); } catch (e) { /* transient resize race */ }
}

function startRenderLoop() {
  if (state.isRendering) return;
  state.isRendering = true;

  function frame() {
    paint();
    requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);
}

// Shared glyph painters. The legend reuses the same geometry so a swatch is
// never a loose approximation of what the map draws.

// One flat 1px edge, and only where it earns its place. On the light theme a
// white edge is a legibility aid for fills that would otherwise sit within 3:1
// of the road, never decoration; on dark the fill stands on its own and gets
// no halo at all.
function glyphEdge(fill) {
  if (!tokens.isLight) return null;
  const map = getMapPalette();
  const f = parseColor(fill);
  const r = parseColor(map.road);
  if (!f || !r) return null;
  return contrast(f, r) < 3 ? map.halo : null;
}

// Detail drawn on top of a marker (the on-scene tick, the blocked cross) knocks
// out in the map's own background colour: a flat cut-out, not a white bloom.
function glyphCut() {
  return getMapPalette().bg;
}

function drawSeverityGlyph(cx, cy, sev, color, ring, scale = 1) {
  const pts = SEVERITY_SHAPE[sev] || SEVERITY_SHAPE[5];
  ctx.save();
  ctx.translate(cx, cy);
  if (scale !== 1) ctx.scale(scale, scale);
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  if (ring) {
    ctx.strokeStyle = ring;
    ctx.lineWidth = GLYPH_HAIRLINE;
    ctx.lineJoin = "round";
    ctx.stroke();
  }
  ctx.restore();
}

function drawUnitGlyph(cx, cy, status, r, edge) {
  const col = statusColor(status);
  const kind = STATUS_RING[status === "onscene" ? "on_scene" : status] || "solid";
  const g = UNIT_GLYPH;
  const cut = glyphCut();
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, TAU);
  ctx.fillStyle = col;
  ctx.fill();
  if (edge) {
    ctx.strokeStyle = edge;
    ctx.lineWidth = g.body.w;
    ctx.stroke();
  }

  ctx.lineWidth = g.body.w;
  if (kind === "halo") {
    ctx.beginPath();
    ctx.arc(cx, cy, g.halo.r * r, 0, TAU);
    ctx.strokeStyle = col;
    ctx.stroke();
  } else if (kind === "outer-ring") {
    ctx.beginPath();
    ctx.arc(cx, cy, g.outerRing.r * r, 0, TAU);
    ctx.strokeStyle = col;
    ctx.lineWidth = g.outerRing.w;
    ctx.stroke();
  } else if (kind === "ring") {
    ctx.beginPath();
    ctx.arc(cx, cy, g.ring.r * r, 0, TAU);
    ctx.strokeStyle = col;
    ctx.lineWidth = g.ring.w;
    ctx.stroke();
  } else if (kind === "dashed") {
    ctx.beginPath();
    ctx.arc(cx, cy, g.dashed.r * r, 0, TAU);
    ctx.strokeStyle = col;
    ctx.lineWidth = g.dashed.w;
    ctx.setLineDash(g.dashed.dash.map((d) => d * r));
    ctx.stroke();
    ctx.setLineDash([]);
  } else if (kind === "tick") {
    ctx.beginPath();
    ctx.moveTo(cx, cy - g.tick.from * r);
    ctx.lineTo(cx, cy - g.tick.to * r);
    ctx.strokeStyle = cut;
    ctx.lineWidth = g.tick.w;
    ctx.lineCap = "round";
    ctx.stroke();
  } else if (kind === "cross") {
    const d = g.cross.d * r;
    ctx.beginPath();
    ctx.moveTo(cx - d, cy - d);
    ctx.lineTo(cx + d, cy + d);
    ctx.moveTo(cx + d, cy - d);
    ctx.lineTo(cx - d, cy + d);
    ctx.strokeStyle = cut;
    ctx.lineWidth = g.cross.w;
    ctx.lineCap = "round";
    ctx.stroke();
  }
  ctx.restore();
}

function drawZones() {
  const map = getMapPalette();
  (state.map.zones || []).forEach((z) => {
    const c = worldToScreen(z.center[0], z.center[1]);
    const r = 46;
    // One flat neutral wash plus a hairline boundary — no radial falloff, so
    // the zones read as regions instead of light sources.
    ctx.beginPath();
    ctx.arc(c.x, c.y, r, 0, TAU);
    ctx.fillStyle = withAlpha(map.zone, map.zoneAlpha);
    ctx.fill();
    ctx.strokeStyle = withAlpha(map.zone, ZONE_EDGE_ALPHA);
    ctx.lineWidth = GLYPH_HAIRLINE;
    ctx.stroke();
    ctx.fillStyle = map.zoneLabel;
    ctx.font = mapFont(null, 9);
    ctx.textAlign = "center";
    ctx.fillText(z.label || z.id, c.x, c.y + 3);
  });
}

function drawEdges() {
  const map = getMapPalette();
  ctx.strokeStyle = map.road;
  ctx.lineWidth = 1.2;
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
  ctx.fillStyle = map.node;
  for (const [nid, pos] of state.nodes) {
    const p = worldToScreen(pos[0], pos[1]);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 1.8, 0, TAU);
    ctx.fill();
  }
}

function drawBlockages() {
  if (!state.snap || !state.snap.blockages) return;
  const known = severityColor(4);
  const hidden = tone("dim");
  const mark = (edge, color, dashed) => {
    const a = state.nodes.get(edge[0]), b = state.nodes.get(edge[1]);
    if (!a || !b) return;
    const p = worldToScreen(a[0], a[1]);
    const q = worldToScreen(b[0], b[1]);
    const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(dashed ? [4, 4] : []);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(mx - 5, my - 5); ctx.lineTo(mx + 5, my + 5);
    ctx.moveTo(mx + 5, my - 5); ctx.lineTo(mx - 5, my + 5);
    ctx.stroke();
    ctx.restore();
  };
  for (const e of state.snap.blockages.revealed) {
    mark(e, known, false);
    // A reveal acknowledges once with a single static ring that fades out; it
    // never expands, repeats, or rings twice.
    const mid = edgeMidpoint(e);
    if (mid) drawFlash(`blk:${e[0]}|${e[1]}`, mid, BLOCKAGE_FLASH_RADIUS);
  }
  for (const e of state.snap.blockages.hidden) mark(e, hidden, true);
}

// Screen-space midpoint of a road edge, for the blockage acknowledgement ring.
function edgeMidpoint(edge) {
  const a = state.nodes.get(edge[0]);
  const b = state.nodes.get(edge[1]);
  if (!a || !b) return null;
  const p = worldToScreen(a[0], a[1]);
  const q = worldToScreen(b[0], b[1]);
  return { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 };
}

// --------------------------------------------------------------------------- //
// Distinct Stations (Garage Depot) vs Hospitals (Medical Cross)               //
// --------------------------------------------------------------------------- //

function drawStations() {
  const map = getMapPalette();
  const roof = facilityColor("station");
  const roofDark = facilityEdge("station");
  const door = shade(roofDark, 0.28);
  const shutter = withAlpha(roof, tokens.isLight ? 0.6 : 0.8);
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
    ctx.fillStyle = roof;
    ctx.strokeStyle = roofDark;
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
    ctx.fillStyle = door;
    ctx.strokeStyle = shutter;
    ctx.lineWidth = 0.8;
    rr(c.x - 5, c.y + 1, 10, 8, 1);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(c.x - 5, c.y + 3.5); ctx.lineTo(c.x + 5, c.y + 3.5);
    ctx.moveTo(c.x - 5, c.y + 6); ctx.lineTo(c.x + 5, c.y + 6);
    ctx.stroke();

    // 4. Clustered idle units parked at the station
    idleAt.forEach((a, i) => {
      const ang = (TAU * i) / Math.max(1, idleAt.length) - Math.PI / 2;
      drawUnitGlyph(c.x + Math.cos(ang) * 17, c.y + Math.sin(ang) * 17,
        a.status, 4.5, glyphEdge(statusColor(a.status)));
    });

    // 5. Clear Station Label
    ctx.fillStyle = meetContrast(roof, map.bg, 4.5);
    ctx.font = mapFontSans(600, 9.5);
    ctx.textAlign = "center";
    ctx.fillText(`${st.id} · ${idleAt.length}`, c.x, c.y + 24);
    ctx.restore();
  }
}

function drawHospitals() {
  const map = getMapPalette();
  const body = facilityColor("hospital");
  const edge = shade(body, tokens.isLight ? 0.3 : 0.4);
  for (const h of state.map.hospitals) {
    const coords = state.nodes.get(h.node);
    if (!coords) continue;
    const c = worldToScreen(...coords);
    ctx.save();
    // 1. Hospital building (medical cyan rounded square)
    ctx.fillStyle = body;
    ctx.strokeStyle = edge;
    ctx.lineWidth = 1.5;
    rr(c.x - 9, c.y - 9, 18, 18, 3.5);
    ctx.fill();
    ctx.stroke();

    // 2. Bold emergency medical cross (+)
    ctx.strokeStyle = map.onFill;
    ctx.lineWidth = 2.4;
    ctx.lineCap = "square";
    ctx.beginPath();
    ctx.moveTo(c.x - 5, c.y); ctx.lineTo(c.x + 5, c.y);
    ctx.moveTo(c.x, c.y - 5); ctx.lineTo(c.x, c.y + 5);
    ctx.stroke();

    // 3. Clear Hospital & Bed Occupancy / Completed Label
    ctx.fillStyle = meetContrast(body, map.bg, 4.5);
    ctx.font = mapFont(600, 9);
    ctx.textAlign = "center";
    const isFin = state.run && state.run.finished;
    const served = Number(h.patients_served) || 0;
    const labelText = isFin && served > 0
      ? `${h.id} [${served} served]`
      : `${h.id} [${h.in_use}/${h.beds}]`;
    ctx.fillText(labelText, c.x, c.y - 14);
    ctx.restore();
  }
}

const INCIDENT_STATUS_TONE = {
  pending: null,
  assigned: "enroute",
  enroute: "enroute",
  on_scene: "transporting",
  transporting: "transporting",
};

function drawIncidents() {
  if (!state.snap) return;
  const map = getMapPalette();
  for (const inc of state.snap.incidents) {
    if (inc.status === "cleared") continue;
    const coords = state.nodes.get(inc.node);
    if (!coords) continue;
    const c = worldToScreen(...coords);
    const col = severityColor(inc.severity);
    ctx.save();

    // Pending: one static hairline ring. The only motion a call ever gets is
    // the single 1.2s acknowledgement below — no repeating pulse.
    if (inc.status === "pending") {
      ctx.beginPath();
      ctx.arc(c.x, c.y, 11, 0, TAU);
      ctx.strokeStyle = withAlpha(col, 0.5);
      ctx.lineWidth = GLYPH_HAIRLINE;
      ctx.stroke();
    }

    // Severity body: S3 triangle, S4 diamond, S5 star
    drawSeverityGlyph(c.x, c.y, inc.severity, col, glyphEdge(col));

    // A brand-new call acknowledges once, then the ring is gone.
    drawFlash(`inc:${inc.id}`, c, FLASH_RADIUS);

    // Status ring for active incidents
    const ringTone = INCIDENT_STATUS_TONE[inc.status];
    if (ringTone) {
      ctx.beginPath();
      ctx.arc(c.x, c.y, 11, 0, TAU);
      ctx.strokeStyle = tokens.status[ringTone];
      ctx.lineWidth = GLYPH_HAIRLINE;
      ctx.stroke();
    }

    ctx.fillStyle = meetContrast(col, map.bg, 4.5);
    ctx.font = mapFont("bold", 9);
    ctx.textAlign = "center";
    ctx.fillText(`S${inc.severity}`, c.x, c.y - 14);
    ctx.restore();
  }
}

function drawAmbulances() {
  if (!state.snap) return;
  const map = getMapPalette();
  for (const a of state.snap.ambulances) {
    if (a.status === "idle" || a.status === "drifting") {
      if (a.station) continue; // Parked units rendered at home station
    }
    const pos = animPos(a);
    const c = worldToScreen(pos.x, pos.y);
    const col = statusColor(a.status);
    const moving = a.status !== "idle" && a.status !== "drifting";
    ctx.save();

    // Planned route: a static 1px dashed line.
    // Suppress routes for returning/transporting/idle units to eliminate visual clutter.
    // Only show planned route for active emergency response ("enroute") or hovered unit.
    const isHovered = state.hover && state.hover.type === "amb" && state.hover.id === a.id;
    if (a.route && a.route.length > 1 && (a.status === "enroute" || isHovered)) {
      const routePoints = [];
      for (const nid of a.route) {
        const n = state.nodes.get(nid);
        if (!n || !Number.isFinite(n[0]) || !Number.isFinite(n[1])) continue;
        const p = worldToScreen(n[0], n[1]);
        if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) {
          routePoints.push(p);
        }
      }

      const validPoints = [];
      if (routePoints.length >= 2) {
        const p0 = routePoints[0];
        const p1 = routePoints[1];
        // Only connect from ambulance position c if it is colinear with the edge (no diagonal cut)
        const isHoriz = Math.abs(p0.y - p1.y) < 3 && Math.abs(c.y - p0.y) < 6;
        const isVert = Math.abs(p0.x - p1.x) < 3 && Math.abs(c.x - p0.x) < 6;
        if (isHoriz || isVert) {
          validPoints.push({ x: c.x, y: c.y });
          for (let i = 1; i < routePoints.length; i++) {
            validPoints.push(routePoints[i]);
          }
        } else {
          validPoints.push(...routePoints);
        }
      } else if (routePoints.length === 1) {
        validPoints.push(...routePoints);
      }

      if (validPoints.length > 1) {
        ctx.strokeStyle = withAlpha(col, ROUTE_ALPHA);
        ctx.lineWidth = ROUTE_LINE_W;
        ctx.setLineDash([3, 4]);
        ctx.beginPath();
        ctx.moveTo(validPoints[0].x, validPoints[0].y);
        for (let i = 1; i < validPoints.length; i++) {
          const prev = validPoints[i - 1];
          const curr = validPoints[i];
          if (Math.hypot(curr.x - prev.x, curr.y - prev.y) > Math.max(canvas.width, canvas.height) * 0.5) {
            break;
          }
          ctx.lineTo(curr.x, curr.y);
        }
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // Motion trail: a thin 1px polyline fading toward the tail. Nothing else
    // about a moving unit is allowed to bloom.
    if (moving) drawTrail(a, col);

    drawUnitGlyph(c.x, c.y, a.status, 7, glyphEdge(col));

    if (moving) {
      ctx.fillStyle = map.label;
      ctx.font = mapFont(null, 8);
      ctx.textAlign = "center";
      const tag = a.algorithm === "astar" ? "A*" : a.algorithm;
      ctx.fillText(tag, c.x, c.y - 11);
      ctx.fillStyle = map.labelMuted;
      ctx.fillText(a.id, c.x, c.y + 16);
    }
    ctx.restore();
  }
}

// One flat 1px polyline per unit, alpha stepping down toward the tail. Under
// reduced motion the trail list is never filled, so nothing is drawn at all.
function drawTrail(a, col) {
  const pts = state.trail[a.id];
  if (!pts || pts.length < 2) return;
  ctx.lineWidth = 1;
  ctx.lineCap = "butt";
  const n = pts.length;
  for (let i = 1; i < n; i++) {
    const p0 = pts[i - 1];
    const p1 = pts[i];
    if (!p0 || !p1 || !Number.isFinite(p0.x) || !Number.isFinite(p0.y) ||
        !Number.isFinite(p1.x) || !Number.isFinite(p1.y)) continue;
    if (Math.hypot(p1.x - p0.x, p1.y - p0.y) > 8.0) continue;
    const p = worldToScreen(p0.x, p0.y);
    const q = worldToScreen(p1.x, p1.y);
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y) ||
        !Number.isFinite(q.x) || !Number.isFinite(q.y)) continue;
    if (Math.hypot(q.x - p.x, q.y - p.y) > Math.max(canvas.width, canvas.height) * 0.5) continue;
    ctx.strokeStyle = withAlpha(col, TRAIL_HEAD_ALPHA * ((i - 1) / (n - 1)));
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(q.x, q.y);
    ctx.stroke();
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
        tone: "orange",
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
        tone: "ops",
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
        tone: "station",
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
        tone: "hospital",
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
      const ang = (TAU * i) / Math.max(1, parked.length) - Math.PI / 2;
      const px = c.x + Math.cos(ang) * 17;
      const py = c.y + Math.sin(ang) * 17;
      if (near({ x: px, y: py }, 6)) {
        return {
          title: `AMBULANCE: ${a.id} (Parked at ${st.id})`,
          tone: "ops",
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
  box.innerHTML = `<div class="font-bold mb-1 val" style="color:${tone(hit.tone)}">${hit.title}</div>` +
    hit.lines.filter(Boolean)
      .map((l) => `<div class="text-[10.5px] leading-relaxed" style="color:${tone("ink")}">${l}</div>`).join("");
  box.classList.remove("hidden");
});

// --------------------------------------------------------------------------- //
// Legend — swatches are generated from the same glyph data the canvas uses    //
// --------------------------------------------------------------------------- //

const LEGEND_KEYS = [
  ["hospital", /(hospital|medical bed)/],
  ["station", /(station|garage|depot)/],
  ["sev3", /(sev(erity)?\s*-?\s*3)/],
  ["sev4", /(sev(erity)?\s*-?\s*4)/],
  ["sev5", /(sev(erity)?\s*-?\s*5)/],
  ["idle", /\bidle/],
  ["drifting", /(drift|mdp positioning)/],
  ["enroute", /(en\s?route)/],
  ["onscene", /(on\s?scene)/],
  ["transporting", /transport/],
  ["returning", /return/],
  ["blocked", /block(?!age)/],
  ["blockageHidden", /(hidden|unknown|probabil)/],
  ["blockage", /blockage/],
  ["route", /(active route|planned route)/],
  ["road", /(road edge|edge)/],
];

function legendKey(text) {
  const t = (text || "").toLowerCase();
  for (const [key, re] of LEGEND_KEYS) {
    if (re.test(t)) return key;
  }
  return null;
}

// The swatches are generated at a smaller scale than the map, so a CSS-pixel
// hairline is scaled up by the viewBox factor to stay 1px on screen.
function swatchScale(size) {
  return 23.2 / Math.max(1, size);
}

function severitySvg(sev, color, ring, size = 18) {
  const pts = (SEVERITY_SHAPE[sev] || SEVERITY_SHAPE[5])
    .map((p) => `${(p[0] + 10).toFixed(2)},${(p[1] + 10).toFixed(2)}`).join(" ");
  const sw = (GLYPH_HAIRLINE * swatchScale(size)).toFixed(2);
  return `<svg width="${size}" height="${size}" viewBox="-1.6 -1.6 23.2 23.2" class="shrink-0" aria-hidden="true" focusable="false">`
    + `<polygon points="${pts}" fill="${color}"${ring ? ` stroke="${ring}" stroke-width="${sw}" stroke-linejoin="round"` : ""}/></svg>`;
}

function unitSvg(status, col, edge, size = 16) {
  const g = UNIT_GLYPH;
  const k = swatchScale(size);
  const r = UNIT_RADIUS_RATIO * size;
  const body = `<circle cx="10" cy="10" r="${r.toFixed(2)}" fill="${col}"`
    + (edge ? ` stroke="${edge}" stroke-width="${(g.body.w * k).toFixed(2)}"` : "") + "/>";
  const cut = glyphCut();
  let deco = "";
  const kind = STATUS_RING[status] || "solid";
  if (kind === "halo") {
    deco = `<circle cx="10" cy="10" r="${(g.halo.r * r).toFixed(2)}" fill="none" stroke="${col}" stroke-width="${(g.halo.w * k).toFixed(2)}"/>`;
  } else if (kind === "outer-ring") {
    deco = `<circle cx="10" cy="10" r="${(g.outerRing.r * r).toFixed(2)}" fill="none" stroke="${col}" stroke-width="${(g.outerRing.w * k).toFixed(2)}"/>`;
  } else if (kind === "ring") {
    deco = `<circle cx="10" cy="10" r="${(g.ring.r * r).toFixed(2)}" fill="none" stroke="${col}" stroke-width="${(g.ring.w * k).toFixed(2)}"/>`;
  } else if (kind === "dashed") {
    deco = `<circle cx="10" cy="10" r="${(g.dashed.r * r).toFixed(2)}" fill="none" stroke="${col}" stroke-width="${(g.dashed.w * k).toFixed(2)}" stroke-dasharray="${g.dashed.dash.map((d) => (d * r).toFixed(2)).join(" ")}"/>`;
  } else if (kind === "tick") {
    deco = `<path d="M10 ${(10 - g.tick.from * r).toFixed(2)} L10 ${(10 - g.tick.to * r).toFixed(2)}" stroke="${cut}" stroke-width="${(g.tick.w * k).toFixed(2)}" stroke-linecap="round"/>`;
  } else if (kind === "cross") {
    const d = g.cross.d * r;
    const lo = (10 - d).toFixed(2), hi = (10 + d).toFixed(2);
    deco = `<path d="M${lo} ${lo} L${hi} ${hi} M${hi} ${lo} L${lo} ${hi}"`
      + ` stroke="${cut}" stroke-width="${(g.cross.w * k).toFixed(2)}" stroke-linecap="round" fill="none"/>`;
  }
  return `<svg width="${size}" height="${size}" viewBox="-1.6 -1.6 23.2 23.2" class="shrink-0" aria-hidden="true" focusable="false">${deco}${body}</svg>`;
}

function facilitySvg(kind, size = 18) {
  const map = getMapPalette();
  if (kind === "station") {
    const base = facilityColor("station");
    const edge = facilityEdge("station");
    const door = shade(edge, 0.28);
    return `<svg width="${size}" height="${size}" viewBox="0 0 20 20" class="shrink-0" aria-hidden="true" focusable="false">`
      + `<path d="M2 9 L10 2 L18 9" fill="${base}" stroke="${edge}" stroke-width="1.2" stroke-linejoin="round"/>`
      + `<rect x="3" y="9" width="14" height="9" rx="1" fill="${base}" stroke="${edge}" stroke-width="1.2"/>`
      + `<rect x="7" y="11" width="6" height="7" rx="0.5" fill="${door}"/>`
      + `<line x1="7" y1="13" x2="13" y2="13" stroke="${withAlpha(base, tokens.isLight ? 0.6 : 0.8)}" stroke-width="0.8"/>`
      + `<line x1="7" y1="15" x2="13" y2="15" stroke="${withAlpha(base, tokens.isLight ? 0.6 : 0.8)}" stroke-width="0.8"/></svg>`;
  }
  const base = facilityColor("hospital");
  const edge = facilityEdge("hospital");
  return `<svg width="${size}" height="${size}" viewBox="0 0 20 20" class="shrink-0" aria-hidden="true" focusable="false">`
    + `<rect x="2" y="2" width="16" height="16" rx="3" fill="${base}" stroke="${edge}" stroke-width="1.2"/>`
    + `<path d="M10 5.5 v9 M5.5 10 h9" stroke="${map.onFill}" stroke-width="2.6" stroke-linecap="square"/></svg>`;
}

function lineSvg(kind, size = 18) {
  const map = getMapPalette();
  if (kind === "road") {
    return `<svg width="${size}" height="${size - 4}" viewBox="0 0 20 16" class="shrink-0" aria-hidden="true" focusable="false">`
      + `<line x1="2" y1="8" x2="18" y2="8" stroke="${map.road}" stroke-width="2.5"/>`
      + `<circle cx="3" cy="8" r="1.5" fill="${map.node}"/><circle cx="17" cy="8" r="1.5" fill="${map.node}"/></svg>`;
  }
  if (kind === "route") {
    return `<svg width="${size}" height="${size - 4}" viewBox="0 0 20 16" class="shrink-0" aria-hidden="true" focusable="false">`
      + `<line x1="2" y1="8" x2="18" y2="8" stroke="${tone("ink")}" stroke-width="2" stroke-dasharray="3 2"/></svg>`;
  }
  const col = kind === "blockage" ? severityColor(4) : tone("dim");
  const dash = kind === "blockage" ? "" : ` stroke-dasharray="3 2"`;
  return `<svg width="${size}" height="${size - 4}" viewBox="0 0 20 16" class="shrink-0" aria-hidden="true" focusable="false">`
    + `<line x1="2" y1="8" x2="18" y2="8" stroke="${col}" stroke-width="2.5"${dash}/>`
    + `<path d="M7 4 L13 12 M13 4 L7 12" stroke="${col}" stroke-width="1.8"/></svg>`;
}

function legendSwatch(key) {
  switch (key) {
    case "station":
    case "hospital":
      return facilitySvg(key);
    case "sev3":
      return severitySvg(3, severityColor(3), glyphEdge(severityColor(3)));
    case "sev4":
      return severitySvg(4, severityColor(4), glyphEdge(severityColor(4)));
    case "sev5":
      return severitySvg(5, severityColor(5), glyphEdge(severityColor(5)));
    case "idle":
      return unitSvg("idle", statusColor("idle"), glyphEdge(statusColor("idle")));
    case "drifting":
      return unitSvg("drifting", statusColor("drifting"), glyphEdge(statusColor("drifting")));
    case "enroute":
      return unitSvg("enroute", statusColor("enroute"), glyphEdge(statusColor("enroute")));
    case "onscene":
      return unitSvg("on_scene", statusColor("on_scene"), glyphEdge(statusColor("on_scene")));
    case "transporting":
      return unitSvg("transporting", statusColor("transporting"), glyphEdge(statusColor("transporting")));
    case "returning":
      return unitSvg("returning", statusColor("returning"), glyphEdge(statusColor("returning")));
    case "blocked":
      return unitSvg("blocked", statusColor("blocked"), glyphEdge(statusColor("blocked")));
    default:
      return lineSvg(key);
  }
}

// Maps a legacy hard-coded text colour onto the current semantic tone so no
// dark-only hex survives a theme switch, whichever build wrote the markup.
const LEGACY_TEXT_TONE = {
  "#e2e8f0": "ink", "#cbd5e1": "ink", "#c7d2fe": "ink", "#67e8f9": "hospital",
  "#8899b5": "muted", "#546682": "dim", "#38bdf8": "ops", "#22d3ee": "ops",
  "#818cf8": "station", "#4338ca": "station", "#06b6d4": "hospital",
  "#0e7490": "hospital", "#34d399": "ok", "#047857": "ok", "#fbbf24": "warn",
  "#a16207": "warn", "#fb923c": "orange", "#c2410c": "orange", "#f43f5e": "alert",
  "#be123c": "alert", "#a78bfa": "violet", "#6d28d9": "violet", "#c084fc": "gini",
  "#e879f9": "reneg", "#94a3b8": "muted", "#64748b": "muted",
};

function rethemeLegacy(root) {
  if (!root || !document.createTreeWalker) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const el of nodes) {
    for (const cls of el.classList) {
      const m = /^text-\[(#[0-9a-fA-F]{3,8})\]$/.exec(cls);
      if (!m) continue;
      const key = LEGACY_TEXT_TONE[m[1].toLowerCase()];
      if (key) el.style.color = tone(key);
      break;
    }
  }
}

function renderLegend() {
  const root = document.getElementById("legend-content");
  if (!root) return;
  const targets = Array.prototype.slice.call(root.querySelectorAll("svg, span[data-swatch]"));
  for (const node of targets) {
    const row = node.parentElement;
    if (!row) continue;
    const key = legendKey(row.textContent);
    if (!key) continue;
    const holder = document.createElement("span");
    holder.className = "shrink-0 inline-flex";
    holder.dataset.swatch = key;
    holder.innerHTML = legendSwatch(key);
    node.replaceWith(holder);
  }
}

// --------------------------------------------------------------------------- //
// Panels & Telemetry                                                          //
// --------------------------------------------------------------------------- //

function toneStyle(key) {
  return `style="color:${tone(key)}"`;
}

function val(key, text, extra = "") {
  return `<span class="val val-${key}${extra ? ` ${extra}` : ""}" ${toneStyle(key)}>${text}</span>`;
}

function word(text, key = "muted", cls = "") {
  return `<span class="${cls}" ${toneStyle(key)}>${text}</span>`;
}

const KPI_DEFS = [
  { id: "calls", label: "CALLS REPORTED", tone: "ink" },
  { id: "cleared", label: "CLEARED", tone: "ok" },
  { id: "active", label: "ACTIVE", tone: "warn" },
  { id: "queued", label: "QUEUED", tone: "alert" },
  { id: "resp_avg", label: "RESP AVG", tone: "ops" },
  { id: "resp_p95", label: "RESP P95", tone: "ink" },
  { id: "dist", label: "DISTANCE", tone: "ink" },
  { id: "replans", label: "REPLANS", tone: "station" },
  { id: "gini", label: "EQUITY GINI", tone: "gini" },
  { id: "replan_saved", label: "REPLAN SAVED", tone: "ops" },
  { id: "reneg", label: "RENEGOTIATED", tone: "reneg" },
  { id: "reneg_saved", label: "RENEG SAVED", tone: "reneg" },
];

function statCard(label, value, toneKey, id = "") {
  const t = toneKey || "ink";
  return `<div class="kpi" data-kpi-id="${id}" role="group" aria-label="${label}: ${value}">
      <div class="text-[9px] tracking-widest uppercase font-bold text-muted">${label}</div>
      <div class="mono text-[15px] font-bold val val-${t}" data-kpi-val style="color:${tone(t)}">${value}</div>
    </div>`;
}

function renderStats(snap) {
  const st = snap.stats;
  const sc = state.scenarios.find((x) => x.id === snap.scenario.name);
  updateFleetSummary(sc);
  const clockEl = document.getElementById("clock");
  if (clockEl) {
    clockEl.textContent = `t ${snap.tick} · ${snap.seconds}s`;
  }

  const container = document.getElementById("stats-cards");
  if (container) {
    const kpiValues = [
      { id: "calls", val: String(st.incidents_reported), tone: "ink" },
      { id: "cleared", val: String(st.incidents_cleared), tone: "ok" },
      { id: "active", val: String(st.active), tone: st.active ? "warn" : "ink" },
      { id: "queued", val: String(st.queue), tone: st.queue ? "alert" : "ink" },
      { id: "resp_avg", val: `${st.response_avg.toFixed(1)}s`, tone: "ops" },
      { id: "resp_p95", val: `${st.response_p95.toFixed(1)}s`, tone: "ink" },
      { id: "dist", val: `${st.total_distance_km.toFixed(0)} km`, tone: "ink" },
      { id: "replans", val: String(st.replans), tone: "station" },
      { id: "gini", val: st.equity?.gini != null ? st.equity.gini.toFixed(3) : "—", tone: "gini" },
      { id: "replan_saved", val: `${st.replan_savings_expansions ?? 0} exp`, tone: "ops" },
      { id: "reneg", val: String(st.renegotiations ?? 0), tone: "reneg" },
      { id: "reneg_saved", val: `${(st.renegotiation_savings_s ?? 0).toFixed(0)}s`, tone: "reneg" },
    ];

    if (!container.dataset.inited || container.children.length !== kpiValues.length) {
      container.innerHTML = kpiValues.map((k, idx) => {
        const def = KPI_DEFS[idx];
        return statCard(def.label, k.val, k.tone, k.id);
      }).join("");
      container.dataset.inited = "true";
    } else {
      const cards = container.children;
      for (let i = 0; i < kpiValues.length; i++) {
        const card = cards[i];
        const item = kpiValues[i];
        const valEl = card.querySelector("[data-kpi-val]");
        if (valEl && valEl.textContent !== item.val) {
          valEl.textContent = item.val;
          card.setAttribute("aria-label", `${KPI_DEFS[i].label}: ${item.val}`);
          const newColor = tone(item.tone);
          if (valEl.style.color !== newColor) {
            valEl.style.color = newColor;
            valEl.className = `mono text-[15px] font-bold val val-${item.tone}`;
          }
        }
      }
    }
  }

  renderFairness(snap);

  const ex = st.search_expansions;
  const maxExp = Math.max(1, ...Object.values(ex));
  const expBox = document.getElementById("expansion-bars");
  if (expBox) {
    expBox.innerHTML =
      Object.entries(ex).map(([k, v]) => `
        <div class="flex items-center gap-2">
          <span class="mono w-14 text-[10px] uppercase" ${toneStyle("muted")}>${k}</span>
          <div class="flex-1 h-2 rounded overflow-hidden" style="background:var(--surface)">
            <div class="h-full" style="width:${(v / maxExp * 100).toFixed(1)}%;background:var(--ink, var(--text))"></div>
          </div>
          <span class="mono w-14 text-right text-[10px] font-medium" ${toneStyle("ink")}>${v}</span>
        </div>`).join("");
  }

  const modCounters = document.getElementById("module-counters");
  if (modCounters) {
    modCounters.innerHTML = `
      <div>${word("CSP", "muted")} &nbsp;${val("station", st.csp_solves)} solves ·
        ${val("station", st.csp_backtracks)} backtracks ·
        ${val("station", st.csp_nodes)} nodes</div>
      <div>${word("MDP", "muted")} ${val("ops", st.mdp_solves)} solves</div>
      <div>${word("Arena", "muted")} ${val("ok", st.arena_runs)} runs</div>`;
  }
}

function heatCell(hue) {
  return hslToRgb(hue, pct(tokens.heat.s), pct(tokens.heat.l));
}

// Picks the ink with the higher contrast; `ratio` feeds the cell tooltip.
function autoInk(bg) {
  let best = INK_ON_DARK, ratio = 0;
  for (const c of [INK_ON_DARK, INK_ON_LIGHT]) {
    const r = contrast(bg, parseColor(c));
    if (r > ratio) { ratio = r; best = c; }
  }
  return { color: best, ratio };
}

function renderFairness(snap) {
  const box = document.getElementById("fairness-box");
  const eq = snap.stats?.equity;
  if (!eq || !eq.per_zone || !Object.keys(eq.per_zone).length) {
    box.innerHTML =
      `<div class="text-[10px] py-3 text-center" ${toneStyle("dim")}>No zone response data yet…</div>`;
    return;
  }
  const rows = Object.entries(eq.per_zone)
    .map(([z, m]) => ({ z, ...m }))
    .sort((a, b) => (a.mean || 0) - (b.mean || 0));
  const maxMean = Math.max(1, ...rows.map((r) => r.mean || 0));
  const best = eq.best_zone, worst = eq.worst_zone;
  const border = `1px solid var(--border)`;
  const heat = rows.map((r) => {
    const hue = Math.round(125 * (1 - (r.mean || 0) / maxMean));
    const cell = heatCell(hue);
    const bg = `hsl(${hue}, ${tokens.heat.s}, ${tokens.heat.l})`;
    const ink = autoInk(cell);
    const label = `${r.z}: ${r.mean}s mean · ${r.p95}s p95 · ${r.n} call(s)`;
    return `<div role="img" aria-label="${label}" title="${label} · text contrast ${ink.ratio.toFixed(1)}:1"
        class="flex-1 h-7 rounded-[4px] flex items-center justify-center mono font-bold"
        style="background:${bg};color:${ink.color};border:${border};font-size:11.5px;line-height:1.05">
        <span aria-hidden="true">${r.z}</span>
      </div>`;
  }).join("");
  const list = rows.map((r) => {
    const tag = r.z === best ? `<span class="font-bold" ${toneStyle("ok")}> BEST</span>`
      : r.z === worst ? `<span class="font-bold" ${toneStyle("alert")}> WORST</span>` : "";
    return `<div class="flex justify-between items-center text-[10px] py-2" style="border-bottom:1px solid var(--border);opacity:.9">
        <span class="font-medium" ${toneStyle("ink")}>${r.z}${tag}</span>
        <span ${toneStyle("muted")}>${r.n} call(s) · ${r.mean}s mean · ${r.p95}s p95</span>
      </div>`;
  }).join("");
  box.innerHTML = `
    <div class="flex items-center justify-between py-1">
      ${val("gini", `Gini ${eq.gini.toFixed(3)}`, "font-bold")}
      ${word(`served ${eq.served_zones}/${eq.zones} zone(s) · max/min ${eq.max_min_ratio != null ? eq.max_min_ratio.toFixed(2) : "—"}×`, "muted")}
    </div>
    <div class="flex gap-1 py-1" role="list" aria-label="Zone response time heat strip">${heat}</div>
    ${list}`;
}

function renderExplainability(snap) {
  const arena = document.getElementById("arena-box");
  if (snap.arena && snap.arena.results && Object.keys(snap.arena.results).length) {
    const q = snap.arena.query || {};
    const rows = Object.entries(snap.arena.results).map(([algo, r]) => `
      <tr style="border-top:1px solid var(--border)">
        <td class="py-2 uppercase text-[10px] font-medium" ${toneStyle("ink")}>${algo}</td>
        <td class="text-right text-[10px] py-2" ${toneStyle("muted")}>${r.cost?.toFixed(1) ?? "—"}</td>
        <td class="text-right text-[10px] py-2" ${toneStyle("muted")}>${r.nodes_expanded}</td>
        <td class="text-right text-[10px] py-2" ${toneStyle("muted")}>${r.duration_ms?.toFixed(1)}ms</td>
        <td class="text-right text-[10px] py-2 font-bold" ${toneStyle("ok")}>${r.optimal ? "✓" : "—"}</td>
      </tr>`).join("");
    arena.innerHTML = `
      <div class="text-[10px] mb-2 font-medium" ${toneStyle("muted")}>Run #${snap.arena.run}
        — ${q.from ?? ""} → ${q.to ?? ""} (${q.incident ?? ""})</div>
      <table class="w-full text-[10px]">
        <tr ${toneStyle("dim")} style="border-bottom:1px solid var(--border)">
          <td class="py-2">ALGO</td><td class="text-right py-2">COST</td>
          <td class="text-right py-2">EXPANDED</td><td class="text-right py-2">TIME</td>
          <td class="text-right py-2">OPT</td></tr>
        ${rows}
      </table>`;
  } else {
    arena.innerHTML = `<div class="text-[10px] py-4 text-center" ${toneStyle("dim")}>Waiting for a dispatch route…</div>`;
  }

  const mdp = document.getElementById("mdp-box");
  if (snap.mdp && snap.mdp.policy && Object.keys(snap.mdp.policy).length) {
    const rows = Object.entries(snap.mdp.policy).map(([z, target]) => `
      <div class="flex justify-between text-[10px] py-2" style="border-bottom:1px solid var(--border);opacity:.9">
        <span class="font-medium" ${toneStyle("muted")}>${z}</span>
        <span ${toneStyle("ink")}>${z === target ? "stay" : `→ ${target}`}
          <span class="ml-1" ${toneStyle("dim")}>V=${snap.mdp.values[z]?.toFixed(2)}</span></span>
      </div>`).join("");
    mdp.innerHTML = `
      <div class="text-[10px] mb-2 font-medium" ${toneStyle("muted")}>Value Iteration —
        ${snap.mdp.iterations} sweeps, ε=${snap.mdp.final_residual?.toExponential(1)}
        ${snap.mdp.converged ? "· converged" : ""}</div>
      ${rows}`;
  } else {
    mdp.innerHTML = `<div class="text-[10px] py-4 text-center" ${toneStyle("dim")}>No idle-positioning computed yet…</div>`;
  }

  const dec = document.getElementById("decisions");
  const rowCls = state.reducedMotion ? "flex gap-1.5 items-start py-0.5"
    : "feed-item flex gap-1.5 items-start py-0.5";
  const items = snap.recent_decisions.slice(-12).reverse().map((evt) => `
    <div class="${rowCls}">
      <span class="w-8 shrink-0 text-[10px] mono" ${toneStyle("dim")}>t${evt.tick}</span>
      <span class="rounded px-1.5 ${badgeClass(evt.kind)} text-[8.5px] leading-4 shrink-0 font-medium">${evt.kind}</span>
      <span class="text-[10.5px]" ${toneStyle("ink")}>${evt.summary}</span>
    </div>`).join("");
  dec.innerHTML = items || `<div class="text-center py-4" ${toneStyle("dim")}>No decisions recorded yet.</div>`;
  document.getElementById("dec-count").textContent =
    Math.min(snap.recent_decisions.length, 12);
}

// Re-colours the chrome that app.js did not generate, so a theme switch never
// leaves a hard-coded dark-only hex behind.
const ACCENT_IDS = {
  "speed-val": "ops", "rotation-label": "ops",
  "gini-count": "gini", "dec-count": "ops", "evt-count": "ops",
  "bench-status": "ops",
};
const MUTED_IDS = ["fleet-summary", "clock", "sim-name", "benchmark-box",
  "map-hint", "legend", "hover-info", "legend-toggle-label"];

function rethemePanels() {
  rethemeLegacy(document.body);
  for (const [id, key] of Object.entries(ACCENT_IDS)) {
    const el = document.getElementById(id);
    if (el) el.style.color = tone(key);
  }
  for (const id of MUTED_IDS) {
    const el = document.getElementById(id);
    if (el) el.style.color = tone("muted");
  }
  const hover = document.getElementById("hover-info");
  if (hover) hover.style.color = tone("ink");
  const hint = document.querySelector("#map-hint > div");
  if (hint) hint.style.color = tone("dim");
}

function queueEvents(events) {
  if (!events || !events.length) return;
  state.pendingEvents.push(...events);
  for (const evt of events) {
    if (evt.kind === "incident.reported") {
      announce(`New call reported. ${evt.summary || ""}`.trim());
    } else if (evt.kind === "world.blockage_detected") {
      announce(`Road blockage detected. ${evt.summary || ""}`.trim());
    }
  }
}

function flushPendingEvents() {
  if (!state.pendingEvents.length) return;
  const events = state.pendingEvents;
  state.pendingEvents = [];
  state.events.push(...events);
  if (state.events.length > 200) state.events = state.events.slice(-200);

  const box = document.getElementById("events");
  const frag = document.createDocumentFragment();
  const cls = state.reducedMotion ? "flex gap-1.5 items-start py-0.5"
    : "feed-item flex gap-1.5 items-start py-0.5";
  for (const evt of events) {
    const div = document.createElement("div");
    div.className = cls;
    div.innerHTML = `
      <span class="w-8 shrink-0 text-[10px] mono" ${toneStyle("dim")}>t${evt.tick}</span>
      <span class="rounded px-1.5 ${badgeClass(evt.kind)} text-[8.5px] leading-4 shrink-0 font-medium">${evt.kind}</span>
      <span class="text-[10.5px]" ${toneStyle("ink")}>${evt.summary}</span>`;
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
  if (state.replayTimer) clearInterval(state.replayTimer);
  state.replayTimer = setInterval(() => {
    if (state.replayIndex >= state.replayQueue.length) {
      clearInterval(state.replayTimer);
      state.replayTimer = null;
      state.replayQueue = [];
      state.replayIndex = 0;
      return;
    }
    const snap = state.replayQueue[state.replayIndex++];
    if (!snap) return;
    state.snap = snap;
    prepAnimation(snap);
    scheduleDomUpdate(snap);
  }, 90);
}
window.startReplayPlayback = startReplayPlayback;

// --------------------------------------------------------------------------- //
// Map Rotation Control                                                      //
// --------------------------------------------------------------------------- //

function initRotationControl() {
  const btn = document.getElementById("btn-rotate-map");
  const label = document.getElementById("rotation-label");
  if (!btn || !label) return;

  const saved = storeGet("ems_map_rotation");
  state.rotation = saved ? parseInt(saved, 10) || 0 : 0;
  label.textContent = `${state.rotation}°`;

  btn.onclick = () => {
    state.rotation = (state.rotation + 90) % 360;
    label.textContent = `${state.rotation}°`;
    storeSet("ems_map_rotation", state.rotation.toString());
    invalidateTransform();
    forceFrame();
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

  const saved = storeGet("ems_legend_visible");
  const isVisible = saved === null ? true : saved === "true";

  const setVisibility = (vis) => {
    if (vis) {
      content.classList.remove("hidden");
      label.textContent = "HIDE";
    } else {
      content.classList.add("hidden");
      label.textContent = "SHOW";
    }
    storeSet("ems_legend_visible", vis ? "true" : "false");
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
  const name = document.getElementById("sim-name");
  if (name) {
    name.textContent = (sel.selectedOptions[0]?.textContent || "—").replace(" · FINISHED", "");
  }
  state.run = state.run || {};
  state.run.finished = false;
  state.run.running = true;
  state.trail = {};
  state.prevPos = {};
  state.anim = {};
  state.flashes = [];
  state.events = [];
  state.pendingEvents = [];
  state.liveSnap = null;
  state.replayQueue = [];
  state.replayIndex = 0;
  if (state.replayTimer) {
    clearInterval(state.replayTimer);
    state.replayTimer = null;
  }
  resetWowRunState();
  send({ action: "start",
         scenario: sel.value,
         seed: Number(document.getElementById("seed").value) });
};
document.getElementById("btn-pause").onclick = () => {
  const btn = document.getElementById("btn-pause");
  const isResume = btn.textContent.trim().toUpperCase().includes("RESUME");
  send({ action: isResume ? "resume" : "pause" });
  btn.textContent = isResume ? "PAUSE" : "RESUME";
  btn.setAttribute("aria-label", isResume ? "Pause simulation" : "Resume simulation");
  btn.className = isResume
    ? "btn px-3.5 py-1.5 text-xs font-bold btn-amber"
    : "btn px-3.5 py-1.5 text-xs font-bold btn-primary";
};
document.getElementById("btn-step").onclick = () => send({ action: "step" });
document.getElementById("btn-reset").onclick = () => {
  const name = document.getElementById("sim-name");
  if (name) name.textContent = name.textContent.replace(" · FINISHED", "");
  state.run = state.run || {};
  state.run.finished = false;
  state.run.running = false;
  state.trail = {};
  state.prevPos = {};
  state.anim = {};
  state.flashes = [];
  state.events = [];
  state.pendingEvents = [];
  state.liveSnap = null;
  state.replayQueue = [];
  state.replayIndex = 0;
  if (state.replayTimer) {
    clearInterval(state.replayTimer);
    state.replayTimer = null;
  }
  resetWowRunState();
  send({ action: "reset" });
  const pauseBtn = document.getElementById("btn-pause");
  if (pauseBtn) pauseBtn.textContent = "PAUSE";
};
document.getElementById("btn-replay").onclick = () => {
  state.replayQueue = [];
  state.replayIndex = 0;
  const label = document.getElementById("wow-replay-label");
  if (label) label.textContent = "Loading replay from engine…";
  send({ action: "replay" });
};

async function runBenchmark(forceFresh = true) {
  const box = document.getElementById("benchmark-box");
  const status = document.getElementById("bench-status");
  const deltaBox = document.getElementById("wow-bench-delta");
  const sel = document.getElementById("scenario");
  const scenario = sel?.value || state.snap?.scenario?.name || "downtown-rush";
  const seedsCount = 3;
  if (status) status.textContent = forceFresh ? "RUNNING…" : "SMART VS NAIVE";
  if (box && forceFresh) {
    box.innerHTML = `<div ${toneStyle("muted")} class="py-2 flex items-center gap-2">
      <span class="inline-block w-2 h-2 rounded-full bg-ops animate-pulse"></span>
      Running ${scenario} × ${seedsCount} seeds × 2 stacks (smart vs baseline)…
    </div>`;
  }
  if (deltaBox && forceFresh) {
    deltaBox.innerHTML = `<div class="wow-dim text-xs py-2">Computing benchmark metrics across seeds…</div>`;
  }
  try {
    const url = forceFresh ? "/benchmark" : `/benchmark?scenario=${encodeURIComponent(scenario)}`;
    const res = forceFresh
      ? await fetch("/benchmark", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scenario, seeds: seedsCount }),
        })
      : await fetch(url);
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      throw new Error(`HTTP ${res.status} from /benchmark`);
    }
    if (!res.ok) throw new Error((data && data.message) || res.statusText);
    if (!data || !data.rows || !data.rows.length) throw new Error("No benchmark rows returned");
    state.benchmarkData = data;
    if (status) status.textContent = `${data.n_runs} RUNS · SEEDS 1–${data.seeds ? data.seeds.length : seedsCount}`;
    const rows = data.rows.map((r) => {
      const isSmart = r.combo === "smart";
      const label = isSmart ? "SMART AI" : "NAIVE BASELINE";
      const subLabel = isSmart ? "CNP · D* Lite · CSP · MDP" : "Greedy · A* · First-Free · Station";
      const respAvg = (Number(r.response_avg) || 0).toFixed(1);
      const respP95 = (Number(r.response_p95) || 0).toFixed(1);
      const respVar = (Number(r.response_variance) || 0).toFixed(0);
      const gini = (Number(r.equity_gini) || 0).toFixed(3);
      const dist = (Number(r.distance_km) || 0).toFixed(0);
      const load = (Number(r.workload_spread) || 0).toFixed(1);
      const reneg = (Number(r.renegotiations) || 0).toFixed(0);
      const savings = (Number(r.replan_savings_expansions) || 0).toFixed(0);

      const cardStyle = isSmart
        ? "border:1px solid rgba(59, 130, 246, 0.35); background: rgba(59, 130, 246, 0.04);"
        : "border:1px solid var(--border); background: var(--surface-2);";
      const badgeStyle = isSmart
        ? "background: rgba(59, 130, 246, 0.15); color: #3b82f6; border: 1px solid rgba(59, 130, 246, 0.4);"
        : "background: var(--surface-3); color: var(--muted); border: 1px solid var(--border);";

      return `
      <div class="benchmark-card p-3.5 my-3 rounded-lg" style="${cardStyle}">
        <div class="flex items-center justify-between pb-2 mb-2" style="border-bottom: 1px solid var(--border);">
          <div class="flex items-center gap-2">
            <span class="font-bold text-xs px-2.5 py-0.5 rounded font-mono" style="${badgeStyle}">${label}</span>
            <span class="text-[11px] text-muted hidden sm:inline">${subLabel}</span>
          </div>
          <div class="text-right">
            <span class="text-[10px] uppercase tracking-wider text-muted mr-1.5">Avg Response</span>
            <span class="font-mono font-bold text-sm" ${toneStyle(isSmart ? "ops" : "ink")}>${respAvg}s</span>
          </div>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono pt-1">
          <div class="p-2 rounded" style="background: var(--surface-1); border: 1px solid var(--border);">
            <div class="text-[9.5px] uppercase tracking-wider" ${toneStyle("muted")}>P95 Response</div>
            <div class="font-bold mt-0.5" ${toneStyle("ink")}>${respP95}s</div>
          </div>
          <div class="p-2 rounded" style="background: var(--surface-1); border: 1px solid var(--border);">
            <div class="text-[9.5px] uppercase tracking-wider" ${toneStyle("muted")}>Gini Equity</div>
            <div class="font-bold mt-0.5" ${toneStyle("gini")}>${gini}</div>
          </div>
          <div class="p-2 rounded" style="background: var(--surface-1); border: 1px solid var(--border);">
            <div class="text-[9.5px] uppercase tracking-wider" ${toneStyle("muted")}>Fleet Travel</div>
            <div class="font-bold mt-0.5" ${toneStyle("ink")}>${dist} km</div>
          </div>
          <div class="p-2 rounded" style="background: var(--surface-1); border: 1px solid var(--border);">
            <div class="text-[9.5px] uppercase tracking-wider" ${toneStyle("muted")}>${isSmart ? "D* Saved" : "Variance"}</div>
            <div class="font-bold mt-0.5" ${toneStyle(isSmart ? "ops" : "ink")}>${isSmart ? "+" + savings + " exp" : respVar}</div>
          </div>
        </div>
      </div>`;
    }).join("");
    if (box) {
      box.innerHTML = `
        <div class="text-[10px] mb-1" ${toneStyle("dim")}>mean over ${data.seeds ? data.seeds.length : seedsCount} seed(s), scenario ${data.scenario}</div>
        ${rows}`;
    }
    if (window.FOAI_WOW && typeof window.FOAI_WOW.renderBenchDelta === "function") {
      window.FOAI_WOW.renderBenchDelta(data);
    }
  } catch (err) {
    if (status) status.textContent = "FAILED";
    if (box) box.innerHTML = `<div ${toneStyle("alert")} class="py-2">Benchmark failed: ${err.message}</div>`;
    if (deltaBox) deltaBox.innerHTML = `<div class="wow-dim text-xs py-1">Benchmark failed: ${err.message}</div>`;
  }
}
document.getElementById("btn-benchmark").onclick = () => runBenchmark(true);
const benchStatusChip = document.getElementById("bench-status");
if (benchStatusChip) {
  benchStatusChip.style.cursor = "pointer";
  benchStatusChip.onclick = () => runBenchmark(true);
}
window.addEventListener("foai:view-change", (e) => {
  if (e.detail?.view === "analyze" && !state.benchmarkData) {
    runBenchmark(false);
  }
});

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

// --------------------------------------------------------------------------- //
// Keyboard, announcements, focus order                                        //
// --------------------------------------------------------------------------- //

// The dashboard updates per tick, so nothing on screen may be a live region:
// an event stream read aloud at 40 ticks a second is unusable. The event and
// decision logs stay reachable and silent, and one polite region carries at
// most one message per 10s.
const ANNOUNCE_INTERVAL_MS = 10000;
const MAP_ALT_INTERVAL_MS = 2500; // the canvas sentence is never rebuilt per frame

let announcer = null;
let lastAnnouncedAt = 0;
let queuedAnnouncement = null;
let lastMapAltAt = 0;

function ensureAnnouncer() {
  if (announcer && announcer.isConnected) return announcer;
  announcer = document.createElement("div");
  announcer.id = "foai-announcer";
  announcer.setAttribute("role", "status");
  announcer.setAttribute("aria-live", "polite");
  announcer.setAttribute("aria-atomic", "true");
  announcer.style.cssText =
    "position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;"
    + "clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;border:0";
  document.body.appendChild(announcer);
  return announcer;
}

function speak(text) {
  if (!text) return;
  ensureAnnouncer().textContent = text;
  lastAnnouncedAt = performance.now();
}

// Rate limit: at most one message per 10s. A backlog collapses to its newest
// entry rather than queueing, so a busy run cannot build up a stale queue.
function announce(text) {
  if (!text) return;
  if (performance.now() - lastAnnouncedAt < ANNOUNCE_INTERVAL_MS) {
    queuedAnnouncement = text;
    return;
  }
  speak(text);
}

setInterval(() => {
  if (!queuedAnnouncement) return;
  const text = queuedAnnouncement;
  queuedAnnouncement = null;
  speak(text);
}, ANNOUNCE_INTERVAL_MS);

// The canvas carries no text, so it gets a sentence describing the run. It is
// rebuilt at most every 2.5s, so the accessible name is stable enough to read
// instead of flickering on every snapshot.
function describeMap(snap) {
  if (!snap) return "Live city map. Awaiting telemetry.";
  const amb = snap.ambulances || [];
  const count = (s) => amb.filter((a) => a.status === s).length;
  const open = (snap.incidents || []).filter((i) => i.status !== "cleared");
  const worst = open.reduce((m, i) => Math.max(m, i.severity || 0), 0);
  const parts = [
    `tick ${snap.tick}, ${snap.seconds} seconds elapsed`,
    `${amb.length} units`,
    `${count("enroute")} en route`,
    `${count("on_scene")} on scene`,
    `${count("transporting")} transporting`,
    `${count("blocked")} blocked`,
    `${open.length} open ${open.length === 1 ? "call" : "calls"}`,
  ];
  if (worst) parts.push(`highest severity ${worst}`);
  if (snap.stats && snap.stats.response_avg != null) {
    parts.push(`mean response ${snap.stats.response_avg.toFixed(0)} seconds`);
  }
  return `Live city map: ${parts.join(", ")}.`;
}

function refreshMapAlt(snap) {
  const now = performance.now();
  if (now - lastMapAltAt < MAP_ALT_INTERVAL_MS) return;
  lastMapAltAt = now;
  const text = describeMap(snap);
  if (canvas.getAttribute("aria-label") !== text) canvas.setAttribute("aria-label", text);
}

// Focus order is the visual order: brand, theme, scenario, seed, run controls,
// clock, map, legend, KPIs. The only node that moves is the theme toggle up
// beside the brand, so Tab can never disagree with what the eye sees. No
// roving tabindex, no key traps, and the tick-rate scrubber keeps its native
// arrow / Home / End behaviour because nothing intercepts those keys.
function initFocusOrder() {
  canvas.setAttribute("tabindex", "0");
  canvas.setAttribute("role", "img");
  if (!canvas.getAttribute("aria-label")) {
    canvas.setAttribute("aria-label", "Live city map. Awaiting telemetry.");
  }

  const kpis = document.getElementById("stats-cards");
  if (kpis) {
    kpis.setAttribute("tabindex", "0");
    kpis.setAttribute("role", "group");
    kpis.setAttribute("aria-label", "City telemetry key performance indicators");
  }

  // The two logs are reference, not narration: reachable, but never announced.
  for (const id of ["events", "decisions"]) {
    const el = document.getElementById(id);
    if (el) el.setAttribute("aria-live", "off");
  }
  // The hover tooltip duplicates what the canvas sentence already carries, and
  // it cannot be reached by keyboard, so it is decoration for the pointer path.
  const hover = document.getElementById("hover-info");
  if (hover) {
    hover.setAttribute("aria-live", "off");
    hover.setAttribute("aria-hidden", "true");
  }
}

function isTypingTarget(el) {
  if (!el || el.nodeType !== 1) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName.toLowerCase();
  return tag === "input" || tag === "select" || tag === "textarea" || tag === "option";
}

// Space runs or pauses only when the map — or any non-interactive region — has
// focus. A focused button keeps its own Space activation, and no field is ever
// hijacked.
function spaceTogglesRun(target) {
  if (!state.run.hasEngine) return false;
  const el = target && target.nodeType === 1 ? target : null;
  if (el && el.closest("button, a[href], input, select, textarea, "
    + "[role='button'], [contenteditable='true']")) return false;
  return true;
}

// Reuses the buttons themselves, so the keyboard can never reach a state the
// pointer cannot.
function toggleRunFromKeyboard() {
  if (!state.run.hasEngine || state.run.finished) {
    document.getElementById("btn-start").click();
  } else {
    document.getElementById("btn-pause").click();
  }
}

// '1' / '2' jump to the command half (map, telemetry, AI modules) and the
// analyze half (benchmark, fairness, decisions, events). Real tabs win if the
// markup ever grows them; otherwise focus lands on the column itself, which is
// a programmatic stop only (tabindex -1) and never a new Tab trap.
function focusPanel(name) {
  const tab = document.querySelector(`[data-panel="${name}"], [role="tab"][data-tab="${name}"]`);
  const el = tab || document.getElementById(name === "command" ? "left-col" : "right-col");
  if (!el) return;
  if (!tab && !el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
  el.focus({ preventScroll: true });
  el.scrollIntoView({ block: "nearest", behavior: state.reducedMotion ? "auto" : "smooth" });
  announce(`${name === "command" ? "Command" : "Analyze"} panel.`);
}

function initKeyboard() {
  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return; // leave OS and browser chords
    if (isTypingTarget(e.target)) return;                                 // never steal a keystroke from a field
    const key = e.key;
    if (key === "t" || key === "T") {
      e.preventDefault();
      requestThemeToggle();
      return;
    }
    if (key === "1") {
      e.preventDefault();
      focusPanel("command");
      return;
    }
    if (key === "2") {
      e.preventDefault();
      focusPanel("analyze");
      return;
    }
    if (key === " " || e.code === "Space") {
      if (spaceTogglesRun(e.target)) {
        e.preventDefault();
        toggleRunFromKeyboard();
      }
      return;
    }
    // Arrow keys are deliberately not handled: the tick-rate scrubber is a
    // native range input and keeps its own arrow / Home / End stepping.
  });
}

function initA11y() {
  ensureAnnouncer();
  initFocusOrder();
  initKeyboard();
}

// --------------------------------------------------------------------------- //
// Theme Wiring — app.js owns the tokens and every theme write                  //
// --------------------------------------------------------------------------- //

function currentTheme() {
  return document.documentElement.dataset.theme
    || (tokens.isLight ? "light" : "dark");
}

function initTheme() {
  syncMotion();
  watchMotion();
  restoreTheme();
  bindThemeControls();
  watchThemeSources();

  // Repaint the chrome once at boot whatever restoreTheme decided: the boot
  // script may have written the attribute before this file ran, and the toggle
  // has to agree with it from the first frame.
  readTokens();
  renderThemeToggle();
  rethemePanels();
  renderLegend();
  forceFrame();
}

window.setTheme = setTheme;
window.requestThemeToggle = requestThemeToggle;
window.getMapPalette = getMapPalette;
window.readTokens = readTokens;
window.toggleTheme = requestThemeToggle;
window.STATUS_COLOR = STATUS_COLOR;
window.SEVERITY_COLOR = SEVERITY_COLOR;
window.FOAI_TOKENS = tokens;
window.worldToScreen = worldToScreen;
window.resize = resize;
window.prepAnimation = prepAnimation;
window.scheduleDomUpdate = scheduleDomUpdate;
window.performDomUpdate = performDomUpdate;
window.forceFrame = forceFrame;
window.send = send;
window.state = state;
window.runBenchmark = runBenchmark;
window.renderControls = renderControls;

window.addEventListener("resize", resize);
if (window.ResizeObserver) {
  new ResizeObserver(resize).observe(document.getElementById("map-shell"));
}
initTheme();
initA11y();
resize();
initRotationControl();
initLegendToggle();
connect();
startRenderLoop();
