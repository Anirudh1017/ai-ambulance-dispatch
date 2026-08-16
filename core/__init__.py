"""
FOAI Project — AI-Based Ambulance Dispatch & Routing System.

Classical-AI simulation core (NO machine learning anywhere in this package):
  * A* / Greedy Best-First / Dijkstra / LRTA* / D* Lite  -> core.search
  * Contract Net Protocol (multi-agent dispatch)          -> core.dispatch
  * Constraint Satisfaction (hospital allocation)         -> core.hospital_allocation
  * Markov Decision Process + exact value iteration      -> core.mdp
  * Tick-based dynamic, partially observable simulation  -> core.engine

Both user interfaces (FastAPI web dashboard and Textual CLI dashboard) consume
the same engine through the same snapshot()/events_since() interface.
"""

__version__ = "1.0.0"

from .graph import RoadNetwork, ZoneMap, haversine_km  # noqa: F401
from .search import (  # noqa: F401
    SearchResult,
    astar,
    greedy_best_first,
    dijkstra,
    LRTAStar,
    DStarLite,
    algorithm_arena,
    INF,
)
from .dispatch import CnpAuctioneer, AuctionRecord  # noqa: F401
from .hospital_allocation import HospitalAllocator, AllocationResult  # noqa: F401
from .mdp import IdlePositioningMDP  # noqa: F401
from .scenarios import DEFAULT_CONFIG, SCENARIOS, resolve_config  # noqa: F401
from .engine import Engine, Ambulance, Incident, Hospital  # noqa: F401
