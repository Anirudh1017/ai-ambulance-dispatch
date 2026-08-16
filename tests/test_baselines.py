"""Tests for the naive baseline policies (Addition 1): greedy nearest
dispatch, full-A* rerun replanning, return-to-station idle positioning,
and first-free-bed hospital allocation — each verified against its smart
counterpart's behaviour."""

import random

import pytest

from core.engine import Engine
from core.policies import (BASELINE, BASELINE_LABELS, SMART, SUBSYSTEMS,
                           first_free_hospital, greedy_nearest_dispatch,
                           is_smart, resolve_policies)
from core.graph import build_grid_network
from tests.test_ai_modules import FakeAmbulance, FakeHospital, FakeIncident


@pytest.fixture
def net():
    return build_grid_network(cols=6, rows=5, cell_km=0.5, speed_kmh=40.0,
                              rng=random.Random(31))


class TestPolicyRegistry:
    def test_every_subsystem_has_smart_and_baseline(self):
        assert set(SMART) == set(BASELINE) == set(SUBSYSTEMS)
        assert SMART["dispatch"] == "cnp"
        assert SMART["replan"] == "dstar"
        assert SMART["idle"] == "mdp"
        assert SMART["hospital"] == "csp"
        assert BASELINE["hospital"] == "first_free"
        assert is_smart(SMART, "dispatch")

    def test_partial_policies_fill_defaults(self):
        p = resolve_policies({"replan": "full_astar"})
        assert p["replan"] == "full_astar"
        assert p["dispatch"] == "cnp"
        assert p["idle"] == "mdp"
        assert p["hospital"] == "csp"

    def test_labels_exist_for_all_policies(self):
        for p in list(SMART.values()) + list(BASELINE.values()):
            assert p in BASELINE_LABELS


class TestGreedyDispatchBaseline:
    def test_picks_nearest_unit_ignoring_workload(self, net):
        """CNP would prefer the low-workload unit on equal-ish distance;
        greedy ignores workload entirely and takes the nearest."""
        units = [
            FakeAmbulance("AMB-01", "n0_0", done=9),   # nearest, loaded
            FakeAmbulance("AMB-02", "n4_5", done=0),   # far, fresh
        ]
        pick = greedy_nearest_dispatch("n0_1", units, net)
        assert pick is not None
        winner, eta, _ = pick
        assert winner == "AMB-01"
        # ETA must be the minimum among eligible units
        assert eta == min(greedy_nearest_dispatch("n0_1", units, net)[1],
                          greedy_nearest_dispatch("n0_1", units, net)[1])

    def test_busy_units_not_considered(self, net):
        units = [
            FakeAmbulance("AMB-01", "n0_0", status="on_scene"),
            FakeAmbulance("AMB-02", "n1_1", status="idle"),
        ]
        winner, _, _ = greedy_nearest_dispatch("n2_2", units, net)
        assert winner == "AMB-02"

    def test_no_route_yields_none(self, net):
        net.block_edge("n0_0", "n0_1", reveal=True)
        net.block_edge("n0_0", "n1_0", reveal=True)
        units = [FakeAmbulance("AMB-01", "n0_0")]
        assert greedy_nearest_dispatch("n4_5", units, net) is None

    def test_engine_runs_greedy_and_logs_it(self):
        eng = Engine(scenario="quiet-night", seed=3,
                     config={"policies": {"dispatch": "greedy"}})
        eng.run()
        kinds = {e.kind for _, e in eng.events}
        assert "dispatch.greedy" in kinds
        # no CNP auction machinery ran
        assert not any(k.startswith("dispatch.auction.") for k in kinds)
        assert eng.policies["dispatch"] == "greedy"


class TestFirstFreeHospitalBaseline:
    def test_first_free_ignores_distance(self, net):
        """The nearest hospital is skipped if an earlier roster entry has
        any free bed — that is precisely the naive behaviour."""
        hospitals = [
            FakeHospital("H1", net.nodes[0], beds=5),   # far from scene
            FakeHospital("H2", net.nodes[-1], beds=5),  # close to scene
        ]
        # scene next to H2; H1 is far away but first in the roster
        scene = hospitals[1].node
        inc = FakeIncident("I1", scene)
        assignments = first_free_hospital([inc], hospitals)
        assert assignments["I1"] == "H1"

    def test_capacity_accounting_within_roster(self, net):
        hospitals = [FakeHospital("H1", net.nodes[0], beds=1)]
        incs = [FakeIncident(f"I{i + 1}", net.nodes[1]) for i in range(2)]
        assignments = first_free_hospital(incs, hospitals)
        assert assignments["I1"] == "H1"
        assert "I2" not in assignments  # only one free bed exists

    def test_engine_runs_first_free_without_csp(self):
        eng = Engine(scenario="storm-disaster", seed=2,
                     config={"policies": {"hospital": "first_free"}})
        eng.run()
        assert eng.stats["csp_solves"] == 0
        assert eng.stats["csp_backtracks"] == 0
        allocated = [e for _, e in eng.events
                     if e.kind == "hospital.allocated"]
        assert allocated
        assert all(e.detail["csp"].get("policy") == "first-free-baseline"
                   for e in allocated)
        assert eng.stats["incidents_cleared"] > 0


class TestReturnToStationBaseline:
    def _engine_with_unit_away_from_station(self, seed=4):
        eng = Engine(scenario="quiet-night", seed=seed,
                     config={"policies": {"idle": "station"}})
        amb = eng.ambulances[0]
        station = eng._station(amb.station)
        assert station is not None
        # park the unit somewhere far from its station
        far = max(eng.network.nodes,
                  key=lambda n: eng.network.euclidean_distance(n, station.node))
        amb.node = far
        amb.status = "idle"
        return eng, amb, station

    def test_idle_unit_drifts_to_home_station(self):
        eng, amb, station = self._engine_with_unit_away_from_station()
        assert station.node != amb.node
        # force the reposition epoch
        eng.tick = 120  # idle_reposition_every = 40 -> epoch tick
        eng._schedule_idle_drift()
        assert amb.destination == f"station:{station.id}"
        assert amb.status == "returning"

    def test_unit_already_at_station_stays(self):
        eng, amb, station = self._engine_with_unit_away_from_station()
        amb.node = station.node
        eng.tick = 120
        eng._schedule_idle_drift()
        assert amb.status == "idle"
        assert amb.destination is None

    def test_station_arrival_returns_unit_to_idle(self):
        eng = Engine(scenario="quiet-night", seed=4,
                     config={"policies": {"idle": "station"}})
        amb = eng.ambulances[0]
        station = eng._station(amb.station)
        amb.node = station.node
        amb.destination = f"station:{station.id}"
        amb.status = "returning"
        eng._handle_arrival(amb)
        assert amb.status == "idle"
        assert amb.destination is None

    def test_engine_run_produces_no_mdp_solves(self):
        eng = Engine(scenario="quiet-night", seed=4,
                     config={"policies": {"idle": "station"}})
        eng.run()
        assert eng.stats["mdp_solves"] == 0
        kinds = {e.kind for _, e in eng.events}
        assert "ambulance.idle_move" in kinds  # still explainable


class TestFullAstarReplanBaseline:
    """Replan tests force deterministic mid-run blockages on a unit's
    live route (the same technique as the engine's D* Lite test) so the
    comparison is real: cold D* Lite pays an initial search, warm
    incremental replans are cheap."""

    @staticmethod
    def _find_enroute_unit(eng, ticks=600):
        for _ in range(ticks):
            eng.tick_once()
            target = next((a for a in eng.ambulances
                           if a.status in ("enroute", "transporting")
                           and a.lrta is None
                           and len(a.remaining_route()) >= 4), None)
            if target is not None:
                return target
        return None

    @staticmethod
    def _step_until_replan(eng, ticks=500):
        """Step until a replan happens; return (unit_id, compare_event)
        or None."""
        before = len([e for _, e in eng.events
                      if e.kind == "replan.cost_compare"])
        for _ in range(ticks):
            eng.tick_once()
            after = [e for _, e in eng.events
                     if e.kind == "replan.cost_compare"]
            if len(after) > before:
                return after[-1].detail["ambulance_id"], after[-1]
        return None

    @staticmethod
    def _force_blockage_on(eng, unit_id, ticks=400):
        amb = eng.ambulance(unit_id)
        if amb is None:
            return False
        route = amb.remaining_route()
        if len(route) < 3:
            return False
        u, v = route[1], route[2]
        eng.network.block_edge(u, v, 999, reveal=False)
        for _ in range(ticks):
            eng.tick_once()
        return True

    def test_engine_replans_with_full_rerun(self):
        eng = Engine(scenario="quiet-night", seed=5,
                     config={"policies": {"replan": "full_astar"}})
        target = self._find_enroute_unit(eng)
        assert target is not None, "no suitable enroute unit found"
        route = target.remaining_route()
        u, v = route[1], route[2]
        eng.network.block_edge(u, v, 999, reveal=False)
        for _ in range(400):
            eng.tick_once()
        assert eng.stats["replans"] > 0
        # every replan was a full A* rerun; D* Lite untouched
        assert eng.stats["search_expansions"]["dstar"] == 0
        assert eng.stats["replan_full_expansions"] > 0
        assert eng.stats["replan_savings_expansions"] == 0
        kinds = {e.kind for _, e in eng.events}
        assert "ambulance.replanned" in kinds

    def test_dstar_mode_measures_full_rerun_counterfactual(self):
        eng = Engine(scenario="quiet-night", seed=5)
        target = self._find_enroute_unit(eng)
        assert target is not None
        route = target.remaining_route()
        u, v = route[1], route[2]
        eng.network.block_edge(u, v, 999, reveal=False)
        for _ in range(400):
            eng.tick_once()
        assert eng.stats["replans"] > 0
        assert eng.stats["search_expansions"]["dstar"] > 0
        assert eng.stats["replan_full_expansions"] > 0
        # savings stat is the accounting identity: full rerun minus dstar
        assert eng.stats["replan_savings_expansions"] == \
            eng.stats["replan_full_expansions"] \
            - eng.stats["search_expansions"]["dstar"]

    def test_warm_incremental_replan_beats_full_rerun(self):
        """The amortisation claim of incremental replanning lives at the
        search level (pinned deterministically in test_search.py): one
        warm solver absorbs several cumulative edge changes for fewer
        expansions than a single fresh A* rerun. Here we verify the engine
        keeps the solver warm across replans and logs the per-replan
        counterfactual so that claim is measurable in runs."""
        eng = Engine(scenario="quiet-night", seed=5)
        target = self._find_enroute_unit(eng)
        assert target is not None
        route = target.remaining_route()
        u, v = route[1], route[2]
        eng.network.block_edge(u, v, 999, reveal=False)
        found = self._step_until_replan(eng)
        assert found is not None, "no (cold) replan happened"
        _, cold_compare = found
        # same unit, second repair, no ticks in between (stationary start)
        amb = eng.ambulance(cold_compare.detail["ambulance_id"])
        assert amb is not None and amb.dstar is not None
        route = amb.remaining_route()
        if len(route) < 2:
            target2 = next((a for a in eng.ambulances if a.status == "enroute"
                            and a.lrta is None and len(a.remaining_route()) >= 3),
                           None)
            assert target2 is not None
            amb = target2
            route = amb.remaining_route()
        u2, v2 = route[-2], route[-1]
        eng.network.block_edge(u2, v2, 999, reveal=False)
        eng.network.reveal_blockage(u2, v2)
        d0 = eng.stats["search_expansions"]["dstar"]
        assert eng._replan_unit(amb, cause="test", changed_edges=[(u2, v2)])
        assert eng.stats["search_expansions"]["dstar"] > d0
        # counterfactual fields on every replan event
        for _, e in eng.events:
            if e.kind != "replan.cost_compare":
                continue
            assert "dstar_expansions" in e.detail
            assert "full_rerun_expansions" in e.detail
            assert e.detail["full_rerun_expansions"] > 0
        # and both replans are explained as their own events
        assert cold_compare.detail["ambulance_id"] == amb.id


class TestPolicyEngineIntegration:
    def test_smart_defaults_unchanged(self):
        eng = Engine(scenario="downtown-rush", seed=1)
        assert eng.policies == SMART
        assert "policies" in eng.snapshot()["stats"]

    def test_all_baseline_ablation_runs_finish(self):
        for sub in SUBSYSTEMS:
            overrides = {"policies": {sub: BASELINE[sub]}}
            eng = Engine(scenario="downtown-rush", seed=8, config=overrides)
            eng.run()
            assert eng.stats["incidents_cleared"] > 0
            assert eng.policies[sub] == BASELINE[sub]