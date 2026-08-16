"""Tests for the equity / fairness metric (Addition 2).

The Gini coefficient is pinned to hand-computed expected values on small
synthetic datasets, and the engine-level per-zone tracking is verified end
to end on a real scenario run.
"""

import pytest

from core.engine import Engine
from core.metrics import gini_coefficient, zone_equity


class TestGiniCoefficient:
    def test_perfect_equality_is_zero(self):
        assert gini_coefficient([100.0, 100.0, 100.0]) == pytest.approx(0.0)

    def test_known_value_three_unequal(self):
        """Hand-computed: for [10, 20, 30] the relative-mean-difference
        Gini is exactly 2/9.
        G = (2 * (1*10 + 2*20 + 3*30)) / (3 * 60) - 4/3 = 2/9."""
        assert gini_coefficient([10.0, 20.0, 30.0]) == pytest.approx(2 / 9)

    def test_known_value_two_unequal(self):
        """For [0, 50]: G = (2 * (0 + 100)) / (2 * 50) - 3/2 = 0.5."""
        assert gini_coefficient([0.0, 50.0]) == pytest.approx(0.5)

    def test_known_value_four(self):
        """For [1, 2, 3, 10]: T = 16, weighted = 1 + 4 + 9 + 40 = 54,
        G = (2*54)/(4*16) - 5/4 = 108/64 - 1.25 = 0.4375."""
        assert gini_coefficient([1.0, 2.0, 3.0, 10.0]) == pytest.approx(0.4375)

    def test_empty_and_singleton(self):
        assert gini_coefficient([]) == 0.0
        assert gini_coefficient([42.0]) == 0.0

    def test_unsorted_input_gives_same_result(self):
        a = gini_coefficient([10.0, 30.0, 20.0])
        b = gini_coefficient([20.0, 10.0, 30.0])
        assert a == pytest.approx(b) == pytest.approx(2 / 9)


class TestZoneEquity:
    def test_summary_fields_on_synthetic_data(self):
        eq = zone_equity({"zone-1": [10.0, 30.0, 20.0],
                          "zone-2": [50.0, 50.0, 50.0],
                          "zone-3": [50.0, 70.0]},
                         all_zones=["zone-1", "zone-2", "zone-3", "zone-4"])
        assert eq["served_zones"] == 3
        assert eq["zones"] == 4
        assert eq["per_zone"]["zone-4"]["n"] == 0
        assert eq["per_zone"]["zone-4"]["mean"] == 0.0
        assert eq["best_zone"] == "zone-1"
        assert eq["worst_zone"] == "zone-3"
        assert eq["max_min_ratio"] == pytest.approx(60.0 / 20.0)
        # gini over means [20, 50, 60]: T=130, weighted=1*20+2*50+3*60=300
        # G = (2*300)/(3*130) - 4/3 = 600/390 - 4/3 = 0.205128...
        assert eq["gini"] == pytest.approx(600 / 390 - 4 / 3, abs=1e-6)

    def test_no_data_yields_neutral(self):
        eq = zone_equity({}, all_zones=["zone-1", "zone-2"])
        assert eq["gini"] == 0.0
        assert eq["best_zone"] is None and eq["worst_zone"] is None
        assert eq["max_min_ratio"] is None


class TestEngineEquity:
    def test_per_zone_responses_recorded(self):
        eng = Engine(scenario="downtown-rush", seed=7)
        eng.run()
        zrt = eng.stats["zone_response_times"]
        # every cleared incident was recorded in exactly its zone
        assert sum(len(v) for v in zrt.values()) == \
            len(eng.stats["response_times"])
        assert eng.stats["response_times"], "run must produce responses"

    def test_equity_block_serialisable_and_bounded(self):
        eng = Engine(scenario="storm-disaster", seed=7)
        eng.run()
        eq = eng.stats["equity"]
        import json
        json.dumps(eq)
        assert 0.0 <= eq["gini"] <= 1.0
        assert eq["served_zones"] >= 1
        assert eq["best_zone"] is not None and eq["worst_zone"] is not None
        # worst-served zone mean must be >= best-served zone mean
        assert (eq["per_zone"][eq["worst_zone"]]["mean"]
                >= eq["per_zone"][eq["best_zone"]]["mean"])

    def test_zone_equity_deterministic_same_seed(self):
        a = Engine(scenario="quiet-night", seed=11)
        b = Engine(scenario="quiet-night", seed=11)
        a.run()
        b.run()
        assert a.stats["equity"] == b.stats["equity"]

    def test_response_variance_tracked(self):
        eng = Engine(scenario="gridlock", seed=5)
        eng.run()
        assert eng.stats["response_variance"] >= 0.0
        if len(eng.stats["response_times"]) >= 2:
            assert eng.stats["response_variance"] > 0.0 or \
                len(set(eng.stats["response_times"])) == 1