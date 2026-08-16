"""
Headless empirical benchmark harness for the baseline-comparison study.

Runs the deterministic engine over scenario × seed × policy-combo cells,
logs per-run metrics, aggregates them, and renders a coursework-style
report: CSV + Markdown + matplotlib PNG charts (see ``run_benchmark.py``
for the CLI entry point).

Policy combos
-------------
``smart``    — CNP auction · D* Lite · MDP idle positioning · CSP allocation
``baseline`` — greedy nearest · full A* rerun · return-to-station ·
               first-free-bed  (every subsystem on its naive baseline)
With ``full=True`` each subsystem is also flipped *individually* against
the smart stack (4 more combos), isolating the marginal value of each
algorithm. Every cell is deterministic: the engine is seeded, and the
whole harness shares one fixed, documented seed schedule.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .engine import Engine

# --------------------------------------------------------------------------- #
# Policy combos                                                                #
# --------------------------------------------------------------------------- #

SMART_POLICIES: Dict[str, str] = {
    "dispatch": "cnp", "replan": "dstar", "idle": "mdp", "hospital": "csp",
}
BASELINE_POLICIES: Dict[str, str] = {
    "dispatch": "greedy", "replan": "full_astar", "idle": "station",
    "hospital": "first_free",
}

COMBO_LABELS: Dict[str, str] = {
    "smart": "Smart stack (CNP · D*Lite · MDP · CSP)",
    "baseline": "Naive stack (greedy · A* rerun · station · first-free)",
    "flip_dispatch": "Smart minus CNP (greedy dispatch)",
    "flip_replan": "Smart minus D* Lite (full A* rerun)",
    "flip_idle": "Smart minus MDP (return-to-station)",
    "flip_hospital": "Smart minus CSP (first free bed)",
}


def combos(full: bool = False) -> List[Dict[str, str]]:
    """Ordered policy sets: [smart, baseline] + 4 single flips when full."""
    out: List[Dict[str, str]] = [dict(SMART_POLICIES), dict(BASELINE_POLICIES)]
    if full:
        for subsystem, baseline in [
            ("dispatch", "greedy"), ("replan", "full_astar"),
            ("idle", "station"), ("hospital", "first_free")]:
            flipped = dict(SMART_POLICIES)
            flipped[subsystem] = baseline
            out.append(flipped)
    return out


def combo_name(policies: Dict[str, str]) -> str:
    """Label for a policies dict ('' smart, full flip name, else baseline)."""
    if policies == SMART_POLICIES:
        return "smart"
    if policies == BASELINE_POLICIES:
        return "baseline"
    diffs = [k for k in SMART_POLICIES if policies.get(k) != SMART_POLICIES[k]]
    if len(diffs) == 1 and policies.get(diffs[0]) \
            == BASELINE_POLICIES[diffs[0]]:
        return f"flip_{diffs[0]}"
    return "+".join(sorted(diffs))


def default_seeds(n: int = 30) -> List[int]:
    """Fixed, documented seed schedule — reproducibility of the study."""
    return list(range(1, n + 1))


# --------------------------------------------------------------------------- #
# Per-run metrics                                                              #
# --------------------------------------------------------------------------- #

def _metric_row(scenario: str, seed: int, combo: str,
                policies: Dict[str, str], stats: Dict[str, Any],
                runtime_ms: float) -> Dict[str, Any]:
    ex = stats["search_expansions"]
    eq = stats.get("equity") or {}
    wins = list(stats.get("dispatch_wins", {}).values()) or [0]
    return {
        "scenario": scenario,
        "seed": seed,
        "combo": combo,
        "policies": "/".join(policies[k] for k in
                             ("dispatch", "replan", "idle", "hospital")),
        "incidents_reported": stats["incidents_reported"],
        "incidents_cleared": stats["incidents_cleared"],
        "workload_max": max(wins),
        "workload_spread": max(wins) - min(wins),
        "response_avg": round(stats["response_avg"], 2),
        "response_p95": round(stats["response_p95"], 2),
        "response_variance": round(stats["response_variance"], 2),
        "equity_gini": round(eq.get("gini", 0.0), 4),
        "zone_variance": round(eq.get("zone_variance", 0.0), 2),
        "max_min_ratio": round(eq.get("max_min_ratio") or 0.0, 3),
        "distance_km": round(stats["total_distance_km"], 1),
        "replans": stats["replans"],
        "astar_expansions": ex["astar"],
        "dstar_expansions": ex["dstar"],
        "replan_full_expansions": stats["replan_full_expansions"],
        "replan_savings_expansions": stats["replan_savings_expansions"],
        "csp_solves": stats["csp_solves"],
        "csp_backtracks": stats["csp_backtracks"],
        "mdp_solves": stats["mdp_solves"],
        "arena_runs": stats["arena_runs"],
        "renegotiations": stats["renegotiations"],
        "renegotiation_savings_s": round(
            stats["renegotiation_savings_s"], 1),
        "runtime_ms": round(runtime_ms, 1),
    }


def run_one(scenario: str, seed: int,
            policies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One deterministic engine run; returns the metric row (with combo)."""
    policies = policies or dict(SMART_POLICIES)
    t0 = time.perf_counter()
    eng = Engine(scenario=scenario, seed=seed, config={"policies": policies})
    eng.run()
    runtime_ms = (time.perf_counter() - t0) * 1000.0
    return _metric_row(scenario, seed, combo_name(policies), policies,
                       eng.stats, runtime_ms)


def run_benchmark(scenarios: Sequence[str], seeds: Sequence[int],
                  full: bool = False,
                  policies_list: Optional[Sequence[Dict[str, str]]] = None,
                  progress: Optional[callable] = None) -> pd.DataFrame:
    """Run every scenario × seed × combo cell. Deterministic for a fixed
    seed schedule (all engine randomness is seeded). ``progress`` gets
    (done, total, label) for CLI/UI tickers."""
    rows: List[Dict[str, Any]] = []
    total = len(scenarios) * len(seeds) * (len(policies_list or combos(full)))
    done = 0
    for scenario in scenarios:
        for seed in seeds:
            for policies in (policies_list or combos(full)):
                label = f"{scenario} s{seed} {combo_name(policies)}"
                rows.append(run_one(scenario, seed, policies))
                done += 1
                if progress:
                    progress(done, total, label)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Aggregation                                                                 #
# --------------------------------------------------------------------------- #

AGG_COLUMNS: Tuple[str, ...] = (
    "incidents_cleared", "workload_max", "workload_spread",
    "response_avg", "response_p95",
    "response_variance", "equity_gini", "zone_variance", "max_min_ratio",
    "distance_km", "replans", "astar_expansions", "dstar_expansions",
    "replan_savings_expansions", "csp_backtracks", "mdp_solves",
    "renegotiations",
)


def aggregate(df: pd.DataFrame,
              group: Sequence[str] = ("scenario", "combo")) -> pd.DataFrame:
    """Mean + std per cell over the seeds, with the per-run variance of
    response times carried as-is (it is already within-run)."""
    means = df.groupby(list(group))[list(AGG_COLUMNS)].mean().round(3)
    stds = df.groupby(list(group))[
        [c for c in AGG_COLUMNS
         if c not in ("response_variance", "max_min_ratio")]].std().round(3)
    out = means.copy()
    for c in stds.columns:
        out[f"{c}_std"] = stds[c]
    return out.reset_index()


def overall(df: pd.DataFrame) -> pd.DataFrame:
    """One row per combo averaged across all scenario-seed cells."""
    return aggregate(df, group=("combo",))