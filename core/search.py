"""
Classical graph search algorithms (NO machine learning — every decision is
a hand-specified algorithm):

  * A* / weighted A*            — informed, optimal (admissible h)
  * Greedy best-first search    — informed, sub-optimal, very fast
  * Dijkstra (uniform cost)     — uninformed, optimal
  * BFS (unweighted)            — uninformed, completeness on finite graphs
  * LRTA*                       — real-time search with learning
  * D* Lite                     — incremental replanning when edge costs change

Every algorithm returns a ``SearchResult`` that also records its exploration
trace (each expanded state + f/g/h values) so the dashboards can explain
exactly why a route was chosen, and the ``algorithm_arena`` helper compares
algorithms head-to-head on the same query.
"""

from __future__ import annotations

import heapq
import itertools
import math
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

INF = float("inf")


# --------------------------------------------------------------------------- #
# Result type                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class SearchResult:
    """Outcome of one search run, with an explainable trace."""
    algorithm: str
    start: str
    goal: str
    path: List[str] = field(default_factory=list)
    cost: Optional[float] = None
    nodes_expanded: int = 0
    states_generated: int = 0
    frontier_max: int = 0
    duration_ms: float = 0.0
    optimal: bool = False
    reason: str = "solved"
    h_consistent: Optional[bool] = None
    h_admissible: Optional[bool] = None
    trace: List[Dict[str, object]] = field(default_factory=list)

    def add_trace(self, node: str, g: float, h: float, f: float,
                  expanded: bool) -> None:
        self.trace.append({"node": node, "g": round(g, 2), "h": round(h, 2),
                           "f": round(f, 2), "expanded": expanded})

    def summary(self) -> Dict[str, object]:
        return {
            "algorithm": self.algorithm,
            "start": self.start,
            "goal": self.goal,
            "path": self.path,
            "cost": self.cost,
            "nodes_expanded": self.nodes_expanded,
            "states_generated": self.states_generated,
            "frontier_max": self.frontier_max,
            "duration_ms": round(self.duration_ms, 2),
            "optimal": self.optimal,
            "reason": self.reason,
            "h_consistent": self.h_consistent,
            "h_admissible": self.h_admissible,
        }

    def to_dict(self) -> Dict[str, object]:
        return {**self.summary(), "trace": self.trace}


# --------------------------------------------------------------------------- #
# Heuristics                                                                  #
# --------------------------------------------------------------------------- #

def euclidean_heuristic(graph, u: str, v: str) -> float:
    return graph.euclidean_distance(u, v)


def zero_heuristic(graph, u: str, v: str) -> float:
    return 0.0


def heuristic_consistent(graph, h) -> bool:
    """Checks h(u) <= c(u,v) + h(v) for every edge — proves admissibility
    for graph search on the current costs."""
    for u, v in graph.edges():
        if h(graph, u, v) > graph.visible_cost(u, v) + h(graph, v, u) + 1e-9:
            return False
    return True


def heuristic_admissible(graph, h) -> bool:
    """Checks h(goal) = 0 and consistency implies admissibility on graphs;
    we also verify h(u) <= true shortest cost to goal on all nodes by running
    a full Dijkstra — only feasible on small graphs, which is exactly our
    coursework setting."""
    if not graph.nodes:
        return True
    goal = next(iter(graph.nodes))
    dist = _dijkstra_dist(graph, goal)
    for n in graph.nodes:
        if h(graph, n, goal) > dist[n] + 1e-9:
            return False
    return True


def _dijkstra_dist(graph, source: str) -> Dict[str, float]:
    dist = {n: INF for n in graph.nodes}
    dist[source] = 0.0
    pq = [(0.0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v in graph.neighbors(u):
            nd = d + graph.visible_cost(u, v)
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


# --------------------------------------------------------------------------- #
# Shared machinery                                                            #
# --------------------------------------------------------------------------- #

def _expand(graph, node: str) -> List[Tuple[str, float]]:
    return [(v, graph.visible_cost(node, v))
            for v in graph.neighbors(node)]


def _reconstruct(came_from: Dict[str, str], start: str, goal: str) -> List[str]:
    path = [goal]
    while path[-1] != start:
        path.append(came_from[path[-1]])
    return list(reversed(path))


def _path_cost(graph, path: Sequence[str]) -> float:
    return sum(graph.visible_cost(path[i], path[i + 1])
               for i in range(len(path) - 1))


# --------------------------------------------------------------------------- #
# A* / weighted A*                                                            #
# --------------------------------------------------------------------------- #

def astar(graph, start: str, goal: str,
          heuristic: Callable = euclidean_heuristic,
          weight: float = 1.0,
          max_nodes: int = 100_000,
          record_trace: bool = True) -> SearchResult:
    """A* (weighted). With ``weight`` = 1 and an admissible heuristic it is
    optimal; larger weights trade optimality for speed."""
    t0 = time.perf_counter()
    res = SearchResult(algorithm=f"A*{'×' + str(weight) if weight != 1.0 else ''}",
                       start=start, goal=goal)
    h_start = heuristic(graph, start, goal)
    open_heap = [(h_start, 0, 0.0, start)]
    open_priority: Dict[str, float] = {start: h_start}
    g_score: Dict[str, float] = {start: 0.0}
    came_from: Dict[str, str] = {}
    closed: set = set()
    counter = itertools.count()

    while open_heap:
        res.frontier_max = max(res.frontier_max, len(open_heap))
        f, _, g, node = heapq.heappop(open_heap)
        if open_priority.get(node, INF) != f or g_score.get(node, INF) != g:
            continue
        if node == goal:
            res.path = _reconstruct(came_from, start, goal)
            res.cost = g
            res.h_admissible = True if res.h_admissible is None else res.h_admissible
            res.optimal = weight == 1.0 and bool(res.h_admissible)
            res.duration_ms = (time.perf_counter() - t0) * 1000
            res.reason = "goal reached"
            return res
        closed.add(node)
        res.nodes_expanded += 1
        if record_trace:
            res.add_trace(node, g, heuristic(graph, node, goal), f, True)
        for v, c in _expand(graph, node):
            tentative = g + c
            if v in closed and tentative >= g_score.get(v, INF):
                continue
            res.states_generated += 1
            if tentative < g_score.get(v, INF):
                came_from[v] = node
                g_score[v] = tentative
                hv = heuristic(graph, v, goal)
                fv = tentative + weight * hv
                open_priority[v] = fv
                heapq.heappush(open_heap, (fv, next(counter), tentative, v))
                if record_trace:
                    res.add_trace(v, tentative, hv, fv, False)
        if res.nodes_expanded >= max_nodes:
            res.duration_ms = (time.perf_counter() - t0) * 1000
            res.reason = f"node budget {max_nodes} exhausted"
            if goal in g_score:
                res.path = _reconstruct(came_from, start, goal)
                res.cost = g_score[goal]
            return res
    res.duration_ms = (time.perf_counter() - t0) * 1000
    res.reason = "no path (search exhausted)"
    return res


# --------------------------------------------------------------------------- #
# Greedy best-first search                                                    #
# --------------------------------------------------------------------------- #

def greedy_best_first(graph, start: str, goal: str,
                      heuristic: Callable = euclidean_heuristic,
                      max_nodes: int = 100_000,
                      record_trace: bool = True) -> SearchResult:
    """Greedy best-first: expand the frontier state with smallest h(s).
    Extremely fast but not optimal (can take a long detour)."""
    t0 = time.perf_counter()
    res = SearchResult(algorithm="GBFS", start=start, goal=goal)
    heap: List[Tuple[float, int, str]] = [(heuristic(graph, start, goal), 0, start)]
    visited: set = set()
    came_from: Dict[str, str] = {}
    counter = itertools.count()

    while heap:
        res.frontier_max = max(res.frontier_max, len(heap))
        _, _, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        res.nodes_expanded += 1
        if record_trace:
            h = heuristic(graph, node, goal)
            res.add_trace(node, float("nan"), h, h, True)
        if node == goal:
            res.path = _reconstruct(came_from, start, goal)
            res.cost = _path_cost(graph, res.path)
            res.optimal = False
            res.duration_ms = (time.perf_counter() - t0) * 1000
            res.reason = "goal reached"
            return res
        for v, _ in _expand(graph, node):
            if v in visited:
                continue
            res.states_generated += 1
            came_from.setdefault(v, node)
            heapq.heappush(heap, (heuristic(graph, v, goal), next(counter), v))
        if res.nodes_expanded >= max_nodes:
            res.duration_ms = (time.perf_counter() - t0) * 1000
            res.reason = f"node budget {max_nodes} exhausted"
            return res
    res.duration_ms = (time.perf_counter() - t0) * 1000
    res.reason = "no path (search exhausted)"
    return res


# --------------------------------------------------------------------------- #
# Dijkstra (uniform-cost / uninformed)                                        #
# --------------------------------------------------------------------------- #

def dijkstra(graph, start: str, goal: str,
             max_nodes: int = 100_000,
             record_trace: bool = False) -> SearchResult:
    """Uniform-cost search: optimal, ignores the heuristic entirely."""
    t0 = time.perf_counter()
    res = SearchResult(algorithm="Dijkstra", start=start, goal=goal)
    heap = [(0.0, 0, start)]
    dist: Dict[str, float] = {start: 0.0}
    came_from: Dict[str, str] = {}
    closed: set = set()
    counter = itertools.count()

    while heap:
        res.frontier_max = max(res.frontier_max, len(heap))
        d, _, node = heapq.heappop(heap)
        if d != dist.get(node):
            continue
        if node == goal:
            res.path = _reconstruct(came_from, start, goal)
            res.cost = d
            res.optimal = True
            res.duration_ms = (time.perf_counter() - t0) * 1000
            res.reason = "goal reached"
            return res
        if node in closed:
            continue
        closed.add(node)
        res.nodes_expanded += 1
        for v, c in _expand(graph, node):
            nd = d + c
            res.states_generated += 1
            if nd < dist.get(v, INF):
                dist[v] = nd
                came_from[v] = node
                heapq.heappush(heap, (nd, next(counter), v))
        if res.nodes_expanded >= max_nodes:
            res.duration_ms = (time.perf_counter() - t0) * 1000
            res.reason = f"node budget {max_nodes} exhausted"
            return res
    res.duration_ms = (time.perf_counter() - t0) * 1000
    res.reason = "no path (search exhausted)"
    return res


# --------------------------------------------------------------------------- #
# BFS (unweighted, uninformed)                                                #
# --------------------------------------------------------------------------- #

def breadth_first(graph, start: str, goal: str,
                  max_nodes: int = 100_000,
                  record_trace: bool = False) -> SearchResult:
    """Breadth-first search over the unweighted graph: finds a route with
    fewest edges, ignoring travel times."""
    t0 = time.perf_counter()
    res = SearchResult(algorithm="BFS", start=start, goal=goal)
    from collections import deque
    queue = deque([start])
    visited: set = {start}
    came_from: Dict[str, str] = {}

    while queue:
        node = queue.popleft()
        res.nodes_expanded += 1
        if node == goal:
            res.path = _reconstruct(came_from, start, goal)
            res.cost = _path_cost(graph, res.path)
            res.optimal = False
            res.duration_ms = (time.perf_counter() - t0) * 1000
            res.reason = "goal reached"
            return res
        for v, _ in _expand(graph, node):
            if v not in visited:
                visited.add(v)
                came_from[v] = node
                queue.append(v)
                res.states_generated += 1
        if res.nodes_expanded >= max_nodes:
            res.duration_ms = (time.perf_counter() - t0) * 1000
            res.reason = f"node budget {max_nodes} exhausted"
            return res
    res.duration_ms = (time.perf_counter() - t0) * 1000
    res.reason = "no path (search exhausted)"
    return res


# --------------------------------------------------------------------------- #
# LRTA* — real-time search with learning                                     #
# --------------------------------------------------------------------------- #

class LRTAStar:
    """Learning Real-Time A* (Korf 1990).

    The agent moves one step per ``act`` call — it interleaves planning and
    execution, commits to a move before seeing the full path, and *learns*
    improved heuristic values (h updates) from what it observes along the
    way. h(s) := c(s, s') + h(s') where s' minimises c(s,s') + h(s'). This is
    the exact classical algorithm — not any form of learned model.

    Used in the simulation for "urgent dispatch on a ticking clock": a unit
    starts moving immediately and refines its plan every time it stops.
    """

    def __init__(self, graph, start: str, goal: str,
                 heuristic: Callable = euclidean_heuristic) -> None:
        self.graph = graph
        self.goal = goal
        self.h: Dict[str, float] = {
            n: heuristic(graph, n, goal) for n in graph.nodes
        }
        self.h[goal] = 0.0
        self.position = start
        self.steps = 0
        self.nodes_expanded = 0
        self.updates: List[Dict[str, object]] = []

    def act(self) -> str:
        """One real-time step: return the next node to move to."""
        if self.position == self.goal:
            return self.goal
        g0 = self.h[self.position]
        best_next, best_val, best_h = None, INF, None
        candidates = []
        for v in self.graph.neighbors(self.position):
            c = self.graph.visible_cost(self.position, v)
            hv = self.h.get(v, INF)
            candidates.append((c + hv, v))
            self.nodes_expanded += 1
        candidates.sort()
        if not candidates:
            self.h[self.position] = INF
            return self.position
        best_val, best_next = candidates[0]
        best_h = self.h[best_next]
        new_h = max(g0, best_val)
        if abs(new_h - g0) > 1e-9:
            self.updates.append({
                "node": self.position, "h_before": round(g0, 2),
                "h_after": round(new_h, 2),
                "via": best_next, "learned": best_val,
            })
            self.h[self.position] = new_h
        self.steps += 1
        self.position = best_next
        return best_next

    def run(self, max_steps: int = 10_000) -> SearchResult:
        """Execute the agent to the goal; return a SearchResult describing
        the walk (may contain revisits)."""
        t0 = time.perf_counter()
        path = [self.position]
        while self.position != self.goal and self.steps < max_steps:
            path.append(self.act())
        res = SearchResult(algorithm="LRTA*", start=path[0], goal=self.goal,
                           path=path, nodes_expanded=self.nodes_expanded,
                           states_generated=self.nodes_expanded,
                           duration_ms=(time.perf_counter() - t0) * 1000,
                           optimal=False,
                           reason=("goal reached" if self.position == self.goal
                                   else "step budget exhausted"))
        if self.position == self.goal:
            res.cost = sum(self.graph.visible_cost(path[i], path[i + 1])
                           for i in range(len(path) - 1))
        res.trace = self.updates
        return res


# --------------------------------------------------------------------------- #
# D* Lite — incremental replanning                                            #
# --------------------------------------------------------------------------- #

class DStarLite:
    """D* Lite (Koenig & Likhachev 2002) for incremental replanning.

    Maintains g and rhs values over the graph; when edge costs change
    (a blockage is discovered mid-route), ``replan`` repairs only the
    affected portion of the search instead of re-searching from scratch.
    Used by the simulation whenever an ambulance hits an unexpected
    blockage — the partial-observability replanning story.
    """

    def __init__(self, graph, start: str, goal: str,
                 heuristic: Callable = euclidean_heuristic) -> None:
        self.graph = graph
        self.start = start
        self.goal = goal
        self.h = heuristic
        self.g: Dict[str, float] = {}
        self.rhs: Dict[str, float] = {}
        self.U: List[Tuple[float, float, int, str]] = []
        self.km = 0.0
        self.counter = itertools.count()
        self.rhs[self.goal] = 0.0
        self._insert(goal)
        self.s_expanded = 0
        self.s_generated = 0
        self.plans = 0

    # -- helpers ------------------------------------------------------------ #
    def _heuristic(self, u: str, v: str) -> float:
        return self.h(self.graph, u, v)

    def _key(self, s: str) -> Tuple[float, float]:
        k1 = min(self.g.get(s, INF), self.rhs.get(s, INF)) \
             + self._heuristic(self.start, s) + self.km
        k2 = min(self.g.get(s, INF), self.rhs.get(s, INF))
        return k1, k2

    def _insert(self, s: str) -> None:
        heapq.heappush(self.U, (*self._key(s), next(self.counter), s))

    def _update(self, s: str) -> None:
        if s != self.goal:
            r = min((self.graph.visible_cost(s, sp) + self.g.get(sp, INF)
                     for sp in self.graph.neighbors(s)), default=INF)
            self.rhs[s] = r
        if s in {x[3] for x in self.U}:
            self.U = [x for x in self.U if x[3] != s]
            heapq.heapify(self.U)
        if self.g.get(s, INF) != self.rhs.get(s, INF):
            self._insert(s)

    def _pop(self) -> Tuple[Optional[str], Optional[Tuple[float, float]]]:
        while self.U:
            k1, k2, _, s = heapq.heappop(self.U)
            if self.g.get(s, INF) == self.rhs.get(s, INF):
                continue
            k_old = (k1, k2)
            if k_old >= self._key(s):
                return s, k_old
            self._insert(s)
        return None, None

    # -- main loop ----------------------------------------------------------- #
    def compute_shortest_path(self, budget: int = 200_000) -> None:
        while self.U:
            s, k_old = self._pop()
            if s is None:
                break
            self.s_expanded += 1
            if self.g.get(s, INF) > self.rhs.get(s, INF):
                self.g[s] = self.rhs[s]
                for pred in self.graph.neighbors(s):
                    self.s_generated += 1
                    self._update(pred)
            else:
                self.g[s] = INF
                for pred in self.graph.neighbors(s):
                    self.s_generated += 1
                    self._update(pred)
                self._update(s)
            if self.s_expanded >= budget:
                break

    def replan(self) -> bool:
        """Recompute the shortest path after cost changes. Returns True if a
        path from start to goal exists."""
        self.km += self._heuristic(self.start, self.goal)
        self.compute_shortest_path()
        self.plans += 1
        return self.rhs.get(self.start, INF) != INF

    def next_node(self) -> Optional[str]:
        """Best next node from current start toward the goal."""
        best, best_c = None, INF
        for v in self.graph.neighbors(self.start):
            c = self.graph.visible_cost(self.start, v) + self.g.get(v, INF)
            if c < best_c:
                best, best_c = v, c
        if best_c == INF:
            return None
        return best

    def extract_path(self, max_len: int = 10_000) -> List[str]:
        """Follow best-neighbor pointers from start to goal (guards against
        cycles)."""
        path = [self.start]
        cur = self.start
        seen = 0
        while cur != self.goal and seen < max_len:
            best, best_c = None, INF
            for v in self.graph.neighbors(cur):
                c = self.graph.visible_cost(cur, v) + self.g.get(v, INF)
                if c < best_c:
                    best, best_c = v, c
            if best is None or best == cur:
                break
            path.append(best)
            cur = best
            seen += 1
        return path

    # -- blockage awareness --------------------------------------------------- #
    def edge_cost_changed(self, u: str, v: str) -> None:
        """Signal that the visible cost of edge (u, v) changed."""
        self._update(u)
        self._update(v)


# --------------------------------------------------------------------------- #
# Algorithm arena                                                             #
# --------------------------------------------------------------------------- #

def algorithm_arena(graph, start: str, goal: str,
                    algorithms: Sequence[str] = ("astar", "dijkstra",
                                                 "gbfs", "bfs"),
                    heuristic: Callable = euclidean_heuristic) -> Dict[str, SearchResult]:
    """Run several algorithms on the same query and collect results for the
    explainability panel's comparison table."""
    out: Dict[str, SearchResult] = {}
    if "astar" in algorithms:
        r = astar(graph, start, goal, heuristic=heuristic)
        r.h_consistent = heuristic_consistent(graph, heuristic)
        r.h_admissible = heuristic_admissible(graph, heuristic)
        out["astar"] = r
    if "dijkstra" in algorithms:
        out["dijkstra"] = dijkstra(graph, start, goal)
    if "gbfs" in algorithms:
        out["gbfs"] = greedy_best_first(graph, start, goal, heuristic=heuristic)
    if "bfs" in algorithms:
        out["bfs"] = breadth_first(graph, start, goal)
    return out
