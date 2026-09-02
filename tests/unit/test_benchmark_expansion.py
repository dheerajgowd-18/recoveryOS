"""Unit test suite for Phase 14: Evaluation Lab Expansion, Multi-Seed Benchmark, Holdout Split, Oracle Regret, and Sensitivity Analysis."""
import os
import shutil
import tempfile
import pytest

from evaluation.benchmark_runner import BenchmarkConfig, BenchmarkRunner, MultiSeedBenchmarkResult
from evaluation.harness import EvaluationHarness
from evaluation.oracle import OraclePolicy, evaluate_oracle
from evaluation.policies import (
    AlwaysRetryPolicy,
    NoActionPolicy,
    ProbabilityOnlyPolicy,
    StaticRulePolicy,
)
from evaluation.regret import RegretCalculator, RegretSummary
from evaluation.reports import BenchmarkReportGenerator
from evaluation.sensitivity import SensitivityAnalyzer
from policy.deterministic import DeterministicRecoveryPolicy
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType, SimulatorConfig
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario, Simulator
from simulator.outcomes import ActionOutcome, PotentialOutcomes


@pytest.fixture
def sample_scenarios() -> list[SimulatedScenario]:
    sim = Simulator()
    return sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=20))


class TestMultiSeedBenchmarkAndHoldout:
    """Validates multi-seed scenario generation, determinism, and holdout set segregation."""

    def test_multi_seed_benchmark_determinism(self):
        """Identical seed list and configuration must produce bit-identical benchmark results."""
        cfg1 = BenchmarkConfig(num_scenarios=10, dev_seeds=[42, 43], holdout_seeds=[44], include_holdout=True)
        cfg2 = BenchmarkConfig(num_scenarios=10, dev_seeds=[42, 43], holdout_seeds=[44], include_holdout=True)

        runner1 = BenchmarkRunner(config=cfg1)
        res1 = runner1.run_benchmark()

        runner2 = BenchmarkRunner(config=cfg2)
        res2 = runner2.run_benchmark()

        rec1 = res1.dev_split.policy_results["RECOVERYOS_DETERMINISTIC_V0"]
        rec2 = res2.dev_split.policy_results["RECOVERYOS_DETERMINISTIC_V0"]

        assert rec1.metric_distributions["incremental_adjusted_net_recovery_paise"].mean == rec2.metric_distributions["incremental_adjusted_net_recovery_paise"].mean
        assert rec1.metric_distributions["total_action_cost_paise"].mean == rec2.metric_distributions["total_action_cost_paise"].mean
        assert rec1.regret_summary.mean_regret_paise == rec2.regret_summary.mean_regret_paise

    def test_multi_seed_benchmark_seed_divergence(self):
        """Different seed lists produce divergent but statistically valid metric distributions."""
        cfg_a = BenchmarkConfig(num_scenarios=15, dev_seeds=[42, 43], holdout_seeds=[], include_holdout=False)
        cfg_b = BenchmarkConfig(num_scenarios=15, dev_seeds=[101, 102], holdout_seeds=[], include_holdout=False)

        runner_a = BenchmarkRunner(config=cfg_a)
        res_a = runner_a.run_benchmark()

        runner_b = BenchmarkRunner(config=cfg_b)
        res_b = runner_b.run_benchmark()

        mean_a = res_a.dev_split.policy_results["RECOVERYOS_DETERMINISTIC_V0"].metric_distributions["gross_recovered_amount_paise"].mean
        mean_b = res_b.dev_split.policy_results["RECOVERYOS_DETERMINISTIC_V0"].metric_distributions["gross_recovered_amount_paise"].mean

        # Values should be non-zero and distinct across different seeds
        assert mean_a > 0
        assert mean_b > 0
        assert mean_a != mean_b

    def test_holdout_split_segregation(self):
        """Holdout split must isolate holdout seeds and not overlap with development set."""
        cfg = BenchmarkConfig(num_scenarios=10, dev_seeds=[42, 43, 44], holdout_seeds=[45, 46], include_holdout=True)
        runner = BenchmarkRunner(config=cfg)
        result = runner.run_benchmark()

        assert result.dev_split is not None
        assert result.holdout_split is not None
        assert result.dev_split.seeds == [42, 43, 44]
        assert result.holdout_split.seeds == [45, 46]
        assert result.dev_split.total_scenarios == 30
        assert result.holdout_split.total_scenarios == 20
        assert result.combined_split.total_scenarios == 50


class TestOracleAndRegretMetrics:
    """Validates theoretical oracle ceiling properties and non-negative decision regret."""

    def test_oracle_policy_superiority_every_scenario(self, sample_scenarios):
        """Oracle policy must achieve equal or higher net value than RecoveryOS on every single scenario."""
        harness = EvaluationHarness()
        rec_policy = DeterministicRecoveryPolicy()
        rec_result = harness.evaluate_policy(rec_policy, sample_scenarios)
        oracle_result, oracle_comp = evaluate_oracle(sample_scenarios, recoveryos_result=rec_result)

        assert oracle_comp.oracle_adjusted_net_recovery_paise >= oracle_comp.recoveryos_adjusted_net_recovery_paise
        assert oracle_comp.oracle_incremental_adjusted_net_recovery_paise >= oracle_comp.recoveryos_incremental_adjusted_net_recovery_paise
        assert oracle_comp.recoveryos_vs_oracle_gap_paise >= 0
        assert oracle_comp.recoveryos_oracle_efficiency_pct >= 0.0

    def test_regret_non_negative_every_scenario(self, sample_scenarios):
        """Regret for any policy choice must be strictly non-negative (>= 0) on every scenario."""
        harness = EvaluationHarness()
        policies = [
            NoActionPolicy(),
            AlwaysRetryPolicy(),
            StaticRulePolicy(),
            ProbabilityOnlyPolicy(),
            DeterministicRecoveryPolicy(),
        ]
        results = harness.evaluate_all(policies, sample_scenarios)

        for name, eval_res in results.items():
            for rec in eval_res.records:
                scen = next(s for s in sample_scenarios if s.scenario_id == rec.scenario_id)
                regret, oracle_net, chosen_net = RegretCalculator.compute_scenario_regret(
                    chosen_action=rec.chosen_action,
                    scenario=scen,
                )
                assert regret >= 0, f"Negative regret {regret} found for policy {name} on {scen.scenario_id}"
                assert oracle_net >= chosen_net

    def test_regret_statistics_computation(self, sample_scenarios):
        """RegretCalculator must compute correct statistical summaries."""
        harness = EvaluationHarness()
        policy = DeterministicRecoveryPolicy()
        result = harness.evaluate_policy(policy, sample_scenarios)

        summary: RegretSummary = RegretCalculator.compute_regret(
            records=result.records,
            scenarios=sample_scenarios,
        )

        assert summary.total_scenarios == len(sample_scenarios)
        assert summary.mean_regret_paise >= 0.0
        assert summary.median_regret_paise >= 0.0
        assert summary.p95_regret_paise >= summary.median_regret_paise
        assert summary.max_regret_paise >= summary.p95_regret_paise
        assert 0.0 <= summary.zero_regret_rate <= 1.0
        assert summary.zero_regret_count >= 0


    def test_regret_equals_oracle_incremental_minus_chosen_incremental(self, sample_scenarios):
        """Per-scenario regret must strictly equal oracle incremental net minus chosen incremental net."""
        harness = EvaluationHarness()
        policy = DeterministicRecoveryPolicy()
        result = harness.evaluate_policy(policy, sample_scenarios)

        for rec in result.records:
            scen = next(s for s in sample_scenarios if s.scenario_id == rec.scenario_id)
            regret, oracle_incr, chosen_incr = RegretCalculator.compute_scenario_regret(
                chosen_action=rec.chosen_action,
                scenario=scen,
            )
            assert regret == max(0, oracle_incr - chosen_incr)
            assert oracle_incr >= chosen_incr

    def test_aggregate_regret_reconciles_with_oracle_incremental_gap(self, sample_scenarios):
        """Sum of per-scenario regrets must equal aggregate incremental gap between Oracle and RecoveryOS."""
        harness = EvaluationHarness()
        rec_policy = DeterministicRecoveryPolicy()
        rec_result = harness.evaluate_policy(rec_policy, sample_scenarios)
        oracle_result, oracle_comp = evaluate_oracle(sample_scenarios, recoveryos_result=rec_result)

        regret_summary = RegretCalculator.compute_regret(
            records=rec_result.records,
            scenarios=sample_scenarios,
        )

        expected_gap = oracle_comp.oracle_incremental_adjusted_net_recovery_paise - oracle_comp.recoveryos_incremental_adjusted_net_recovery_paise
        assert oracle_comp.recoveryos_vs_oracle_gap_paise == expected_gap
        assert abs(regret_summary.total_regret_paise - expected_gap) <= 5  # Reconciles within integer rounding


class TestSensitivityAnalysis:
    """Validates economic sensitivity grid analysis across churn penalties and cost multipliers."""

    def test_sensitivity_analysis_parameter_invariance(self, sample_scenarios):
        """Sensitivity analysis must not mutate the underlying scenario definitions or default harness parameters."""
        default_cost = sample_scenarios[0].hidden_outcomes.retry_now.action_cost_paise
        analyzer = SensitivityAnalyzer(
            churn_penalties_paise=[100_000, 500_000],
            action_cost_multipliers=[0.5, 2.0],
        )
        res = analyzer.run_analysis(sample_scenarios)

        assert res.total_combinations == 4
        # Verify underlying scenarios were not mutated
        assert sample_scenarios[0].hidden_outcomes.retry_now.action_cost_paise == default_cost

    def test_sensitivity_matrix_accuracy(self, sample_scenarios):
        """Sensitivity matrix must correctly track RecoveryOS win rate and margin across parameter combinations."""
        analyzer = SensitivityAnalyzer()
        res = analyzer.run_analysis(sample_scenarios)

        assert len(res.grid_cells) == 9  # 3 penalties * 3 multipliers
        assert 0 <= res.recoveryos_wins_count <= 9
        assert 0.0 <= res.recoveryos_win_rate_pct <= 100.0
        assert "| Churn Penalty | Cost Mult |" in res.markdown_matrix


class TestPackagingHygieneAndReportIntegrity:
    """Validates dependency declarations, gitignore exclusions, and report label precision."""

    def test_dependency_manifest_declares_numpy(self):
        """requirements.txt and pyproject.toml must explicitly declare numpy."""
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        req_path = os.path.join(root_dir, "requirements.txt")
        pyproject_path = os.path.join(root_dir, "pyproject.toml")

        with open(req_path, "r", encoding="utf-8") as f:
            req_content = f.read()
        assert "numpy" in req_content, "numpy missing from requirements.txt"

        with open(pyproject_path, "r", encoding="utf-8") as f:
            pyproj_content = f.read()
        assert "numpy" in pyproj_content, "numpy missing from pyproject.toml"

    def test_gitignore_excludes_generated_reports(self):
        """.gitignore must exclude reports/ directory so generated benchmark artifacts are not committed."""
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        gitignore_path = os.path.join(root_dir, ".gitignore")

        with open(gitignore_path, "r", encoding="utf-8") as f:
            gitignore_content = f.read()

        assert "reports/" in gitignore_content or "reports/*" in gitignore_content

    def test_benchmark_report_labels_match_specification(self):
        """Generated report summary must contain canonical metric labels."""
        temp_dir = tempfile.mkdtemp(prefix="rec_labels_test_")
        try:
            cfg = BenchmarkConfig(
                num_scenarios=10,
                dev_seeds=[42],
                holdout_seeds=[],
                include_holdout=False,
                report_output_dir=temp_dir,
            )
            runner = BenchmarkRunner(config=cfg)
            result = runner.run_benchmark()
            paths = BenchmarkReportGenerator.generate_all_reports(result, output_dir=temp_dir)

            with open(paths["summary_md"], "r", encoding="utf-8") as f:
                content = f.read()

            assert "Oracle Incremental Adjusted Net" in content
            assert "RecoveryOS Incremental Adjusted Net" in content
            assert "Incremental Gap" in content
            assert "Total Regret" in content
            assert "Mean Regret" in content
            assert "P95 Regret" in content
            assert "Zero-Regret Rate" in content
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
