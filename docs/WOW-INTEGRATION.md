# FOAI "Wow" Layer — Integration Guide

An additive, self-bootstrapping presentation layer that sits **on top of** the
Command / Analyze dashboard. It never edits the application it decorates: every
feature binds to a documented hook ID, creates the container itself when one is
missing, and no-ops (silently, without throwing) when app.js is absent.

**Files this layer owns (the only files ever written):**

| File | Rule |
| --- | --- |
| `web/static/wow-features.js` | owned — the whole behaviour layer |
| `web/static/wow-features.css` | owned — token-only styling |
| `docs/WOW-INTEGRATION.md` | owned — this document |

**Protected (never edited by the layer):** `web/static/index.html`,
`web/static/app.js`, `web/static/style.css`, `web/main.py`, everything under
`core/`. The hook markup and the two insertion points below are already shipped
in `index.html`; the layer only reads them.

---

## 1. Insertion points (already in place)

```html
<!-- index.html line 57-58: after style.css -->
<link rel="stylesheet" href="/static/style.css">
<link rel="stylesheet" href="/static/wow-features.css">

<!-- index.html line 566-567: after app.js -->
<script src="/static/app.js"></script>
<script src="/static/wow-features.js"></script>
```

Order matters both times: the CSS layer aliases `style.css` tokens, and the
script reads globals `app.js` declares (`state`, `worldToScreen`,
`prepAnimation`, `scheduleDomUpdate`, `startReplayPlayback`) — always through a
guard, never by writing to them. The file is one classic-script IIFE that boots
on `DOMContentLoaded` (or immediately if the DOM is already parsed) and exports
`window.FOAI_WOW`.

## 2. View contract

The dashboard is two tab panels (the segmented tablist at the top of the page):

| View | Panel | Contains |
| --- | --- | --- |
| Command | `#view-command` (`role="tabpanel"`) | `#left-col` — HUD row, story cards, map card (`#map-shell`), ticker, hospital load |
| Analyze | `#view-analyze` (`role="tabpanel"`) | `#right-col` — sparkline, Gini, benchmark delta, replay scrubber, capture |

The layer resolves a view with this selector order (first hit that is a real
container wins):

1. `[data-view="…"]` / `[data-panel="…"]`
2. `#view-command` / `#view-analyze`
3. the flat pre-tab layout `#left-col` / `#right-col`
4. `#main-layout` as the last resort, so a hook can always be placed once the
   shell exists

Map overlays (`#wow-trails`, `#wow-blockage-flash`) anchor to `#map-shell`
wherever the map is, independent of tabs. A hidden view is fine: canvases
report 0×0, redraw on the next frame after the tab becomes visible, and never
throw.

## 3. Hook table

Every hook is **optional** — present markup wins, otherwise the layer builds the
documented container in that view. `auto-created` marks the fallback path
(`data-wow="auto"`).

| ID(s) | Feature | View | Shipped location | Auto-create anchor |
| --- | --- | --- | --- | --- |
| `#wow-phase`, `#wow-audio-toggle` | Phase banner + sound toggle | Command | HUD row at the top of `#left-col` | wraps both in `#wow-hud`, inserted first in the view (internal) |
| `#wow-story-cards` | Scenario story cards | Command | "SCENARIO BRIEFS" card | new card before the map card (after the HUD) |
| `#wow-ticker` | Live incident ticker (5 items, 15 s TTL) | Command | "LIVE TICKER (15s)" card | appended to the view |
| `#wow-hospital-loads` | Hospital load bars | Command | "HOSPITAL LOAD" card | appended to the view |
| `#wow-trails` | Unit trail polylines | Map | inside `#map-shell`, after `#map` | after `#map`, else first child of `#map-shell` |
| `#wow-blockage-flash` | Blockage reveal pulse | Map | inside `#map-shell` | appended to `#map-shell` |
| `#wow-spark-kpi` | KPI sparkline (60 pts) | Analyze | "RESPONSE TIME" card after `#stats-cards` | after that card, else appended to the view |
| `#wow-gini-val`, `#wow-gini` | Gini value + sparkline | Analyze | after `#fairness-box` | next to `#fairness-box` / existing canvas |
| `#wow-bench-delta` | Benchmark delta table | Analyze | after `#benchmark-box` | after `#benchmark-box`, else appended |
| `#wow-replay`, `#wow-replay-label`, `#wow-replay-play`, `#wow-replay-slider`, `#wow-replay-rate` | Replay scrubber | Analyze | "REPLAY SCRUBBER" card | appended as a full card |
| `#wow-export-png`, `#wow-print`, `#wow-summary-card` | Export PNG / print / summary | Analyze | "CAPTURE" card | whole card if both buttons are gone; summary alone re-inserts after `.wow-actions` |
| `#wow-hud` | internal HUD wrapper | Command | not in markup | created only when phase/sound have to be auto-built (flagged `internal: true` in `hookStatus`) |

## 4. Self-bootstrapping contract

- `ensureHooks()` is idempotent, only ever adds nodes it can parse, and is
  re-run by three triggers:
  1. a 250 ms poll (also drives rendering: ticker, hospital bars, KPI/Gini
     buffers, trails, phase, summary, event drain, replay drain);
  2. a debounced `MutationObserver` (`childList`, subtree, 120 ms) — catches a
     late tab restructure or injected shell;
  3. boot itself.
- Staged binding (`bindOnce`) is likewise retried by the poll until app.js
  exists: story-card click delegation, export/print buttons, `beforeprint`,
  audio toggle, the replay takeover, and the benchmark `fetch` wrap.
- Theme is tracked two ways: a `MutationObserver` on `<html data-theme>` and the
  `foai:theme` event; canvases re-read `--wow-*` tokens on change.
- Nothing may throw when app.js is absent: `state` is read via
  `typeof state !== "undefined"`, `window[name]` helpers via a function guard,
  and every feature body runs inside `guard(label, fn)` which logs
  `[wow:label]` and moves on.

## 5. How the layer stays non-invasive

- **Globals:** reads only. `state` is a bare global identifier in app.js —
  never assigned.
- **Replay:** when the scrubber is present, `window.startReplayPlayback` is
  replaced with a no-op (identity-checked, retried until app.js lands) so
  app.js's 90 ms queue drain does not fight the slider; the layer drains
  `state.replayQueue` itself into a sorted 1500-frame list. Without the
  element, the original replay path is untouched.
- **Benchmark:** `window.fetch` is wrapped once; only `POST …/benchmark` is
  observed, the response is `clone()`d for `renderBenchDelta`, and the original
  `Response` is handed straight back to app.js.
- **Events:** consumed through a cursor over `state.events`, never mutated;
  duplicate summaries are deduped by signature.
- **Styling:** only `wow-*` IDs/classes are styled. Colours come from `--wow-*`
  tokens that alias `style.css` tokens (`--bg`, `--surface`, `--text`, `--line`,
  `--ops`, `--font-*`) with `rgb()` fallbacks, so the layer renders even if
  style.css is missing. Hex appears solely in the semantic dual-tones
  (`--wow-pos`, `--wow-neg`) and their light-theme overrides. The only
  `box-shadow` in the layer is on the blockage overlay (`#wow-blockage-flash`
  plus its pulse keyframes) — the fresh ticker row uses an `outline`.

## 6. Theme, print, reduced motion, audio

- **Theme:** reads `<html data-theme>` (`dark` / `light`) — the same attribute
  app.js's single theme writer sets. In light mode the dual-tones darken for
  contrast (`--wow-pos: #059669`, `--wow-neg: #e11d48`); every other colour
  follows `style.css` tokens automatically. Canvases (spark, Gini, trails) pull
  their palette through `getComputedStyle` on each theme change.
- **Print:** `@media print` drops the interactive chrome (actions, scrubber,
  sound toggle, ticker) and forces the remaining cards to white/black.
- **Reduced motion — two parallel paths:**
  1. `@media (prefers-reduced-motion: reduce)` — works with no app.js at all;
  2. `[data-motion="reduce"] …` — the attribute app.js mirrors from that same
     media query (`<html data-motion="reduce|full">`), so a JS-forced reduce
     lands here too.

  Both disable transitions/animations (cards, bars, ticker, phase dot), hide
  the trails canvas, and turn the blockage pulse into a static ring. On the JS
  side: trails are not sampled, audio pulses are suppressed, and the flash
  element still appears (opacity only) so the alert is never lost. Opt audio
  back in under reduced motion with `FOAI_WOW.setAudioReducedMotionPolicy(true)`.
- **Audio:** WebAudio FX (dispatch / blockage / clear), **muted by default**,
  toggled by `#wow-audio-toggle` and persisted in
  `localStorage["foai.wow.audio"]`.

## 7. `window.FOAI_WOW` API

| Member | Purpose |
| --- | --- |
| `version` | layer version string (`"1.1.0"`) |
| `ensureHooks()` | idempotent hook creation; returns true when all required hooks exist |
| `hookStatus()` | `[{id, present, auto, internal, view}]` for every hook |
| `theme()` / `reducedMotion()` | current `<html data-theme>` / OS media query |
| `kpiBuffer()` / `giniBuffer()` | ring-buffer snapshots (`{tick, avg, p95}` / gini points) |
| `replayFrames()` | copied replay frame list |
| `hospitalLoadData()` | parsed hospital loads for external consumers |
| `renderSummary()` / `renderBenchDelta(data)` | manual re-render entry points |
| `exportPNG()` | header + map composite download |
| `setAudioEnabled(on)` / `isAudioEnabled()` | programmatic sound control |
| `setAudioReducedMotionPolicy(allow)` | opt audio pulses back in under reduced motion |

## 8. Scenario context (`core/scenarios.py`, additive)

Six scenarios ship: `downtown-rush`, `storm-disaster`, `quiet-night`,
`gridlock`, `chokepoint-catastrophe`, `hospital-surge`. The last two are
additive entries (no existing scenario touched):

- `chokepoint-catastrophe` — permanent river blockages at t=0 on the five odd
  column bridges with timed waves that always leave ≥2 bridges open (the graph
  never disconnects), plus early/late hidden flaps and one visible cut.
  Incidents are capped at **severity ≤ 4** on purpose: a severity-5 (LRTA*)
  unit whose route is later reset by a blockage replan leaves a stale
  `amb.lrta.position` and crashes `_extend_lrta` with `KeyError` in
  `core/engine.py` (off-limits, so the scenario is designed around it).
- `hospital-surge` — high concurrency, `"blockages": []`, `ambulance_count: 16`,
  `max_ticks: 1800`: keeps severity-5 dispatches (CSP backtracking pressure)
  while guaranteeing zero blockage replans, so the LRTA*/blockage interaction
  can never trigger.

## 9. Verification

```powershell
node --check "web\static\wow-features.js"                      # → SYNTAX OK
python -m pytest tests/test_engine.py -q                        # → 17 passed
python -c "from core.scenarios import scenario_summaries; print([s['id'] for s in scenario_summaries()])"
# → ['downtown-rush', 'storm-disaster', 'quiet-night', 'gridlock',
#    'chokepoint-catastrophe', 'hospital-surge']
python run_web.py                                              # → http://127.0.0.1:8000/
```

In the browser console:

```js
FOAI_WOW.version                                   // "1.1.0"
FOAI_WOW.hookStatus().filter(h => !h.present && !h.internal)   // []
```

Manual smoke test (verified live against the integrated page):

1. Open the dashboard → six story cards, active scenario outlined, phase shows
   a standby label, sound reads `SOUND: OFF` (`aria-pressed="false"`).
2. Press **START** → ticker fills from `state.events` (fresh row outlined,
   15 s TTL), hospital bars animate, KPI/Gini buffers grow, phase walks
   `DEPLOYMENT → ACTIVE RESPONSE → …` with 4 s hysteresis; trails draw behind
   units (Command view only).
3. Switch to **Analyze** → spark/Gini canvases size themselves to the visible
   panel (hidden views stay 0×0 without errors).
4. Press **BENCHMARK** → `6 RUNS · SEEDS 1–3` and the delta table renders
   under `#benchmark-box` with SMART-vs-baseline chips (the wrapped `fetch`
   hands the original response back; app.js's own status still updates).
5. Press **REPLAY** → scrubber takes over (`frame n/1500`, play/pause, 1–8x),
   app.js auto-play stays off.
6. Toggle the theme → light mode: darkened dual-tones, token-driven greys;
   toggle back → dark defaults.
7. Force `<html data-motion="reduce">` → trails hidden, blockage flash static
   ring, transitions killed.
8. Strip every `#wow-*` node and call `FOAI_WOW.ensureHooks()` → all hooks are
   recreated in the right views (`hookStatus().filter(h => !h.present &&
   !h.internal)` → `[]`), `#wow-hud` wraps phase+sound as a flex row, no
   duplicates. Reload to restore the shipped markup.
