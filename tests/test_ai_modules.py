"""Tests for CNP dispatch, CSP hospital allocation, and the MDP."""

import random

import pytest

from core.dispatch import CnpAuctioneer
from core.graph import build_grid_network
from core.hospital_allocation import HospitalAllocator, AllocationResult
from core.mdp import IdlePositioningMDP


# --------------------------------------------------------------------------- #
# Shared fakes                                                               #
# --------------------------------------------------------------------------- #

class FakeAmbulance:
    def __init__(self, aid, node, status="idle", speed=45.0, done=0):
        self.id = aid
        self.node = node
        self.status = status
        self.speed_kmh = speed
        self.responses_done = done


class FakeHospital:
    def __init__(self, hid, node, beds):
        self.id = hid
        self.node = node
        self._beds = beds
        self._used = 0

    def free_beds(self):
        return self._beds - self._used


class FakeIncident:
    def __init__(self, iid, node):
        self.id = iid
        self.node = node


@pytest.fixture
def net():
    return build_grid_network(cols=6, rows=5, cell_km=0.5, speed_kmh=40.0,
                              rng=random.Random(21))


# --------------------------------------------------------------------------- #
# Contract Net Protocol                                                      #
# --------------------------------------------------------------------------- #

class TestCnpAuction:
    def test_winner_is_fastest_unit(self, net):
        auctioneer = CnpAuctioneer()
        units = [
            FakeAmbulance("AMB-01", "n0_0"),
            FakeAmbulance("AMB-02", "n4_5"),   # much further away
            FakeAmbulance("AMB-03", "n2_2"),
        ]
        rec = auctioneer.run_auction("INC-1", 3, "n3_3", units, net)
        assert rec.winner == "AMB-01" or rec.winner == "AMB-03"
        # ETA of winner must be the minimum
        winner_eta = next(b.eta_seconds for b in rec.bids
                          if b.ambulance_id == rec.winner)
        assert winner_eta == min(b.eta_seconds for b in rec.bids)

    def test_busy_units_are_excluded(self, net):
        auctioneer = CnpAuctioneer()
        units = [
            FakeAmbulance("AMB-01", "n2_2", status="idle"),
            FakeAmbulance("AMB-02", "n2_3", status="on_scene"),  # busy
        ]
        rec = auctioneer.run_auction("INC-1", 3, "n3_3", units, net)
        assert rec.winner == "AMB-01"
        assert any("busy" in ex["reason"] for ex in rec.excluded)

    def test_all_busy_yields_no_winner(self, net):
        auctioneer = CnpAuctioneer()
        units = [FakeAmbulance("AMB-01", "n2_2", status="on_scene"),
                 FakeAmbulance("AMB-02", "n2_3", status="enroute")]
        rec = auctioneer.run_auction("INC-1", 3, "n3_3", units, net)
        assert rec.winner is None
        assert rec.phases[-1] == "no_bids"

    def test_workload_fairness_breaks_ties(self, net):
        """Two units equidistant: the one with fewer responses wins."""
        auctioneer = CnpAuctioneer()
        units = [
            FakeAmbulance("AMB-01", "n2_2", done=7),
            FakeAmbulance("AMB-02", "n2_2", done=0),
        ]
        rec = auctioneer.run_auction("INC-1", 3, "n2_4", units, net)
        assert rec.winner == "AMB-02"

    def test_auction_record_is_explainable(self, net):
        auctioneer = CnpAuctioneer()
        units = [FakeAmbulance("AMB-01", "n0_0"),
                 FakeAmbulance("AMB-02", "n4_5")]
        rec = auctioneer.run_auction("INC-1", 4, "n3_3", units, net)
        assert rec.phases[0] == "announce"
        assert all(b.rationale for b in rec.bids)
        import json
        json.dumps(rec.to_dict())


# --------------------------------------------------------------------------- #
# CSP hospital allocation                                                    #
# --------------------------------------------------------------------------- #

class TestHospitalAllocator:
    def make_hospitals(self, net, beds):
        nodes = net.nodes[:3]
        return [FakeHospital(f"H{i+1}", nodes[i], beds) for i in range(3)]

    def test_single_patient_allocated(self, net):
        h = self.make_hospitals(net, 5)
        alloc = HospitalAllocator()
        res = alloc.solve([FakeIncident("I1", "n3_3")], h, net)
        assert res.feasible
        assert res.assignments["I1"] in {"H1", "H2", "H3"}

    def test_capacity_respected(self, net):
        """One free bed in the whole city, two patients: infeasible, and
        the partial assignment may use that bed at most once."""
        h = self.make_hospitals(net, 0)
        h[0] = FakeHospital("H1", net.nodes[0], beds=1)
        alloc = HospitalAllocator()
        res = alloc.solve([FakeIncident("I1", "n1_1"),
                           FakeIncident("I2", "n1_2")], h, net)
        assert not res.feasible
        beds_used = sum(1 for hid in res.assignments.values()
                        if hid == "H1")
        assert beds_used <= 1

    def test_overload_flagged_infeasible_with_partial(self, net):
        """3 beds total, 4 patients: solver must backtrack and report the
        infeasibility with a partial assignment."""
        h = self.make_hospitals(net, 1)
        alloc = HospitalAllocator()
        res = alloc.solve([FakeIncident(f"I{i}", n)
                           for i, n in enumerate(["n1_1", "n1_2", "n2_1",
                                                  "n2_2"])], h, net)
        assert not res.feasible
        assert len(res.assignments) <= 3
        assert res.backtracks > 0
        assert res.nodes_explored > 0

    def test_mrv_finds_solution_without_backtrack_when_possible(self, net):
        h = self.make_hospitals(net, 3)
        alloc = HospitalAllocator()
        res = alloc.solve([FakeIncident(f"I{i}", n)
                           for i, n in enumerate(["n1_1", "n1_2", "n2_1"])],
                          h, net)
        assert res.feasible
        assert len(res.assignments) == 3

    def test_trace_recorded(self, net):
        h = self.make_hospitals(net, 1)
        alloc = HospitalAllocator()
        res = alloc.solve([FakeIncident(f"I{i}", n)
                           for i, n in enumerate(["n1_1", "n1_2", "n2_1",
                                                  "n2_2"])], h, net)
        assert any(t["step"] == "assign" for t in res.trace)
        assert isinstance(res.to_dict()["assignments"], dict)


# --------------------------------------------------------------------------- #
# MDP â€” exact value iteration                                                #
# --------------------------------------------------------------------------- #

class TestIdlePositioningMDP:
    @staticmethod
    def _travel_fn(zones):
        pos = {z: (x, y) for z, x, y in zones}

        def travel(a, b):
            ax, ay = pos[a]
            bx, by = pos[b]
            return 10.0 * (abs(ax - bx) + abs(ay - by))

        return travel

    def test_value_iteration_converges(self):
        zones = [("Z1", 0.0, 0.0), ("Z2", 10.0, 0.0), ("Z3", 0.0, 10.0),
                 ("Z4", 10.0, 10.0)]
        prior = {"Z1": 0.6, "Z2": 0.2, "Z3": 0.1, "Z4": 0.1}
        mdp = IdlePositioningMDP(zones, prior, self._travel_fn(zones),
                                 gamma=0.9)
        res = mdp.solve()
        assert res.converged
        assert res.iterations > 1
        assert res.final_residual < 1e-6
        assert len(res.values) == 4
        assert len(res.policy) == 4

    def test_policy_prefers_high_prior_zone(self):
        zones = [("Z1", 0.0, 0.0), ("Z2", 10.0, 0.0), ("Z3", 0.0, 10.0),
                 ("Z4", 10.0, 10.0)]
        prior = {"Z1": 0.9, "Z2": 0.03, "Z3": 0.04, "Z4": 0.03}
        mdp = IdlePositioningMDP(zones, prior, self._travel_fn(zones),
                                 gamma=0.9, lambda_cost=0.002)
        res = mdp.solve()
        # a unit in Z2 with a tiny repositioning cost should move to Z1
        assert res.policy["Z2"] == "Z1"

    def test_exact_dp_matches_brute_force_greedy_bound(self):
        """The optimal action's one-step value must be >= any alternative's
        (that is exactly what argmax enforces) — verified exhaustively."""
        zones = [("Z1", 0.0, 0.0), ("Z2", 10.0, 0.0), ("Z3", 0.0, 10.0)]
        prior = {z: 1 / 3 for z, _, _ in zones}
        mdp = IdlePositioningMDP(zones, prior, self._travel_fn(zones),
                                 gamma=0.9)
        res = mdp.solve()
        for s in zones:
            s_id = s[0]
            chosen = res.policy[s_id]
            chosen_value = mdp.reward(s_id, chosen) \
                + 0.9 * res.values[chosen]
            for a in zones:
                a_id = a[0]
                alt = mdp.reward(s_id, a_id) + 0.9 * res.values[a_id]
                assert chosen_value >= alt - 1e-9

    def test_sweep_log_explainable(self):
        zones = [("Z1", 0.0, 0.0), ("Z2", 10.0, 0.0)]
        prior = {"Z1": 0.8, "Z2": 0.2}
        mdp = IdlePositioningMDP(zones, prior, lambda a, b: 10.0, gamma=0.5)
        res = mdp.solve()
        assert res.sweep_log
        assert res.to_dict()["iterations"] == res.iterations
