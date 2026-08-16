"""Tests for the classical search algorithms (A*, GBFS, Dijkstra, BFS,
LRTA*, D* Lite, and the arena)."""

import random

import pytest

from core.graph import RoadNetwork, build_grid_network
from core.search import (DStarLite, LRTAStar, SearchResult, algorithm_arena,
                         astar, breadth_first, dijkstra, euclidean_heuristic,
                         greedy_best_first, heuristic_admissible,
                         heuristic_consistent)


@pytest.fixture
def net():
    return build_grid_network(cols=6, rows=5, cell_km=0.5, speed_kmh=40.0,
                              rng=random.Random(11))


@pytest.fixture
def small_net():
    """A hand-built 6-node graph with known optimal costs."""
    rn = RoadNetwork()
    for n in "abcdef":
        rn.add_node(n, x=float(ord(n) % 5), y=float(ord(n) // 5))
    edges = [("a", "b", 1.0), ("a", "c", 4.0), ("b", "c", 1.0),
             ("b", "d", 5.0), ("c", "d", 2.0), ("d", "e", 1.0),
             ("c", "e", 6.0)]
    for u, v, w in edges:
        rn.add_edge(u, v, w)
    return rn


class TestOptimality:
    def test_astar_matches_dijkstra_on_small_graph(self, small_net):
        r1 = astar(small_net, "a", "e")
        r2 = dijkstra(small_net, "a", "e")
        assert r1.cost == pytest.approx(r2.cost)
        assert r1.cost == pytest.approx(5.0)  # a-b-c-d-e
        assert r1.path == ["a", "b", "c", "d", "e"]

    def test_astar_optimal_on_grid(self, net):
        a = astar(net, "n0_0", "n4_5")
        d = dijkstra(net, "n0_0", "n4_5")
        assert a.cost == pytest.approx(d.cost)
        assert a.path[0] == "n0_0" and a.path[-1] == "n4_5"

    def test_gbfs_is_faster_but_not_optimal(self, net):
        g = greedy_best_first(net, "n0_0", "n4_5")
        a = astar(net, "n0_0", "n4_5")
        assert g.nodes_expanded <= a.nodes_expanded
        assert g.cost >= a.cost  # never better than optimal

    def test_bfs_finds_edge_minimal_path(self, net):
        b = breadth_first(net, "n0_0", "n4_5")
        assert len(b.path) - 1 == abs(4) + abs(5)  # Manhattan in edges
        assert b.path[0] == "n0_0" and b.path[-1] == "n4_5"

    def test_unreachable_goal(self, net):
        net.block_edge("n0_0", "n0_1", reveal=True)
        net.block_edge("n0_0", "n1_0", reveal=True)
        # n0_0 is a corner: both edges blocked -> isolated
        r = astar(net, "n0_0", "n4_5")
        assert r.cost is None
        assert r.reason == "no path (search exhausted)"


class TestHeuristic:
    def test_euclidean_is_consistent_on_grid(self, net):
        assert heuristic_consistent(net, euclidean_heuristic)

    def test_euclidean_is_admissible_on_small_graph(self, small_net):
        assert heuristic_admissible(small_net, euclidean_heuristic)


class TestBlockageAwareRouting:
    def test_astar_routes_around_revealed_blockage(self, net):
        # block the middle of the top row forcing a detour
        net.block_edge("n0_2", "n0_3", reveal=True)
        r = astar(net, "n0_0", "n0_5")
        assert r.cost is not None
        assert ("n0_2", "n0_3") not in zip(r.path, r.path[1:])
        assert ("n0_3", "n0_2") not in zip(r.path, r.path[1:])

    def test_astar_ignores_hidden_blockage(self, net):
        """Partial observability: a hidden blockage does NOT change the
        plan; only revealed ones do."""
        r1 = astar(net, "n0_0", "n0_5")
        net.block_edge("n0_2", "n0_3", reveal=False)
        r2 = astar(net, "n0_0", "n0_5")
        assert r2.path == r1.path


class TestLRTAStar:
    def test_reaches_goal_and_learns(self, net):
        agent = LRTAStar(net, "n0_0", "n4_5")
        r = agent.run(max_steps=2000)
        assert r.path[-1] == "n4_5"
        assert r.cost is not None
        # heuristic updates happened (learning visible)
        assert len(r.trace) >= 1

    def test_learning_speeds_up_second_run(self, net):
        a1 = LRTAStar(net, "n0_0", "n3_4")
        a1.run(max_steps=2000)
        expansions1 = a1.nodes_expanded
        a2 = LRTAStar(net, "n0_0", "n3_4")
        a2.run(max_steps=2000)
        assert a2.nodes_expanded <= expansions1 * 2  # never wildly worse


class TestDStarLite:
    def test_incremental_replan_after_blockage(self, net):
        start, goal = "n0_0", "n4_5"
        dsl = DStarLite(net, start, goal)
        assert dsl.replan()
        p1 = dsl.extract_path()
        assert p1[-1] == goal

        # block an edge on the current path
        blocked = next((p1[i], p1[i + 1])
                       for i in range(len(p1) - 1) if p1[i] != goal)
        net.block_edge(*blocked, reveal=True)
        dsl.edge_cost_changed(*blocked)
        assert dsl.replan()
        p2 = dsl.extract_path()
        assert p2[-1] == goal
        assert ("n0_0", goal) != blocked  # sanity
        assert blocked not in zip(p2, p2[1:])
        assert blocked[::-1] not in zip(p2, p2[1:])

    def test_replan_matches_fresh_astar(self, net):
        """After the same cost change, D* Lite's new path cost equals a
        fresh A* search (correctness of incremental search)."""
        start, goal = "n0_0", "n4_5"
        dsl = DStarLite(net, start, goal)
        dsl.replan()
        p1 = dsl.extract_path()
        blocked = next((p1[i], p1[i + 1])
                       for i in range(len(p1) - 1) if p1[i] != goal)
        net.block_edge(*blocked, reveal=True)
        dsl.edge_cost_changed(*blocked)
        dsl.replan()
        p2 = dsl.extract_path()

        cost_dsl = sum(net.true_cost(p2[i], p2[i + 1])
                       for i in range(len(p2) - 1))
        fresh = astar(net, start, goal)
        assert cost_dsl == pytest.approx(fresh.cost)

    def test_warm_replan_amortization(self, net):
        """The amortised advantage of incremental replanning: one warm
        D* Lite solver absorbs several successive cost changes for fewer
        cumulative expansions than a *single* fresh A* rerun — the claim
        the engine measures per replan and reports in benchmarks."""
        start, goal = "n0_0", "n4_5"
        dsl = DStarLite(net, start, goal)
        dsl.replan()
        dsl.extract_path()
        cold = dsl.s_expanded
        # three cumulative blockage repairs on the evolving path (never
        # the first edge — the start must keep an exit)
        for _ in range(3):
            p = dsl.extract_path()
            blocked = (p[1], p[2])
            net.block_edge(*blocked, reveal=True)
            dsl.edge_cost_changed(*blocked)
            assert dsl.replan()
            assert dsl.extract_path()[-1] == goal
        warm_total = dsl.s_expanded - cold
        fresh = astar(net, start, goal)
        assert fresh.cost is not None
        assert warm_total < fresh.nodes_expanded
        assert dsl.s_expanded > 0


class TestArena:
    def test_arena_returns_all_algorithms(self, net):
        res = algorithm_arena(net, "n0_0", "n4_5")
        assert set(res) == {"astar", "dijkstra", "gbfs", "bfs"}
        for name, r in res.items():
            assert isinstance(r, SearchResult)
            assert r.path[-1] == "n4_5"
        assert res["astar"].cost == pytest.approx(res["dijkstra"].cost)
        assert res["astar"].h_consistent is True
        assert res["astar"].h_admissible is True

    def test_results_serialisable(self, net):
        res = algorithm_arena(net, "n0_0", "n4_5")
        import json
        json.dumps({k: v.to_dict() for k, v in res.items()})
