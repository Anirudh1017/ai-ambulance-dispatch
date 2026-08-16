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
python -m pytest tests -q        # 55 tests: optimality, CSP backtracks,
                                 # value-iteration residual, engine invariants
python -m pytest tests/test_engine.py -q   # UI contract (snapshot/events/replay)
```

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