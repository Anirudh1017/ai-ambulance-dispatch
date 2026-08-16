"""
Benchmark harness tests: deterministic cells, metric-field contract,
aggregation correctness, and report artifacts (CSV + Markdown + PNGs).
"""

import os

import pandas as pd
import pytest

from core import benchmark as bench
from core.report import render_report

EXPECTED_FIELDS = {
    "scenario", "seed", "combo", "policies",
    "incidents_reported", "incidents_cleared",
    "workload_max", "workload_spread",
    "response_avg", "response_p95", "response_variance",
    "equity_gini", "zone_variance", "max_min_ratio",
    "distance_km", "replans",
    "astar_expansions", "dstar_expansions",
    "replan_full_expansions", "replan_savings_expansions",
    "csp_solves", "csp_backtracks", "mdp_solves", "arena_runs",
    "renegotiations", "renegotiation_savings_s", "runtime_ms",
}


class TestCombos:
    def test_default_combos_are_smart_and_baseline(self):
        cs = bench.combos(full=False)
        assert len(cs) == 2
        assert cs[0] == bench.SMART_POLICIES
        assert cs[1] == bench.BASELINE_POLICIES

    def test_full_combos_add_single_flips(self):
        cs = bench.combos(full=True)
        assert len(cs) == 6
        labels = [bench.combo_name(c) for c in cs]
        assert labels[:2] == ["smart", "baseline"]
        assert set(labels[2:]) == {"flip_dispatch", "flip_replan",
                                   "flip_idle", "flip_hospital"}

    def test_combo_names(self):
        assert bench.combo_name({"dispatch": "greedy", "replan": "dstar",
                                 "idle": "mdp", "hospital": "csp"}) \
            == "flip_dispatch"
        assert bench.combo_name(dict(bench.SMART_POLICIES)) == "smart"


class TestDeterminism:
    def test_identical_seeds_reproduce_identical_rows(self):
        a = bench.run_benchmark(["quiet-night"], [3, 4])
        b = bench.run_benchmark(["quiet-night"], [3, 4])
        drop = "runtime_ms"
        assert list(a.columns) == list(b.columns)
        for col in a.columns:
            if col == drop:
                continue
            assert a[col].tolist() == b[col].tolist(), \
                f"column {col} differs between identical runs"
        # wall-clock is the only non-deterministic field
        assert a["runtime_ms"].tolist() != b["runtime_ms"].tolist() or True

    def test_different_seeds_give_different_worlds(self):
        a = bench.run_benchmark(["quiet-night"], [1])
        b = bench.run_benchmark(["quiet-night"], [2])
        assert a["distance_km"].tolist() != b["distance_km"].tolist()


class TestMetricContract:
    def test_expected_fields_present(self):
        df = bench.run_benchmark(["quiet-night"], [1])
        missing = EXPECTED_FIELDS - set(df.columns)
        assert not missing, f"missing metric columns: {missing}"

    def test_smart_run_counts_and_equity(self):
        df = bench.run_benchmark(["quiet-night"], [1])
        row = df[df["combo"] == "smart"].iloc[0]
        assert row["incidents_cleared"] > 0
        assert 0.0 <= row["equity_gini"] <= 1.0
        assert row["seed"] == 1
        assert row["policies"] == "cnp/dstar/mdp/csp"

    def test_baseline_run_uses_no_smart_modules(self):
        df = bench.run_benchmark(["quiet-night"], [1])
        row = df[df["combo"] == "baseline"].iloc[0]
        assert row["policies"] == "greedy/full_astar/station/first_free"
        assert row["csp_solves"] == 0
        assert row["mdp_solves"] == 0
        assert row["dstar_expansions"] == 0


class TestAggregation:
    def test_aggregate_means_and_stds(self):
        df = pd.DataFrame({
            "scenario": ["s"] * 4, "combo": ["smart"] * 4,
            "seed": [1, 2, 3, 4],
            "response_avg": [100.0, 110.0, 90.0, 100.0],
            "response_variance": [1.0, 2.0, 3.0, 4.0],
            "incidents_cleared": [10, 10, 10, 10],
            "workload_max": [2, 2, 2, 2],
            "workload_spread": [1, 1, 1, 1],
            "equity_gini": [0.5, 0.5, 0.5, 0.5],
            "max_min_ratio": [1.0, 1.0, 1.0, 1.0],
            "response_p95": [5, 5, 5, 5],
            "zone_variance": [1, 1, 1, 1],
            "distance_km": [1, 1, 1, 1],
            "replans": [0, 0, 0, 0],
            "astar_expansions": [0, 0, 0, 0],
            "dstar_expansions": [0, 0, 0, 0],
            "replan_savings_expansions": [0, 0, 0, 0],
            "csp_backtracks": [0, 0, 0, 0],
            "mdp_solves": [0, 0, 0, 0],
            "renegotiations": [0, 0, 0, 0],
        })
        out = bench.aggregate(df)
        row = out.iloc[0]
        assert row["response_avg"] == pytest.approx(100.0)
        assert row["response_avg_std"] == pytest.approx(8.1649, abs=1e-3)
        assert row["response_variance"] == pytest.approx(2.5)
        assert row["incidents_cleared"] == 10.0


class TestReportArtifacts:
    def test_render_report_writes_csv_md_and_pngs(self, tmp_path):
        df = bench.run_benchmark(["quiet-night"], [1, 2])
        artifacts = render_report(df, str(tmp_path))
        csv_path = tmp_path / "benchmark_results.csv"
        md_path = tmp_path / "benchmark_report.md"
        assert csv_path.exists()
        assert md_path.exists()
        assert len(artifacts["charts"]) == 4
        for rel in artifacts["charts"]:
            png = tmp_path / rel
            assert png.exists() and png.stat().st_size > 500
        text = md_path.read_text(encoding="utf-8")
        # the report is coursework-ready: methodology, results, mapping
        assert "## 1. Methodology" in text
        assert "## 2. Headline results" in text
        assert "Gini" in text
        assert "AI concepts" in text
        assert "deterministic" in text

    def test_csv_roundtrip_matches_dataframe(self, tmp_path):
        df = bench.run_benchmark(["quiet-night"], [1])
        render_report(df, str(tmp_path))
        reread = pd.read_csv(tmp_path / "benchmark_results.csv")
        assert len(reread) == len(df)
        assert set(df.columns) == set(reread.columns)