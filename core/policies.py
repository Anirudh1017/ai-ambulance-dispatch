"""
Naive baseline policies for the empirical comparison study.

Every subsystem of the engine has a "smart" classical-AI implementation
(CNP auction · D* Lite incremental replanning · MDP value-iteration idle
positioning · CSP hospital allocation). To *prove* those algorithms beat
naive alternatives — rather than merely running — each subsystem also has
an explicit baseline policy, selected per run through the engine config
``policies`` dict:

  subsystem   smart             baseline
  ---------   -----             --------
  dispatch    ``cnp``           ``greedy``       nearest available unit
  replan      ``dstar``         ``full_astar``   full A* rerun on every change
  idle        ``mdp``           ``station``      always return to home station
  hospital    ``csp``           ``first_free``   first hospital with a free bed

Baselines are implemented here as small, fully deterministic functions —
no randomness, no scoring subtleties, so the ablation study isolates the
value of the smart algorithm itself.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .search import SearchResult, astar

SMART: Dict[str, str] = {
    "dispatch": "cnp",
    "replan": "dstar",
    "idle": "mdp",
    "hospital": "csp",
}

BASELINE: Dict[str, str] = {
    "dispatch": "greedy",
    "replan": "full_astar",
    "idle": "station",
    "hospital": "first_free",
}

SUBSYSTEMS: Tuple[str, ...] = ("dispatch", "replan", "idle", "hospital")

BASELINE_LABELS: Dict[str, str] = {
    "greedy": "Greedy nearest available",
    "full_astar": "Full A* rerun",
    "station": "Return to home station",
    "first_free": "First free bed (no CSP)",
    "cnp": "CNP auction",
    "dstar": "D* Lite",
    "mdp": "MDP value iteration",
    "csp": "CSP allocator",
}


def resolve_policies(cfg_policies: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Normalise a (possibly partial) policies dict against the defaults."""
    out = dict(SMART)
    if cfg_policies:
        for k in SUBSYSTEMS:
            if k in cfg_policies:
                out[k] = cfg_policies[k]
    return out


def is_smart(policies: Dict[str, str], subsystem: str) -> bool:
    return policies.get(subsystem) == SMART[subsystem]


# --------------------------------------------------------------------------- #
# Dispatch baseline — greedy nearest available                                #
# --------------------------------------------------------------------------- #

def greedy_nearest_dispatch(scene_node: str,
                            ambulances: Sequence[Any],
                            network) -> Optional[Tuple[str, float, SearchResult]]:
    """One criterion, no auction: the available unit whose A* ETA to the
    scene is smallest wins outright. Ties break on unit id (deterministic).

    Available = the same eligibility set the CNP auctioneer uses
    (idle / drifting / returning). Returns (winner_id, eta_seconds, search)
    or None when no unit has a route.
    """
    candidates: List[Tuple[float, str, SearchResult]] = []
    for amb in ambulances:
        if amb.status not in ("idle", "drifting", "returning"):
            continue
        res = astar(network, amb.node, scene_node)
        if res.cost is None:
            continue
        candidates.append((res.cost, amb.id, res))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    eta, aid, res = candidates[0]
    return aid, eta, res


# --------------------------------------------------------------------------- #
# Hospital baseline — first hospital with any free bed                        #
# --------------------------------------------------------------------------- #

def first_free_hospital(waiting: Sequence[Any],
                        hospitals: Sequence[Any]) -> Dict[str, str]:
    """Walk the hospital roster in fixed order and take the first with a
    free bed. No distance domain, no specialty information, no capacity
    pressure reasoning — the pure naive baseline the CSP is compared
    against. Deterministic by construction.
    """
    assignments: Dict[str, str] = {}
    used = {h.id: 0 for h in hospitals}
    for inc in waiting:
        for h in hospitals:
            if h.free_beds() - used[h.id] > 0:
                assignments[inc.id] = h.id
                used[h.id] += 1
                break
    return assignments