"""End-to-end engine tests: the full tick loop, snapshot/events interface
(shared by both UIs), scenario runs, and invariant checks."""

import json

import pytest

from core.engine import Engine
from core.scenarios import DEFAULT_CONFIG, SCENARIOS, resolve_config


class TestConfig:
    def test_resolve_config_merges_scenario(self):
        cfg = resolve_config("downtown-rush")
        assert cfg["name"] == "downtown-rush"
        assert cfg["ambulance_count"] == 16
        assert cfg["station_count"] == 4
        assert cfg["incidents"]  # scenario supplies incidents

    def test_resolve_config_custom_seed(self):
        cfg = resolve_config("downtown-rush", seed=7)
        assert cfg["seed"] == 7

    def test_default_config_complete(self):
        for key in ("seconds_per_tick", "ambulance_count", "search",
                    "dispatch", "csp", "mdp", "max_ticks"):
            assert key in DEFAULT_CONFIG

    def test_scenarios_exist(self):
        assert {"downtown-rush", "storm-disaster", "quiet-night",
                "gridlock"} <= set(SCENARIOS)


class TestEngineInterface:
    """Both UIs consume snapshot()/events_since(); these tests pin the
    contract."""

    def test_snapshot_serialisable(self):
        eng = Engine(scenario="quiet-night", seed=1)
        for _ in range(30):
            eng.tick_once()
        s = eng.snapshot()
        json.dumps(s)
        assert s["tick"] == 30
        assert s["map"]["nodes"] and s["map"]["edges"]
        assert s["map"]["zones"] and s["map"]["hospitals"]
        assert s["map"]["stations"]  # garage nodes for the fleet
        assert isinstance(s["ambulances"], list)
        assert all(a["station"] for a in s["ambulances"])
        assert "stats" in s and "recent_decisions" in s

    def test_events_since_cursor(self):
        eng = Engine(scenario="quiet-night", seed=1)
        evts, cursor = eng.events_since(0)
        assert cursor > 0
        for _ in range(90):
            eng.tick_once()
        evts2, cursor2 = eng.events_since(cursor)
        assert cursor2 > cursor
        assert len(evts2) > 0
        assert all(e["tick"] >= 1 for e in evts2)

    def test_snapshot_history_enables_replay(self):
        eng = Engine(scenario="quiet-night", seed=1)
        for _ in range(25):
            eng.tick_once()
            eng.snapshot()
        ticks = eng.replay_ticks()
        assert len(ticks) == 25
        s5 = eng.snapshot_at(5)
        assert s5["tick"] == 5

    def test_determinism_same_seed(self):
        a = Engine(scenario="gridlock", seed=9)
        b = Engine(scenario="gridlock", seed=9)
        for _ in range(100):
            a.tick_once()
            b.tick_once()
        sa, sb = a.snapshot(), b.snapshot()
        assert sa["stats"] == sb["stats"]
        assert [x["node"] for x in sa["ambulances"]] == \
               [x["node"] for x in sb["ambulances"]]


class TestEngineBehaviour:
    def test_incidents_eventually_cleared(self):
        eng = Engine(scenario="downtown-rush")
        eng.run()
        s = eng.snapshot()
        assert s["stats"]["incidents_reported"] == 20
        assert s["stats"]["incidents_cleared"] >= 16
        assert s["stats"]["queue"] == 0

    def test_no_teleportation(self):
        """Movement invariant: units only move to graph neighbours."""
        eng = Engine(scenario="downtown-rush")
        prev = {a.id: a.node for a in eng.ambulances}
        for _ in range(300):
            eng.tick_once()
            for a in eng.ambulances:
                if a.node != prev[a.id]:
                    assert a.node in eng.network.neighbors(prev[a.id])
                prev[a.id] = a.node

    def test_mass_casualty_shows_all_ai(self):
        eng = Engine(scenario="storm-disaster")
        eng.run()
        s = eng.snapshot()
        st = s["stats"]
        # every classical-AI module must have contributed
        assert st["incidents_reported"] == 30
        assert st["csp_solves"] >= 5
        assert st["mdp_solves"] >= 1
        assert st["search_expansions"]["lrta"] > 0
        assert st["arena_runs"] > 0

    def test_idle_mdp_creates_drift_events(self):
        eng = Engine(scenario="quiet-night")
        eng.run()
        kinds = {e.kind for _, e in eng.events}
        assert "mdp.solved" in kinds
        assert "ambulance.idle_move" in kinds

    def test_csp_backtracking_observable(self):
        eng = Engine(scenario="storm-disaster")
        eng.run()
        assert eng.stats["csp_backtracks"] > 0

    def test_blockage_reveal_triggers_dstar_replan(self):
        """A hidden blockage on a fixed route: the unit discovers it at the
        junction, D* Lite repairs the route incrementally."""
        eng = Engine(scenario="downtown-rush")
        target = None
        for _ in range(600):
            eng.tick_once()
            # fixed (non-LRTA) route with at least 3 edges remaining
            target = next((a for a in eng.ambulances
                           if a.status in ("enroute", "transporting")
                           and a.lrta is None
                           and len(a.remaining_route()) >= 4), None)
            if target is not None:
                break
        assert target is not None, "no suitable enroute unit found"
        route = target.remaining_route()
        u, v = route[1], route[2]   # second edge ahead: hidden blockage
        eng.network.block_edge(u, v, 999, reveal=False)
        replanned = []
        for _ in range(400):
            eng.tick_once()
            for _, e in eng.events:
                if e.kind == "ambulance.replanned" and \
                        e.detail.get("algorithm") == "D* Lite":
                    replanned.append(e.summary)
            if replanned:
                break
        assert replanned, \
            "expected an incremental D* Lite replan after hidden blockage"
        # the new route must avoid the blocked edge
        cur = eng.ambulance(target.id)
        new_route = cur.remaining_route() + [cur.node]
        assert (u, v) not in [(new_route[i], new_route[i + 1])
                              for i in range(len(new_route) - 1)]
        assert (v, u) not in [(new_route[i], new_route[i + 1])
                              for i in range(len(new_route) - 1)]

    def test_lrta_dispatches_for_severity_5(self):
        eng = Engine(scenario="quiet-night")
        eng.run()
        dispatched = [e.detail["algorithm"]
                      for _, e in eng.events
                      if e.kind == "ambulance.dispatched"]
        assert dispatched  # at least one dispatch happened
        # quiet-night has no sev-5 incidents, so force one
        eng2 = Engine(scenario="quiet-night")
        eng2._active_incidents = []
        from core.engine import Incident
        from core.dispatch import DEADLINE_SECONDS
        inc = Incident("INC-URG", "n3_3", 5, "cardiac arrest", eng2.tick)
        eng2._active_incidents.append(inc)
        eng2._run_auction(inc)
        assert inc.ambulance_id is not None
        amb = eng2.ambulance(inc.ambulance_id)
        assert amb.algorithm == "LRTA*"

    def test_hospital_capacity_accounting(self):
        eng = Engine(scenario="quiet-night")
        eng.run()
        for h in eng.hospitals:
            assert 0 <= h.in_use <= h.beds

    def test_scenario_script_deterministic_nodes(self):
        a = Engine(scenario="downtown-rush", seed=42)
        b = Engine(scenario="downtown-rush", seed=42)
        assert [x[3] for x in a.incident_schedule] == \
               [x[3] for x in b.incident_schedule]
