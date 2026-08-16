"""
CNP re-negotiation (dynamic task re-allocation) tests.

Addition 3: an incident already awarded to one unit is re-auctioned among
currently eligible units while the incumbent is still travelling to the
scene. The contract moves only when a challenger's ETA beats the
incumbent's remaining ETA by at least the configurable reassignment
penalty (anti-thrash). Every re-negotiation is a first-class
explainability event with costs before/after and the reason.
"""

import pytest

from core.engine import Engine, Incident
from core.graph import build_grid_network

SCENE = "n4_4"


@pytest.fixture
def eng():
    return Engine(scenario="quiet-night", seed=7)


def _eta_between(eng, u, v):
    from core.search import astar
    res = astar(eng.network, u, v)
    assert res.cost is not None
    return res.cost


def _enroute_incumbent(eng, at_node, eta_node=SCENE, edge_progress=60.0):
    """Set up incident I0 assigned to AMB-00 which is enroute to the scene
    from ``at_node``. Returns (inc, incumbent)."""
    inc = Incident("I0", eta_node, 3, "medical", 0)
    inc.status = "enroute"
    inc.assigned_tick = 10
    eng._active_incidents.append(inc)
    amb = eng.ambulances[0]
    amb.node = at_node
    amb.status = "enroute"
    amb.lrta = None
    res = eng._plan_route(amb, eta_node)
    assert res is not None
    eng._set_route(amb, res.path, "A*", eta_node)
    amb.destination = f"incident:{inc.id}"
    amb.incident_id = inc.id
    amb.edge_progress = edge_progress
    inc.ambulance_id = amb.id
    return inc, amb


def _busy_other_units(eng, keep_idle=None):
    """Park every unit except AMB-00 (incumbent) and ``keep_idle`` in a
    busy state so the re-auction pool is exactly the units we control."""
    for amb in eng.ambulances[2:]:
        amb.status = "transporting"
        amb.incident_id = "busy"
    if keep_idle is not None:
        keep_idle.status = "idle"
        keep_idle.incident_id = None
    return eng.ambulances[1]


class TestRenegotiationTrigger:
    def test_contract_moves_to_strictly_better_unit(self, eng):
        inc, incumbent = _enroute_incumbent(eng, at_node="n0_0")
        challenger = eng.ambulances[1]
        challenger.node = SCENE  # ETA 0
        challenger.status = "idle"
        challenger.incident_id = None
        _busy_other_units(eng)

        eng.tick = 100
        eng._maybe_renegotiate()

        assert eng.stats["renegotiations"] == 1
        assert inc.ambulance_id == challenger.id
        assert challenger.incident_id == inc.id
        assert incumbent.status == "idle"
        assert incumbent.incident_id is None
        assert incumbent.route == []
        # response time still measured from the original report tick
        assert inc.assigned_tick == 10
        # savings stat = pre-penalty ETA gain
        eta0 = eng._remaining_eta(incumbent, SCENE)  # now idle: no route
        assert eta0 is None
        assert eng.stats["renegotiation_savings_s"] >= 0

    def test_no_trigger_below_penalty_threshold(self, eng):
        """A challenger that is better but not by the penalty margin must
        NOT move the contract (anti-thrash)."""
        inc, incumbent = _enroute_incumbent(eng, at_node="n0_0")
        incumbent_eta = eng._remaining_eta(incumbent, SCENE)
        # challenger at a node whose ETA is inside the penalty margin
        nodes = sorted(eng.network.nodes,
                       key=lambda n: abs(_eta_between(eng, n, SCENE)
                                         - (incumbent_eta - 30.0)))
        challenger = eng.ambulances[1]
        challenger.node = nodes[0]
        challenger.status = "idle"
        challenger.incident_id = None
        _busy_other_units(eng)
        challenger_eta = _eta_between(eng, nodes[0], SCENE)
        assert challenger_eta + 60.0 >= incumbent_eta  # margin not beaten

        eng.tick = 100
        eng._maybe_renegotiate()

        assert eng.stats["renegotiations"] == 0
        assert inc.ambulance_id == incumbent.id
        assert incumbent.status == "enroute"
        assert challenger.incident_id is None
        kinds = {e.kind for _, e in eng.events}
        assert "dispatch.renegotiated" not in kinds

    def test_no_trigger_when_penalty_disables_thrash(self, eng):
        """A huge reassignment penalty is equivalent to banning the move."""
        inc, incumbent = _enroute_incumbent(eng, at_node="n0_0")
        challenger = eng.ambulances[1]
        challenger.node = SCENE
        challenger.status = "idle"
        challenger.incident_id = None
        _busy_other_units(eng)
        eng.renog_cfg["reassign_penalty_seconds"] = 1_000_000.0

        eng.tick = 100
        eng._maybe_renegotiate()

        assert eng.stats["renegotiations"] == 0
        assert inc.ambulance_id == incumbent.id

    def test_renog_disabled_by_config(self, eng):
        inc, incumbent = _enroute_incumbent(eng, at_node="n0_0")
        challenger = eng.ambulances[1]
        challenger.node = SCENE
        challenger.status = "idle"
        challenger.incident_id = None
        _busy_other_units(eng)
        eng.renog_cfg["renog_enabled"] = False

        eng.tick = 100
        eng._maybe_renegotiate()

        assert eng.stats["renegotiations"] == 0
        assert inc.ambulance_id == incumbent.id

    def test_renegotiation_is_cnp_only(self):
        eng = Engine(scenario="quiet-night", seed=7,
                     config={"policies": {"dispatch": "greedy"}})
        inc, incumbent = _enroute_incumbent(eng, at_node="n0_0")
        challenger = eng.ambulances[1]
        challenger.node = SCENE
        challenger.status = "idle"
        challenger.incident_id = None
        _busy_other_units(eng)
        eng.tick = 100
        eng._maybe_renegotiate()
        assert eng.stats["renegotiations"] == 0
        assert inc.ambulance_id == incumbent.id


class TestRenegotiationLogging:
    def test_renegotiation_fully_logged(self, eng):
        inc, incumbent = _enroute_incumbent(eng, at_node="n0_0")
        incumbent_eta = eng._remaining_eta(incumbent, SCENE)
        challenger = eng.ambulances[1]
        challenger.node = SCENE
        challenger.status = "idle"
        challenger.incident_id = None
        _busy_other_units(eng)
        challenger_eta = 0.0

        eng.tick = 100
        eng._maybe_renegotiate()

        events = [e for _, e in eng.events]
        reneg = [e for e in events if e.kind == "dispatch.renegotiated"]
        assert len(reneg) == 1
        ev = reneg[0]
        assert ev.detail["incident_id"] == "I0"
        assert ev.detail["old_ambulance_id"] == incumbent.id
        assert ev.detail["new_ambulance_id"] == challenger.id
        assert ev.detail["old_eta_seconds"] == pytest.approx(incumbent_eta,
                                                             abs=0.1)
        assert ev.detail["new_eta_seconds"] == 0.0
        assert ev.detail["penalty_seconds"] == 60.0
        assert "reason" in ev.detail
        assert "str" in ev.summary  # human-readable why

        # the re-auction itself is a full, marked transcript
        announces = [e.detail for e in events
                     if e.kind == "dispatch.auction.announce"
                     and e.detail.get("renegotiation") is True]
        assert len(announces) == 1
        bids = [e for e in events
                if e.kind == "dispatch.auction.bid"
                and e.detail.get("renegotiation") is True]
        assert bids  # challenger bid logged
        # the originally-assigned unit was released with its own event
        statuses = [e for e in events if e.kind == "ambulance.status"]
        assert any(e.detail.get("new") == "idle"
                   and e.detail.get("ambulance_id") == incumbent.id
                   for e in statuses)

    def test_cooldown_prevents_immediate_rethrash(self, eng):
        """After a re-negotiation, the same incident cannot be re-auctioned
        again until the cooldown elapses — the second anti-thrash guard."""
        inc, _ = _enroute_incumbent(eng, at_node="n0_0")
        eng.ambulances[1].node = SCENE
        eng.ambulances[1].status = "idle"
        eng.ambulances[1].incident_id = None
        _busy_other_units(eng)

        eng.tick = 100
        eng._maybe_renegotiate()
        assert eng.stats["renegotiations"] == 1
        last = inc.last_renog_tick
        assert last == 100

        # next scan inside the cooldown: the new incumbent is enroute and
        # the old one is idle again — but the cooldown blocks the scan
        eng.tick = 110
        eng._maybe_renegotiate()
        assert eng.stats["renegotiations"] == 1
        # after the cooldown the scan runs again
        eng.tick = 200
        eng._maybe_renegotiate()
        assert eng.stats["renegotiations"] == 1  # no better challenger left