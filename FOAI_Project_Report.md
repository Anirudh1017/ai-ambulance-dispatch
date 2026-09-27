# AI-Based Ambulance Dispatch & Routing System — FOAI Project Report

> **Project:** AI-Based Ambulance Dispatch & Routing System  
> **Core Stack:** Pure Python · Classical AI Only (No ML)  
> **Engine:** `core/` tick-based simulation · Dual UI: `web/main.py` (FastAPI + WebSocket) & `cli/app.py` (Textual)  
> **Reproducibility:** Deterministic by `--seed` · 105 pytest tests · `run_benchmark.py` harness  
> **Generated:** 2026-09-14 · Source: `C:/Users/sanir/FOAI Project`

---

## 1. Problem Statement

Emergency Medical Services (EMS) must dispatch a limited ambulance fleet to stochastic, time-critical incidents over a dynamic, partially-observable road network under hard hospital-bed constraints.

**Formal problem:** Given a weighted road graph `G=(V,E,w)`, a fleet `A` stationed at garage nodes, a stream of incidents `I = {(node, severity, kind, tick)}` with severity-dependent deadlines `{1:540s, 2:420s, 3:300s, 4:210s, 5:120s}`, hidden edge blockages revealed only on physical arrival, and hospitals `H` with finite beds — minimize mean/p95 response time and zone Gini inequity while maximizing on-time deadline adherence.

**Five sub-problems the project solves:**

1. **Optimal Dispatch** — *Which unit to which call?* Naive nearest-available is sub-optimal under heterogeneous status/workload/distance.
2. **Optimal Routing** — Shortest path under weighted edges; plus *dynamic replanning* when a road is discovered blocked mid-route.
3. **Resource Allocation** — Assign patients to hospitals without violating hard bed-capacity, especially during mass-casualty scarcity.
4. **Idle Positioning** — Where should idle units wait to maximize *future* coverage, not just return to base?
5. **Fairness & Dynamism** — Equitable response across city zones (`ZoneMap`) and *en-route* re-allocation when a strictly better unit becomes free.

**Objectives & Constraints:** Minimize `mean_response`, `p95_response`, `workload_spread (max-min)`, `Gini(zone_means)`; respect `free_beds(h) >= 0` and `severity deadlines`; operate under partial observability (planners route on *visible* cost).

---

## 2. Abstract

This project presents a pure-Python, tick-based simulation of an emergency ambulance fleet driven **entirely by hand-specified classical AI — no machine learning anywhere**. A single simulation core (`core/engine.py`) implements a 7-stage tick pipeline (world update → incident spawn → CNP dispatch → movement → scene/transport/CSP → MDP idle positioning → D* Lite replanning) and exposes a UI-agnostic contract `snapshot()` / `events_since(cursor)` / `snapshot_at(tick)` consumed identically by a FastAPI + WebSocket web dashboard (HTML5 Canvas live map) and a Textual terminal dashboard (ASCII live map).

Six classical paradigms are integrated: **(i)** Informed/Uninformed graph search (A*, Weighted A*, GBFS, Dijkstra, BFS) with an `algorithm_arena` head-to-head panel; **(ii)** **LRTA*** real-time heuristic search (Korf 1990) for severity-5 urgent calls that learns its heuristic table while moving; **(iii)** **D* Lite** incremental replanning (Koenig & Likhachev 2002) that repairs only the affected search tree on hidden-blockage discovery; **(iv)** **Contract Net Protocol** multi-agent dispatch with explainable scored bids and anti-thrash re-negotiation; **(v)** **CSP** hospital allocation via backtracking + MRV + LCV + forward checking; and **(vi)** **MDP** idle positioning solved exactly by value iteration to a Bellman residual < ε.

Every subsystem has an explicit naive baseline (`core/policies.py`) for a controlled empirical study (`run_benchmark.py`: 4 scenarios × 30 seeds × 2 stacks + 4 single-flip ablations) reporting response time, distance, replans/expansion savings, CSP backtracks, Gini equity, workload spread, and re-negotiation savings into `benchmark_out/`. The system is deterministic, in-memory (snapshot ring buffer replay), fully explainable via a typed event stream (`core/events.py`), and validated by 105 tests. Diagrams: `diagram_architecture.png`, `diagram_cnp_flow.png`, `diagram_search_methods.png`.

**Keywords:** Classical AI, A* Search, D* Lite, LRTA*, Contract Net Protocol, CSP, MDP, Value Iteration, Gini Equity, EMS

---

## 3. Literature Review

| # | AI Concept | Foundational Literature | How Project Implements (`file:symbol`) |
|---|------------|------------------------|----------------------------------------|
| 1 | **Informed Search — A*** | Hart, Nilsson & Raphael (1968). *A Formal Basis for the Heuristic Determination of Minimum Cost Paths.* | `core/search.py: astar()` with Euclidean heuristic, weight parameter (optimal when w=1). Records expansions, frontier size, duration, optimality, admissibility/consistency checks. |
| 2 | **Weighted A* & GBFS** | Pohl (1970) Weighted A*; Doran & Michie (1966) GBFS | `core/search.py: astar(weight>1)`, `greedy_best_first()` — suboptimal but faster; compared in arena. |
| 3 | **Uninformed Search** | Dijkstra (1959); BFS | `core/search.py: dijkstra()`, `breadth_first()` — optimal/uninformed baselines. |
| 4 | **Real-Time Search — LRTA*** | Korf (1990). *Real-Time Heuristic Search.* Kuo & Sutcliffe variant | `core/search.py: LRTAStar` — severity ≥5 incidents. One `act()` per junction; updates `H(s) ← min_{s'} c(s,s')+H(s')`; emits learned h-values trace. |
| 5 | **Incremental Search — D* Lite** | Koenig & Likhachev (2002). *D* Lite.* | `core/search.py: DStarLite` — `edge_cost_changed()` + `replan()` repairs only inconsistent vertices (`g`/`rhs` + queue `U`); counts `expansions_saved` vs full A* counterfactual. |
| 6 | **Multi-Agent Coordination — CNP** | Smith (1980). *The Contract Net Protocol.* | `core/dispatch.py: CnpAuctioneer` — announce → bid (ETA+status+workload+distance scored) → award → re-announce on failure; `renog_check_every` + `reassign_penalty_seconds` (60s) + `renog_cooldown_ticks` for re-negotiation. |
| 7 | **Constraint Satisfaction — CSP** | Dechter (2003); Haralick & Elliott (1980) MRV/LCV/Forward Checking | `core/hospital_allocation.py: HospitalAllocator` — variables=patients, domains=hospitals with free beds, constraint=capacity; backtracking + MRV + LCV + forward checking; trace shown in events. |
| 8 | **Markov Decision Process — Value Iteration** | Bellman (1957). *Dynamic Programming.* | `core/mdp.py: IdlePositioningMDP` — states=zones, actions=reposition to any zone, reward=`coverage(zone) − λ·travel`, solved by synchronous value iteration `V_{k+1}(s)=max_a[R+γΣP·V_k]` to `max_delta < ε`; displays policy + sweep count. |
| 9 | **Fairness Metric — Gini** | Gini (1912); adapted for spatial equity | `core/metrics.py: zone_equity()` — Gini over per-zone mean response + zone variance + max/min ratio + best/worst zones; shown in ZONE FAIRNESS panel. |

All algorithms are hand-specified; no learning component exists in the codebase (`requirements.txt`: `fastapi`, `uvicorn`, `textual`, `matplotlib` only).

---

## 4. Existing System

The codebase explicitly retains **naive baselines** as the "existing system" for controlled comparison — toggleable per run via the `policies` dict (`core/policies.py: resolve_policies()`), never replacing the smart stack.

| Subsystem | Existing / Naive Baseline | How It Works | Limitations Observed (via `benchmark_out/benchmark_report.md`) |
|-----------|---------------------------|--------------|---------------------------------------------------------------|
| **Dispatch** | `greedy_nearest_dispatch()` | Assign nearest available unit by straight-line / shortest-path distance | Ignores unit status, current workload, severity; causes higher mean/p95 response and workload imbalance (higher `max-min` load). No re-negotiation. |
| **Replanning** | Full A* rerun per blockage | On discovering a blocked edge, discard old plan and run `astar()` from scratch | Wastes expansions; measured `expansions_saved` by D* Lite is lost; higher `runtime_ms` under `gridlock` / `storm-disaster`. |
| **Idle Positioning** | `always return to home station` | Idle units drift back to their garage node | Poor future coverage; higher zone Gini and zone variance — inequitable service. |
| **Hospital Allocation** | `first_free_hospital()` | First hospital with `free_beds() > 0` in list order | No constraint reasoning; under scarcity (`storm-disaster`: 30 incidents, scarce beds) causes higher handover delay and misses backtracking optimization; no load balancing. |

In practice these correspond to the manual / CAD-nearest-vehicle dispatch and static stationing still common in EMS operations — the benchmark harness quantifies exactly what classical AI improves over them.

---

## 5. Proposed System

### 5.1 Overview
One simulation core, two identical UIs, six classical AI modules, fully deterministic and explainable.

```
┌────────────────────────────────────────────────────────────┐
│                  SIMULATION CORE  (core/)                  │
│   RoadNetwork (grid graph) · ZoneMap · Hospital · Station  │
│   Incident · Ambulance · Blockage · Scenario Config        │
│   Tick Engine (engine.py): snapshot()/events_since()/      │
│                            snapshot_at(tick)               │
│                                                            │
│   AI MODULES                                               │
│   ├─ search.py: A*/Weighted A*/GBFS/Dijkstra/BFS           │
│   │             + LRTAStar (real-time) + DStarLite         │
│   ├─ dispatch.py: CNP Auctioneer + Re-negotiation          │
│   ├─ hospital_allocation.py: CSP Solver (MRV/LCV/FC)       │
│   ├─ mdp.py: MDP Value Iteration (exact)                   │
│   ├─ metrics.py: Gini & Equity                             │
│   └─ benchmark.py: Smart vs Naive Harness                  │
│   events.py: typed explainability event stream             │
└─────────────────────────────┬──────────────────────────────┘
              ┌───────────────┴───────────────┐
              ▼                               ▼
     web/main.py (FastAPI+WS)          cli/app.py (Textual)
     HTML5 Canvas live map             ASCII live map
     Algorithm Arena + Fairness        Same panels, terminal
```

*Source: `README.md` + `diagram_architecture.png` (generated by `generate_diagrams.py`)*

### 5.2 Tick Engine Pipeline (`core/engine.py`, 7 stages per tick)

1. **World Update** — scheduled blockages apply/expire; hidden blockages revealed when a unit reaches the junction.
2. **Incident Spawn** — scripted incidents from `core/scenarios.py` become `pending`.
3. **CNP Dispatch + Re-negotiation** — `CnpAuctioneer` auctions pending calls; en-route contracts re-auctioned every `cnp.renog_check_every` ticks if challenger ETA beats incumbent remaining ETA by ≥ `reassign_penalty_seconds` (default 60s) with `renog_cooldown_ticks` damping. LRTA* urgent and greedy-policy runs exempt.
4. **Movement** — units advance along routes at speed (edge-progress aware for ETA calc).
5. **Scene / Transport** — on-scene stabilisation → **CSP hospital allocation** → transport → handover → bed release.
6. **Idle Positioning** — every `idle_reposition_every` ticks, `IdlePositioningMDP` policy decides target zone.
7. **Replanning** — units whose remaining route hits a newly revealed blockage trigger `DStarLite.edge_cost_changed() + replan()`.

Search usage: dispatch routes → A*/Weighted A*; urgent (sev≥5) → LRTA*; blockage replans → D* Lite; arena panel → all four head-to-head per dispatch.

### 5.3 Scenarios (`core/scenarios.py`)

| id | Fleet | Calls | Highlight |
|----|-------|-------|-----------|
| `downtown-rush` | 16 units, 4 stations | 20 | All four routing algorithms at work |
| `storm-disaster` | 18 units | 30, scarce beds | CSP backtracking under scarcity |
| `quiet-night` | sparse | sparse | MDP idle-positioning showcase |
| `gridlock` | — | pre-revealed blockages | D* Lite incremental replans |

Every run reproducible via `--seed` (web: Seed field; CLI: `--seed`).

### 5.4 Key Advantages over Existing System
Optimal (A*), adaptive (D* Lite/LRTA*), constraint-sound (CSP), provably optimal idle policy (MDP), dynamically re-allocating (CNP re-negotiation), equitable (Gini-optimized), fully explainable (event stream), and empirically validated (benchmark + 105 tests).

---

## 6. Methodologies

### 6.1 Graph Search (Informed & Uninformed) — `core/search.py`
- **Graph:** `RoadNetwork` grid with weighted edges; `euclidean_heuristic` (admissible & consistent on grid).
- **Algorithms:** `astar(weight)`, `greedy_best_first`, `dijkstra`, `breadth_first` — each returns `SearchResult {path, cost, expansions, frontier_max, duration_ms, optimal, admissible, consistent}`.
- **Arena:** `algorithm_arena(start, goal, network)` runs all four on the same dispatch; results feed the "algorithm arena" panel.

### 6.2 Real-Time Search — LRTA* — `core/search.py: LRTAStar`
- Trigger: `severity >= 5`.
- Loop: at node `s`, lookahead to neighbours, pick `s' = argmin c(s,s')+H(s')`, update `H(s) ← c(s,s')+H(s')`, then `act()` moves one edge. Learning trace emitted as `events.lrta.*`.

### 6.3 Incremental Search — D* Lite — `core/search.py: DStarLite`
- Maintains `g`, `rhs`, priority queue `U` keyed by `k = [min(g,rhs)+h , min(g,rhs)]`.
- On discovery: `edge_cost_changed(u,v, INF)` marks affected vertices inconsistent; `replan()` repairs only that subtree.
- Dashboard counts `expansions_saved` vs measured full-A* counterfactual; `benchmark.py` reports savings.

### 6.4 Multi-Agent Dispatch — Contract Net Protocol — `core/dispatch.py`
- **Announce:** dispatcher broadcasts `Incident` to all `free` units.
- **Bid:** each unit scores `bid = w_eta*ETA + w_status*status_penalty + w_load*workload + w_dist*distance` (explainable breakdown in event).
- **Award:** best bid wins; failed auctions re-announce after backoff.
- **Re-negotiation:** periodic re-auction among eligible units; moves only if `challenger_ETA + penalty < incumbent_remaining_ETA` and cooldown elapsed. Events: `dispatch.auction.*` (`renegotiation:true`) + `dispatch.renegotiated {old,new,eta_before,eta_after,penalty}`; KPIs `renegotiations`, `renegotiation_savings_s`.

### 6.5 Hospital Allocation — CSP — `core/hospital_allocation.py`
- **Model:** Variables = patients needing transport; Domains = hospitals with `free_beds()>0`; Constraints = `Σ assigned(h) ≤ beds(h)` (hard).
- **Solver:** Depth-first backtracking + **MRV** (most constrained patient first) + **LCV** (least constraining hospital first) + **Forward Checking** (prune domains on assignment). Trace + `backtracks` count in events/stats; mass-casualty `storm-disaster` forces genuine backtracking.

### 6.6 Idle Positioning — MDP — `core/mdp.py`
- **MDP:** States = zones (`ZoneMap`), Actions = reposition to any zone, Transition = deterministic, Reward = `coverage(zone) − λ·travel_cost(s,a)` (λ from config), Discount `γ`.
- **Solver:** Synchronous **Value Iteration** until `max_s |V_{k+1}(s)-V_k(s)| < ε` (Bellman residual). Outputs optimal deterministic policy `π*(s)` + `sweeps` count; displayed in explainability panel. Baseline: return-to-station.

### 6.7 Evaluation & Fairness — `core/benchmark.py`, `core/metrics.py`, `core/report.py`
- **Benchmark harness:** `run_benchmark.py` — default `4 scenarios × 30 seeds × 2 stacks` (smart vs naive); `--full` adds 4 single-flip ablations isolating each algorithm. Fixed seed schedule → bit-for-bit reproducible CSV (except `runtime_ms`). Web `BENCHMARK` button runs 3-seed mini version.
- **Metrics per run:** `mean_response`, `p95_response`, `variance_response`, `zone Gini`, `zone_variance`, `max/min ratio`, `best/worst zones`, `workload_spread`, `distance`, `replans`, `expansions_saved`, `csp_backtracks`, `mdp_solves`, `renegotiations`, `renegotiation_savings_s`, `runtime_ms` → `benchmark_out/benchmark_results.csv`, `benchmark_out/benchmark_report.md`, `benchmark_out/charts/*.png` (matplotlib Agg).
- **Fairness:** `zone_equity(per_zone_means)` — Gini-style coefficient in `[0,1]`, lower = fairer; travels in `stats.equity` to both UIs (web ZONE FAIRNESS heat strip + table; CLI fairness panel).

---

## 7. Architecture

### 7.1 High-Level Architecture
```
Scenarios + Config (scenarios.py, policies.py)
        │
        ▼
┌─────────────────────┐     snapshot()/events_since()     ┌──────────────────────┐
│   Simulation Core   │ ───────────────────────────────► │   Presentation Layer │
│   core/engine.py    │     snapshot_at(tick) replay     │  web/main.py (WS)    │
│   7-stage tick loop │ ◄─────────────────────────────── │  cli/app.py (TUI)    │
│   Snapshot ring buf │        seed + controls           │  Canvas / ASCII map  │
│   (in-memory, no DB)│                                  │  Arena + Fairness    │
└──────────┬──────────┘                                  └──────────────────────┘
           │
     ┌─────┴──────┬──────────────┬────────────┬──────────┬──────────┐
     ▼            ▼              ▼            ▼          ▼          ▼
  search.py  dispatch.py  hospital_     mdp.py   metrics.py benchmark.py
  A*/GBFS/    CNP +        allocation    MDP VI    Gini      Smart vs
  LRTA*/      re-negot.    CSP                    equity    Naive
  D* Lite
           events.py (typed stream) ──► report.py ──► benchmark_out/
```

- **One core, two UIs:** Both dashboards consume only the engine contract — guaranteed identical simulation.
- **Everything in memory:** No database; scenario to `max_ticks` in <1s; replay served from ring buffer.
- **Deterministic:** Same `scenario + seed` → identical decisions and unit IDs.

*Diagrams on disk:* `diagram_architecture.png`, `diagram_cnp_flow.png`, `diagram_search_methods.png` (source: `generate_diagrams.py`); screenshots: `web_screenshot_*.png`; presentation: `Project_Review_1_Presentation.pptx` (source: `generate_ppt.py`).

### 7.2 Module Map

| Module | Responsibility | Key Exports |
|--------|---------------|-------------|
| `core/graph.py` | Road network & zones | `RoadNetwork`, `ZoneMap`, `build_grid_network` |
| `core/engine.py` | Tick loop, domain objects, snapshot contract | `SimulationEngine`, `Hospital`, `Station`, `Incident`, `Ambulance` |
| `core/search.py` | All search algorithms | `astar`, `greedy_best_first`, `dijkstra`, `breadth_first`, `LRTAStar`, `DStarLite`, `algorithm_arena` |
| `core/dispatch.py` | CNP auction + re-negotiation | `CnpAuctioneer` |
| `core/hospital_allocation.py` | CSP bed assignment | `HospitalAllocator` |
| `core/mdp.py` | Idle positioning MDP | `IdlePositioningMDP`, `MDPResult` |
| `core/metrics.py` | Equity | `zone_equity` |
| `core/policies.py` | Smart/naive policy switches | `resolve_policies`, `greedy_nearest_dispatch`, `first_free_hospital` |
| `core/events.py` | Explainability event stream | event builders |
| `core/benchmark.py` + `run_benchmark.py` | Empirical study harness | benchmark runner |
| `core/report.py` | Markdown report + charts | report generator |
| `web/main.py` / `cli/app.py` | Presentation | FastAPI WS / Textual dashboards |

### 7.3 Verification
```bash
pip install -r requirements.txt
python -m pytest tests -q              # 105 tests (optimality, CSP, MDP residual, engine, equity, re-negotiation, benchmark)
python run_benchmark.py --quick        # smoke: 1 scenario × 3 seeds
python run_web.py                      # http://127.0.0.1:8000
python run_cli.py --scenario storm-disaster --seed 7 --tps 8
```

---

*End of report. For the full codebase walkthrough see `README.md`; for empirical results see `benchmark_out/benchmark_report.md` and `benchmark_out/benchmark_results.csv`.*
