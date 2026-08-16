"""Tests for the road-network and blockage (partial observability) layer."""

import random

import pytest

from core.graph import (RoadNetwork, ZoneMap, build_grid_network,
                        build_radial_network, haversine_km)


@pytest.fixture
def net():
    return build_grid_network(cols=5, rows=4, cell_km=0.5, speed_kmh=40.0,
                              rng=random.Random(3))


class TestRoadNetwork:
    def test_connectivity(self, net):
        assert net.node_count == 20
        assert net.edge_count >= 30
        for node in net.nodes:
            assert net.neighbors(node), f"isolated node {node}"

    def test_haversine(self):
        # ~111 km per degree of latitude
        d = haversine_km(0.0, 0.0, 1.0, 0.0)
        assert 110.0 < d < 112.0
        assert haversine_km(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0)

    def test_radial_network_builds(self):
        rn = build_radial_network(rings=3, spokes=6, rng=random.Random(4))
        assert rn.node_count == 1 + 3 * 6
        assert all(rn.neighbors(n) for n in rn.nodes)


class TestBlockageVisibility:
    """The core partial-observability contract: planners must NOT see
    hidden blockages, and MUST see them once revealed."""

    def test_hidden_blockage_invisible_to_planner(self, net):
        u, v = "n0_0", "n0_1"
        cost = net.visible_cost(u, v)
        net.block_edge(u, v, reveal=False)
        # hidden: planner still sees the nominal cost
        assert net.visible_cost(u, v) == cost
        assert net.is_blocked(u, v)
        assert not net.is_revealed_blocked(u, v)

    def test_reveal_changes_visible_cost_to_inf(self, net):
        net.block_edge("n0_0", "n0_1", reveal=False)
        assert net.reveal_blockage("n0_0", "n0_1")
        assert net.visible_cost("n0_0", "n0_1") == float("inf")
        # second reveal is a no-op
        assert not net.reveal_blockage("n0_1", "n0_0")

    def test_blockage_expiry(self, net):
        net.block_edge("n0_0", "n0_1", duration_ticks=3, reveal=True)
        assert not net.tick_blockages()
        assert not net.tick_blockages()
        expired = net.tick_blockages()
        assert ("n0_0", "n0_1") in expired
        assert not net.is_blocked("n0_0", "n0_1")

    def test_undirected_keys(self, net):
        net.block_edge("n0_0", "n0_1", reveal=True)
        assert net.is_revealed_blocked("n0_1", "n0_0")


class TestZoneMap:
    def test_zones_cover_all_nodes(self, net):
        zm = ZoneMap.build(net, 4, rng=random.Random(5))
        assert zm.zone_count() == 4
        for n in net.nodes:
            assert zm.zone_of_node(n) in {z.id for z in zm.zones}

    def test_zone_center_node_is_reachable(self, net):
        zm = ZoneMap.build(net, 3, rng=random.Random(6))
        for z in zm.zones:
            node = zm.zone_center_node(net, z.id)
            assert node in net.nodes
