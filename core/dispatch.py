"""
Multi-agent dispatch via the Contract Net Protocol (CNP, Smith 1980).

Phases, each fully observable and explainable:

  1. ANNOUNCE  — the auctioneer (dispatch centre) broadcasts the task:
                 incident node, severity, service deadline.
  2. BID       — every eligible unit independently evaluates the task and
                 may submit a sealed bid: proposed route (A*), ETA,
                 distance, and its own priority/status factors.
  3. AWARD     — the auctioneer evaluates bids with an explicit multi-
                 criteria scoring function and awards the contract to the
                 best bidder (deterministic tie-breaks).
  4. REJECT    — losing bidders and self-excluded units are notified.

Scoring function (hand-built, fully specified):

    score = w_eta * norm(ETA) + w_dist * norm(distance)
            + w_status * status_penalty + w_load * workload_penalty

where norm(x) maps into [0,1] against the worst bid; status_penalty favours
units already moving (they have en-route momentum); workload_penalty favours
the unit with the fewest completed responses so far (fairness).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from .search import SearchResult, astar, euclidean_heuristic

DEADLINE_SECONDS = {1: 540, 2: 420, 3: 300, 4: 210, 5: 120}


@dataclass
class Bid:
    ambulance_id: str
    eta_seconds: float
    distance_units: float
    route: List[str]
    algorithm: str
    search: Optional[SearchResult] = None
    score: float = 0.0
    rationale: str = ""
    raw_components: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "ambulance_id": self.ambulance_id,
            "eta_seconds": round(self.eta_seconds, 1),
            "distance_units": round(self.distance_units, 1),
            "route": self.route,
            "algorithm": self.algorithm,
            "score": round(self.score, 4),
            "rationale": self.rationale,
            "components": {k: round(v, 4) for k, v in self.raw_components.items()},
        }


@dataclass
class AuctionRecord:
    """Full transcript of one CNP auction — used for explainability."""
    incident_id: str
    severity: int
    task: Dict[str, Any]
    deadline_seconds: float
    bids: List[Bid] = field(default_factory=list)
    excluded: List[Dict[str, str]] = field(default_factory=list)
    winner: Optional[str] = None
    winning_bid: Optional[Bid] = None
    phases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "severity": self.severity,
            "task": self.task,
            "deadline_seconds": self.deadline_seconds,
            "bids": [b.to_dict() for b in self.bids],
            "excluded": self.excluded,
            "winner": self.winner,
            "phases": self.phases,
        }


class CnpAuctioneer:
    """Runs one Contract-Net auction for a single incident."""

    def __init__(self,
                 w_eta: float = 0.45,
                 w_dist: float = 0.20,
                 w_status: float = 0.15,
                 w_load: float = 0.20) -> None:
        self.w_eta = w_eta
        self.w_dist = w_dist
        self.w_status = w_status
        self.w_load = w_load
        self.search_fn: Callable = astar

    # ------------------------------------------------------------------ #
    # Public entry point                                                  #
    # ------------------------------------------------------------------ #
    def run_auction(self, incident_id: str, severity: int, scene_node: str,
                    ambulances: Sequence[Any], graph,
                    deadline_seconds: Optional[float] = None,
                    max_scene_gap_seconds: float = 60.0) -> AuctionRecord:
        """Run a full CNP auction. ``ambulances`` are engine.Ambulance
        objects exposing: id, node, status, responses_done, work_capacity,
        speed_kmh, and a proposed ETA helper. Returns the transcript."""
        deadline = deadline_seconds or DEADLINE_SECONDS.get(severity, 300.0)
        rec = AuctionRecord(incident_id=incident_id, severity=severity,
                            task={"scene_node": scene_node,
                                  "severity": severity,
                                  "deadline_seconds": deadline},
                            deadline_seconds=deadline)
        rec.phases.append("announce")

        eligible: List[Any] = []
        for amb in ambulances:
            # --- per-agent decision: may I even consider this task? ------
            if amb.status not in ("idle", "moving", "returning", "blocked"):
                rec.excluded.append({"ambulance_id": amb.id,
                                     "reason": f"busy ({amb.status})"})
                continue
            eligible.append(amb)

        if not eligible:
            rec.phases.append("no_bids")
            return rec

        # ------------------------------------------------------------------
        # BID phase: every eligible unit solves its own routing subproblem  #
        # ------------------------------------------------------------------
        rec.phases.append("bid")
        raw_etas: List[float] = []
        for amb in eligible:
            res = self.search_fn(graph, amb.node, scene_node,
                                 heuristic=euclidean_heuristic)
            if res.cost is None:
                rec.excluded.append({"ambulance_id": amb.id,
                                     "reason": "no route exists"})
                continue
            bid = Bid(
                ambulance_id=amb.id,
                eta_seconds=res.cost,
                distance_units=sum(
                    graph.euclidean_distance(res.path[i], res.path[i + 1])
                    for i in range(len(res.path) - 1)
                ),
                route=res.path,
                algorithm=res.algorithm,
                search=res,
            )
            rec.bids.append(bid)
            raw_etas.append(res.cost)

        if not rec.bids:
            rec.phases.append("no_bids")
            return rec

        # ------------------------------------------------------------------
        # AWARD phase: multi-criteria scoring over normalised components   #
        # ------------------------------------------------------------------
        rec.phases.append("award")
        worst_eta = max(raw_etas) or 1.0   # all-zero ETAs (unit on scene)
        worst_dist = max(b.distance_units for b in rec.bids)
        max_load = max(amb.responses_done for amb in eligible) or 1

        for bid, amb in zip(rec.bids, [a for a in eligible
                                       if a.id in {b.ambulance_id
                                                   for b in rec.bids}]):
            n_eta = bid.eta_seconds / worst_eta
            n_dist = bid.distance_units / worst_dist if worst_dist else 0.0
            # momentum bonus: a unit already moving is slightly preferred
            status_p = 0.0 if amb.status in ("idle",) else 0.4
            load_p = amb.responses_done / max_load
            score = (self.w_eta * n_eta
                     + self.w_dist * n_dist
                     + self.w_status * status_p
                     + self.w_load * load_p)
            bid.score = score
            bid.raw_components = {"eta": n_eta, "distance": n_dist,
                                  "status_penalty": status_p,
                                  "load_penalty": load_p}
            bid.rationale = (f"ETA {bid.eta_seconds:.0f}s (norm {n_eta:.2f}) "
                             f"· dist {bid.distance_units:.0f}u "
                             f"({n_dist:.2f}) · status {status_p:.2f} "
                             f"· load {load_p:.2f} = {score:.3f}")

        # deterministic tie-break: lowest ETA, then lowest id
        winner_bid = min(rec.bids, key=lambda b: (b.score, b.eta_seconds, b.ambulance_id))
        rec.winner = winner_bid.ambulance_id
        rec.winning_bid = winner_bid
        rec.task["late_eta"] = winner_bid.eta_seconds > deadline
        rec.task["deadline_met"] = not rec.task["late_eta"]
        return rec
