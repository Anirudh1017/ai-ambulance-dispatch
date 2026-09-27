# Changelog

All notable changes to the AI-Based Ambulance Dispatch & Routing System are
recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Nothing yet.

---

## [0.4.0] —â€ 2026-09-27

Dashboard overhaul, status-chip and launcher fixes, and the presentation layer
being brought under version control for the first time.

### Added
- **`wow-features` presentation layer** (`web/static/wow-features.js`,
 `wow-features.css`) —â€ a phase indicator that derives the current operational
 phase (deploy / respond / surge / disruption / recovery / complete) from the
 live engine snapshot. Includes `prefers-reduced-motion` and
 `[data-motion="reduce"]` variants.
- **Verification scripts** —â€ `verify_idle_dot.py` (regression guard for the
 status-chip dot; measures computed pixels in both themes, exercises the real
 start/pause flow, and neutralises the CSS rule at runtime to prove the guard
 is not vacuous), plus `verify_7_fixes.py` and `verify_all_updates.py`.
- **Project documentation** —â€ `FOAI_Project_Report.md`, the
 `Project_Review_1_Presentation.pptx` deck, `docs/WOW-INTEGRATION.md`, and
 the `generate_diagrams.py` / `generate_ppt.py` generators.

### Fixed
- **IDLE status indicator was invisible** (`web/static/style.css`). The
 `.dot-idle` class had *no* CSS rule at all. The base `.dot` class sets only
 geometry and deliberately no background —â€ colour always came from the state
 modifier —â€ and every sibling state had one except idle. The 8px circle
 therefore rendered fully transparent while still occupying space, so the
 status chip read `IDLE` with a blank left-hand side. The text label was
 never affected, because it is driven from the class name by a
 `MutationObserver` independently of the paint. Idle is now a hollow ring
 (transparent fill, 1px `--muted` border); since `box-sizing: border-box` is
 global, the border draws inside the 8px box and the chip does not grow. A
 ring also reads as "no engine attached yet", staying visually distinct from
 paused, finished and running, and it adapts to both themes via the existing
 token.
- **`run_server.bat` exited silently after ~1 second** and left the browser
 showing "refuse to connect". Not a crash: a stale server already held port
 8000, so the new instance died instantly with `WinError 10048` and the error
 scrolled past before the window closed.
 - The launcher now probes the port first. If free it starts normally; if a
  server is already serving it reports that the dashboard is *already live*
  and opens the browser; on any other failure it `pause`s so the window
  stays open and readable, printing the `netstat` / `taskkill` recovery
  steps inline.
 - Interpreter resolution no longer hard-codes an absolute path to a specific
  `python.exe`; it uses `python` from `PATH` and falls back to the `py -3`
  launcher.
 - It now `cd`s to `%~dp0`, so it works from any caller's directory.
- **`run_web.py` failed opaquely on a busy port.** Added a matching socket
 pre-flight check that prints a clear message and exits 0 instead of an
 opaque uvicorn traceback. `HOST` / `PORT` / `URL` are now module constants
 and the entry point returns an exit code.
- **Scenario and benchmark refinements** —â€ reworked scenario configurations
 (grid and cell sizing, incident schedules, per-scenario idle-reposition
 cadence), tightened bed-capacity accounting, and corresponding
 NaN/Inf sanitisation in the benchmark layer.

### Changed
- `web/static/app.js` and `web/static/index.html` —â€ large UI revision
 introducing the command/analyze view split and the equity, re-negotiation and
 baseline surfaces.
- `web/main.py` —â€ transport-layer changes backing the new UI.
- `*.log` is now git-ignored. The launchers and the pytest/uvicorn runs emit
 logs into the repository root, they are regenerated on every start, and one
 is held open by a live server.

---

## [0.3.0] —â€ 2026-08-16

Empirical baseline study, equity metric, and CNP re-negotiation.

### Added
- **Per-zone response tracking and a Gini fairness metric**
 (`core/metrics.py`) —â€ a Gini-style coefficient over per-zone mean response
 (lower is fairer), plus zone variance, max/min ratio and best/worst zones.
 Travels in `stats.equity` and is reported per stack in the benchmark report.
- **Naive policy ablation study** —â€ every subsystem gained an explicit
 baseline: greedy nearest-available dispatch, full-A* rerun per change,
 return-to-station idle positioning, and first-free-bed hospital allocation.
- **Headless baseline-comparison harness** (`run_benchmark.py`) with
 `benchmark_out/` outputs: a per-run CSV, a markdown report (methodology,
 headline and per-scenario tables, equity deep-dive, discussion of threats to
 validity) and headless matplotlib charts. `--full` adds single-flip
 ablations that isolate each algorithm; `--quick` is a smoke run.
- **CNP re-negotiation** —â€ the dispatcher periodically re-auctions in-flight
 contracts among eligible units. The contract moves only when a challenger's
 ETA beats the incumbent's remaining ETA by at least
 `cnp.reassign_penalty_seconds` (the anti-thrash margin), with a per-incident
 cooldown to damp churn further. LRTA* urgent contracts and greedy-policy
 runs are exempt. Every move is a first-class explainability event
 (`dispatch.renegotiated`).
- **In-dashboard BENCHMARK trigger** —â€ `POST /benchmark` runs 3 seeds of smart
 vs naive for the current scenario and renders the summary inline, using the
 same `core.benchmark` harness.
- Equity, re-negotiation and baseline surfaces in **both** dashboards
 (web *ZONE FAIRNESS* panel, CLI fairness panel).

### Fixed
- Mangled `.gitignore` line —â€ restored the `*.png` and `benchmark_out/`
 patterns.

---

## [0.2.0] —â€ earlier development

Initial simulation core and the two dashboards.

- Weighted road graph, incidents, blockages, hospital capacity and fleet, with
 a tick engine exposing `snapshot()`, `events_since(cursor)` and
 `snapshot_at(tick)` for replay. Both dashboards consume only this contract,
 so the web and terminal versions are guaranteed to show the same simulation.
- Informed and uninformed search: weighted A*, greedy best-first, Dijkstra and
 BFS, each recording expansions, frontier size, duration and optimality.
- `LRTAStar` real-time heuristic search (Kuo & Sutcliffe; Korf 1990) —â€ the
 learned heuristic table and update trace are emitted as events.
- `DStarLite` incremental replanning (Koenig & Likhachev 2002) —â€ repairs only
 the affected search tree on discovery of a blocked road.
- Contract Net Protocol dispatch with explainable bid scoring (ETA, status,
 workload, distance) and backoff re-announcement.
- CSP hospital allocation with backtracking, MRV, LCV and forward checking.
- MDP idle positioning solved exactly by value iteration to a Bellman residual
 below ÃŽÂε.
- FastAPI + WebSocket dashboard with an HTML5 canvas live map, and a Textual
 terminal dashboard with an ASCII map.

---

## Notes on determinism

Every run is reproducible from `--seed` (web: *Seed* field, CLI: `--seed`).
The same scenario and seed produce an identical run including the sequence of
decisions, since unit ids are seed-stable. The benchmark harness uses a fixed
documented seed schedule, so `benchmark_results.csv` reproduces bit-for-bit
except for wall-clock `runtime_ms`.

---

