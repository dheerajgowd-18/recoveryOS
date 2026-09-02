#!/usr/bin/env python3
"""CLI benchmark utility for running multi-seed, holdout, oracle, and sensitivity evaluations for RecoveryOS."""
import argparse
import os
import sys

# Reconfigure stdout to UTF-8 if supported
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from evaluation.benchmark_runner import BenchmarkConfig, BenchmarkRunner
from evaluation.reports import BenchmarkReportGenerator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RecoveryOS Multi-Seed Benchmark & Evaluation Lab Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--scenarios",
        type=int,
        default=1000,
        help="Number of scenarios generated per seed (e.g. 100, 1000, 10000)",
    )
    parser.add_argument(
        "--seeds",
        type=str,
        default="42,43,44",
        help="Comma-separated list of random seeds for the development set",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Single seed override (runs development set with exactly 1 seed and disables holdout)",
    )
    parser.add_argument(
        "--holdout-seeds",
        type=str,
        default="45,46",
        help="Comma-separated list of random seeds for the holdout set",
    )
    parser.add_argument(
        "--no-holdout",
        action="store_true",
        help="Disable the holdout dataset split evaluation",
    )
    parser.add_argument(
        "--churn-penalty",
        type=int,
        default=250_000,
        help="Economic churn friction penalty in paise (default: 250000 paise = ₹2,500)",
    )
    parser.add_argument(
        "--compare-llm",
        action="store_true",
        help="Include RECOVERYOS_LLM_DRIVEN policy in the evaluation comparison cohort",
    )
    parser.add_argument(
        "--run-ablation",
        action="store_true",
        help="Execute the 3-variant ablation study (Rules vs LLM-Diag vs LLM-Diag+LLM-Strat)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports",
        help="Directory to save markdown and JSON benchmark reports",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.seed is not None:
        dev_seeds = [args.seed]
        holdout_seeds = []
        include_holdout = False
    else:
        dev_seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
        holdout_seeds = [int(s.strip()) for s in args.holdout_seeds.split(",") if s.strip()] if not args.no_holdout else []
        include_holdout = not args.no_holdout and len(holdout_seeds) > 0

    config = BenchmarkConfig(
        num_scenarios=args.scenarios,
        dev_seeds=dev_seeds,
        holdout_seeds=holdout_seeds,
        include_holdout=include_holdout,
        churn_penalty_paise=args.churn_penalty,
        compare_llm=args.compare_llm,
        report_output_dir=args.output_dir,
    )

    total_scenarios = (len(dev_seeds) + (len(holdout_seeds) if include_holdout else 0)) * args.scenarios

    print("=" * 80)
    print("  [RECOVERYOS] Multi-Seed Benchmark & Evaluation Lab")
    print("  Razorpay AI Buildathon 2026 -- Track 03: Autonomous AI Revenue Recovery")
    print("=" * 80)
    print(f"  Scenarios Per Seed : {args.scenarios:,}")
    print(f"  Development Seeds  : {dev_seeds} ({len(dev_seeds) * args.scenarios:,} scenarios)")
    print(f"  Holdout Seeds      : {holdout_seeds if include_holdout else 'None (Disabled)'} ({(len(holdout_seeds) * args.scenarios) if include_holdout else 0:,} scenarios)")
    print(f"  Total Cohort Size  : {total_scenarios:,} scenarios")
    print(f"  Churn Friction     : INR {args.churn_penalty / 100:,.2f} per churned customer")
    print(f"  Output Directory   : {args.output_dir}/")
    print("-" * 80)
    print("  Executing benchmark evaluation across all policies and splits...")

    runner = BenchmarkRunner(config=config)
    result = runner.run_benchmark()

    # Generate and write report files
    report_paths = BenchmarkReportGenerator.generate_all_reports(
        benchmark_result=result,
        output_dir=args.output_dir,
    )

    # Print Executive Summary in Terminal
    print("\n" + "=" * 80)
    print("  DEVELOPMENT SPLIT BENCHMARK SUMMARY (Seeds: " + str(dev_seeds) + ")")
    print("=" * 80)
    print(f"{'Policy':<28} | {'Adj Net (Mean ± Std)':<23} | {'Incr Adj Net':<23} | {'Acts':<6} | {'Churn':<6}")
    print("-" * 92)

    for name, p_metrics in result.dev_split.policy_results.items():
        d = p_metrics.metric_distributions
        adj_str = f"INR {d['adjusted_net_recovery_paise'].mean / 100:,.0f} ± {d['adjusted_net_recovery_paise'].std / 100:,.0f}"
        incr_str = f"INR {d['incremental_adjusted_net_recovery_paise'].mean / 100:,.0f} ± {d['incremental_adjusted_net_recovery_paise'].std / 100:,.0f}"
        acts_str = f"{d['intervention_count'].mean:.1f}"
        churn_str = f"{d['total_churned_customers'].mean:.1f}"
        print(f"{name:<28} | {adj_str:<23} | {incr_str:<23} | {acts_str:<6} | {churn_str:<6}")

    if result.holdout_split:
        print("\n" + "=" * 80)
        print("  HOLDOUT SPLIT BENCHMARK SUMMARY (Seeds: " + str(holdout_seeds) + " - Strictly Untuned)")
        print("=" * 80)
        print(f"{'Policy':<28} | {'Adj Net (Mean ± Std)':<23} | {'Incr Adj Net':<23} | {'Acts':<6} | {'Churn':<6}")
        print("-" * 92)
        for name, p_metrics in result.holdout_split.policy_results.items():
            d = p_metrics.metric_distributions
            adj_str = f"INR {d['adjusted_net_recovery_paise'].mean / 100:,.0f} ± {d['adjusted_net_recovery_paise'].std / 100:,.0f}"
            incr_str = f"INR {d['incremental_adjusted_net_recovery_paise'].mean / 100:,.0f} ± {d['incremental_adjusted_net_recovery_paise'].std / 100:,.0f}"
            acts_str = f"{d['intervention_count'].mean:.1f}"
            churn_str = f"{d['total_churned_customers'].mean:.1f}"
            print(f"{name:<28} | {adj_str:<23} | {incr_str:<23} | {acts_str:<6} | {churn_str:<6}")

    print("\n" + "=" * 80)
    print("  ORACLE CEILING & DECISION REGRET (Combined Cohort)")
    print("=" * 80)
    oracle_comp = result.combined_split.oracle_comparison
    rec_regret = result.combined_split.policy_results["RECOVERYOS_DETERMINISTIC_V0"].regret_summary
    print(f"  Oracle Incremental Adjusted Net     : INR {oracle_comp.oracle_incremental_adjusted_net_recovery_paise / 100:,.2f}")
    print(f"  RecoveryOS Incremental Adjusted Net : INR {oracle_comp.recoveryos_incremental_adjusted_net_recovery_paise / 100:,.2f}")
    print(f"  Incremental Gap                     : INR {oracle_comp.recoveryos_vs_oracle_gap_paise / 100:,.2f} ({oracle_comp.recoveryos_oracle_efficiency_pct:.1f}% Efficiency)")
    print(f"  Total Regret                        : INR {rec_regret.total_regret_paise / 100:,.2f}")
    print(f"  Mean Regret                         : INR {rec_regret.mean_regret_paise / 100:,.2f} per scenario")
    print(f"  Median Regret                       : INR {rec_regret.median_regret_paise / 100:,.2f}")
    print(f"  P95 Regret                          : INR {rec_regret.p95_regret_paise / 100:,.2f}")
    print(f"  Zero-Regret Rate                    : {rec_regret.zero_regret_rate * 100:.1f}% ({rec_regret.zero_regret_count}/{rec_regret.total_scenarios} optimal choices)")

    print("\n" + "=" * 80)
    print("  SENSITIVITY ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"  Combinations Evaluated    : {result.sensitivity_analysis.total_combinations}")
    print(f"  RecoveryOS Win Rate       : {result.sensitivity_analysis.recoveryos_win_rate_pct:.1f}% ({result.sensitivity_analysis.recoveryos_wins_count}/{result.sensitivity_analysis.total_combinations} cells won)")

    print("\n" + "=" * 80)
    print("  BENCHMARK ARTIFACTS WRITTEN")
    print("=" * 80)
    for k, path in report_paths.items():
        print(f"  [SAVED] {k:<15} -> {path}")

    if args.run_ablation:
        from evaluation.ablation import AblationRunner
        print("\n" + "=" * 80)
        print("  EXECUTING ABLATION STUDY (Rules vs LLM-Diag vs Full Agentic)")
        print("=" * 80)
        ablation_runner = AblationRunner(output_dir=args.output_dir)
        ab_res = ablation_runner.run_ablation(seeds=dev_seeds, scenarios_per_seed=args.scenarios)
        print(f"  [SAVED] ablation_summary -> {os.path.join(args.output_dir, 'ablation_summary.md')}")
        print(f"  LLM Diagnosis Incremental Uplift (B - A)            : INR {ab_res.diagnosis_contribution_uplift_paise / 100:,.2f}")
        print(f"  Incremental Value of Full Agentic Strategy Layer (C - B): INR {ab_res.strategy_layer_incremental_value_paise / 100:,.2f}")
        print(f"  Total Combined AI Layer Value (C - A)               : INR {ab_res.total_ai_layer_uplift_paise / 100:,.2f}")

    print("=" * 80)


if __name__ == "__main__":
    main()
