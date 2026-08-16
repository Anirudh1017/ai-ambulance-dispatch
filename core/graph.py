"""
Road-network layer: a weighted, undirected graph with geometric node
positions, travel-time edge weights, a hidden-blockage map (partial
observability), and a spatial zone map used by the MDP idle-positioning
module.

The engine treats the graph as the *true* world. Planners (search module)
consult it through ``visible_cost``, which hides blockages that the
simulation has not yet revealed — this is the partial-observability
mechanism of the project.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import networkx as nx

INF = float("inf")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres (used to build realistic city
    geometries from latitude/longitude coordinates)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Zone:
    """A coverage zone: the MDP state space of the idle-positioning problem."""
    id: str
    center: Tuple[float, float]      # (x, y) in graph coordinates
    label: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {"id": self.id, "center": list(self.center), "label": self.label}


class RoadNetwork:
    """Weighted undirected graph with per-edge travel times and a
    hidden blockage map.

    Edge weights are travel times (seconds). ``visible_cost(u, v)`` is what
    search algorithms see; blocked edges that have not been revealed yet are
    reported at their nominal cost, so planners can unknowingly plan through
    a future blockage until the simulation reveals it (``reveal_blockage``).
    """

    def __init__(self, graph: Optional[nx.Graph] = None) -> None:
        self.graph: nx.Graph = graph if graph is not None else nx.Graph()
        self._blocked: Set[Tuple[str, str]] = set()       # true blockages
        self._revealed: Set[Tuple[str, str]] = set()      # known to planners
        self._block_age: Dict[Tuple[str, str], int] = {}  # remaining ticks

    # -- construction ------------------------------------------------------ #
    def add_node(self, node: str, x: float, y: float,
                 **attrs: object) -> None:
        self.graph.add_node(node, x=x, y=y, **attrs)

    def add_edge(self, u: str, v: str, travel_seconds: float) -> None:
        self.graph.add_edge(u, v, travel_seconds=travel_seconds)

    # -- structure --------------------------------------------------------- #
    @property
    def nodes(self) -> List[str]:
        return list(self.graph.nodes)

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def node_pos(self, node: str) -> Tuple[float, float]:
        d = self.graph.nodes[node]
        return float(d["x"]), float(d["y"])

    def neighbors(self, node: str) -> List[str]:
        return list(self.graph.neighbors(node))

    def edges(self) -> Iterable[Tuple[str, str]]:
        return self.graph.edges()

    def random_node(self, rng: random.Random) -> str:
        return rng.choice(self.nodes)

    def edge_key(self, u: str, v: str) -> Tuple[str, str]:
        """Canonical undirected edge key."""
        return (u, v) if u <= v else (v, u)

    # -- costs ------------------------------------------------------------- #
    def true_cost(self, u: str, v: str) -> float:
        return float(self.graph[u][v]["travel_seconds"])

    def visible_cost(self, u: str, v: str) -> float:
        """Cost visible to planners. Blocked-but-unrevealed edges report
        their nominal cost (agents cannot see the future)."""
        k = self.edge_key(u, v)
        if k in self._revealed:
            return INF
        return self.true_cost(u, v)

    def is_blocked(self, u: str, v: str) -> bool:
        return self.edge_key(u, v) in self._blocked

    def is_revealed_blocked(self, u: str, v: str) -> bool:
        return self.edge_key(u, v) in self._revealed

    # -- blockage lifecycle ------------------------------------------------- #
    def block_edge(self, u: str, v: str, duration_ticks: int = 999_999,
                   reveal: bool = True) -> None:
        """Create a real blockage. If ``reveal`` is True the planners learn
        immediately (scheduled roadworks); otherwise it is hidden until an
        ambulance physically reaches the edge (partial observability)."""
        k = self.edge_key(u, v)
        self._blocked.add(k)
        self._block_age[k] = duration_ticks
        if reveal:
            self._revealed.add(k)

    def unblock_edge(self, u: str, v: str) -> None:
        k = self.edge_key(u, v)
        self._blocked.discard(k)
        self._revealed.discard(k)
        self._block_age.pop(k, None)

    def reveal_blockage(self, u: str, v: str) -> bool:
        """Ambulance physically detects a blocked edge; returns True if the
        planner's world model actually changed."""
        k = self.edge_key(u, v)
        if k in self._blocked and k not in self._revealed:
            self._revealed.add(k)
            return True
        return False

    def hidden_blockages(self) -> List[Tuple[str, str]]:
        return [list(k) for k in self._blocked - self._revealed]

    def tick_blockages(self) -> List[Tuple[str, str]]:
        """Advance blockage lifespans; remove expired ones. Returns the
        edges that were unblocked this tick."""
        expired: List[Tuple[str, str]] = []
        for k in list(self._block_age):
            self._block_age[k] -= 1
            if self._block_age[k] <= 0:
                expired.append(k)
                self.unblock_edge(*k)
        return expired

    def blocked_edges(self) -> List[Tuple[str, str]]:
        return [k for k in self._blocked]

    # -- geometry helpers --------------------------------------------------- #
    def euclidean_distance(self, u: str, v: str) -> float:
        x1, y1 = self.node_pos(u)
        x2, y2 = self.node_pos(v)
        return math.hypot(x2 - x1, y2 - y1)

    def distance_km(self, u: str, v: str) -> float:
        """Approximate km from graph units (world is generated to ~1 unit =
        100 m, so km = units / 10)."""
        return self.euclidean_distance(u, v) / 10.0

    def random_edge(self, rng: random.Random) -> Tuple[str, str]:
        return tuple(rng.choice(list(self.graph.edges())))

    # -- serialisation ------------------------------------------------------- #
    def to_dict(self) -> Dict[str, object]:
        return {
            "nodes": [
                {"id": n, "x": d["x"], "y": d["y"]}
                for n, d in self.graph.nodes(data=True)
            ],
            "edges": [
                {"u": u, "v": v, "travel_seconds": d["travel_seconds"]}
                for u, v, d in self.graph.edges(data=True)
            ],
            "blocked": [list(k) for k in self._blocked],
            "revealed": [list(k) for k in self._revealed],
        }


class ZoneMap:
    """Spatial partition of the city into coverage zones (MDP states).

    Zones are built by a simple k-means-style clustering of graph nodes
    (Lloyd's algorithm over node coordinates) so that each zone is a
    coherent neighbourhood.
    """

    def __init__(self, zones: Sequence[Zone]) -> None:
        self.zones = list(zones)
        self._zone_of: Dict[str, str] = {}

    @classmethod
    def build(cls, network: RoadNetwork, n_zones: int, rng: Optional[random.Random] = None,
              labels: Optional[Sequence[str]] = None) -> "ZoneMap":
        rng = rng or random.Random(7)
        nodes = network.nodes
        coords = [network.node_pos(n) for n in nodes]

        centers = rng.sample(coords, min(n_zones, len(coords)))
        assignment = [0] * len(nodes)
        for _ in range(25):
            changed = False
            for i, (x, y) in enumerate(coords):
                best, best_d = 0, float("inf")
                for j, (cx, cy) in enumerate(centers):
                    d = (x - cx) ** 2 + (y - cy) ** 2
                    if d < best_d:
                        best, best_d = j, d
                if assignment[i] != best:
                    assignment[i], changed = best, True
            if not changed:
                break
            sums = [(0.0, 0.0, 0) for _ in centers]
            for i, (x, y) in enumerate(coords):
                sx, sy, c = sums[assignment[i]]
                sums[assignment[i]] = (sx + x, sy + y, c + 1)
            centers = [
                (sx / c, sy / c) if c else centers[j]
                for j, (sx, sy, c) in enumerate(sums)
            ]

        zone_labels = list(labels) if labels else [
            f"Z{j + 1}" for j in range(len(centers))]
        zones = [
            Zone(f"zone-{j + 1}", (round(cx, 1), round(cy, 1)), zone_labels[j])
            for j, (cx, cy) in enumerate(centers)
        ]
        zm = cls(zones)
        for i, n in enumerate(nodes):
            zm._zone_of[n] = zones[assignment[i]].id
        return zm

    def zone_of_node(self, node: str) -> str:
        return self._zone_of.get(node, self.zones[0].id)

    def zone_center(self, zone_id: str) -> Tuple[float, float]:
        for z in self.zones:
            if z.id == zone_id:
                return z.center
        raise KeyError(zone_id)

    def zone_center_node(self, network: RoadNetwork, zone_id: str) -> str:
        """Nearest graph node to a zone centre — where an idle ambulance
        will physically drift."""
        cx, cy = self.zone_center(zone_id)
        return min(network.nodes,
                   key=lambda n: (network.node_pos(n)[0] - cx) ** 2
                                 + (network.node_pos(n)[1] - cy) ** 2)

    def zone_count(self) -> int:
        return len(self.zones)

    def to_dict(self) -> List[Dict[str, object]]:
        return [z.to_dict() for z in self.zones]


def build_grid_network(
    cols: int = 9,
    rows: int = 7,
    cell_km: float = 0.6,
    speed_kmh: float = 40.0,
    rng: Optional[random.Random] = None,
) -> RoadNetwork:
    """Build a Manhattan-style grid road network. Nodes at grid
    intersections, weighted edges proportional to cell size and inverse
    speed (with mild per-edge noise for realism). 1 graph unit = 100 m."""
    rng = rng or random.Random(1)
    net = RoadNetwork()
    units = cell_km * 10.0          # graph units
    seconds = cell_km / (speed_kmh / 3600.0)

    for r in range(rows):
        for c in range(cols):
            nid = f"n{r}_{c}"
            net.add_node(nid, x=c * units, y=r * units)

    for r in range(rows):
        for c in range(cols):
            nid = f"n{r}_{c}"
            if c + 1 < cols:
                nid_r = f"n{r}_{c + 1}"
                net.add_edge(nid, nid_r, seconds * rng.uniform(0.85, 1.15))
            if r + 1 < rows:
                nid_d = f"n{r + 1}_{c}"
                net.add_edge(nid, nid_d, seconds * rng.uniform(0.85, 1.15))
    return net


def build_radial_network(
    rings: int = 4,
    spokes: int = 8,
    ring_km: float = 0.9,
    speed_kmh: float = 45.0,
    rng: Optional[random.Random] = None,
) -> RoadNetwork:
    """Build a radial (ring + spoke) city network for variety."""
    rng = rng or random.Random(2)
    net = RoadNetwork()
    center = "c0"
    net.add_node(center, x=0.0, y=0.0)
    node_ids = [center]

    for r in range(1, rings + 1):
        radius = r * ring_km * 10.0
        for s in range(spokes):
            ang = 2 * math.pi * s / spokes
            nid = f"r{r}s{s}"
            net.add_node(nid, x=radius * math.cos(ang), y=radius * math.sin(ang))
            node_ids.append(nid)
            if r == 1:
                sec = (ring_km / (speed_kmh / 3600.0)) * rng.uniform(0.85, 1.15)
                net.add_edge(center, nid, sec)
            else:
                prev = f"r{r - 1}s{s}"
                sec = (ring_km / (speed_kmh / 3600.0)) * rng.uniform(0.85, 1.15)
                net.add_edge(prev, nid, sec)
            nxt = f"r{r}s{(s + 1) % spokes}"
            if nxt not in net.graph[nid]:
                arc = (2 * math.pi * radius / spokes / 10.0)
                sec = (arc / (speed_kmh / 3600.0)) * rng.uniform(0.85, 1.15)
                net.add_edge(nid, nxt, sec)
    return net
