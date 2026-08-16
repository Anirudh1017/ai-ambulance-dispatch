"""
run_benchmark.py — headless baseline-comparison study.

Runs the deterministic harness (core.benchmark) over scenario × seed ×
policy-combo cells and emits, into ``--out`` (default ./benchmark_out):

    benchmark_results.csv      every run, one row (raw evidence)
    benchmark_report.md        methodology + aggregates + charts + mapping
    charts/*.png               matplotlib figures (Agg, headless)

Examples
--------
    python run_benchmark.py                        # 4 scenarios × 30 seeds × 2 stacks
    python run_benchmark.py --full                 # + 4 single-flip ablations
    python run_benchmark.py --quick                # 1 scenario × 3 seeds (smoke)
    python run_benchmark.py --scenarios storm-disaster --seeds 10

Determinism: every cell is Engine(seed)-seeded; two runs with the same
seed schedule reproduce the CSV bit-for-bit (except wall-clock runtime_ms).
"""

from __future__ import annotations

import argparse
import os
import sys

from core import benchmark as bench
from core.report import render_report
from core.scenarios import scenario_summaries

SCENARIOS = [s["id"] for s in scenario_summaries()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS,
                        default=SCENARIOS)
    parser.add_argument("--seeds", type=int, default=30,
                        help="use seeds 1..N (default 30)")
    parser.add_argument("--full", action="store_true",
                        help="also flip each subsystem individually (6 combos)")
    parser.add_argument("--quick", action="store_true",
                        help="1 scenario × 3 seeds × 2 stacks (smoke test)")
    parser.add_argument("--out", default="benchmark_out",
                        help="output directory")
    args = parser.parse_args()

    if args.quick:
        scenarios, seeds = [args.scenarios[0]], [1, 2, 3]
    else:
        scenarios, seeds = args.scenarios, bench.default_seeds(args.seeds)

    total = len(scenarios) * len(seeds) * len(bench.combos(args.full))
    print(f"benchmark: {len(scenarios)} scenario(s) × {len(seeds)} seed(s) "
          f"× {len(bench.combos(args.full))} combo(s) = {total} runs"
          + ("  [quick smoke]" if args.quick else ""))

    def progress(done: int, total_: int, label: str) -> None:
        print(f"  [{done:>4}/{total_}] {label}", flush=True)

    df = bench.run_benchmark(scenarios, seeds, full=args.full,
                             progress=progress)
    artifacts = render_report(df, args.out)

    overall = bench.overall(df)
    row = overall.set_index("combo")
    print("\nheadline (mean over seeds):")
    print(f"  {'combo':<10} {'cleared':>8} {'resp_avg':>9} "
          f"{'gini':>6} {'replans':>7} {'reneg':>5}")
    for _, r in overall.iterrows():
        print(f"  {r['combo']:<10} {r['incidents_cleared']:>8.1f} "
              f"{r['response_avg']:>9.1f} {r['equity_gini']:>6.3f} "
              f"{r['replans']:>7.1f} {r['renegotiations']:>5.1f}")

    print(f"\nartifacts written to {os.path.abspath(args.out)}")
    for path in artifacts["csv"] + artifacts["md"] + artifacts["charts"]:
        print(f"  {path}")


if __name__ == "__main__":
    sys.exit(main())