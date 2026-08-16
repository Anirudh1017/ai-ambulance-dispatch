"""
Scenario definitions: everything needed to build a simulation run.

``DEFAULT_CONFIG`` holds engine parameters; each named scenario in
``SCENARIOS`` overrides a subset. ``resolve_config(name, seed=None)``
merges the two and returns a ready-to-use config dict.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    # ---- timing ---------------------------------------------------------
    "seconds_per_tick": 2.0,        # simulation seconds advanced per tick
    "max_ticks": 1500,              # default run horizon
    "idle_reposition_every": 40,    # ticks between MDP idle-position solves
    "replan_check_every": 5,        # ticks between D* Lite replan checks
    "scene_radius_units": 14.0,     # detection radius for hidden blockages
    # ---- fleet ----------------------------------------------------------
    "ambulance_count": 4,
    "station_count": 3,             # garage nodes where units are based
    "ambulance_speed_kmh": 45.0,
    "base_response_s": 300.0,       # severity-1 deadline scale
    # ---- world -----------------------------------------------------------
    "grid_cols": 10,
    "grid_rows": 8,
    "cell_km": 0.55,
    "hospital_count": 3,
    "hospital_beds": 6,             # free beds per hospital at t=0
    "zone_count": 8,
    # ---- AI parameters ---------------------------------------------------
    "search": {
        "default": "astar",         # engine routing algorithm
        "weighted_astar_weight": 1.0,
        "arena": ("astar", "dijkstra", "gbfs", "bfs"),
    },
    "dispatch": {
        "w_eta": 0.45, "w_dist": 0.20, "w_status": 0.15, "w_load": 0.20,
    },
    "csp": {"max_distance_units": 150.0},
    "mdp": {"gamma": 0.9, "lambda_cost": 0.12, "tau": 240.0,
            "epsilon": 1e-6},
    "incident_priors": None,        # per-zone p(next incident), auto if None
    # ---- scenario script (spawned over time) ----------------------------
    "incidents": [],                # list of (tick, severity, kind) — nodes auto-picked
    "blockages": [],                # list of (tick, edge_or_node_pair, duration, reveal)
    "seed": 42,
    # ---- explainability ---------------------------------------------------
    "max_event_log": 4000,          # ring buffer of decision events
    "max_snapshot_history": 1500,   # snapshots kept for replay/scrubbing
}

INCIDENT_KINDS = ["cardiac arrest", "trauma", "stroke", "obstetric",
                  "burn", "respiratory distress"]


def _auto_incidents(n: int, start: int = 30, step: int = 95,
                    severities: Optional[List[int]] = None,
                    kinds: Optional[List[str]] = None) -> List[List[Any]]:
    sevs = severities or [2, 3, 3, 4, 2, 3, 5, 2, 4, 3, 2, 3, 4, 2, 3, 5]
    ks = kinds or INCIDENT_KINDS
    out = []
    for i in range(n):
        out.append([start + i * step, sevs[i % len(sevs)], ks[i % len(ks)]])
    return out


SCENARIOS: Dict[str, Dict[str, Any]] = {
    "downtown-rush": {
        "title": "Downtown rush hour",
        "description": "Dense Manhattan grid, a 16-unit fleet across four "
                       "stations, 20 calls with many simultaneous, and two "
                       "scheduled roadworks that ambulances discover only "
                       "when they get close.",
        "grid_cols": 10, "grid_rows": 8, "cell_km": 0.5,
        "ambulance_count": 16, "station_count": 4,
        "hospital_count": 4, "zone_count": 8,
        "max_ticks": 1800,
        "incidents": _auto_incidents(20, start=30, step=70),
        "blockages": [
            [260, ("n2_4", "n2_5"), 300, False],   # hidden roadworks
            [420, ("n4_6", "n4_7"), 250, False],
        ],
    },
    "storm-disaster": {
        "title": "Storm disaster — mass casualty",
        "description": "Burst of simultaneous high-severity incidents and "
                       "unexpected blockages: CSP capacity pressure, "
                       "frequent D* Lite replans, CNP bidding races — "
                       "now with an 18-unit fleet.",
        "grid_cols": 9, "grid_rows": 7, "cell_km": 0.6,
        "ambulance_count": 18, "station_count": 5,
        "hospital_count": 4, "hospital_beds": 1,
        "zone_count": 6, "max_ticks": 2000,
        "csp": {"max_distance_units": 40},   # tight range -> scarce beds
        "incidents": [
            [60, 5, "trauma"], [65, 4, "burn"], [70, 5, "cardiac arrest"],
            [80, 3, "trauma"], [90, 4, "obstetric"], [150, 5, "trauma"],
            [200, 3, "burn"], [240, 4, "cardiac arrest"], [300, 5, "trauma"],
            [320, 3, "stroke"], [420, 4, "trauma"], [520, 2, "respiratory distress"],
            [640, 5, "trauma"], [700, 3, "obstetric"], [800, 4, "burn"],
            [900, 5, "cardiac arrest"], [1000, 3, "trauma"], [1100, 4, "stroke"],
            [1200, 4, "trauma"], [1250, 3, "burn"], [1300, 5, "cardiac arrest"],
            [1350, 4, "obstetric"], [1400, 3, "stroke"], [1450, 2, "respiratory distress"],
            [1500, 4, "trauma"], [1550, 3, "cardiac arrest"],
            [1600, 5, "trauma"], [1650, 2, "burn"], [1700, 4, "stroke"],
            [1750, 3, "cardiac arrest"],
        ],
        "blockages": [
            [120, ("n1_3", "n2_3"), 500, False],
            [200, ("n4_2", "n4_3"), 400, False],
            [400, ("n2_5", "n2_6"), 300, False],
            [650, ("n5_4", "n5_5"), 200, True],   # visible roadworks
            [850, ("n1_6", "n1_7"), 250, False],
        ],
    },
    "quiet-night": {
        "title": "Quiet night shift",
        "description": "Few incidents: the interesting decision is the MDP "
                       "idle-positioning — units drift between zones based "
                       "on the coverage prior and the value-iteration policy.",
        "grid_cols": 8, "grid_rows": 6, "cell_km": 0.7,
        "ambulance_count": 8, "station_count": 3,
        "hospital_count": 3, "zone_count": 6,
        "max_ticks": 2100, "idle_reposition_every": 60,
        "incidents": [
            [80, 3, "trauma"], [300, 2, "stroke"], [520, 4, "cardiac arrest"],
            [750, 2, "burn"], [980, 3, "obstetric"], [1200, 2, "respiratory distress"],
            [1350, 3, "trauma"], [1450, 2, "cardiac arrest"],
        ],
        "blockages": [],
    },
    "gridlock": {
        "title": "Gridlock — congestion experiment",
        "description": "Heavy planned blockages (visible to planners) "
                       "stress the search layer: A* must route around them "
                       "and the arena comparison shows how the algorithms "
                       "diverge — a 16-unit fleet keeps the city moving.",
        "grid_cols": 10, "grid_rows": 8, "cell_km": 0.5,
        "ambulance_count": 16, "station_count": 4,
        "hospital_count": 4, "zone_count": 8,
        "max_ticks": 1700,
        "incidents": _auto_incidents(20, start=40, step=80),
        "blockages": [
            [100, ("n2_2", "n2_3"), 900, True],
            [100, ("n3_5", "n3_6"), 900, True],
            [100, ("n5_2", "n5_3"), 900, True],
            [200, ("n1_7", "n2_7"), 800, True],
            [500, ("n4_1", "n5_1"), 700, True],
        ],
    },
}


def resolve_config(scenario_name: Optional[str] = None,
                   seed: Optional[int] = None,
                   overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge DEFAULT_CONFIG with the named scenario (and any user
    overrides). Returns a deep-ish copy safe to mutate."""
    import copy

    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if scenario_name and scenario_name in SCENARIOS:
        cfg.update(copy.deepcopy(SCENARIOS[scenario_name]))
    if seed is not None:
        cfg["seed"] = seed
    if overrides:
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    cfg["name"] = scenario_name or "custom"
    cfg["title"] = SCENARIOS.get(scenario_name or "", {}).get(
        "title", "Custom configuration")
    cfg["description"] = SCENARIOS.get(scenario_name or "", {}).get(
        "description", "Hand-assembled configuration.")
    if cfg.get("incident_priors") is None:
        cfg["incident_priors"] = "auto"
    return cfg


def seed_rng(cfg: Dict[str, Any]) -> random.Random:
    return random.Random(cfg["seed"])


def scenario_summaries() -> List[Dict[str, Any]]:
    return [
        {"id": sid, "title": s.get("title", sid),
         "description": s.get("description", ""),
         "ambulances": s.get("ambulance_count"),
         "stations": s.get("station_count"),
         "incidents": len(s.get("incidents", [])),
         "max_ticks": s.get("max_ticks")}
        for sid, s in SCENARIOS.items()
    ]
