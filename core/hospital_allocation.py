"""
Hospital allocation as a Constraint Satisfaction Problem (CSP).

Variables   : the incidents that need a bed (each incident = one variable).
Domains     : hospitals that (a) are within the incident's max-transport
              distance and (b) have at least one free bed.
Constraints :
    C1 capacity  — for every hospital h, |{v : v assigned to h}| <= free_beds(h)
                   (binary constraint, enforced by forward checking).
    C2 unary     — distance / capability constraints folded into domains.

Solved by chronological backtracking with the classic heuristics
MRV (minimum remaining values), LCV (least constraining value) and
forward checking (arc-consistency pruning). Fully hand-built — every
backtrack is counted and reported so the dashboards can explain the solver.

If the problem is infeasible (all hospitals overwhelmed), the solver
returns the best-effort greedy completion with ``feasible=False`` so the
engine can still route patients (soft failure, clearly flagged).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class AllocationResult:
    """Result + explainability trace of one CSP solve."""
    assignments: Dict[str, str] = field(default_factory=dict)  # incident -> hospital
    feasible: bool = False
    backtracks: int = 0
    nodes_explored: int = 0
    forward_checks: int = 0
    variables: List[str] = field(default_factory=list)
    domains: Dict[str, List[str]] = field(default_factory=dict)
    capacities: Dict[str, int] = field(default_factory=dict)
    duration_ms: float = 0.0
    trace: List[Dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "assignments": self.assignments,
            "feasible": self.feasible,
            "backtracks": self.backtracks,
            "nodes_explored": self.nodes_explored,
            "forward_checks": self.forward_checks,
            "variables": self.variables,
            "domains": {k: list(v) for k, v in self.domains.items()},
            "capacities": self.capacities,
            "duration_ms": round(self.duration_ms, 2),
        }


class HospitalAllocator:
    """CSP solver: chronological backtracking + MRV + LCV + forward
    checking, with capacity constraints."""

    def __init__(self, max_distance_units: float = 180.0) -> None:
        self.max_distance = max_distance_units

    # ------------------------------------------------------------------ #
    # Public entry                                                        #
    # ------------------------------------------------------------------ #
    def solve(self,
              incidents: Sequence[Any],
              hospitals: Sequence[Any],
              graph,
              allow_partial: bool = True) -> AllocationResult:
        """``incidents`` are objects with .id and .node; ``hospitals`` with
        .id, .node, .free_beds(). Builds domains, then solves."""
        t0 = time.perf_counter()
        res = AllocationResult()
        res.variables = [inc.id for inc in incidents]
        res.capacities = {h.id: h.free_beds() for h in hospitals}

        for inc in incidents:
            dom = []
            for hosp in hospitals:
                if res.capacities.get(hosp.id, 0) <= 0:
                    continue
                if graph.euclidean_distance(inc.node, hosp.node) <= self.max_distance:
                    dom.append(hosp.id)
            res.domains[inc.id] = dom

        domains = {v: list(res.domains[v]) for v in res.variables}
        used = {h: 0 for h in res.capacities}
        assignment: Dict[str, str] = {}

        ok = self._backtrack(assignment, used, res, domains)

        if not ok and allow_partial:
            # best-effort completion: assign patients to hospitals with
            # remaining capacity; patients left unassigned are handled by
            # the engine's own overflow fallback
            prov: Dict[str, int] = {}
            for var in res.variables:
                if var in assignment or not res.domains.get(var):
                    continue
                candidates = [
                    h for h in res.domains[var]
                    if res.capacities.get(h, 0) - prov.get(h, 0) > 0
                ]
                if not candidates:
                    continue
                choice = min(candidates)
                assignment[var] = choice
                prov[choice] = prov.get(choice, 0) + 1
            res.feasible = False
        else:
            res.feasible = ok

        res.assignments = assignment
        res.duration_ms = (time.perf_counter() - t0) * 1000
        return res

    # ------------------------------------------------------------------ #
    # Backtracking search                                                 #
    # ------------------------------------------------------------------ #
    def _backtrack(self, assignment: Dict[str, str],
                   used: Dict[str, int],
                   res: AllocationResult,
                   domains: Dict[str, List[str]]) -> bool:
        if len(assignment) == len(res.variables):
            res.nodes_explored += 1
            return True

        # ---- MRV: unassigned variable with the fewest legal values -----
        unassigned = [v for v in res.variables if v not in assignment]
        var = min(unassigned, key=lambda v: len(domains[v]))
        if not domains[var]:
            res.nodes_explored += 1
            return False

        # ---- LCV: try values that prune the least ----------------------
        ordered = sorted(domains[var],
                         key=lambda h: self._prune_impact(h, unassigned,
                                                          assignment, domains))

        for value in ordered:
            res.nodes_explored += 1
            res.trace.append({"step": "assign", "var": var, "value": value,
                              "domain_size": len(domains[var]),
                              "backtracks": res.backtracks})
            assignment[var] = value
            used[value] += 1

            pruned = self._forward_check(value, unassigned, assignment,
                                         used, res, domains)
            if pruned is not None:
                if self._backtrack(assignment, used, res, domains):
                    return True
                self._restore(domains, pruned)
            else:
                res.backtracks += 1
                res.trace.append({"step": "backtrack", "var": var,
                                  "value": value,
                                  "backtracks": res.backtracks,
                                  "reason": "empty domain after forward "
                                            "checking"})
            del assignment[var]
            used[value] -= 1
        return False

    def _prune_impact(self, hospital: str, unassigned: Sequence[str],
                      assignment: Dict[str, str],
                      domains: Dict[str, List[str]]) -> int:
        """LCV score: number of (variable, value) pairs this commitment
        would remove from other domains (fewer removals = more flexible)."""
        impact = 0
        for v in unassigned:
            if v in assignment:
                continue
            if hospital in domains[v]:
                impact += 1
        return impact

    def _forward_check(self, hospital: str, unassigned: Sequence[str],
                       assignment: Dict[str, str],
                       used: Dict[str, int],
                       res: AllocationResult,
                       domains: Dict[str, List[str]]) -> Optional[List[Tuple[str, str]]]:
        """Prune ``hospital`` from other domains once its capacity is
        exhausted. Returns pruned pairs (for restore) or None if any
        domain empties (dead end)."""
        pruned: List[Tuple[str, str]] = []
        capacity_hit = used[hospital] >= res.capacities.get(hospital, 0)
        if not capacity_hit:
            return pruned
        for v in unassigned:
            if v in assignment:
                continue
            if hospital in domains[v]:
                domains[v].remove(hospital)
                pruned.append((v, hospital))
                res.forward_checks += 1
                if not domains[v]:
                    return None
        return pruned

    def _restore(self, domains: Dict[str, List[str]],
                 pruned: List[Tuple[str, str]]) -> None:
        for v, h in pruned:
            domains[v].append(h)
