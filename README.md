# AI-Based Ambulance Dispatch & Routing System

A pure-Python simulation of an emergency ambulance fleet, driven **entirely by
hand-specified classical AI** — no machine learning anywhere in the system.
Two complete user interfaces (a web dashboard and a terminal dashboard) share
one tick-based simulation core.

```
┌────────────────────────────────────────────────────────────┐
│                  SIMULATION CORE  (core/)                  │
│   weighted road graph · incidents · blockages · hospital   │
│   fleet · tick engine · snapshot()/events_since() stream   │
│                                                            │
│   dispatch → Contract Net Protocol (CNP)                   │
│   routing  → A* · weighted A* · GBFS · Dijkstra · BFS      │
│               LRTA* (real-time) · D* Lite (incremental)    │
│   hospital → CSP (backtracking + MRV + LCV + forward check)│
│   idle     → MDP solved by exact value iteration           │
└─────────────────────────────┬──────────────────────────────┘
              ┌───────────────┴───────────────┐
              ▼                               ▼
     web/main.py (FastAPI + WebSocket)   cli/app.py (Textual)
     HTML5 Canvas live map               ASCII live map
```

## Quick start

```bash
pip install -r requirements.txt

# web dashboard (http://127.0.0.1:8000)
python run_web.py

# terminal dashboard
python run_cli.py                 # or: --scenario storm-disaster --seed 7 --tps 8
```

## Scenarios

| id              | story                                                    |
|-----------------|----------------------------------------------------------|
| `downtown-rush` | 16-unit fleet from 4 stations, 20 calls — all four routing algorithms at work |
| `storm-disaster`| mass casualty: 18 units, 30 incidents, scarce beds — LRTA* real-time routing and CSP backtracking under scarcity |
| `quiet-night`   | sparse incidents — the MDP idle-positioning showcase     |
| `gridlock`      | pre-revealed blockages — D* Lite incremental replans     |

Every run is reproducible via `--seed` (web: Seed field, CLI: `--seed`).
Ambulances are based at **stations** (garage nodes on the map; units are
clustered around their station when idle). Scenario summary shows the fleet
size, station count and call load in the dashboard header.

## Classical-AI contents (no ML)

1. **Informed/uninformed graph search** (`core/search.py`)
   `astar` (weighted, optimal when weight = 1), `greedy_best_first`,
   `dijkstra`, `breadth_first`. Each result records expansions, frontier
   size, duration, optimality and heuristic admissibility/consistency
   checks — shown head-to-head in the "algorithm arena" panel.

2. **Real-time heuristic search** — `LRTAStar` (Kuo & Sutcliffe; Korf 1990).
   Severity-5 incidents are answered by a unit that learns its heuristic
   table while moving, one `act()` per junction. The learned h-values and
   update trace are emitted as events.

3. **Incremental replanning** — `DStarLite` (Koenig & Likhachev 2002).
   When a unit discovers a blocked road mid-route, the planner repairs
   only the affected search tree (`edge_cost_changed` + `replan`), and
   the dashboard counts the saved expansions.

4. **Multi-agent dispatch — Contract Net Protocol** (`core/dispatch.py`).
   For every 911 call the dispatcher announces the task; every free unit
   bids with an explainable score (ETA, status, workload, distance);
   the best bid wins; failed auctions re-announce after a backoff.

5. **Hospital allocation — CSP** (`core/hospital_allocation.py`).
   Bed capacity is a hard constraint solved with backtracking, MRV,
   LCV and forward checking. During mass-casualty events the solver
   genuinely backtracks, and the trace is shown in the event stream.

6. **Idle positioning — MDP solved exactly** (`core/mdp.py`).
   States = zones, actions = reposition to any zone, rewards =
   coverage(zone) − λ·travel, solved by value iteration to a Bellman
   residual below ε. The policy (and its sweep count) is displayed in
   the explainability panel.

**Blockages** provide the partial-observability story: hidden road
incidents are revealed only when a unit physically reaches the junction —
planners route on the visible cost, and discovery triggers D* Lite replans.

## Reproducibility

```bash
python -m pytest tests -q        # 105 tests: optimality, CSP backtracks,
                                 # value-iteration residual, engine invariants,
                                 # baselines, equity, re-negotiation, benchmark
python -m pytest tests/test_engine.py -q   # UI contract (snapshot/events/replay)
```

## Empirical baseline-comparison study (`run_benchmark.py`)

Every subsystem has an explicit **naive baseline** next to its smart
algorithm (never replacing it), toggleable per run through the engine
config `policies` dict:

| subsystem | smart | naive baseline |
|---|---|---|
| dispatch | CNP auction | greedy nearest available unit |
| replanning | D* Lite | full A* rerun per change |
| idle positioning | MDP value iteration | always return to home station |
| hospital allocation | CSP | first hospital with a free bed |

```bash
python run_benchmark.py            # 4 scenarios × 30 seeds × 2 stacks
python run_benchmark.py --full     # + 4 single-flip ablations (isolates each algorithm)
python run_benchmark.py --quick    # 1 scenario × 3 seeds (smoke)
```

Outputs into `benchmark_out/`: `benchmark_results.csv` (every run, one row),
`benchmark_report.md` (methodology, headline + per-scenario tables, equity
deep-dive, honest discussion, AI-concept mapping, threats to validity) and
`charts/*.png` (matplotlib, Agg — headless). Each cell is deterministic for
a given seed; the harness uses a fixed documented seed schedule, so the
CSV reproduces bit-for-bit (except wall-clock `runtime_ms`). The web
dashboard has a smaller **BENCHMARK** button (POST `/benchmark`) that runs
3 seeds of smart vs naive for the current scenario and renders the summary
inline — the same `core.benchmark` harness.

Key metric fields: response time (mean/p95/variance), per-zone **Gini
coefficient** and zone variance, workload spread (max−min unit load),
distance, replans + D* Lite expansion savings vs a measured full-rerun
counterfactual, CSP backtracks, MDP solves, CNP re-negotiations and saved
seconds.

## Fairness / equity metric

Per-zone response times are tracked for every cleared incident (reusing the
`ZoneMap` zones). `core/metrics.py` computes a Gini-style coefficient over
per-zone mean response — lower is fairer — plus zone variance, the
max/min ratio, and best/worst zones. The equity block travels in
`stats.equity`, is shown in **both** dashboards (web: ZONE FAIRNESS panel
with heat strip + table; CLI: fairness panel) and is reported per stack in
the benchmark report (MDP idle positioning vs return-to-station).

## CNP re-negotiation (dynamic task re-allocation)

While a unit is still travelling to its scene, the dispatcher periodically
re-auctions the contract among currently eligible units
(`cnp.renog_check_every` ticks). The contract moves **only** when a
challenger's ETA beats the incumbent's remaining ETA (edge-progress aware)
by at least `cnp.reassign_penalty_seconds` (default 60 s) — the
anti-thrash margin — and a per-incident cooldown
(`renog_cooldown_ticks`) damps churn further. LRTA* urgent contracts and
greedy-policy runs are exempt. Every re-negotiation is a first-class
explainability event (`dispatch.renegotiated`) carrying the old/new unit,
ETAs before/after, penalty and reason; the re-auction itself is a fully
marked transcript (`dispatch.auction.*` with `renegotiation: true`).
Totals appear as `renegotiations` / `renegotiation_savings_s` KPIs in both
UIs.

## Architecture notes

- **One core, two UIs.** The engine exposes `snapshot()` (full serialisable
  state), `events_since(cursor)` (decision events with explainability
  detail) and `snapshot_at(tick)` (replay). Both dashboards consume only
  this contract, so the web and terminal versions are guaranteed to show
  the same simulation.
- **Everything in memory.** No database; a scenario runs to `max_ticks`
  in well under a second, so replays are served straight from a snapshot
  ring buffer.
- **Deterministic.** Same scenario + seed ⇒ identical run, including the
  sequence of decisions (unit ids are seed-stable).