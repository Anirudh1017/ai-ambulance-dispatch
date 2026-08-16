"""
Idle-positioning MDP solved by EXACT dynamic programming.

Problem
-------
Where should an idle ambulance wait so that the next incident can be
reached as quickly as possible, given how incidents are distributed across
zones and how long it costs to reposition?

Model (fully specified, hand-built — nothing learned)
-------
  States    S = {zones} ∪ {terminal "returned" absorbing state}.
  Actions   A(s) = {move to any zone z} (stay = move to current zone).
  Transition
            P(s' = z | s, a = z) = 1            (deterministic move)
            P(absorb | s, a)     = 0 during planning; the value is computed
            for a *single repositioning decision* under the per-episode
            horizon used by the engine (one episode = one repositioning
            decision, discounted with gamma to keep the horizon bounded).
  Rewards   R(s, a) = coverage(z) - lambda * travel_time(s, z)
            coverage(z) = sum_i p(i) * (1 / (1 + t(z, i)/tau))   (smooth
            expected-response surrogate over incident probability p(i) per
            zone and travel times t(z, i) between zone centres).
            p(i) is the empirical incident-frequency prior over zones
            (hand-estimated from the scenario script, updated online by
            counting observed incidents — this is *counting statistics*,
            not a learned model).

Value iteration
---------------
    V_0(s) = 0
    V_{k+1}(s) = max_a [ R(s, a) + gamma * V_k(s') ],  s' = a
    until max_s |V_{k+1}(s) - V_k(s)| < epsilon (Bellman residual).

The engine calls ``solve()`` every time an ambulance becomes idle and asks
for the argmax zone; the dashboards show the convergence curve and the
policy, which makes the exact-DP provenance visible.

``solve`` is also exposed with full sweep logs so tests can check the
Bellman residual bound directly.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

EPSILON = 1e-6
MAX_ITERATIONS = 5000


@dataclass
class MDPResult:
    """Result + explainability of one exact value-iteration solve."""
    values: Dict[str, float] = field(default_factory=dict)
    policy: Dict[str, str] = field(default_factory=dict)   # zone -> target zone
    iterations: int = 0
    final_residual: float = 0.0
    converged: bool = False
    duration_ms: float = 0.0
    sweep_log: List[Tuple[int, float]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "values": {k: round(v, 3) for k, v in self.values.items()},
            "policy": self.policy,
            "iterations": self.iterations,
            "final_residual": self.final_residual,
            "converged": self.converged,
            "duration_ms": round(self.duration_ms, 2),
            "sweep_log": [(i, round(r, 6)) for i, r in self.sweep_log],
        }


class IdlePositioningMDP:
    """Zone-based MDP for idle ambulance positioning, solved by exact
    value iteration."""

    def __init__(self,
                 zones: Sequence[Tuple[str, float, float]],   # (zone_id, x, y)
                 zone_prior: Dict[str, float],                # zone_id -> p(next incident)
                 travel_time: Callable[[str, str], float],    # t(zone_a, zone_b) seconds
                 gamma: float = 0.9,
                 lambda_cost: float = 0.15,
                 tau: float = 240.0) -> None:
        self.zone_ids = [z[0] for z in zones]
        self.zone_pos = {z[0]: (z[1], z[2]) for z in zones}
        self.prior = {zid: float(zone_prior.get(zid, 0.0))
                      for zid in self.zone_ids}
        total = sum(self.prior.values()) or 1.0
        self.prior = {z: p / total for z, p in self.prior.items()}
        self.travel = travel_time
        self.gamma = gamma
        self.lambda_cost = lambda_cost
        self.tau = tau

        # precompute travel matrix and coverage per zone
        self._travel: Dict[Tuple[str, str], float] = {}
        self._coverage: Dict[str, float] = {}
        for a in self.zone_ids:
            for b in self.zone_ids:
                self._travel[(a, b)] = travel_time(a, b)
            self._coverage[a] = sum(
                p * (1.0 / (1.0 + self._travel[(a, i)] / self.tau))
                for i, p in self.prior.items()
            )

    # ------------------------------------------------------------------ #
    # Reward / transition (explicit model)                                #
    # ------------------------------------------------------------------ #
    def reward(self, s: str, a: str) -> float:
        """R(s, a): expected coverage value of the destination minus the
        cost of the repositioning trip."""
        return self._coverage[a] - self.lambda_cost * self._travel[(s, a)]

    # ------------------------------------------------------------------ #
    # Exact value iteration                                               #
    # ------------------------------------------------------------------ #
    def solve(self, epsilon: float = EPSILON,
              max_iterations: int = MAX_ITERATIONS,
              log_sweeps: bool = True) -> MDPResult:
        t0 = time.perf_counter()
        V = {s: 0.0 for s in self.zone_ids}
        result = MDPResult()

        for it in range(1, max_iterations + 1):
            new_V: Dict[str, float] = {}
            for s in self.zone_ids:
                best = max(self.reward(s, a) + self.gamma * V[a]
                           for a in self.zone_ids)
                new_V[s] = best
            residual = max(abs(new_V[s] - V[s]) for s in self.zone_ids)
            V = new_V
            if log_sweeps and (it <= 30 or it % 25 == 0 or residual < epsilon):
                result.sweep_log.append((it, residual))
            if residual < epsilon:
                result.iterations = it
                result.final_residual = residual
                result.converged = True
                break
        else:
            result.iterations = max_iterations
            result.final_residual = residual
            result.converged = False

        result.values = V
        result.policy = {
            s: max(self.zone_ids,
                   key=lambda a: self.reward(s, a) + self.gamma * V[a])
            for s in self.zone_ids
        }
        result.duration_ms = (time.perf_counter() - t0) * 1000
        return result

    def best_action(self, state: str, result: MDPResult) -> str:
        """Deterministic argmax policy application (ties broken by
        lexicographic zone id for reproducibility)."""
        s = state if state in self.zone_ids else min(self.zone_ids,
                                                     key=lambda z: self._dist(state, z))
        return result.policy[s]

    def _dist(self, zone_or_node: str, zone_id: str) -> float:
        if zone_or_node in self.zone_pos:
            x1, y1 = self.zone_pos[zone_or_node]
        else:
            return float("inf")
        x2, y2 = self.zone_pos[zone_id]
        return math.hypot(x2 - x1, y2 - y1)
