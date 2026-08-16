"""
Tick-based simulation engine: the single source of truth consumed by both
user interfaces (FastAPI web dashboard and Textual CLI dashboard) through
the ``snapshot()`` / ``events_since()`` interface.

Decision pipeline inside one tick:

  1. world update      — scheduled blockages apply/expire; hidden blockages
                         revealed by units that physically reach them
  2. incident spawn    — scripted incidents become pending
  3. CNP dispatch      — Contract Net Protocol auction for pending incidents
  4. movement          — units advance along routes at their speed
  5. scene/transport   — on-scene stabilisation, CSP hospital allocation,
                         transport, handover, bed release
  6. idle positioning  — MDP (exact value iteration) decides where idle
                         units should drift every ``idle_reposition_every``
  7. replanning        — units whose remaining route uses a newly revealed
                         blockage replan incrementally with D* Lite

Search usage by task:
  * dispatch routes     — A* (or weighted A*)
  * urgent (sev>=5)     — LRTA* real-time search (move first, learn en route)
  * blockage replans    — D* Lite incremental replanning
  * algorithm arena     — head-to-head A*/Dijkstra/GBFS/BFS per dispatch
"""

from __future__ import annotations

import itertools
import random
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

from . import events as ev
from .dispatch import CnpAuctioneer
from .graph import RoadNetwork, ZoneMap, build_grid_network
from .hospital_allocation import HospitalAllocator
from .mdp import IdlePositioningMDP, MDPResult
from .scenarios import DEFAULT_CONFIG, resolve_config
from .search import (DStarLite, LRTAStar, SearchResult, algorithm_arena,
                     astar, euclidean_heuristic)

INF = float("inf")
SEVERITY_DEADLINE = {1: 540.0, 2: 420.0, 3: 300.0, 4: 210.0, 5: 120.0}


# --------------------------------------------------------------------------- #
# Domain objects                                                              #
# --------------------------------------------------------------------------- #

class Hospital:
    def __init__(self, hid: str, node: str, name: str, beds: int) -> None:
        self.id = hid
        self.node = node
        self.name = name
        self.beds = beds
        self.in_use = 0

    def free_beds(self) -> int:
        return self.beds - self.in_use

    def to_dict(self) -> Dict[str, object]:
        return {"id": self.id, "node": self.node, "name": self.name,
                "beds": self.beds, "in_use": self.in_use}


class Station:
    """A garage / ambulance station: fixed nodes where units are based."""

    def __init__(self, sid: str, node: str, label: str) -> None:
        self.id = sid
        self.node = node
        self.label = label

    def to_dict(self) -> Dict[str, object]:
        return {"id": self.id, "node": self.node, "label": self.label}


class Incident:
    def __init__(self, iid: str, node: str, severity: int, kind: str,
                 reported_tick: int) -> None:
        self.id = iid
        self.node = node
        self.severity = severity
        self.kind = kind
        self.reported_tick = reported_tick
        self.status = "pending"            # pending|assigned|enroute|on_scene|transporting|cleared
        self.ambulance_id: Optional[str] = None
        self.hospital_id: Optional[str] = None
        self.assigned_tick: Optional[int] = None
        self.on_scene_tick: Optional[int] = None
        self.transport_tick: Optional[int] = None
        self.cleared_tick: Optional[int] = None
        self.service_remaining: float = 0.0
        self.retry_after: int = 0
        self.last_dispatch_tick: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return {"id": self.id, "node": self.node, "severity": self.severity,
                "kind": self.kind, "status": self.status,
                "ambulance_id": self.ambulance_id,
                "hospital_id": self.hospital_id,
                "reported_tick": self.reported_tick,
                "assigned_tick": self.assigned_tick,
                "on_scene_tick": self.on_scene_tick,
                "cleared_tick": self.cleared_tick}


class Ambulance:
    def __init__(self, node: str, zone: str, speed_kmh: float,
                 aid: str) -> None:
        self.id = aid
        self.node = node
        self.zone = zone
        self.speed_kmh = speed_kmh
        self.station: Optional[str] = None   # home station id
        self.station_ix = 0                  # index within its station
        self.status = "idle"               # idle|drifting|enroute|on_scene|transporting|returning|blocked
        self.route: List[str] = []
        self.route_ix = 0
        self.edge_progress: float = 0.0    # seconds remaining on current edge
        self.destination: Optional[str] = None   # incident:<id>|hospital:<id>|zone:<z>
        self.algorithm = "astar"
        self.incident_id: Optional[str] = None
        self.hospital_id: Optional[str] = None
        self.lrta: Optional[LRTAStar] = None
        self.dstar: Optional[DStarLite] = None
        self.responses_done = 0
        self.total_distance_km = 0.0
        self.avg_speed = 0.0
        self.positions_visited: int = 0

    # -- movement helpers -------------------------------------------------- #
    def current_edge(self) -> Optional[Tuple[str, str]]:
        if self.route_ix + 1 < len(self.route):
            return self.route[self.route_ix], self.route[self.route_ix + 1]
        return None

    def remaining_route(self) -> List[str]:
        return self.route[self.route_ix:]

    def set_route(self, path: List[str], algorithm: str,
                  edge_seconds: float) -> None:
        self.route = list(path) if path else [self.node]
        self.route_ix = 0
        self.algorithm = algorithm
        self.edge_progress = edge_seconds

    def cancel_route(self) -> None:
        self.route = []
        self.route_ix = 0
        self.edge_progress = 0.0

    def position(self, network: RoadNetwork) -> Tuple[float, float]:
        """Interpolated position along the current edge (for animation)."""
        x, y = network.node_pos(self.node)
        e = self.current_edge()
        if e:
            x2, y2 = network.node_pos(e[1])
            total = network.true_cost(e[0], e[1])
            frac = 0.0 if total <= 0 else 1.0 - self.edge_progress / total
            frac = max(0.0, min(1.0, frac))
            return (x + (x2 - x) * frac, y + (y2 - y) * frac)
        return (x, y)

    def to_dict(self, network: RoadNetwork) -> Dict[str, object]:
        px, py = self.position(network)
        return {"id": self.id, "node": self.node, "zone": self.zone,
                "status": self.status, "x": round(px, 1), "y": round(py, 1),
                "route": self.route[self.route_ix:],
                "algorithm": self.algorithm,
                "destination": self.destination,
                "incident_id": self.incident_id,
                "hospital_id": self.hospital_id,
                "station": self.station,
                "station_ix": self.station_ix,
                "responses_done": self.responses_done,
                "distance_km": round(self.total_distance_km, 1),
                "speed_kmh": self.speed_kmh}


# --------------------------------------------------------------------------- #
# Engine                                                                      #
# --------------------------------------------------------------------------- #

class Engine:
    """Turns a resolved config into a live simulation. UI-agnostic."""

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 scenario: Optional[str] = None,
                 seed: Optional[int] = None) -> None:
        self.cfg = resolve_config(scenario, seed, config)
        self.scenario_name = self.cfg["name"]
        self.seed = self.cfg["seed"]
        self.rng = random.Random(self.seed)
        self.tick = 0
        self.seconds = 0.0
        self.dt = float(self.cfg["seconds_per_tick"])
        self.events: Deque[Tuple[int, ev.Event]] = deque()
        self._evt_seq = 0
        self._evt_start = 0
        self.snapshot_history: Dict[int, Dict[str, Any]] = {}

        self._build_world()
        self._build_fleet()
        self._build_schedule()

        self.auctioneer = CnpAuctioneer(**self.cfg["dispatch"])
        self.allocator = HospitalAllocator(
            max_distance_units=self.cfg["csp"]["max_distance_units"])
        self.mdp_cache: Optional[MDPResult] = None
        self.mdp_iterations_total = 0
        self.mdp_solves = 0
        self.arena: Dict[str, Any] = {}
        self.arena_runs = 0
        self._active_incidents: List[Incident] = []
        self._pending_allocation: List[Incident] = []

        # stats
        self.stats: Dict[str, Any] = {
            "incidents_reported": 0, "incidents_cleared": 0,
            "active": 0, "queue": 0,
            "response_times": [], "response_avg": 0.0, "response_p95": 0.0,
            "total_distance_km": 0.0, "replans": 0, "csp_backtracks": 0,
            "csp_nodes": 0, "csp_solves": 0, "mdp_solves": 0,
            "dispatch_wins": {}, "arena_runs": 0,
            "search_expansions": {"astar": 0, "lrta": 0, "dstar": 0},
        }
        self._event_emit(ev.scenario_started(
            self.tick, self.scenario_name, self.seed,
            len(self.ambulances), len(self.incident_schedule)))

    # ------------------------------------------------------------------ #
    # Construction                                                       #
    # ------------------------------------------------------------------ #
    def _build_world(self) -> None:
        self.network = build_grid_network(
            cols=int(self.cfg["grid_cols"]), rows=int(self.cfg["grid_rows"]),
            cell_km=float(self.cfg["cell_km"]),
            speed_kmh=float(self.cfg["ambulance_speed_kmh"]),
            rng=self.rng)
        self.zones: ZoneMap = ZoneMap.build(self.network,
                                            int(self.cfg["zone_count"]),
                                            rng=self.rng)
        self.hospitals: List[Hospital] = []
        names = ["St. Mary's General", "Mercy Memorial", "City East Trauma",
                 "Riverside Care", "Lakeside Clinic"]
        nodes = self.rng.sample(self.network.nodes, int(self.cfg["hospital_count"]))
        for i, node in enumerate(nodes):
            self.hospitals.append(Hospital(f"H{i + 1}", node, names[i % len(names)],
                                           int(self.cfg["hospital_beds"])))

    def _build_fleet(self) -> None:
        n_stations = max(1, int(self.cfg.get("station_count", 3)))
        station_nodes = self.rng.sample(
            self.network.nodes, min(n_stations, len(self.network.nodes)))
        self.stations: List[Station] = [
            Station(f"S{i + 1}", node, f"Station {i + 1}")
            for i, node in enumerate(station_nodes)
        ]
        n_units = int(self.cfg["ambulance_count"])
        self.ambulances: List[Ambulance] = []
        for i in range(n_units):
            st = self.stations[i % len(self.stations)]
            amb = Ambulance(st.node, self.zones.zone_of_node(st.node),
                            float(self.cfg["ambulance_speed_kmh"]),
                            aid=f"AMB-{i:02d}")
            amb.station = st.id
            amb.station_ix = i // len(self.stations)
            self.ambulances.append(amb)

    def _build_schedule(self) -> None:
        self.incident_schedule: List[Tuple[int, int, str, str]] = []
        prior = self._zone_priors_from_script()
        for i, (tick, sev, kind) in enumerate(self.cfg["incidents"]):
            node = self._weighted_node(prior)
            iid = f"INC-{i + 1:03d}"
            self.incident_schedule.append((int(tick), sev, kind, node))
            self._event_emit(ev.incident_generated(0, iid, node, sev, kind,
                                                   int(tick)))
        self.blockage_schedule: List[Tuple[int, str, str, int, bool]] = [
            (int(t), u, v, int(dur), reveal)
            for t, (u, v), dur, reveal in self.cfg["blockages"]
        ]
        self._pending_schedule = sorted(self.incident_schedule,
                                        key=lambda s: s[0])
        self._pending_blockages = sorted(self.blockage_schedule,
                                         key=lambda b: b[0])

    def _zone_priors_from_script(self) -> Dict[str, float]:
        """Hand-built incident-likelihood prior: counts how often the
        scenario script places incidents per zone, smoothed so no zone gets
        zero probability (the MDP's zone_prior)."""
        counts: Dict[str, float] = {z.id: 0.5 for z in self.zones.zones}
        for tick, sev, kind, node in self.incident_schedule:
            counts[self.zones.zone_of_node(node)] += 1.0
        return counts

    def _weighted_node(self, priors: Dict[str, float]) -> str:
        zid = self.rng.choices(list(priors.keys()),
                               weights=list(priors.values()), k=1)[0]
        return self.zones.zone_center_node(self.network, zid)

    # ------------------------------------------------------------------ #
    # Event plumbing                                                      #
    # ------------------------------------------------------------------ #
    def _event_emit(self, e: ev.Event) -> None:
        self.events.append((self._evt_seq, e))
        self._evt_seq += 1
        while len(self.events) > int(self.cfg["max_event_log"]):
            self.events.popleft()
            self._evt_start += 1

    def events_since(self, cursor: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        """Return (events, new_cursor) — events with seq > cursor."""
        out = []
        for seq, e in self.events:
            if seq >= cursor:
                out.append(e.to_dict())
        return out, self._evt_seq

    # ------------------------------------------------------------------ #
    # Incident / ambulance lookup                                         #
    # ------------------------------------------------------------------ #
    def incident(self, iid: str) -> Optional[Incident]:
        for inc in self._active_incidents:
            if inc.id == iid:
                return inc
        return None

    def ambulance(self, aid: str) -> Optional[Ambulance]:
        for a in self.ambulances:
            if a.id == aid:
                return a
        return None

    def hospital(self, hid: str) -> Optional[Hospital]:
        for h in self.hospitals:
            if h.id == hid:
                return h
        return None

    def _ambulance_status_change(self, amb: Ambulance, new: str) -> None:
        if amb.status != new:
            self._event_emit(ev.status_change(self.tick, amb.id, amb.status,
                                              new))
            amb.status = new
        if new == "idle":
            # a unit just freed up: let queued incidents bid immediately
            for inc in self._active_incidents:
                if inc.status == "pending":
                    inc.retry_after = 0

    # ------------------------------------------------------------------ #
    # Routing                                                             #
    # ------------------------------------------------------------------ #
    def _route_seconds(self, u: str, v: str) -> float:
        return self.network.visible_cost(u, v)

    def _plan_route(self, amb: Ambulance, goal: str, algorithm: str = "astar",
                    weight: float = 1.0) -> Optional[SearchResult]:
        """Plan a route with the engine's routing algorithm. Returns the
        search result or None if unreachable."""
        if algorithm == "astar":
            res = astar(self.network, amb.node, goal,
                        weight=weight)
        elif algorithm == "gbfs":
            res = astar(self.network, amb.node, goal, weight=5.0)
        else:
            res = astar(self.network, amb.node, goal)
        self.stats["search_expansions"]["astar"] += res.nodes_expanded
        return res if res.cost is not None else None

    def _reveal_at_node(self, amb: Ambulance) -> bool:
        """Reveal hidden blockages incident to the unit's current node.
        Returns True if the shared world model changed."""
        changed = False
        for nb in self.network.neighbors(amb.node):
            if self.network.reveal_blockage(amb.node, nb):
                changed = True
                self._event_emit(ev.blockage_detected(
                    self.tick, amb.node, nb, amb.id,
                    "unit physically reached the junction"))
        return changed

    def _replan_affected(self, blocked_edge: Tuple[str, str]) -> None:
        """Incremental replanning: every unit whose remaining route uses the
        revealed edge switches to D* Lite and re-solves locally."""
        for amb in self.ambulances:
            if amb.status not in ("enroute", "transporting", "drifting",
                                  "returning", "blocked"):
                continue
            route = amb.remaining_route()
            if len(route) < 2:
                continue
            uses = any((route[i], route[i + 1]) == blocked_edge
                       or (route[i + 1], route[i]) == blocked_edge
                       for i in range(len(route) - 1))
            if not uses:
                continue
            self._replan_unit(amb, cause="blockage on route",
                              changed_edges=[blocked_edge])

    def _replan_unit(self, amb: Ambulance, cause: str,
                     changed_edges: Optional[List[Tuple[str, str]]] = None) -> bool:
        """Incremental replanning with D* Lite. Returns True when a new
        route was installed."""
        goal = self._current_goal_node(amb)
        if goal is None or goal == amb.node:
            return False
        old_len = len(amb.remaining_route())
        if amb.dstar is None or amb.dstar.goal != goal:
            amb.dstar = DStarLite(self.network, amb.node, goal)
        else:
            # correct D* Lite start movement: km absorbs the heuristic shift
            amb.dstar.km += amb.dstar._heuristic(amb.dstar.start, amb.node)
            amb.dstar.start = amb.node
        for u, v in (changed_edges or []):
            amb.dstar.edge_cost_changed(u, v)
        amb.dstar.replan()
        new_path = amb.dstar.extract_path()
        self.stats["search_expansions"]["dstar"] += amb.dstar.s_expanded
        if len(new_path) >= 2 and new_path[-1] == goal:
            self._set_route(amb, new_path, "D* Lite", goal)
            self.stats["replans"] += 1
            self._event_emit(ev.route_replanned(
                self.tick, amb.id, amb.incident_id or "",
                old_len, len(new_path) - 1, "D* Lite", cause,
                max(0, old_len - (len(new_path) - 1)), amb.dstar.s_expanded))
            return True
        return False

    def _current_goal_node(self, amb: Ambulance) -> Optional[str]:
        if amb.destination and amb.destination.startswith("incident:"):
            inc = self.incident(amb.destination.split(":", 1)[1])
            return inc.node if inc else None
        if amb.destination and amb.destination.startswith("hospital:"):
            h = self.hospital(amb.destination.split(":", 1)[1])
            return h.node if h else None
        if amb.destination and amb.destination.startswith("zone:"):
            return self.zones.zone_center_node(self.network,
                                               amb.destination[5:])
        return None

    def _set_route(self, amb: Ambulance, path: List[str], algorithm: str,
                   goal: str) -> None:
        amb.set_route(path, algorithm,
                      self._route_seconds(path[0], path[1])
                      if len(path) >= 2 else 0.0)

    def _dispatch_to(self, amb: Ambulance, goal_node: str,
                     destination: str, algorithm: str = "astar",
                     weight: float = 1.0) -> Optional[SearchResult]:
        res = self._plan_route(amb, goal_node, algorithm, weight)
        if res is None:
            return None
        self._set_route(amb, res.path, res.algorithm, goal_node)
        amb.destination = destination
        return res

    # ------------------------------------------------------------------ #
    # CNP dispatch                                                       #
    # ------------------------------------------------------------------ #
    def _eligible_units(self) -> List[Ambulance]:
        return [a for a in self.ambulances
                if a.status in ("idle", "drifting", "returning")]

    def _run_auction(self, inc: Incident) -> None:
        eligible = self._eligible_units()
        self._event_emit(ev.auction_phase(
            self.tick, inc.id, "announce",
            {"eligible": len(eligible), "severity": inc.severity}))
        rec = self.auctioneer.run_auction(
            inc.id, inc.severity, inc.node, eligible, self.network)
        for bid in rec.bids:
            self._event_emit(ev.auction_phase(
                self.tick, inc.id, "bid", bid.to_dict()))
        for ex in rec.excluded:
            self._event_emit(ev.auction_phase(
                self.tick, inc.id, "reject", ex))
        if rec.winner is None:
            self._event_emit(ev.dispatch_failed(
                self.tick, inc.id, "no eligible unit with feasible ETA"))
            inc.retry_after = self.tick + 30
            return
        amb = self.ambulance(rec.winner)
        assert amb is not None
        late = rec.task.get("late_eta", False)
        self._event_emit(ev.auction_phase(
            self.tick, inc.id, "award",
            {"winner": amb.id, "score": round(rec.winning_bid.score, 3),
             "eta_seconds": rec.winning_bid.eta_seconds,
             "algorithm": rec.winning_bid.algorithm,
             "late": late}))
        self.stats["dispatch_wins"][amb.id] = \
            self.stats["dispatch_wins"].get(amb.id, 0) + 1

        inc.status = "assigned"
        inc.ambulance_id = amb.id
        inc.assigned_tick = self.tick
        inc.last_dispatch_tick = self.tick
        amb.incident_id = inc.id
        amb.hospital_id = None

        # urgent: LRTA* real-time search; else A*
        if inc.severity >= 5:
            amb.lrta = LRTAStar(self.network, amb.node, inc.node)
            amb.algorithm = "LRTA*"
            nxt = amb.lrta.act()
            self.stats["search_expansions"]["lrta"] += amb.lrta.nodes_expanded
            if nxt == amb.node:
                amb.lrta = None
                res = self._plan_route(amb, inc.node)
                if res is None:
                    inc.status = "pending"
                    inc.ambulance_id = None
                    self._event_emit(ev.dispatch_failed(
                        self.tick, inc.id, "no route exists to scene"))
                    return
                self._set_route(amb, res.path, res.algorithm, inc.node)
            else:
                self._set_route(amb, [amb.node, nxt], "LRTA*", inc.node)
            amb.destination = f"incident:{inc.id}"
        else:
            res = self._dispatch_to(amb, inc.node, f"incident:{inc.id}")
            if res is None:
                inc.status = "pending"
                inc.ambulance_id = None
                self._event_emit(ev.dispatch_failed(
                    self.tick, inc.id, "no route exists to scene"))
                return
        self._ambulance_status_change(amb, "enroute")
        self._event_emit(ev.ambulance_dispatched(
            self.tick, amb.id, inc.id, inc.node,
            max(0, len(amb.route) - amb.route_ix - 1), amb.algorithm,
            self.network.distance_km(amb.node, inc.node) * 3600
            / amb.speed_kmh))
        self._run_arena(amb, inc)

    def _run_arena(self, amb: Ambulance, inc: Incident) -> None:
        """Head-to-head algorithm comparison on the current dispatch query,
        cached in the snapshot for the explainability panel."""
        self.arena_runs += 1
        res = algorithm_arena(self.network, amb.node, inc.node)
        self.arena = {
            "query": {"from": amb.node, "to": inc.node,
                      "incident": inc.id},
            "results": {k: r.summary() for k, r in res.items()},
            "run": self.arena_runs,
        }
        self.stats["arena_runs"] = self.arena_runs

    # ------------------------------------------------------------------ #
    # Incident lifecycle                                                  #
    # ------------------------------------------------------------------ #
    def _spawn_due_incidents(self) -> None:
        while (self._pending_schedule
               and self._pending_schedule[0][0] <= self.tick):
            _, sev, kind, node = self._pending_schedule.pop(0)
            iid = f"INC-{self.stats['incidents_reported'] + 1:03d}"
            inc = Incident(iid, node, sev, kind, self.tick)
            self._active_incidents.append(inc)
            self.stats["incidents_reported"] += 1
            self._event_emit(ev.incident_reported(
                self.tick, iid, node, sev, kind,
                f"node {node} ({self.zones.zone_of_node(node)})"))

    def _dispatch_pending(self) -> None:
        pending = sorted(
            [i for i in self._active_incidents if i.status == "pending"
             and i.retry_after <= self.tick],
            key=lambda i: (-i.severity, i.reported_tick))
        for inc in pending:
            self._run_auction(inc)

    def _arrive_at_incident(self, amb: Ambulance, inc: Incident) -> None:
        inc.status = "on_scene"
        inc.on_scene_tick = self.tick
        response = (self.tick - inc.reported_tick) * self.dt
        self.stats["response_times"].append(response)
        self._ambulance_status_change(amb, "on_scene")
        amb.cancel_route()
        inc.service_remaining = 40.0 + inc.severity * 25.0
        self._event_emit(ev.ambulance_arrived_scene(
            self.tick, amb.id, inc.id, response))
        # register this patient with the CSP allocator; the actual batched
        # solve happens when a transport is about to start (see
        # _start_transport), so several patients accumulate on scene
        self._pending_allocation.append(inc)

    def _solve_allocations(self) -> None:
        waiting = [i for i in self._pending_allocation
                   if i.hospital_id is None and i.status == "on_scene"
                   and i.ambulance_id is not None]
        if not waiting:
            return
        seen: Dict[str, Incident] = {}
        for i in waiting:
            seen.setdefault(i.id, i)
        waiting = list(seen.values())
        res = self.allocator.solve(waiting, self.hospitals, self.network)
        self.stats["csp_solves"] += 1
        self.stats["csp_backtracks"] += res.backtracks
        self.stats["csp_nodes"] += res.nodes_explored
        csp_info = {"assignments": len(res.assignments),
                    "backtracks": res.backtracks,
                    "nodes": res.nodes_explored,
                    "feasible": res.feasible,
                    "variables": len(waiting)}
        for inc in waiting:
            amb = self.ambulance(inc.ambulance_id)
            target = res.assignments.get(inc.id)
            if target is None:
                # every hospital full: nearest-hospital fallback, flagged
                target = min(self.hospitals,
                             key=lambda h: self.network.euclidean_distance(
                                 inc.node, h.node)).id
            inc.hospital_id = target
            if amb is not None:
                amb.hospital_id = target
            hosp = self.hospital(target)
            if hosp and hosp.free_beds() > 0:
                hosp.in_use += 1
            self._event_emit(ev.hospital_allocated(
                self.tick, inc.id, target,
                self.network.distance_km(inc.node, hosp.node)
                if hosp else 0.0,
                beds_used=1,
                csp_info=csp_info))

    def _start_transport(self, amb: Ambulance, inc: Incident) -> None:
        # CSP: solve bed allocation for EVERY patient still on scene in one
        # batched problem — during a mass casualty event several patients
        # are being stabilised at once and compete over scarce beds, so the
        # solver has genuine capacity constraints (and backtracking) to do.
        self._solve_allocations()
        inc.status = "transporting"
        inc.transport_tick = self.tick
        self._ambulance_status_change(amb, "transporting")
        goal = self.hospital(inc.hospital_id)
        if goal is None:
            goal = self.hospitals[0]
            inc.hospital_id = goal.id
        res = self._dispatch_to(amb, goal.node,
                                f"hospital:{goal.id}")
        if res is None:
            # no route: force clear (dead end) — flagged in the event
            self._event_emit(ev.engine_message(
                self.tick, "warning",
                f"No route {amb.id} -> {goal.id}; incident {inc.id} "
                f"cleared on scene."))
            self._clear_incident(inc, amb)
            return
        self._event_emit(ev.patient_loaded(self.tick, amb.id, inc.id,
                                           goal.id))

    def _arrive_at_hospital(self, amb: Ambulance, inc: Incident,
                            hosp: Hospital) -> None:
        handover = 20.0 + inc.severity * 15.0
        self._event_emit(ev.arrived_hospital(self.tick, amb.id, inc.id,
                                             hosp.id, handover))
        self._clear_incident(inc, amb)
        hosp.in_use = max(0, hosp.in_use - 1)

    def _clear_incident(self, inc: Incident, amb: Ambulance) -> None:
        inc.status = "cleared"
        inc.cleared_tick = self.tick
        total = (self.tick - inc.reported_tick) * self.dt
        response = (inc.on_scene_tick - inc.reported_tick) * self.dt \
            if inc.on_scene_tick else total
        self.stats["incidents_cleared"] += 1
        self._event_emit(ev.incident_cleared(self.tick, inc.id, inc.severity,
                                             response, total))
        amb.incident_id = None
        amb.lrta = None
        amb.destination = None
        amb.cancel_route()
        amb.responses_done += 1
        self._ambulance_status_change(amb, "idle")
        self._schedule_idle_drift()

    # ------------------------------------------------------------------ #
    # Idle positioning (MDP)                                             #
    # ------------------------------------------------------------------ #
    def _solve_mdp(self) -> MDPResult:
        """Exact value iteration over the zone MDP. Solved fresh each epoch
        so the priors (counting statistics over observed incidents) evolve
        with the simulation; the result is shared by all idle units."""
        priors = self._zone_priors_from_script()
        for inc in self._active_incidents:
            if inc.status not in ("cleared",):
                priors[self.zones.zone_of_node(inc.node)] += 0.5
        mdp = IdlePositioningMDP(
            zones=[(z.id, z.center[0], z.center[1]) for z in self.zones.zones],
            zone_prior=priors,
            travel_time=lambda a, b: self._zone_travel(a, b),
            gamma=self.cfg["mdp"]["gamma"],
            lambda_cost=self.cfg["mdp"]["lambda_cost"],
            tau=self.cfg["mdp"]["tau"])
        res = mdp.solve(epsilon=self.cfg["mdp"]["epsilon"])
        self.mdp_cache = res
        self.mdp_solves += 1
        self.stats["mdp_solves"] = self.mdp_solves
        self.mdp_iterations_total += res.iterations
        self._event_emit(ev.mdp_summary(self.tick, len(mdp.zone_ids),
                                        len(mdp.zone_ids),
                                        res.iterations, res.final_residual,
                                        mdp.gamma))
        return res

    def _zone_travel(self, a: str, b: str) -> float:
        u = self.zones.zone_center_node(self.network, a)
        v = self.zones.zone_center_node(self.network, b)
        res = astar(self.network, u, v)
        return res.cost if res.cost is not None else 3600.0

    def _schedule_idle_drift(self) -> None:
        if self.tick % int(self.cfg["idle_reposition_every"]) != 0:
            return
        idle = [a for a in self.ambulances if a.status == "idle"]
        if not idle:
            return
        res = self._solve_mdp()
        for amb in idle:
            from_zone = self.zones.zone_of_node(amb.node)
            target = res.policy[from_zone]
            if target == from_zone:
                self._event_emit(ev.idle_reposition(
                    self.tick, amb.id, from_zone, from_zone,
                    res.values[from_zone], "exact value iteration",
                    res.iterations, 0.0,
                    f"Policy keeps unit in {from_zone} "
                    f"(V={res.values[from_zone]:.2f}) after "
                    f"{res.iterations} Bellman sweeps."))
                continue
            goal_node = self.zones.zone_center_node(self.network, target)
            if goal_node == amb.node:
                continue
            tres = self._dispatch_to(amb, goal_node, f"zone:{target}")
            if tres is None:
                continue
            self._ambulance_status_change(amb, "drifting")
            self._event_emit(ev.idle_reposition(
                self.tick, amb.id, from_zone, target,
                res.values[from_zone], "exact value iteration",
                res.iterations, tres.cost,
                f"Coverage prior favours {target} after {res.iterations} "
                f"Bellman sweeps."))

    # ------------------------------------------------------------------ #
    # Main tick                                                          #
    # ------------------------------------------------------------------ #
    def tick_once(self) -> None:
        self.tick += 1
        self.seconds += self.dt

        # 1. world update -------------------------------------------------
        self._apply_scheduled_blockages()
        expired = self.network.tick_blockages()
        for u, v in expired:
            self._event_emit(ev.engine_message(
                self.tick, "info", f"Blockage {u}–{v} cleared (reopened)."))
            self._replan_affected((u, v))

        # 2. incidents ----------------------------------------------------
        self._spawn_due_incidents()
        self._dispatch_pending()

        # 3. movement ------------------------------------------------------
        for amb in self.ambulances:
            if amb.status in ("enroute", "transporting", "drifting",
                              "returning"):
                self._move_unit(amb)
            elif amb.status == "blocked":
                if self._replan_unit(amb, cause="recovery from blockage"):
                    kind = (amb.destination or "").split(":", 1)[0]
                    self._ambulance_status_change(
                        amb, {"incident": "enroute",
                              "hospital": "transporting",
                              "zone": "drifting"}.get(kind, "idle"))
            elif amb.status == "on_scene":
                inc = self.incident(amb.incident_id) if amb.incident_id else None
                if inc is not None:
                    inc.service_remaining -= self.dt
                    if inc.service_remaining <= 0:
                        self._start_transport(amb, inc)

        # 4. idle positioning epoch ----------------------------------------
        if self.tick % int(self.cfg["idle_reposition_every"]) == 0:
            self._schedule_idle_drift()

        self._refresh_stats()

    def _apply_scheduled_blockages(self) -> None:
        while (self._pending_blockages
               and self._pending_blockages[0][0] <= self.tick):
            _, u, v, dur, reveal = self._pending_blockages.pop(0)
            self.network.block_edge(u, v, dur, reveal=reveal)
            self._event_emit(ev.blockage_detected(
                self.tick, u, v, None,
                "scheduled roadworks (visible to planners)"
                if reveal else "road incident (hidden until reached)"))
            if reveal:
                self._replan_affected((u, v))

    def _move_unit(self, amb: Ambulance) -> None:
        """Advance one unit for this tick: travel along edges, reveal
        blockages, replan when blocked, and extend LRTA* routes in real
        time as the unit reaches each junction."""
        guard = 0
        while guard < 25:
            guard += 1
            e = amb.current_edge()
            if e is None:
                self._handle_arrival(amb)
                return
            u, v = e
            if self.network.is_revealed_blocked(u, v):
                if not self._replan_unit(amb, cause="blocked edge ahead",
                                         changed_edges=[(u, v)]):
                    self._ambulance_status_change(amb, "blocked")
                    return
                e = amb.current_edge()
                if e is None:
                    self._handle_arrival(amb)
                    return
                u, v = e
            edge_time = self.network.true_cost(u, v)
            if edge_time <= 0:
                edge_time = 1.0
            amb.edge_progress -= self.dt
            if amb.edge_progress > 0:
                return
            self._finish_edge(amb)
            if self._at_destination(amb):
                self._handle_arrival(amb)
            else:
                self._extend_lrta(amb)

    def _at_destination(self, amb: Ambulance) -> bool:
        if not amb.destination:
            return False
        kind, ref = amb.destination.split(":", 1)
        if kind == "incident":
            inc = self.incident(ref)
            return inc is not None and amb.node == inc.node
        if kind == "hospital":
            h = self.hospital(ref)
            return h is not None and amb.node == h.node
        if kind == "zone":
            return amb.node == self.zones.zone_center_node(self.network, ref)
        return False

    def _extend_lrta(self, amb: Ambulance) -> None:
        """LRTA* real-time mode: each time the unit reaches a junction, it
        commits to its next move using its learned heuristic table."""
        if amb.lrta is None or not amb.destination:
            return
        kind, ref = amb.destination.split(":", 1)
        if kind != "incident":
            return
        inc = self.incident(ref)
        if inc is None or amb.node == inc.node:
            return
        nxt = amb.lrta.act()
        if nxt == amb.node:
            res = self._plan_route(amb, inc.node)
            if res is None:
                self._ambulance_status_change(amb, "blocked")
                return
            amb.lrta = None
            self._set_route(amb, res.path, res.algorithm, inc.node)
            return
        self.stats["search_expansions"]["lrta"] += amb.lrta.nodes_expanded
        self._set_route(amb, [amb.node, nxt], "LRTA*", inc.node)

    def _finish_edge(self, amb: Ambulance) -> None:
        e = amb.current_edge()
        if e is None:
            return
        u, v = e
        amb.route_ix += 1
        amb.node = v
        amb.edge_progress = 0.0
        dist = self.network.euclidean_distance(u, v) / 10.0
        amb.total_distance_km += dist
        self.stats["total_distance_km"] += dist
        self._reveal_at_node(amb)
        if amb.current_edge():
            amb.edge_progress = self.network.true_cost(*amb.current_edge())

    def _handle_arrival(self, amb: Ambulance) -> None:
        if not amb.destination:
            return
        kind, ref = amb.destination.split(":", 1)
        if kind == "incident":
            inc = self.incident(ref)
            if inc and amb.node == inc.node:
                if inc.status in ("assigned", "enroute"):
                    self._arrive_at_incident(amb, inc)
            return
        if kind == "hospital":
            hosp = self.hospital(ref)
            inc = self.incident(amb.incident_id) if amb.incident_id else None
            if hosp and inc and amb.node == hosp.node \
                    and inc.status == "transporting":
                self._arrive_at_hospital(amb, inc, hosp)
            return
        if kind == "zone":
            if amb.node == self.zones.zone_center_node(self.network, ref):
                amb.destination = None
                amb.cancel_route()
                amb.zone = ref
                self._ambulance_status_change(amb, "idle")

    # ------------------------------------------------------------------ #
    # Stats / snapshot                                                   #
    # ------------------------------------------------------------------ #
    def _refresh_stats(self) -> None:
        incs = self._active_incidents
        self.stats["active"] = len([i for i in incs
                                    if i.status != "cleared"])
        self.stats["queue"] = len([i for i in incs if i.status == "pending"])
        rt = sorted(self.stats["response_times"])
        if rt:
            self.stats["response_avg"] = sum(rt) / len(rt)
            self.stats["response_p95"] = rt[int(0.95 * (len(rt) - 1))]
        else:
            self.stats["response_avg"] = 0.0
            self.stats["response_p95"] = 0.0

    def _incident_list(self) -> List[Incident]:
        """Active (not cleared) incidents plus recent cleared ones."""
        return [i for i in self._active_incidents]

    def snapshot(self) -> Dict[str, Any]:
        """Serialisable full state for UI consumption."""
        self._refresh_stats()
        map_state = {
            "nodes": [{"id": n,
                       "x": round(d["x"], 1), "y": round(d["y"], 1)}
                      for n, d in self.network.graph.nodes(data=True)],
            "edges": [{"u": u, "v": v, "travel_seconds": d["travel_seconds"]}
                      for u, v, d in self.network.graph.edges(data=True)],
            "zones": [z.to_dict() for z in self.zones.zones],
            "hospitals": [h.to_dict() for h in self.hospitals],
            "stations": [s.to_dict() for s in self.stations],
        }
        snap = {
            "tick": self.tick,
            "seconds": round(self.seconds, 1),
            "scenario": {"name": self.scenario_name,
                         "title": self.cfg.get("title"),
                         "description": self.cfg.get("description"),
                         "seed": self.seed},
            "map": map_state,
            "ambulances": [a.to_dict(self.network) for a in self.ambulances],
            "incidents": [i.to_dict() for i in self._incident_list()],
            "blockages": {"revealed": [list(k) for k in
                                       self.network._revealed],
                          "hidden": [list(k) for k in
                                     self.network._blocked
                                     - self.network._revealed]},
            "stats": dict(self.stats),
            "arena": self.arena,
            "mdp": self.mdp_cache.to_dict() if self.mdp_cache else {},
            "recent_decisions": [e.to_dict() for _, e
                                 in list(self.events)[-40:]],
        }
        # replay buffer (capped)
        self.snapshot_history[self.tick] = snap
        cap = int(self.cfg["max_snapshot_history"])
        if len(self.snapshot_history) > cap:
            drop = sorted(self.snapshot_history)[:len(self.snapshot_history) - cap]
            for k in drop:
                del self.snapshot_history[k]
        return snap

    def snapshot_at(self, tick: int) -> Optional[Dict[str, Any]]:
        """Replay support: a stored snapshot for a past tick."""
        return self.snapshot_history.get(tick)

    def replay_ticks(self) -> List[int]:
        return sorted(self.snapshot_history.keys())

    # ------------------------------------------------------------------ #
    # Run helpers                                                        #
    # ------------------------------------------------------------------ #
    def run(self, max_ticks: Optional[int] = None) -> None:
        limit = max_ticks or int(self.cfg["max_ticks"])
        while self.tick < limit:
            self.tick_once()

    @property
    def active_incidents(self) -> List[Incident]:
        return self._active_incidents

    @property
    def ambulances_list(self) -> List[Ambulance]:
        return self.ambulances
