/* ==========================================================================
   FOAI "Wow" layer — additive presentation features on top of app.js.

   Self-bootstrapping contract:
     * boots on DOMContentLoaded (or immediately if already parsed);
     * detects every documented hook id from docs/WOW-INTEGRATION.md;
     * creates the minimal container itself, in the correct view
       (Command: HUD banner, story cards, ticker, hospital load;
        Analyze: sparkline, Gini, benchmark delta, scrubber, capture;
        map overlays live inside #map-shell wherever the map is);
     * never throws when app.js has not loaded yet — every app.js global is
       read through a guard and retried by the poll/MutationObserver;
     * reads the theme from <html data-theme> and honours reduced motion
       (trails off, blockage pulse static, audio pulses off, instant
       switches) with audio muted by default.

   Protected files (never edited): index.html, app.js, style.css, main.py,
   core/engine.py. This file only ever writes into the DOM it owns.
   ========================================================================== */

(function () {
  "use strict";

  const VERSION = "1.1.0";
  const POLL_MS = 250;
  const KPI_CAP = 60;
  const TRAIL_CAP = 15;
  const TICKER_TTL_MS = 15000;
  const TICKER_MAX = 5;
  const AUDIO_KEY = "foai.wow.audio";

  const byId = (id) => document.getElementById(id);

  function appState() {
    // `state` is exposed on window and also as a top-level const in app.js
    try {
      if (typeof window.state !== "undefined" && window.state) return window.state;
      return typeof state !== "undefined" && state ? state : null;
    } catch (e) {
      return null;
    }
  }

  function globalFn(name) {
    try {
      return typeof window[name] === "function" ? window[name] : null;
    } catch (e) {
      return null;
    }
  }

  function reducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) {
      return false;
    }
  }

  function currentTheme() {
    try {
      return document.documentElement.getAttribute("data-theme") || "dark";
    } catch (e) {
      return "dark";
    }
  }

  let cachedPalette = null;
  function invalidatePalette() {
    cachedPalette = null;
  }

  function css(name, fallback) {
    try {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name);
      if (v && v.trim()) return v.trim();
    } catch (e) { /* style not ready */ }
    return fallback;
  }

  function palette() {
    if (!cachedPalette) {
      cachedPalette = {
        ops: css("--wow-ops", css("--ops", "rgb(56,189,248)")),
        ok: css("--wow-ok", css("--ok", "rgb(52,211,153)")),
        warn: css("--wow-warn", css("--warn", "rgb(251,191,36)")),
        alert: css("--wow-alert", css("--alert", "rgb(244,63,94)")),
        fair: css("--wow-fair", "rgb(192,132,252)"),
        muted: css("--wow-muted", css("--muted", "rgb(136,153,181)")),
        dim: css("--wow-dim", css("--dim", "rgb(84,102,130)")),
        line: css("--wow-line", css("--line", "rgb(30,45,74)")),
        surface: css("--wow-surface", css("--surface", "rgb(13,21,39)")),
        text: css("--wow-text", css("--text", "rgb(226,232,240)")),
        pos: css("--wow-pos", "rgb(52,211,153)"),
        neg: css("--wow-neg", "rgb(244,63,94)"),
      };
    }
    return cachedPalette;
  }

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function num(v, dp) {
    if (v == null || typeof v !== "number" || !isFinite(v)) return "—";
    return v.toFixed(dp == null ? 1 : dp);
  }

  function guard(label, fn) {
    try {
      return fn();
    } catch (err) {
      if (window.console && console.warn) console.warn("[wow:" + label + "]", err);
      return undefined;
    }
  }

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) {
      return null;
    }
    return null;
  }

  // ------------------------------------------------------------------ //
  // Hook registry — mirrors the table in docs/WOW-INTEGRATION.md.       //
  // Every id below is optional: present markup wins, otherwise the      //
  // layer builds the documented container in its view.                  //
  // ------------------------------------------------------------------ //

  const HOOK_IDS = [
    "wow-hud", "wow-phase", "wow-audio-toggle",
    "wow-story-cards", "wow-ticker", "wow-hospital-loads",
    "wow-trails", "wow-blockage-flash",
    "wow-spark-kpi", "wow-gini-val", "wow-gini",
    "wow-bench-delta",
    "wow-replay", "wow-replay-label", "wow-replay-play",
    "wow-replay-slider", "wow-replay-rate",
    "wow-export-png", "wow-print", "wow-summary-card",
  ];

  const autoCreated = new Set();

  // wow-hud is an internal wrapper: created only when phase/sound have to be
  // auto-built, so a "missing" entry in hookStatus is not a failure.
  const INTERNAL_IDS = new Set(["wow-hud"]);

  // View resolution order. The first two selectors are the documented
  // contract for the Command/Analyze tab restructure; #left-col / #right-col
  // keep the layer working on the flat (pre-tab) layout, and #main-layout is
  // the last resort so a hook can always be placed once the shell exists.
  const VIEW_SELECTORS = {
    command: [
      '[data-view="command"]',
      '[data-panel="command"]',
      "#view-command",
      "#panel-command",
      "#command-view",
      "#command-panel",
      "#tab-command-panel",
      "#tab-command",
      "#command",
      "#left-col",
      "#main-layout",
    ],
    analyze: [
      '[data-view="analyze"]',
      '[data-panel="analyze"]',
      "#view-analyze",
      "#panel-analyze",
      "#analyze-view",
      "#analyze-panel",
      "#tab-analyze-panel",
      "#tab-analyze",
      "#analyze",
      "#right-col",
      "#main-layout",
    ],
  };

  function isContainer(el) {
    if (!el || !el.tagName) return false;
    const tag = el.tagName;
    if (tag === "BUTTON" || tag === "A" || tag === "INPUT" ||
        tag === "SELECT" || tag === "SPAN" || tag === "CANVAS") {
      return false;
    }
    return el.getAttribute("role") !== "tab";
  }

  function viewEl(kind) {
    const sels = VIEW_SELECTORS[kind] || [];
    for (let i = 0; i < sels.length; i++) {
      let hit = null;
      try {
        hit = document.querySelector(sels[i]);
      } catch (e) {
        hit = null;
      }
      if (hit && isContainer(hit)) return hit;
    }
    return null;
  }

  /* Which view actually owns an element: the innermost matching container
     across both selector lists, so a flat layout (#left-col / #right-col)
     and a tabbed layout ([data-view]) both report correctly. */
  function viewOf(el) {
    if (!el) return "missing";
    const shell = byId("map-shell");
    if (shell && shell.contains(el)) return "map";
    const innermost = (kind) => {
      let best = null;
      const sels = VIEW_SELECTORS[kind] || [];
      for (let i = 0; i < sels.length; i++) {
        let nodes = [];
        try {
          nodes = document.querySelectorAll(sels[i]);
        } catch (e) {
          nodes = [];
        }
        for (let j = 0; j < nodes.length; j++) {
          const n = nodes[j];
          if (isContainer(n) && n.contains(el) && (!best || best.contains(n))) best = n;
        }
      }
      return best;
    };
    const c = innermost("command");
    const a = innermost("analyze");
    if (c && a) {
      if (c === a) return "shell";
      if (c.contains(a)) return "analyze";
      if (a.contains(c)) return "command";
      return "other";
    }
    if (c) return "command";
    if (a) return "analyze";
    return "other";
  }

  function parseFirst(html) {
    try {
      const t = document.createElement("template");
      t.innerHTML = String(html).trim();
      return t.content.firstElementChild;
    } catch (e) {
      return null;
    }
  }

  function appendParsed(parent, html) {
    const node = parseFirst(html);
    if (!node) return null;
    parent.appendChild(node);
    autoCreated.add(node.id || parent.id);
    return node;
  }

  function insertAfter(ref, node) {
    if (!ref || !ref.parentNode || !node) return false;
    ref.parentNode.insertBefore(node, ref.nextSibling);
    return true;
  }

  function sectionOf(el) {
    let n = el;
    while (n && n !== document.body && n !== document.documentElement) {
      if (n.tagName === "SECTION") return n;
      n = n.parentNode;
    }
    return null;
  }

  function placeTop(parent, node) {
    const hud = byId("wow-hud");
    if (hud && hud.parentNode === parent) parent.insertBefore(node, hud.nextSibling);
    else parent.insertBefore(node, parent.firstChild);
  }

  function markAuto(root) {
    if (!root) return;
    const ids = root.id ? [root.id] : [];
    const withId = root.querySelectorAll("[id]");
    for (let i = 0; i < withId.length; i++) ids.push(withId[i].id);
    for (let i = 0; i < ids.length; i++) autoCreated.add(ids[i]);
  }

  // Markup below matches the snippets documented in docs/WOW-INTEGRATION.md.
  const HOOK_HTML = {
    phase:
      '<div id="wow-phase" class="wow-phase" role="status" aria-live="polite">' +
      '<span class="wow-phase__dot"></span>' +
      '<span class="wow-phase__label">SYSTEM STANDBY</span>' +
      '<span class="wow-phase__note">waiting for a run</span></div>',
    audio:
      '<button id="wow-audio-toggle" class="wow-btn wow-btn--shrink" type="button" ' +
      'aria-pressed="false">SOUND: OFF</button>',
    hudWrap:
      '<div id="wow-hud" class="wow-slot wow-slot--hud" data-wow="auto"></div>',
    story:
      '<section class="card p-3.5" data-wow="auto">' +
      '<div class="card-title mb-2">SCENARIO BRIEFS</div>' +
      '<div id="wow-story-cards"></div></section>',
    ticker:
      '<section class="card p-3.5" data-wow="auto">' +
      '<div class="card-title mb-2">LIVE TICKER (15s)</div>' +
      '<ul id="wow-ticker" aria-live="polite"></ul></section>',
    hospital:
      '<section class="card p-3.5" data-wow="auto">' +
      '<div class="card-title mb-2">HOSPITAL LOAD</div>' +
      '<div id="wow-hospital-loads"></div></section>',
    spark:
      '<section class="card p-3.5" data-wow="auto">' +
      '<div class="card-title mb-1">RESPONSE TIME — LAST 60 SAMPLES</div>' +
      '<canvas id="wow-spark-kpi" aria-label="response time sparkline"></canvas></section>',
    giniVal:
      '<div id="wow-gini-val" class="mono text-[10px] text-muted mt-2">Gini —</div>',
    giniCanvas:
      '<canvas id="wow-gini" aria-label="gini coefficient over time"></canvas>',
    benchDelta:
      '<div id="wow-bench-delta" class="mt-3" data-wow="auto"></div>',
    trails:
      '<canvas id="wow-trails" aria-hidden="true"></canvas>',
    flash:
      '<div id="wow-blockage-flash" role="alert" aria-live="assertive">' +
      '<span class="wow-flash__label">ROUTE CUT DETECTED</span></div>',
    replay:
      '<section class="card p-3.5" data-wow="auto">' +
      '<div class="card-title mb-2">REPLAY SCRUBBER</div>' +
      '<div id="wow-replay">' +
      '<div id="wow-replay-label">no replay loaded — press REPLAY in the header</div>' +
      '<div class="wow-replay__row">' +
      '<button id="wow-replay-play" class="wow-btn" type="button">PLAY</button>' +
      '<input id="wow-replay-slider" type="range" min="0" max="0" value="0" step="1" ' +
      'aria-label="replay frame">' +
      '<select id="wow-replay-rate" aria-label="replay rate">' +
      '<option value="1">1x</option><option value="2">2x</option>' +
      '<option value="4">4x</option><option value="8">8x</option>' +
      "</select></div></div></section>",
    capture:
      '<section class="card p-3.5" data-wow="auto">' +
      '<div class="card-title mb-2">CAPTURE</div>' +
      '<div class="wow-actions mb-3">' +
      '<button id="wow-export-png" class="wow-btn" type="button">EXPORT PNG</button>' +
      '<button id="wow-print" class="wow-btn" type="button">PRINT SUMMARY</button>' +
      "</div>" +
      '<div id="wow-summary-card"></div></section>',
    summary:
      '<div id="wow-summary-card" data-wow="auto"></div>',
  };

  /* Creates any missing hook in its documented view. Returns true when every
     hook exists. Safe to call repeatedly — it is idempotent and never
     touches markup it did not create. */
  function ensureHooks() {
    let ready = true;
    const cmd = viewEl("command");
    const ana = viewEl("analyze");

    // ---- Command: HUD banner (phase + sound toggle) -------------------
    if (!byId("wow-phase") || !byId("wow-audio-toggle")) {
      if (!cmd) {
        ready = false;
      } else {
        let hud = byId("wow-hud");
        if (!hud) {
          hud = parseFirst(HOOK_HTML.hudWrap);
          if (hud) {
            cmd.insertBefore(hud, cmd.firstChild);
            autoCreated.add("wow-hud");
          }
        }
        if (hud) {
          if (!byId("wow-phase")) markAuto(appendParsed(hud, HOOK_HTML.phase));
          if (!byId("wow-audio-toggle")) markAuto(appendParsed(hud, HOOK_HTML.audio));
          if (!byId("wow-phase") || !byId("wow-audio-toggle")) ready = false;
        } else {
          ready = false;
        }
      }
    }

    // ---- Command: scenario story cards (before the map card) ----------
    if (!byId("wow-story-cards")) {
      if (!cmd) ready = false;
      else {
        const node = parseFirst(HOOK_HTML.story);
        if (!node) ready = false;
        else {
          placeTop(cmd, node);
          markAuto(node);
        }
      }
    }

    // ---- Command: live ticker ----------------------------------------
    if (!byId("wow-ticker")) {
      if (!cmd) ready = false;
      else markAuto(appendParsed(cmd, HOOK_HTML.ticker));
    }

    // ---- Command: hospital load bars ---------------------------------
    if (!byId("wow-hospital-loads")) {
      if (!cmd) ready = false;
      else markAuto(appendParsed(cmd, HOOK_HTML.hospital));
    }

    // ---- Map overlays (trail canvas + blockage flash) -----------------
    const shell = byId("map-shell");
    if (!shell) {
      ready = false;
    } else {
      if (!byId("wow-trails")) {
        const map = byId("map");
        const node = parseFirst(HOOK_HTML.trails);
        if (node) {
          if (map) insertAfter(map, node);
          else shell.insertBefore(node, shell.firstChild);
          markAuto(node);
        }
      }
      if (!byId("wow-blockage-flash")) markAuto(appendParsed(shell, HOOK_HTML.flash));
    }

    // ---- Analyze: KPI sparkline (anchored to #stats-cards when it is
    //      inside the Analyze view, otherwise appended to the view) -----
    if (!byId("wow-spark-kpi")) {
      const anchor = sectionOf(byId("stats-cards"));
      const node = parseFirst(HOOK_HTML.spark);
      if (!node) {
        ready = false;
      } else if (anchor && anchor.parentNode && (!ana || ana.contains(anchor))) {
        insertAfter(anchor, node);
        markAuto(node);
      } else if (ana) {
        ana.appendChild(node);
        markAuto(node);
      } else {
        ready = false;
      }
    }

    // ---- Analyze: Gini value + sparkline (anchored to #fairness-box) --
    if (!byId("wow-gini") || !byId("wow-gini-val")) {
      const giniCv = byId("wow-gini");
      const fairness = byId("fairness-box");
      const anchor = giniCv || fairness;
      const host = anchor && anchor.parentNode && (!ana || ana.contains(anchor))
        ? anchor.parentNode
        : ana;
      if (!host) {
        ready = false;
      } else {
        if (!byId("wow-gini-val")) {
          const v = parseFirst(HOOK_HTML.giniVal);
          if (v) {
            if (giniCv && giniCv.parentNode === host) host.insertBefore(v, giniCv);
            else if (fairness && fairness.parentNode === host) insertAfter(fairness, v);
            else host.appendChild(v);
            markAuto(v);
          }
        }
        if (!byId("wow-gini")) {
          const c = parseFirst(HOOK_HTML.giniCanvas);
          if (c) {
            const v = byId("wow-gini-val");
            if (v && v.parentNode === host) insertAfter(v, c);
            else if (fairness && fairness.parentNode === host) insertAfter(fairness, c);
            else host.appendChild(c);
            markAuto(c);
          }
        }
        if (!byId("wow-gini") || !byId("wow-gini-val")) ready = false;
      }
    }

    // ---- Analyze: benchmark delta (after #benchmark-box) --------------
    if (!byId("wow-bench-delta")) {
      const bb = byId("benchmark-box");
      const node = parseFirst(HOOK_HTML.benchDelta);
      if (!node) {
        ready = false;
      } else if (bb && bb.parentNode && (!ana || ana.contains(bb))) {
        insertAfter(bb, node);
        markAuto(node);
      } else if (ana) {
        ana.appendChild(node);
        markAuto(node);
      } else {
        ready = false;
      }
    }

    // ---- Analyze: replay scrubber ------------------------------------
    if (!byId("wow-replay")) {
      if (!ana) ready = false;
      else markAuto(appendParsed(ana, HOOK_HTML.replay));
    }

    // ---- Analyze: capture (export + print + summary card) ------------
    if (!byId("wow-export-png") || !byId("wow-print")) {
      if (!ana) ready = false;
      else markAuto(appendParsed(ana, HOOK_HTML.capture));
    } else if (!byId("wow-summary-card")) {
      // Export/print shipped inline — only the summary container is gone.
      const node = parseFirst(HOOK_HTML.summary);
      const ref = byId("wow-print") || byId("wow-export-png");
      const row = ref && ref.closest ? ref.closest(".wow-actions") : null;
      const host = row && row.parentNode ? row.parentNode
        : sectionOf(ref) || (ref && ref.parentNode) || ana;
      if (!node || !host) ready = false;
      else {
        insertAfter(row && row.parentNode === host ? row : null, node) ||
          host.appendChild(node);
        markAuto(node);
      }
    }

    return ready;
  }

  // ------------------------------------------------------------------ //
  // Event tone + sound maps                                             //
  // ------------------------------------------------------------------ //

  const TONE = {
    "world.blockage_detected": "alert",
    "dispatch.failed": "alert",
    "ambulance.replanned": "ops",
    "replan.cost_compare": "ops",
    "search.run": "ops",
    "mdp.solved": "ops",
    "ambulance.dispatched": "good",
    "dispatch.greedy": "good",
    "dispatch.auction.award": "good",
    "incident.cleared": "good",
    "hospital.allocated": "med",
    "ambulance.on_scene": "warn",
    "ambulance.idle_move": "info",
    "incident.reported": "warn",
    "dispatch.renegotiated": "med",
    "sim.start": "ops",
    "run.finished": "good",
  };

  function toneOf(kind) {
    return TONE[kind] || "info";
  }

  const SOUND = {
    "ambulance.dispatched": "dispatch",
    "dispatch.greedy": "dispatch",
    "world.blockage_detected": "blockage",
    "incident.cleared": "clear",
  };

  let cursorRef = null;
  let lastBlockTick = null;
  const tickerItems = [];
  const seenKeys = new Map();
  const spark = { tick: [], avg: [], p95: [] };
  const giniBuf = [];
  const trails = new Map();
  let lastKpiTick = null;
  let lastGiniTick = null;
  let lastTrailTick = null;
  let lastTrailMapId = null;

  function drainEvents() {
    const st = appState();
    if (!st) return [];
    const evs = st.events || [];
    if (!evs.length) {
      cursorRef = null;
      return [];
    }
    const tail = evs[evs.length - 1];
    let fresh;
    if (cursorRef == null) fresh = evs.slice(-TICKER_MAX);
    else {
      const i = evs.indexOf(cursorRef);
      fresh = i >= 0 ? evs.slice(i + 1) : evs.slice(-TICKER_MAX);
    }
    cursorRef = tail;
    if (fresh.length > 30) fresh = fresh.slice(-30);
    return fresh;
  }

  function fanout(events) {
    for (const evt of events) {
      if (!evt || !evt.kind) continue;
      if (evt.kind === "world.blockage_detected") {
        lastBlockTick = evt.tick;
        blockagePulse(evt);
      }
      const snd = SOUND[evt.kind];
      if (snd) audioPlay(snd);
      tickerPush(evt);
    }
  }

  // ------------------------------------------------------------------ //
  // 1. scenario story cards (state.scenarios from the init message)     //
  // ------------------------------------------------------------------ //

  function renderStoryCards() {
    const box = byId("wow-story-cards");
    if (!box) return;
    const st = appState();
    if (!st || !st.scenarios || !st.scenarios.length) return;
    const sig = st.scenarios.length + ":" + st.scenarios.map((s) => s.id).join(",");
    if (box.getAttribute("data-sig") === sig) {
      markActiveStory();
      return;
    }
    box.setAttribute("data-sig", sig);
    box.innerHTML = st.scenarios
      .map((s) => {
        const meta = [
          ["UNITS", s.ambulances == null ? "—" : s.ambulances],
          ["STATIONS", s.stations == null ? "—" : s.stations],
          ["CALLS", s.incidents == null ? "—" : s.incidents],
          ["TICKS", s.max_ticks == null ? "—" : s.max_ticks],
        ]
          .map(
            (m) =>
              '<div class="wow-card__meta-item"><dt>' +
              m[0] +
              "</dt><dd>" +
              esc(m[1]) +
              "</dd></div>"
          )
          .join("");
        const fullDesc = s.description || "";
        const oneLine = fullDesc ? (fullDesc.split(".")[0].trim() + ".") : "";
        return (
          '<article class="wow-card" data-scenario="' +
          esc(s.id) +
          '" tabindex="0" role="button" aria-pressed="false" title="' +
          esc(fullDesc) +
          '">' +
          '<header class="wow-card__head">' +
          '<span class="wow-card__title">' +
          esc(s.title || s.id) +
          "</span>" +
          '<span class="wow-card__id font-mono">' +
          esc(s.id) +
          "</span></header>" +
          '<p class="wow-card__desc" title="' +
          esc(fullDesc) +
          '">' +
          esc(oneLine) +
          "</p>" +
          '<div class="wow-card__detail" aria-hidden="true">' +
          esc(fullDesc) +
          "</div>" +
          '<dl class="wow-card__meta">' +
          meta +
          "</dl></article>"
        );
      })
      .join("");
    markActiveStory();
  }

  function markActiveStory() {
    const box = byId("wow-story-cards");
    if (!box) return;
    const sel = byId("scenario");
    const id = sel ? sel.value : null;
    for (const card of box.querySelectorAll(".wow-card")) {
      const on = !!id && card.getAttribute("data-scenario") === id;
      card.classList.toggle("is-active", on);
      card.setAttribute("aria-pressed", on ? "true" : "false");
    }
  }

  function bindStoryCards() {
    const box = byId("wow-story-cards");
    if (!box) return;
    document.addEventListener("change", (e) => {
      if (e.target && e.target.id === "scenario") markActiveStory();
    });
    box.addEventListener("click", (e) => {
      const card = e.target.closest ? e.target.closest(".wow-card") : null;
      if (!card) return;
      const sel = byId("scenario");
      const id = card.getAttribute("data-scenario");
      if (sel && id && sel.value !== id) {
        sel.value = id;
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        markActiveStory();
      }
    });
    box.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const card = e.target.closest ? e.target.closest(".wow-card") : null;
      if (!card) return;
      e.preventDefault();
      card.click();
    });
  }

  // ------------------------------------------------------------------ //
  // 2. live ticker — latest 5 entries, 15s time-to-live                  //
  // ------------------------------------------------------------------ //

  function tickerPush(evt) {
    const key = evt.tick + "|" + evt.kind + "|" + evt.summary;
    if (seenKeys.has(key)) seenKeys.delete(key);
    seenKeys.set(key, Date.now());
    if (seenKeys.size > 300) {
      const oldest = seenKeys.keys().next().value;
      seenKeys.delete(oldest);
    }
    tickerItems.push({ evt: evt, ts: Date.now(), key: key });
    if (tickerItems.length > 80) tickerItems.splice(0, tickerItems.length - 80);
  }

  function renderTicker() {
    const box = byId("wow-ticker");
    if (!box) return;
    const now = Date.now();
    const st = appState();
    const finished = !!(st && st.run && st.run.finished);
    // A finished run keeps its final entries: expiring them after 15s of
    // silence replaced the last thing the owner sees with the idle
    // "awaiting telemetry…" placeholder.
    if (!finished) {
      while (tickerItems.length && now - tickerItems[0].ts > TICKER_TTL_MS) {
        tickerItems.shift();
      }
    } else {
      if (!tickerItems.some((it) => it.pin) && st && st.snap) {
        onRunFinished(st.snap);
      }
      if (tickerItems.length === 0 && st && st.events && st.events.length) {
        const tail = st.events.slice(-5);
        for (const ev of tail) {
          tickerPush(ev);
        }
      }
    }
    // Pinned lines (the run verdict) stay on top; the rolling feed fills the
    // remaining slots underneath.
    const rolling = tickerItems.filter((it) => !it.pin).slice(-TICKER_MAX).reverse();
    const live = tickerItems.filter((it) => it.pin).concat(rolling).slice(0, TICKER_MAX);
    const ageBucket = finished ? "end" : live.length ? Math.floor((now - live[0].ts) / 1000) : 0;
    const sig = ageBucket + ";" + live.map((it) => it.key + "@" + it.ts).join(";");
    if (box.getAttribute("data-sig") === sig) return;
    box.setAttribute("data-sig", sig);
    if (!live.length) {
      if (finished) {
        const snap = st && st.snap;
        const stats = (snap && snap.stats) || {};
        const cleared = stats.incidents_cleared || stats.hospitals_completed || 0;
        const reported = stats.incidents_reported || cleared || 0;
        box.innerHTML =
          '<li class="wow-ticker__item wow-tone-good is-fresh" tabindex="0" role="listitem">' +
          '<span class="wow-ticker__t">END</span>' +
          '<span class="wow-ticker__summary">RUN COMPLETE · ' + cleared + '/' + reported + ' calls cleared</span>' +
          '<span class="wow-ticker__age">done</span>' +
          '</li>';
      } else {
        box.innerHTML = '<li class="wow-ticker__empty">awaiting telemetry…</li>';
      }
      return;
    }
    box.innerHTML = live
      .map((it, i) => {
        const e = it.evt;
        const age = Math.round((now - it.ts) / 1000);
        const ageTxt = finished ? "end" : age + "s";
        const fullMsg = "t" + e.tick + " · [" + e.kind + "] " + (e.summary || "") +
          (finished ? " · end of run" : " (" + age + "s ago)");
        const words = (e.summary || e.kind || "Event").trim().split(/\s+/);
        // Synthetic run-status lines carry the whole verdict, so they are not
        // clipped to the usual 4-word event summary.
        const cap = it.pin ? 12 : 4;
        const plainSummary = words.slice(0, cap).join(" ") + (words.length > cap ? "…" : "");
        return (
          '<li class="wow-ticker__item wow-tone-' +
          toneOf(e.kind) +
          (i === 0 ? " is-fresh" : "") +
          '" tabindex="0" role="listitem" title="' +
          esc(fullMsg) +
          '" aria-label="' +
          esc(fullMsg) +
          '"><span class="wow-ticker__t">t' +
          esc(e.tick) +
          '</span><span class="wow-ticker__summary">' +
          esc(plainSummary) +
          '</span><span class="wow-ticker__age">' +
          ageTxt +
          "</span></li>"
        );
      })
      .join("");
  }

  // End-of-run verdict: the ticker's last frame is what the owner reads back
  // after a run, so the run's totals are pinned as a permanent line instead
  // of letting the feed expire into the idle placeholder.
  let lastFinishedTick = null;

  function onRunFinished(snap) {
    const st = appState();
    const s = snap || (st && st.snap);
    if (!s) return;
    if (lastFinishedTick === s.tick && tickerItems.some((it) => it.pin)) return;
    lastFinishedTick = s.tick;
    const stats = s.stats || {};
    const cleared = stats.incidents_cleared || stats.hospitals_completed || 0;
    const reported = stats.incidents_reported || cleared || 0;
    const evt = {
      tick: s.tick,
      kind: "run.finished",
      summary:
        "RUN COMPLETE · " +
        cleared +
        "/" +
        reported +
        " calls cleared" +
        " · avg " + num(stats.response_avg, 1) + "s" +
        " · p95 " + num(stats.response_p95, 1) + "s" +
        " · gini " + num(stats.equity ? stats.equity.gini : null, 3),
    };
    tickerPush(evt);
    if (tickerItems.length) tickerItems[tickerItems.length - 1].pin = true;
    renderTicker();
    pushSummary();
    renderHospitalLoads(s);
  }

  // ------------------------------------------------------------------ //
  // 3. hospital load bars (also exported as FOAI_WOW.hospitalLoadData)  //
  // ------------------------------------------------------------------ //

  function hospitalLoadData(snap) {
    const s = snap || (appState() && appState().snap);
    const hs = (s && s.map && s.map.hospitals) || [];
    return hs.map((h) => {
      const beds = Number(h.beds) || 0;
      const used = Number(h.in_use) || 0;
      const served = Number(h.patients_served) || 0;
      const ratio = beds > 0 ? used / beds : 0;
      return {
        id: h.id,
        name: h.name,
        node: h.node,
        beds: beds,
        in_use: used,
        patients_served: served,
        ratio: ratio,
        tone: ratio >= 1 ? "full" : ratio >= 0.75 ? "high" : "ok",
      };
    });
  }

  function renderHospitalLoads(snap) {
    const box = byId("wow-hospital-loads");
    if (!box) return;
    const st = appState();
    const s = snap || (st && st.snap);
    const isFinished = !!(st && st.run && st.run.finished);
    const data = hospitalLoadData(s);
    if (!data.length) {
      const ph = '<div class="wow-dim">no hospital telemetry yet…</div>';
      if (box.innerHTML !== ph) box.innerHTML = ph;
      box.removeAttribute("data-sig");
      return;
    }

    const heading = byId("hospitalHeading");
    const stats = (s && s.stats) || {};
    const cleared = Number(stats.incidents_cleared || stats.hospitals_completed || 0);
    const reported = Number(stats.incidents_reported || cleared || 0);
    const totalServed = data.reduce((acc, h) => acc + (h.patients_served || 0), 0);
    const completedCount = totalServed > 0 ? totalServed : cleared;
    const totalCount = reported > 0 ? reported : completedCount;

    if (heading) {
      heading.textContent = isFinished
        ? `Hospital load · ${completedCount}/${totalCount} calls cleared`
        : (completedCount > 0 ? `Hospital load · ${completedCount}/${totalCount} calls cleared` : "Hospital load");
    }

    const sig = (isFinished ? "fin:" : "run:") +
      data.map((h) => h.id + ":" + h.in_use + "/" + h.beds + "s" + h.patients_served).join(",");
    if (box.getAttribute("data-sig") === sig) return;
    box.setAttribute("data-sig", sig);

    box.innerHTML = data
      .map((h) => {
        const pct = Math.round(clamp(h.ratio, 0, 1) * 100);
        const tone = h.tone;
        const numText = `${h.in_use}/${h.beds} beds`;
        const servedText = `${h.patients_served} served`;
        const fullDetail = `${h.name} (${h.id}): ${h.in_use}/${h.beds} beds in use (${pct}%), ${h.patients_served} patients served`;

        return (
          '<div class="wow-load wow-load--' +
          tone +
          '" tabindex="0" title="' +
          esc(fullDetail) +
          '" aria-label="' +
          esc(fullDetail) +
          '">' +
          '<span class="wow-load__name" title="' +
          esc(h.name) +
          '">' +
          esc(h.name) +
          '</span>' +
          '<div class="wow-load__track" role="progressbar" aria-label="' +
          esc(fullDetail) +
          '" aria-valuemin="0" aria-valuemax="' +
          h.beds +
          '" aria-valuenow="' +
          h.in_use +
          '"><div class="wow-load__fill" style="width:' +
          pct +
          '%"></div></div>' +
          '<span class="wow-load__num mono" title="' +
          h.in_use + '/' + h.beds + ' beds currently in use">' +
          esc(numText) +
          '</span>' +
          '<span class="wow-load__served mono" style="font-size:10.5px;color:var(--wow-dim);flex-shrink:0;min-width:54px;text-align:right" title="' +
          h.patients_served + ' patients completed">' +
          esc(servedText) +
          '</span>' +
          '</div>'
        );
      })
      .join("");
  }

  // ------------------------------------------------------------------ //
  // 4. KPI sparkline — 60-point ring buffer of resp avg / p95            //
  // ------------------------------------------------------------------ //

  let sparkDirty = true;
  let giniDirty = true;

  function pushKpi() {
    const el = byId("wow-spark-kpi");
    if (!el) return;
    const st = appState();
    const snap = st && st.snap;
    if (!snap || snap.tick === lastKpiTick) return;
    lastKpiTick = snap.tick;
    const s = snap.stats || {};
    spark.tick.push(snap.tick);
    spark.avg.push(Number(s.response_avg) || 0);
    spark.p95.push(Number(s.response_p95) || 0);
    while (spark.tick.length > KPI_CAP) {
      spark.tick.shift();
      spark.avg.shift();
      spark.p95.shift();
    }
    sparkDirty = true;
  }

  function fitCanvas(cv) {
    const rect = cv.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(rect.width));
    const h = Math.max(1, Math.round(rect.height));
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
    }
    const c = cv.getContext("2d");
    if (!c) return { c: null, w: w, h: h };
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    return { c: c, w: w, h: h };
  }

  function line(c, pts, color, width) {
    if (!c || pts.length < 2) return;
    c.beginPath();
    c.strokeStyle = color;
    c.lineWidth = width || 1.5;
    c.lineJoin = "round";
    c.lineCap = "round";
    pts.forEach((p, i) => (i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1])));
    c.stroke();
  }

  function drawSpark() {
    const cv = byId("wow-spark-kpi");
    if (!cv || spark.tick.length < 2) return;
    const P = palette();
    const g = fitCanvas(cv);
    const c = g.c;
    if (!c) return;
    sparkDirty = false;
    const w = g.w, h = g.h;
    const pad = 6;
    const all = spark.avg.concat(spark.p95);
    let lo = Math.min.apply(null, all);
    let hi = Math.max.apply(null, all);
    if (hi - lo < 1) hi = lo + 1;
    const X = (i) => pad + (i * (w - pad * 2)) / Math.max(1, spark.tick.length - 1);
    const Y = (v) => h - pad - ((v - lo) / (hi - lo)) * (h - pad * 2);

    c.strokeStyle = P.line;
    c.lineWidth = 1;
    c.beginPath();
    c.moveTo(pad, h - pad);
    c.lineTo(w - pad, h - pad);
    c.stroke();

    const p95 = spark.p95.map((v, i) => [X(i), Y(v)]);
    const avg = spark.avg.map((v, i) => [X(i), Y(v)]);
    c.globalAlpha = 0.35;
    line(c, p95, P.warn, 1.5);
    c.globalAlpha = 1;
    line(c, avg, P.ops, 1.8);
    const last = avg[avg.length - 1];
    c.fillStyle = P.ops;
    c.beginPath();
    c.arc(last[0], last[1], 2.4, 0, Math.PI * 2);
    c.fill();

    c.font = "9px ui-monospace, monospace";
    c.textAlign = "left";
    c.fillStyle = P.ops;
    c.fillText("AVG " + num(spark.avg[spark.avg.length - 1], 0) + "s", pad, 10);
    c.fillStyle = P.warn;
    c.fillText("P95 " + num(spark.p95[spark.p95.length - 1], 0) + "s", pad + 74, 10);
  }

  // ------------------------------------------------------------------ //
  // 5. unit trails — 15 points per unit, disabled under reduced motion   //
  // ------------------------------------------------------------------ //

  // Distance beyond which a position change is a teleport (run restart,
  // scenario switch, replay scrub) rather than movement: stitching those
  // points together is what drew the stray diagonal across the map.
  function trailJumpLimit(st) {
    const w = st && st.world;
    if (!w || w.minX == null || w.maxX == null || w.minY == null || w.maxY == null) return 0;
    const dx = Math.max(1e-6, w.maxX - w.minX);
    const dy = Math.max(1e-6, w.maxY - w.minY);
    return Math.hypot(dx, dy) * 0.25;
  }

  function pushTrails() {
    if (reducedMotion()) return;
    const cv = byId("wow-trails");
    if (!cv) return;
    const st = appState();
    const snap = st && st.snap;
    if (!snap || snap.tick === lastTrailTick) return;
    if (lastTrailTick != null && snap.tick < lastTrailTick) trails.clear(); // rewind / new run
    if (st.mapId !== lastTrailMapId) {
      trails.clear();
      lastTrailMapId = st.mapId;
    }
    lastTrailTick = snap.tick;
    const jump = trailJumpLimit(st);
    for (const a of snap.ambulances || []) {
      let buf = trails.get(a.id);
      if (!buf) {
        buf = [];
        trails.set(a.id, buf);
      }
      const last = buf.length ? buf[buf.length - 1] : null;
      if (!last || last.x !== a.x || last.y !== a.y) {
        if (last && jump > 0 && Math.hypot(a.x - last.x, a.y - last.y) > jump) {
          buf.length = 0;
        }
        buf.push({ x: a.x, y: a.y });
      }
      while (buf.length > TRAIL_CAP) buf.shift();
    }
    if (trails.size > 64) {
      const first = trails.keys().next().value;
      trails.delete(first);
    }
  }

  function project(x, y) {
    const w2s = globalFn("worldToScreen");
    if (w2s) {
      const s = w2s(x, y);
      return s && isFinite(s.x) && isFinite(s.y) ? s : null;
    }
    const st = appState();
    const w = st && st.world;
    const shell = byId("map-shell");
    if (!w || !shell) return null;
    const rect = shell.getBoundingClientRect();
    const spanX = Math.max(0.1, w.maxX - w.minX);
    const spanY = Math.max(0.1, w.maxY - w.minY);
    const scale = Math.min(rect.width / spanX, rect.height / spanY);
    const ox = (rect.width - spanX * scale) / 2;
    const oy = (rect.height - spanY * scale) / 2;
    return { x: ox + (x - w.minX) * scale, y: oy + (y - w.minY) * scale };
  }

  function drawTrails() {
    const cv = byId("wow-trails");
    if (!cv) return;
    const g = fitCanvas(cv);
    const c = g.c;
    if (c) c.clearRect(0, 0, cv.width, cv.height);
    // Smooth 1px motion trails are painted natively on the primary canvas by app.js.
    // Suppressing duplicate overlay trails here eliminates diagonal line artifacts and clutter.
  }

  // ------------------------------------------------------------------ //
  // 6. blockage reveal pulse — animated only when motion is allowed      //
  // ------------------------------------------------------------------ //

  let pulseTimer = null;
  let lastPulseAt = 0;

  function blockagePulse(evt) {
    const el = byId("wow-blockage-flash");
    if (!el) return;
    const now = performance.now();
    if (now - lastPulseAt < 700) return;
    lastPulseAt = now;
    const d = (evt && evt.detail) || {};
    const label = el.querySelector(".wow-flash__label");
    if (label) {
      label.textContent = d.edge_u
        ? "ROUTE CUT " + d.edge_u + "-" + d.edge_v
        : "ROUTE CUT DETECTED";
    }
    // Reduced motion: CSS drops the animation, the element still appears
    // as a static ring/box, so the alert is never lost — just not pulsed.
    el.classList.remove("is-live");
    void el.offsetWidth;
    el.classList.add("is-live");
    if (pulseTimer) clearTimeout(pulseTimer);
    pulseTimer = setTimeout(() => el.classList.remove("is-live"), 1600);
  }

  // ------------------------------------------------------------------ //
  // 7. benchmark delta — observes POST /benchmark through a wrapped      //
  //    fetch, clones the response and hands the original back untouched  //
  // ------------------------------------------------------------------ //

  let fetchPatched = false;

  function patchFetchForBenchmark() {
    if (fetchPatched) return;
    if (!byId("wow-bench-delta")) return;
    if (typeof window.fetch !== "function") return;
    fetchPatched = true;
    const orig = window.fetch.bind(window);
    window.fetch = function (input, init) {
      let url = "";
      if (typeof input === "string") url = input;
      else if (input && typeof input.url === "string") url = input.url;
      const method = ((init && init.method) || "GET").toUpperCase();
      const isBench = url.indexOf("/benchmark") !== -1 && method === "POST";
      const p = orig(input, init);
      if (!isBench) return p;
      return p.then((res) => {
        try {
          res
            .clone()
            .json()
            .then((data) => guard("bench-delta", () => renderBenchDelta(data)))
            .catch(() => {});
        } catch (e) { /* clone already consumed elsewhere */ }
        return res; // original Response handed straight back to app.js
      });
    };
  }

  function pctDelta(val, base, higherBetter = false) {
    if (base == null || !isFinite(base)) return null;
    if (base === 0) {
      if (val === 0) return 0;
      return higherBetter ? (val > 0 ? 100 : -100) : (val > 0 ? -100 : 100);
    }
    return higherBetter
      ? ((val - base) / Math.abs(base)) * 100
      : ((base - val) / Math.abs(base)) * 100;
  }

  function chip(pct) {
    if (pct == null || !isFinite(pct)) return '<span class="wow-chip wow-chip--flat">—</span>';
    const cls = pct >= 0 ? "wow-chip--pos" : "wow-chip--neg";
    return '<span class="wow-chip ' + cls + '">' + (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%</span>";
  }

  function renderBenchDelta(data) {
    const box = byId("wow-bench-delta");
    if (!box || !data || !data.rows || !data.rows.length) return;
    const rows = data.rows;
    const smart = rows.find((r) => r.combo === "smart");
    const naive = rows.find((r) => r.combo === "baseline" || r.combo === "naive");
    if (!smart || !naive) {
      box.innerHTML = '<div class="wow-dim">benchmark rows missing smart/naive pair</div>';
      return;
    }
    const st = appState();
    const stats = (st && st.snap && st.snap.stats) || null;
    const metrics = [
      { key: "response_avg", label: "RESP AVG (s)", dp: 1, cur: stats ? stats.response_avg : null, higherBetter: false },
      { key: "response_p95", label: "RESP P95 (s)", dp: 1, cur: stats ? stats.response_p95 : null, higherBetter: false },
      {
        key: "equity_gini",
        label: "GINI",
        dp: 3,
        cur: stats && stats.equity ? stats.equity.gini : null,
        higherBetter: false,
      },
      { key: "distance_km", label: "DIST (km)", dp: 0, cur: stats ? stats.total_distance_km : null, higherBetter: false },
      { key: "workload_spread", label: "LOAD SPREAD", dp: 1, cur: null, higherBetter: false },
      { key: "incidents_cleared", label: "CALLS CLEARED", dp: 0, cur: stats ? stats.incidents_cleared : null, higherBetter: true },
      { key: "replan_savings_expansions", label: "D* SAVINGS", dp: 0, cur: stats ? stats.replan_savings_expansions : null, higherBetter: true },
    ];
    const body = metrics
      .map((m) => {
        const s = Number(smart[m.key]) || 0;
        const n = Number(naive[m.key]) || 0;
        const vsNaive = pctDelta(s, n, m.higherBetter);
        const vsRun = m.cur == null ? null : pctDelta(Number(m.cur), s, m.higherBetter);
        const cur = m.cur == null ? "—" : num(Number(m.cur), m.dp);
        return (
          "<tr><th>" +
          m.label +
          "</th><td>" +
          num(n, m.dp) +
          "</td><td><b>" +
          num(s, m.dp) +
          "</b></td><td>" +
          chip(vsNaive) +
          "</td><td>" +
          cur +
          " " +
          chip(vsRun) +
          "</td></tr>"
        );
      })
      .join("");
    box.innerHTML =
      '<div class="wow-delta__head"><span class="wow-delta__title">SMART vs NAIVE</span>' +
      '<span class="wow-delta__meta">' +
      esc(data.scenario || "") +
      " · seeds " +
      esc((data.seeds || []).join(",")) +
      "</span></div>" +
      '<table class="wow-table"><caption class="wow-visually-hidden">Benchmark ' +
      "SMART versus NAIVE with this run's values</caption>" +
      "<thead><tr><th>METRIC</th><th>NAIVE</th><th>SMART</th>" +
      "<th>SMART Δ</th><th>THIS RUN vs SMART</th></tr></thead><tbody>" +
      body +
      "</tbody></table>";
  }

  // ------------------------------------------------------------------ //
  // 8. replay scrubber — takes over startReplayPlayback, drains          //
  //    state.replayQueue itself, scrubs 1-8x                              //
  // ------------------------------------------------------------------ //

  const replay = {
    frames: [],
    idx: 0,
    playing: false,
    rate: 1,
    timer: null,
    owned: false,
    bound: false,
    noop: null,
  };

  function replayPanelPresent() {
    return !!(byId("wow-replay") && byId("wow-replay-slider"));
  }

  function installReplayHooks() {
    if (!replayPanelPresent()) return;
    replay.owned = true;
    if (!replay.noop) {
      replay.noop = function () {};
    }
    window.startReplayPlayback = replay.noop;
    const st = appState();
    if (st && st.replayTimer) {
      clearInterval(st.replayTimer);
      st.replayTimer = null;
    }
    if (replay.bound) {
      syncReplayUi();
      return;
    }
    replay.bound = true;

    const slider = byId("wow-replay-slider");
    const play = byId("wow-replay-play");
    const rate = byId("wow-replay-rate");
    if (slider) {
      slider.addEventListener("input", () => {
        if (!replay.frames.length) {
          const s = appState();
          if (s && s.replayQueue && s.replayQueue.length) {
            drainReplayQueue();
          } else {
            const send = globalFn("send");
            if (send) {
              const label = byId("wow-replay-label");
              if (label) label.textContent = "Loading replay from engine…";
              send({ action: "replay" });
            }
          }
          return;
        }
        replay.playing = false;
        if (replay.timer) {
          clearInterval(replay.timer);
          replay.timer = null;
        }
        replay.idx = clamp(Number(slider.value) || 0, 0, replay.frames.length - 1);
        applyReplayFrame();
        syncReplayUi();
      });
    }
    if (play) {
      play.addEventListener("click", () => {
        if (!replay.frames.length) {
          const s = appState();
          if (s && s.replayQueue && s.replayQueue.length) {
            drainReplayQueue();
          } else {
            const send = globalFn("send");
            if (send) {
              const label = byId("wow-replay-label");
              if (label) label.textContent = "Loading replay from engine…";
              send({ action: "replay" });
            }
          }
          return;
        }
        replay.playing = !replay.playing;
        if (replay.playing && replay.idx >= replay.frames.length - 1) replay.idx = 0;
        ensureReplayTimer();
        syncReplayUi();
      });
    }
    if (rate) {
      rate.addEventListener("change", () => {
        replay.rate = clamp(Number(rate.value) || 1, 1, 8);
        ensureReplayTimer();
        syncReplayUi();
      });
    }
    syncReplayUi();
  }

  function drainReplayQueue() {
    replay.owned = true;
    const st = appState();
    if (!st) return;
    if (st.replayTimer) {
      clearInterval(st.replayTimer);
      st.replayTimer = null;
    }
    const q = st.replayQueue;
    if (!q || !q.length) return;
    const batch = q.splice(0, q.length);
    const batchMin = Math.min.apply(
      null,
      batch.map((s) => s.tick)
    );
    const hasMin = replay.frames.length ? replay.frames[0].tick : Infinity;
    if (batchMin <= hasMin) {
      replay.frames = [];
      replay.idx = 0;
    }
    if (!replay.frames.length) {
      replay.frames = batch.sort((a, b) => a.tick - b.tick);
    } else {
      const lastTick = replay.frames[replay.frames.length - 1].tick;
      let strictlyAfter = true;
      for (let i = 0; i < batch.length; i++) {
        if (batch[i].tick <= lastTick) {
          strictlyAfter = false;
          break;
        }
      }
      if (strictlyAfter) {
        batch.sort((a, b) => a.tick - b.tick);
        replay.frames.push(...batch);
      } else {
        const seen = new Map();
        for (let i = 0; i < replay.frames.length; i++) seen.set(replay.frames[i].tick, replay.frames[i]);
        for (let i = 0; i < batch.length; i++) seen.set(batch[i].tick, batch[i]);
        replay.frames = Array.from(seen.values()).sort((a, b) => a.tick - b.tick);
      }
    }
    const slider = byId("wow-replay-slider");
    if (slider) {
      slider.max = String(Math.max(0, replay.frames.length - 1));
      slider.value = String(replay.idx);
    }
    // Do NOT auto-play replay frames on arrival; only play if user clicked PLAY
    if (replay.playing) {
      ensureReplayTimer();
      applyReplayFrame();
    }
    syncReplayUi();
  }

  function ensureReplayTimer() {
    if (replay.playing && !replay.timer) {
      replay.timer = setInterval(() => {
        if (!replay.frames.length) {
          replay.playing = false;
          clearInterval(replay.timer);
          replay.timer = null;
          syncReplayUi();
          return;
        }
        replay.idx = clamp(replay.idx + replay.rate, 0, replay.frames.length - 1);
        if (replay.idx >= replay.frames.length - 1) replay.playing = false;
        applyReplayFrame();
        syncReplayUi();
        if (!replay.playing) {
          clearInterval(replay.timer);
          replay.timer = null;
        }
      }, 90);
    } else if (!replay.playing && replay.timer) {
      clearInterval(replay.timer);
      replay.timer = null;
    }
  }

  function applyReplayFrame() {
    const st = appState();
    const f = replay.frames[replay.idx];
    if (!st || !f) return;
    // Server replay frames are map-stripped; borrowing the live map keeps the
    // hospital bars, summary and every other map-derived panel alive while
    // scrubbing instead of blanking them to their last live values.
    if (!f.map && st.map) f.map = st.map;
    st.snap = f;
    const prep = globalFn("prepAnimation");
    if (prep) prep(f);
    const sched = globalFn("scheduleDomUpdate");
    if (sched) sched(f);
  }

  function syncReplayUi() {
    const label = byId("wow-replay-label");
    const play = byId("wow-replay-play");
    const slider = byId("wow-replay-slider");
    const rate = byId("wow-replay-rate");
    if (rate && Number(rate.value) !== replay.rate) rate.value = String(replay.rate);
    if (play) play.textContent = replay.playing ? "PAUSE" : "PLAY";
    if (slider && Number(slider.value) !== replay.idx) slider.value = String(replay.idx);
    if (slider && replay.frames.length) {
      slider.max = String(Math.max(0, replay.frames.length - 1));
    }
    if (label) {
      if (!replay.frames.length) {
        label.textContent = "Replay scrubber · Ready to play";
      } else {
        const f = replay.frames[replay.idx];
        label.textContent =
          "t " + f.tick + " · frame " + (replay.idx + 1) + "/" +
          replay.frames.length + " · " + replay.rate + "x";
      }
    }
  }

  function onReplayEnd() {
    const st = appState();
    if (st && st.replayQueue && st.replayQueue.length) {
      drainReplayQueue();
    }
    const slider = byId("wow-replay-slider");
    if (slider) slider.max = String(Math.max(0, replay.frames.length - 1));
    syncReplayUi();
  }

  // Every buffer owned by this layer belongs to one run; app.js calls this on
  // start / reset / reconnect so nothing bleeds into the next run.
  function resetRunState() {
    tickerItems.length = 0;
    seenKeys.clear();
    cursorRef = null;
    trails.clear();
    lastTrailTick = null;
    lastTrailMapId = null;
    lastFinishedTick = null;
    replay.frames = [];
    replay.idx = 0;
    replay.playing = false;
    if (replay.timer) {
      clearInterval(replay.timer);
      replay.timer = null;
    }
    const st = appState();
    if (st) {
      st.replayQueue = [];
      st.replayIndex = 0;
      if (st.replayTimer) {
        clearInterval(st.replayTimer);
        st.replayTimer = null;
      }
    }
    const heading = byId("hospitalHeading");
    if (heading) heading.textContent = "Hospital load";
    renderHospitalLoads({}); // placeholder until the first live snapshot
    renderTicker();
    const cv = byId("wow-trails");
    if (cv) fitCanvas(cv); // drop stale segments left by the previous run
    const label = byId("wow-replay-label");
    if (label) label.textContent = "Replay scrubber · Ready to play";
    const slider = byId("wow-replay-slider");
    if (slider) {
      slider.max = "0";
      slider.value = "0";
    }
    const play = byId("wow-replay-play");
    if (play) play.textContent = "PLAY";
  }

  // ------------------------------------------------------------------ //
  // 9. export PNG + summary card + print                                 //
  // ------------------------------------------------------------------ //

  function summaryModel() {
    const st = appState();
    const snap = st && st.snap;
    const sel = byId("scenario");
    const s = snap && snap.scenario ? snap.scenario : null;
    const stats = (snap && snap.stats) || {};
    const seedEl = byId("seed");
    return {
      title: (s && (s.title || s.name)) ||
        (sel && sel.selectedOptions[0] && sel.selectedOptions[0].textContent) || "EMS run",
      scenario: (s && s.name) || (sel && sel.value) || "—",
      seed: s && s.seed != null ? s.seed : seedEl ? seedEl.value : "—",
      tick: snap ? snap.tick : 0,
      seconds: snap ? snap.seconds : 0,
      reported: stats.incidents_reported || 0,
      cleared: stats.incidents_cleared || 0,
      respAvg: stats.response_avg || 0,
      respP95: stats.response_p95 || 0,
      replans: stats.replans || 0,
      backtracks: stats.csp_backtracks || 0,
      gini: stats.equity && stats.equity.gini != null ? stats.equity.gini : null,
      distance: stats.total_distance_km || 0,
      renegotiations: stats.renegotiations || 0,
    };
  }

  function summaryHtml(m) {
    const rows = [
      ["SCENARIO", m.scenario],
      ["SEED", m.seed],
      ["TICK", m.tick + " (" + m.seconds + "s)"],
      ["CALLS", m.cleared + "/" + m.reported + " cleared"],
      ["RESP AVG", num(m.respAvg, 1) + "s"],
      ["RESP P95", num(m.respP95, 1) + "s"],
      ["REPLANS", m.replans],
      ["CSP BACKTRACKS", m.backtracks],
      ["GINI", num(m.gini, 3)],
      ["DISTANCE", num(m.distance, 1) + " km"],
      ["RENEGOTIATIONS", m.renegotiations],
    ];
    return (
      '<div class="wow-summary__title">' +
      esc(m.title) +
      "</div>" +
      '<dl class="wow-summary__grid">' +
      rows
        .map(
          (r) =>
            '<div class="wow-summary__row"><dt>' +
            r[0] +
            "</dt><dd>" +
            esc(String(r[1])) +
            "</dd></div>"
        )
        .join("") +
      "</dl>"
    );
  }

  function renderSummary() {
    const box = byId("wow-summary-card");
    if (!box) return;
    const m = summaryModel();
    box.innerHTML = summaryHtml(m);
    box.setAttribute("data-sig", summarySig(m));
  }

  function summarySig(m) {
    return [
      m.scenario, m.seed, m.tick, m.seconds, m.reported, m.cleared,
      Math.round(m.respAvg * 10), Math.round(m.respP95 * 10),
      m.replans, m.backtracks, m.gini == null ? "-" : Math.round(m.gini * 1000),
      Math.round(m.distance), m.renegotiations,
    ].join("|");
  }

  function pushSummary() {
    const box = byId("wow-summary-card");
    if (!box) return;
    const m = summaryModel();
    const sig = summarySig(m);
    if (box.getAttribute("data-sig") === sig) return;
    box.innerHTML = summaryHtml(m);
    box.setAttribute("data-sig", sig);
  }

  function exportPNG() {
    return guard("export-png", () => {
      const map = byId("map");
      if (!map || !map.width || !map.height) return;
      const m = summaryModel();
      const dpr = window.devicePixelRatio || 1;
      const headH = Math.round(132 * dpr);
      const out = document.createElement("canvas");
      out.width = map.width;
      out.height = map.height + headH;
      const c = out.getContext("2d");
      if (!c) return;
      const P = palette();
      c.fillStyle = P.surface;
      c.fillRect(0, 0, out.width, out.height);
      c.fillStyle = P.text;
      c.font = "bold " + Math.round(34 * dpr) + "px system-ui, sans-serif";
      c.fillText(m.title, 28 * dpr, 50 * dpr);
      c.fillStyle = P.ops;
      c.font = Math.round(22 * dpr) + "px ui-monospace, monospace";
      c.fillText(
        m.scenario + " · seed " + m.seed + " · t " + m.tick + " · " + m.seconds + "s",
        28 * dpr,
        84 * dpr
      );
      c.fillStyle = P.muted;
      c.font = Math.round(18 * dpr) + "px ui-monospace, monospace";
      c.fillText(
        "calls " + m.cleared + "/" + m.reported +
          " · resp " + num(m.respAvg, 1) + "s (p95 " + num(m.respP95, 1) +
          "s) · replans " + m.replans + " · backtracks " + m.backtracks +
          " · gini " + num(m.gini, 3) + " · " + num(m.distance, 1) + " km",
        28 * dpr,
        114 * dpr
      );
      c.drawImage(map, 0, headH);
      const url = out.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = url;
      a.download = "foai_" + m.scenario + "_s" + m.seed + "_t" + m.tick + ".png";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      renderSummary();
      return url;
    });
  }

  function bindOnce() {
    if (!bound.story && byId("wow-story-cards")) {
      bindStoryCards();
      bound.story = true;
    }
    if (!bound.exportBtn && byId("wow-export-png")) {
      byId("wow-export-png").addEventListener("click", () => exportPNG());
      bound.exportBtn = true;
    }
    if (!bound.printBtn && byId("wow-print")) {
      byId("wow-print").addEventListener("click", () => {
        renderSummary();
        window.print();
      });
      bound.printBtn = true;
    }
    if (!bound.beforePrint) {
      window.addEventListener("beforeprint", () => guard("beforeprint", renderSummary));
      bound.beforePrint = true;
    }
    if (!bound.audio && byId("wow-audio-toggle")) {
      initAudio();
      bound.audio = true;
    }
  }

  // ------------------------------------------------------------------ //
  // 10. fairness — Gini sparkline + dashed equal line                    //
  // ------------------------------------------------------------------ //

  function pushGini() {
    const el = byId("wow-gini");
    if (!el) return;
    const st = appState();
    const snap = st && st.snap;
    if (!snap || snap.tick === lastGiniTick) return;
    lastGiniTick = snap.tick;
    const eq = snap.stats && snap.stats.equity;
    if (!eq || eq.gini == null) return;
    giniBuf.push(Number(eq.gini));
    while (giniBuf.length > KPI_CAP) giniBuf.shift();
    giniDirty = true;
    const val = byId("wow-gini-val");
    if (val) {
      const delta = giniBuf.length > 1 ? giniBuf[giniBuf.length - 1] - giniBuf[0] : 0;
      val.textContent =
        "Gini " + num(eq.gini, 3) +
        (giniBuf.length > 1 ? " (" + (delta >= 0 ? "+" : "") + num(delta, 3) + ")" : "");
    }
  }

  function drawGini() {
    const cv = byId("wow-gini");
    if (!cv || giniBuf.length < 2) return;
    const P = palette();
    const g = fitCanvas(cv);
    const c = g.c;
    if (!c) return;
    giniDirty = false;
    const w = g.w, h = g.h;
    const pad = 8;
    const hi = Math.max(0.3, Math.max.apply(null, giniBuf) * 1.15);
    const X = (i) => pad + (i * (w - pad * 2)) / Math.max(1, giniBuf.length - 1);
    const Y = (v) => h - pad - (clamp(v, 0, hi) / hi) * (h - pad * 2 - 10);

    c.setLineDash([4, 4]);
    c.strokeStyle = P.ok;
    c.lineWidth = 1;
    c.beginPath();
    c.moveTo(pad, Y(0));
    c.lineTo(w - pad, Y(0));
    c.stroke();
    c.setLineDash([]);
    c.font = "9px ui-monospace, monospace";
    c.fillStyle = P.ok;
    c.textAlign = "right";
    c.fillText("EQUAL LINE (0.000)", w - pad, Y(0) - 4);

    const pts = giniBuf.map((v, i) => [X(i), Y(v)]);
    c.globalAlpha = 0.22;
    c.fillStyle = P.fair;
    c.beginPath();
    c.moveTo(pts[0][0], Y(0));
    pts.forEach((p) => c.lineTo(p[0], p[1]));
    c.lineTo(pts[pts.length - 1][0], Y(0));
    c.closePath();
    c.fill();
    c.globalAlpha = 1;
    line(c, pts, P.fair, 1.8);
    const last = pts[pts.length - 1];
    c.fillStyle = P.fair;
    c.beginPath();
    c.arc(last[0], last[1], 2.4, 0, Math.PI * 2);
    c.fill();
  }

  // ------------------------------------------------------------------ //
  // 11. phase banner — 4s hysteresis between phase switches              //
  // ------------------------------------------------------------------ //

  const PHASES = {
    standby: ["SYSTEM STANDBY", "waiting for a run"],
    deploy: ["DEPLOYMENT", "fleet rolling out"],
    respond: ["ACTIVE RESPONSE", "units en route"],
    surge: ["DISPATCH SURGE", "queue pressure on the fleet"],
    disruption: ["ROUTE DISRUPTION", "blockage on the network — D* Lite repairing"],
    recovery: ["RECOVERY", "queue draining, zones rebalancing"],
    complete: ["RUN COMPLETE", "final metrics locked"],
  };

  const PHASE_HOLD_MS = 4000;
  const phaseState = { key: "", since: 0 };

  function computePhase(snap) {
    const dot = byId("status-dot");
    if (dot && dot.className.indexOf("dot-finished") >= 0) return "complete";
    if (!snap) return "standby";
    const s = snap.stats || {};
    const tick = snap.tick || 0;
    if (lastBlockTick != null && tick - lastBlockTick < 80) return "disruption";
    if ((s.queue || 0) > 0 || (s.active || 0) >= 4) return "surge";
    if ((s.incidents_reported || 0) === 0) return "deploy";
    if ((s.active || 0) <= 1 && (s.queue || 0) === 0) return "recovery";
    return "respond";
  }

  function renderPhase() {
    const el = byId("wow-phase");
    if (!el) return;
    const st = appState();
    const snap = st && st.snap;
    const key = computePhase(snap);
    const now = performance.now();
    const keyChanged = key !== phaseState.key;
    if (keyChanged) {
      if (phaseState.key && now - phaseState.since < PHASE_HOLD_MS) return;
      phaseState.key = key;
      phaseState.since = now;
      const p = PHASES[key] || PHASES.respond;
      el.className = "wow-phase wow-phase--" + key;
      el.setAttribute("data-phase", key);
      el.innerHTML =
        '<span class="wow-phase__dot"></span><span class="wow-phase__label">' +
        p[0] +
        '</span><span class="wow-phase__note">' +
        p[1] +
        "</span>";
    }

    const ind = byId("wow-phase-indicator");
    if (ind) {
      const stats = snap ? snap.stats : null;
      const nAmbs = snap && snap.ambulances ? snap.ambulances.length : 16;
      const nHosps = snap && snap.hospitals ? snap.hospitals.length : 4;
      const cleared = stats ? (stats.incidents_cleared || 0) : 0;
      const reported = stats ? (stats.incidents_reported || 0) : 0;

      let indLabel = "DISPATCH READY";
      let indMetrics = `${nAmbs} UNITS · ${nHosps} HOSPITALS`;

      if (key === "complete") {
        indLabel = "100% COVERAGE VERIFIED";
        indMetrics = `${cleared}/${reported} CLEARED · ALL HOSPITALS ACTIVE`;
      } else if (key === "surge") {
        indLabel = "CSP CAPACITY STRESS";
        indMetrics = "OPTIMIZING BED ASSIGNMENTS";
      } else if (key === "disruption") {
        indLabel = "ROUTE REPAIR ACTIVE";
        indMetrics = "D* LITE DYNAMIC REPLAN";
      } else if (key === "deploy") {
        indLabel = "FLEET MOBILIZING";
        indMetrics = `${nAmbs} UNITS DISPATCHED`;
      } else if (key === "respond") {
        indLabel = "ACTIVE OPERATIONS";
        indMetrics = `${cleared}/${reported} CLEARED · REAL-TIME AI`;
      } else if (key === "recovery") {
        indLabel = "FINALIZING RUN";
        indMetrics = `${cleared}/${reported} CLEARED · RETURNING`;
      }

      const sig = key + ":" + indLabel + ":" + indMetrics;
      if (ind.dataset.sig !== sig) {
        ind.dataset.sig = sig;
        ind.className = "wow-phase-indicator wow-phase-indicator--" + key;
        ind.innerHTML =
          '<span class="wow-phase-indicator__dot"></span><span class="wow-phase-indicator__label">' +
          indLabel +
          '</span><span class="wow-phase-indicator__metrics">' +
          indMetrics +
          "</span>";
      }
    }
  }

  // ------------------------------------------------------------------ //
  // 12. WebAudio FX — muted by default, visual pulses follow motion      //
  // ------------------------------------------------------------------ //

  const FX = {
    dispatch: { type: "square", f0: 660, f1: 990, dur: 0.09, gain: 0.05 },
    blockage: { type: "sawtooth", f0: 140, f1: 55, dur: 0.34, gain: 0.07 },
    clear: { type: "sine", f0: 523, f1: 784, dur: 0.2, gain: 0.06 },
  };

  const audio = {
    ctx: null,
    enabled: false,
    inited: false,
    lastAny: 0,
    lastKind: {},
    allowReducedMotion: false,
  };

  function audioApplyToggle() {
    const btn = byId("wow-audio-toggle");
    if (btn) {
      const stateEl = btn.querySelector(".wow-audio-state");
      if (stateEl) {
        stateEl.textContent = audio.enabled ? "ON" : "OFF";
      } else {
        btn.textContent = audio.enabled ? "SOUND: ON" : "SOUND: OFF";
      }
      btn.setAttribute("aria-pressed", audio.enabled ? "true" : "false");
      btn.classList.toggle("is-on", audio.enabled);
    }
  }

  function audioEnsure() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    if (!audio.ctx) {
      try {
        audio.ctx = new AC();
      } catch (e) {
        return false;
      }
    }
    if (audio.ctx.state === "suspended") {
      const r = audio.ctx.resume();
      if (r && r.catch) r.catch(() => {});
    }
    return true;
  }

  function audioPlay(kind) {
    if (!audio.enabled || !audio.ctx) return;
    // Reduced motion: visual and audio pulses are suppressed together;
    // FOAI_WOW.setAudioReducedMotionPolicy(true) opts back in.
    if (reducedMotion() && !audio.allowReducedMotion) return;
    const fx = FX[kind];
    if (!fx) return;
    const now = performance.now();
    if (now - audio.lastAny < 120) return;
    if (audio.lastKind[kind] && now - audio.lastKind[kind] < 220) return;
    try {
      const t = audio.ctx.currentTime;
      const osc = audio.ctx.createOscillator();
      const g = audio.ctx.createGain();
      osc.type = fx.type;
      osc.frequency.setValueAtTime(fx.f0, t);
      osc.frequency.exponentialRampToValueAtTime(fx.f1, t + fx.dur);
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(fx.gain, t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t + fx.dur);
      osc.connect(g);
      g.connect(audio.ctx.destination);
      osc.start(t);
      osc.stop(t + fx.dur + 0.02);
      audio.lastAny = now;
      audio.lastKind[kind] = now;
    } catch (e) { /* audio device denied */ }
  }

  function audioToggle() {
    audio.enabled = !audio.enabled;
    if (audio.enabled) audioEnsure();
    store(AUDIO_KEY, audio.enabled ? "1" : "0");
    audioApplyToggle();
  }

  function initAudio() {
    if (audio.inited) {
      audioApplyToggle();
      return;
    }
    audio.inited = true;
    audio.enabled = store(AUDIO_KEY) === "1";
    const btn = byId("wow-audio-toggle");
    if (btn) btn.addEventListener("click", audioToggle);
    audioApplyToggle();
  }

  // ------------------------------------------------------------------ //
  // Theme / motion reactions                                             //
  // ------------------------------------------------------------------ //

  function onThemeChange() {
    invalidatePalette();
    sparkDirty = true;
    giniDirty = true;
    guard("theme", () => {
      for (const id of ["wow-story-cards", "wow-ticker", "wow-hospital-loads"]) {
        const el = byId(id);
        if (el) el.removeAttribute("data-sig");
      }
      phaseState.since = 0;
      renderPhase();
      renderStoryCards();
      renderTicker();
      renderHospitalLoads();
      pushSummary();
    });
  }

  // ------------------------------------------------------------------ //
  // Main loops + bootstrap                                               //
  // ------------------------------------------------------------------ //

  const bound = {
    story: false,
    exportBtn: false,
    printBtn: false,
    beforePrint: false,
    audio: false,
  };

  function maintain() {
    guard("hooks", ensureHooks);
    guard("replay-hook", installReplayHooks);
    guard("fetch-hook", patchFetchForBenchmark);
    guard("bind", bindOnce);
  }

  function poll() {
    guard("maintain", maintain);
    const fresh = guard("drain", drainEvents) || [];
    if (fresh.length) guard("fanout", () => fanout(fresh));
    guard("story", renderStoryCards);
    guard("ticker", renderTicker);
    guard("hospital", renderHospitalLoads);
    guard("kpi", pushKpi);
    guard("gini", pushGini);
    guard("trails", pushTrails);
    guard("phase", renderPhase);
    guard("summary", pushSummary);
    guard("replay-drain", drainReplayQueue);
  }

  function isAnalyzeTabVisible() {
    const ana = byId("view-analyze");
    if (!ana) return true;
    return !ana.classList.contains("hidden");
  }

  function drawFrame() {
    if (isAnalyzeTabVisible()) {
      if (sparkDirty) guard("spark", drawSpark);
      if (giniDirty) guard("gini-draw", drawGini);
    }
    guard("trails-draw", drawTrails);
    requestAnimationFrame(drawFrame);
  }

  function watchDom() {
    if (!window.MutationObserver) return;
    // Retry observer: hooks (or the Command/Analyze shell that hosts them)
    // may be injected after boot — e.g. a deferred app.js or a late tab
    // restructure. Debounced so our own DOM writes settle immediately.
    let pending = false;
    const mo = new MutationObserver(() => {
      if (pending) return;
      pending = true;
      setTimeout(() => {
        pending = false;
        guard("maintain", maintain);
      }, 120);
    });
    try {
      mo.observe(document.documentElement, { childList: true, subtree: true });
    } catch (e) { /* observer unsupported */ }

    try {
      new MutationObserver(() => onThemeChange()).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });
    } catch (e) { /* observer unsupported */ }
  }

  function init() {
    guard("init", () => {
      maintain();
      watchDom();
      renderSummary();
      renderPhase();
      window.addEventListener("foai:theme", onThemeChange);
      window.addEventListener("foai:view-change", (e) => {
        if (e && e.detail && e.detail.view === "analyze") {
          sparkDirty = true;
          giniDirty = true;
        }
      });
      setInterval(() => guard("poll", poll), POLL_MS);
      requestAnimationFrame(drawFrame);
      poll();
    });
  }

  window.FOAI_WOW = {
    version: VERSION,
    hospitalLoadData: hospitalLoadData,
    // app.js drives these directly on snapshot / run-end / replay frames; the
    // 250ms poll below stays as a safety net when the guarded call is absent.
    renderHospitalLoads: (snap) => guard("hospital", () => renderHospitalLoads(snap)),
    onRunFinished: (snap) => guard("run-finished", () => onRunFinished(snap)),
    drainReplayQueue: () => guard("replay-drain", drainReplayQueue),
    onReplayEnd: (count) => guard("replay-end", () => onReplayEnd(count)),
    resetRunState: () => guard("reset-run", resetRunState),
    exportPNG: exportPNG,
    renderSummary: renderSummary,
    renderBenchDelta: renderBenchDelta,
    ensureHooks: () => guard("hooks", ensureHooks),
    hookStatus: () =>
      HOOK_IDS.map((id) => ({
        id: id,
        present: !!byId(id),
        auto: autoCreated.has(id),
        internal: INTERNAL_IDS.has(id),
        view: viewOf(byId(id)),
      })),
    theme: currentTheme,
    reducedMotion: reducedMotion,
    replayFrames: () => replay.frames.slice(),
    setAudioEnabled: (on) => {
      audio.enabled = !!on;
      if (audio.enabled) audioEnsure();
      store(AUDIO_KEY, audio.enabled ? "1" : "0");
      audioApplyToggle();
    },
    isAudioEnabled: () => audio.enabled,
    setAudioReducedMotionPolicy: (allow) => {
      audio.allowReducedMotion = !!allow;
    },
    giniBuffer: () => giniBuf.slice(),
    kpiBuffer: () => ({
      tick: spark.tick.slice(),
      avg: spark.avg.slice(),
      p95: spark.p95.slice(),
    }),
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
