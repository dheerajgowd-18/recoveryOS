"""Multi-seed benchmark orchestrator with holdout split, oracle benchmarking, and statistical aggregation."""
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from evaluation.harness import EvaluationExecutionMode, EvaluationHarness, EvaluationResult
from evaluation.metrics import DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER, EvaluationMetrics
from evaluation.oracle import OracleComparisonResult, evaluate_oracle
from evaluation.policies import (
    AlwaysRetryPolicy,
    BasePolicy,
    NoActionPolicy,
    ProbabilityOnlyPolicy,
    StaticRulePolicy,
)
from evaluation.regret import RegretCalculator, RegretSummary
from evaluation.sensitivity import SensitivityAnalysisResult, SensitivityAnalyzer
from policy.deterministic import DeterministicRecoveryPolicy
from simulator.config import SimulatorConfig
from simulator.generator import SimulatedScenario, Simulator

__all__ = [
    "BenchmarkConfig",
    "MetricDistribution",
    "AggregatedPolicyMetrics",
    "BenchmarkDatasetSplit",
    "MultiSeedBenchmarkResult",
    "BenchmarkRunner",
]


class BenchmarkConfig(BaseModel):
    """Configuration model for multi-seed and holdout benchmark runs."""
    model_config = ConfigDict(extra="forbid")

    num_scenarios: int = Field(default=1000, ge=1, description="Number of scenarios generated per seed")
    dev_seeds: List[int] = Field(default=[42, 43, 44], min_length=1, description="Seed list for development benchmark")
    holdout_seeds: List[int] = Field(default=[45, 46], description="Seed list for holdout benchmark evaluation")
    scenario_family_filter: Optional[str] = Field(default=None, description="Optional filter for scenario families")
    include_holdout: bool = Field(default=True, description="Whether to generate and evaluate the holdout split")
    churn_penalties_paise: List[int] = Field(
        default=[100_000, 250_000, 500_000], description="Grid of churn penalties in paise for sensitivity"
    )
    action_cost_multipliers: List[float] = Field(
        default=[0.5, 1.0, 2.0], description="Grid of action cost multipliers for sensitivity"
    )
    churn_penalty_paise: int = Field(
        default=DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER, description="Standard benchmark churn penalty in paise"
    )
    compare_llm: bool = Field(
        default=False, description="Whether to include RECOVERYOS_LLM_DRIVEN in benchmark evaluation cohort"
    )
    execution_mode: EvaluationExecutionMode = Field(
        default=EvaluationExecutionMode.OFFLINE_REPLAY,
        description="Evaluation execution mode (OFFLINE_REPLAY, LIVE_LLM, STRICT_NO_FALLBACK)",
    )
    report_output_dir: str = Field(default="reports", description="Destination directory for benchmark reports")


class MetricDistribution(BaseModel):
    """Statistical distribution summary for a metric across multiple seed evaluations."""
    model_config = ConfigDict(extra="forbid")

    mean: float = Field(..., description="Mean value across seed runs")
    std: float = Field(..., description="Sample standard deviation across seed runs")
    median: float = Field(..., description="Median value across seed runs")
    min: float = Field(..., description="Minimum value observed across seed runs")
    max: float = Field(..., description="Maximum value observed across seed runs")
    ci_95_lower: float = Field(..., description="95% Confidence Interval lower bound")
    ci_95_upper: float = Field(..., description="95% Confidence Interval upper bound")


class AggregatedPolicyMetrics(BaseModel):
    """Aggregated multi-seed performance metrics for a single recovery policy."""
    model_config = ConfigDict(extra="forbid")

    policy_name: str = Field(..., description="Name of the evaluated policy")
    metric_distributions: Dict[str, MetricDistribution] = Field(
        ..., description="Statistical distributions for all tracked metrics"
    )
    regret_summary: RegretSummary = Field(..., description="Aggregated decision regret distribution vs Oracle")
    per_seed_metrics: List[EvaluationMetrics] = Field(
        default_factory=list, description="Per-seed unaggregated evaluation metrics"
    )


class BenchmarkDatasetSplit(BaseModel):
    """Evaluation outcomes for a specific dataset split (development, holdout, or combined)."""
    model_config = ConfigDict(extra="forbid")

    split_name: str = Field(..., description="Dataset split name: 'development', 'holdout', or 'combined'")
    seeds: List[int] = Field(..., description="Random generator seeds included in this split")
    scenarios_per_seed: int = Field(..., ge=1, description="Scenario count per seed")
    total_scenarios: int = Field(..., ge=1, description="Total evaluated scenarios in this split")
    policy_results: Dict[str, AggregatedPolicyMetrics] = Field(
        ..., description="Aggregated benchmark results per policy"
    )
    oracle_comparison: OracleComparisonResult = Field(
        ..., description="Oracle theoretical benchmark comparison vs RecoveryOS"
    )


class MultiSeedBenchmarkResult(BaseModel):
    """Complete benchmark execution artifact containing splits, sensitivity, oracle, and failure cases."""
    model_config = ConfigDict(extra="forbid")

    config: BenchmarkConfig = Field(..., description="Benchmark configuration used for the run")
    timestamp_iso: str = Field(..., description="ISO 8601 execution timestamp")
    dev_split: BenchmarkDatasetSplit = Field(..., description="Development dataset split evaluation")
    holdout_split: Optional[BenchmarkDatasetSplit] = Field(
        default=None, description="Holdout dataset split evaluation (untuned)"
    )
    combined_split: BenchmarkDatasetSplit = Field(..., description="Combined evaluation across all seeds")
    sensitivity_analysis: SensitivityAnalysisResult = Field(
        ..., description="Economic sensitivity matrix across churn penalties and action costs"
    )
    failure_cases: List[Dict[str, Any]] = Field(
        default_factory=list, description="Sample failure cases and anomalies for diagnostic audit"
    )


class BenchmarkRunner:
    """Orchestrates multi-seed batch generation, holdout segregation, oracle evaluation, and report compilation."""

    def __init__(self, config: Optional[BenchmarkConfig] = None) -> None:
        self.config = config or BenchmarkConfig()
        self.simulator = Simulator()
        self.harness = EvaluationHarness(
            churn_penalty_paise_per_customer=self.config.churn_penalty_paise,
            mode=self.config.execution_mode,
        )
        self.sensitivity_analyzer = SensitivityAnalyzer(
            churn_penalties_paise=self.config.churn_penalties_paise,
            action_cost_multipliers=self.config.action_cost_multipliers,
        )

    def get_default_policies(self) -> List[BasePolicy]:
        """Returns the canonical benchmark policy cohort."""
        from evaluation.policies import AgenticGraphRecoveryPolicy
        policies: List[BasePolicy] = [
            NoActionPolicy(),
            AlwaysRetryPolicy(),
            StaticRulePolicy(),
            ProbabilityOnlyPolicy(),
            DeterministicRecoveryPolicy(),
            AgenticGraphRecoveryPolicy(),
        ]
        if self.config.compare_llm:
            from policy.deterministic import LLMDrivenRecoveryPolicy
            policies.append(LLMDrivenRecoveryPolicy())
        return policies

    def _compute_distribution(self, values: List[float]) -> MetricDistribution:
        """Computes statistical distribution with sample std and 95% confidence interval."""
        if not values:
            return MetricDistribution(mean=0.0, std=0.0, median=0.0, min=0.0, max=0.0, ci_95_lower=0.0, ci_95_upper=0.0)

        n = len(values)
        arr = np.array(values, dtype=np.float64)
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr, ddof=1)) if n > 1 else 0.0
        median_val = float(np.median(arr))
        min_val = float(np.min(arr))
        max_val = float(np.max(arr))

        # 95% Confidence Interval (t_crit ~ 1.96 for n >= 3)
        margin = 1.96 * (std_val / math.sqrt(n)) if n > 1 else 0.0
        ci_lower = mean_val - margin
        ci_upper = mean_val + margin

        return MetricDistribution(
            mean=round(mean_val, 2),
            std=round(std_val, 2),
            median=round(median_val, 2),
            min=round(min_val, 2),
            max=round(max_val, 2),
            ci_95_lower=round(ci_lower, 2),
            ci_95_upper=round(ci_upper, 2),
        )

    def evaluate_split(
        self,
        split_name: str,
        seeds: List[int],
        num_scenarios_per_seed: int,
        policies: Optional[List[BasePolicy]] = None,
    ) -> tuple[BenchmarkDatasetSplit, List[SimulatedScenario], Dict[str, List[EvaluationResult]]]:
        """Runs evaluation over a list of seeds for a given split name."""
        if policies is None:
            policies = self.get_default_policies()

        all_scenarios: List[SimulatedScenario] = []
        seed_results_by_policy: Dict[str, List[EvaluationResult]] = {p.name: [] for p in policies}
        policy_regret_pairs: Dict[str, List[tuple[str, int]]] = {p.name: [] for p in policies}
        seed_oracle_results: List[EvaluationResult] = []
        seed_oracle_comparisons: List[OracleComparisonResult] = []

        for seed in seeds:
            sim_cfg = SimulatorConfig(seed=seed, num_scenarios=num_scenarios_per_seed)
            scenarios = self.simulator.generate_batch(sim_cfg)
            scen_map = {s.scenario_id: s for s in scenarios}
            all_scenarios.extend(scenarios)

            # Evaluate each policy on this seed
            seed_res = self.harness.evaluate_all(
                policies=policies,
                scenarios=scenarios,
                churn_penalty_paise_per_customer=self.config.churn_penalty_paise,
            )
            for p in policies:
                eval_res = seed_res[p.name]
                seed_results_by_policy[p.name].append(eval_res)
                for rec in eval_res.records:
                    scen = scen_map.get(rec.scenario_id)
                    if scen:
                        r, _, _ = RegretCalculator.compute_scenario_regret(
                            chosen_action=rec.chosen_action,
                            scenario=scen,
                            churn_penalty_paise=self.config.churn_penalty_paise,
                        )
                        unique_id = f"seed_{seed}_{rec.scenario_id}"
                        policy_regret_pairs[p.name].append((unique_id, r))

            # Evaluate Oracle on this seed
            rec_res = seed_res.get("RECOVERYOS_DETERMINISTIC_V0")
            oracle_res, oracle_comp = evaluate_oracle(
                scenarios=scenarios,
                churn_penalty_paise=self.config.churn_penalty_paise,
                recoveryos_result=rec_res,
            )
            seed_oracle_results.append(oracle_res)
            seed_oracle_comparisons.append(oracle_comp)

        # Aggregate metrics across seeds for each policy
        tracked_metric_keys = [
            "gross_recovered_amount_paise",
            "natural_recovered_amount_paise",
            "incremental_amount_paise",
            "total_action_cost_paise",
            "churn_penalty_paise",
            "adjusted_net_recovery_paise",
            "incremental_adjusted_net_recovery_paise",
            "intervention_count",
            "actions_avoided_count",
            "total_churned_customers",
            "governor_allow_count",
            "governor_deny_count",
            "governor_abstain_count",
            "governor_defer_count",
            "human_review_count",
            "policy_block_count",
            "actions_scheduled_count",
            "actions_executed_immediately_count",
        ]

        aggregated_policies: Dict[str, AggregatedPolicyMetrics] = {}

        for p in policies:
            eval_list = seed_results_by_policy[p.name]
            per_seed_metrics = [e.metrics for e in eval_list]

            regret_summary = RegretCalculator.compute_from_regrets(
                policy_name=p.name,
                regret_pairs=policy_regret_pairs[p.name],
            )

            metric_distributions: Dict[str, MetricDistribution] = {}
            for key in tracked_metric_keys:
                vals = [float(getattr(m, key, 0.0)) for m in per_seed_metrics]
                metric_distributions[key] = self._compute_distribution(vals)

            aggregated_policies[p.name] = AggregatedPolicyMetrics(
                policy_name=p.name,
                metric_distributions=metric_distributions,
                regret_summary=regret_summary,
                per_seed_metrics=per_seed_metrics,
            )

        # Compute combined Oracle comparison across seeds
        total_oracle_gross = sum(c.oracle_gross_recovery_paise for c in seed_oracle_comparisons)
        total_oracle_cost = sum(c.oracle_action_cost_paise for c in seed_oracle_comparisons)
        total_oracle_churn_pen = sum(c.oracle_churn_penalty_paise for c in seed_oracle_comparisons)
        total_oracle_adj_net = sum(c.oracle_adjusted_net_recovery_paise for c in seed_oracle_comparisons)
        total_oracle_incr_adj = sum(c.oracle_incremental_adjusted_net_recovery_paise for c in seed_oracle_comparisons)
        total_rec_adj_net = sum(c.recoveryos_adjusted_net_recovery_paise for c in seed_oracle_comparisons)
        total_rec_incr_adj = sum(c.recoveryos_incremental_adjusted_net_recovery_paise for c in seed_oracle_comparisons)
        total_gap = max(0, total_oracle_incr_adj - total_rec_incr_adj)

        if total_oracle_incr_adj > 0:
            efficiency = round((total_rec_incr_adj / total_oracle_incr_adj) * 100.0, 2)
        else:
            efficiency = 100.0 if total_rec_incr_adj >= 0 else 0.0

        split_oracle_comp = OracleComparisonResult(
            oracle_gross_recovery_paise=total_oracle_gross,
            oracle_action_cost_paise=total_oracle_cost,
            oracle_churn_penalty_paise=total_oracle_churn_pen,
            oracle_adjusted_net_recovery_paise=total_oracle_adj_net,
            oracle_incremental_adjusted_net_recovery_paise=total_oracle_incr_adj,
            recoveryos_adjusted_net_recovery_paise=total_rec_adj_net,
            recoveryos_incremental_adjusted_net_recovery_paise=total_rec_incr_adj,
            recoveryos_vs_oracle_gap_paise=total_gap,
            recoveryos_oracle_efficiency_pct=efficiency,
            oracle_intervention_count=sum(c.oracle_intervention_count for c in seed_oracle_comparisons),
            oracle_actions_avoided_count=sum(c.oracle_actions_avoided_count for c in seed_oracle_comparisons),
            oracle_churn_count=sum(c.oracle_churn_count for c in seed_oracle_comparisons),
        )

        split_obj = BenchmarkDatasetSplit(
            split_name=split_name,
            seeds=seeds,
            scenarios_per_seed=num_scenarios_per_seed,
            total_scenarios=len(all_scenarios),
            policy_results=aggregated_policies,
            oracle_comparison=split_oracle_comp,
        )

        return split_obj, all_scenarios, seed_results_by_policy

    def run_benchmark(self) -> MultiSeedBenchmarkResult:
        """Executes the full multi-seed benchmark with Dev split, Holdout split, sensitivity, and failure tracing."""
        # 1. Evaluate Development Split
        dev_split, dev_scenarios, dev_seed_results = self.evaluate_split(
            split_name="development",
            seeds=self.config.dev_seeds,
            num_scenarios_per_seed=self.config.num_scenarios,
        )

        # 2. Evaluate Holdout Split (if enabled)
        holdout_split: Optional[BenchmarkDatasetSplit] = None
        holdout_scenarios: List[SimulatedScenario] = []

        if self.config.include_holdout and self.config.holdout_seeds:
            holdout_split, holdout_scenarios, _ = self.evaluate_split(
                split_name="holdout",
                seeds=self.config.holdout_seeds,
                num_scenarios_per_seed=self.config.num_scenarios,
            )

        # 3. Evaluate Combined Split
        all_seeds = list(self.config.dev_seeds)
        if self.config.include_holdout and self.config.holdout_seeds:
            all_seeds.extend(self.config.holdout_seeds)

        combined_split, combined_scenarios, combined_seed_results = self.evaluate_split(
            split_name="combined",
            seeds=all_seeds,
            num_scenarios_per_seed=self.config.num_scenarios,
        )

        # 4. Run Economic Sensitivity Analysis on the development or combined cohort
        sensitivity_scenarios = combined_scenarios if combined_scenarios else dev_scenarios
        sensitivity_result = self.sensitivity_analyzer.run_analysis(
            scenarios=sensitivity_scenarios,
            policies=self.get_default_policies(),
        )

        # 5. Extract Sample Failure Cases (High Regret, Unrecovered, Policy Blocked, Human Review)
        failure_cases = self._extract_failure_cases(combined_scenarios, combined_seed_results)

        timestamp_str = datetime.now(timezone.utc).isoformat()

        return MultiSeedBenchmarkResult(
            config=self.config,
            timestamp_iso=timestamp_str,
            dev_split=dev_split,
            holdout_split=holdout_split,
            combined_split=combined_split,
            sensitivity_analysis=sensitivity_result,
            failure_cases=failure_cases,
        )

    def _extract_failure_cases(
        self,
        scenarios: List[SimulatedScenario],
        seed_results_by_policy: Dict[str, List[EvaluationResult]],
        max_samples: int = 15,
    ) -> List[Dict[str, Any]]:
        """Identifies diagnostic failure cases and suboptimal decisions for audit inspection."""
        rec_evals = seed_results_by_policy.get("RECOVERYOS_DETERMINISTIC_V0", [])
        if not rec_evals:
            return []

        scenario_map = {s.scenario_id: s for s in scenarios}
        failure_list: List[Dict[str, Any]] = []

        for eval_res in rec_evals:
            for rec in eval_res.records:
                scen = scenario_map.get(rec.scenario_id)
                if not scen:
                    continue

                regret, oracle_net, chosen_net = RegretCalculator.compute_scenario_regret(
                    chosen_action=rec.chosen_action,
                    scenario=scen,
                    churn_penalty_paise=self.config.churn_penalty_paise,
                )

                # Flag scenario if: high regret (> ₹50), or customer churned, or unrecovered high value (> ₹2,000)
                is_high_regret = regret >= 5000  # >= ₹50
                is_churn_failure = rec.customer_churned and not rec.natural_customer_churned
                is_unrecovered_high_val = (not rec.recovered) and (rec.recovered_amount_paise == 0) and (scen.event.payment.amount >= 200_000 if scen.event.payment else False)

                if is_high_regret or is_churn_failure or is_unrecovered_high_val or rec.is_human_review or rec.is_policy_blocked:
                    failure_list.append({
                        "scenario_id": rec.scenario_id,
                        "failure_class": scen.failure_class.value,
                        "archetype": scen.archetype.value,
                        "amount_in_paise": scen.event.payment.amount if scen.event.payment else 0,
                        "chosen_action": rec.chosen_action.value,
                        "timing_window": rec.timing_window,
                        "recovered": rec.recovered,
                        "customer_churned": rec.customer_churned,
                        "governor_decision": rec.governor_decision,
                        "governor_reason_codes": rec.governor_reason_codes,
                        "regret_paise": regret,
                        "oracle_net_value_paise": oracle_net,
                        "chosen_net_value_paise": chosen_net,
                        "diagnosis_label": rec.predicted_diagnosis,
                        "diagnosis_correct": rec.diagnosis_correct,
                        "failure_type": "HIGH_REGRET" if is_high_regret else ("CHURN_INCIDENT" if is_churn_failure else ("HUMAN_REVIEW" if rec.is_human_review else "POLICY_BLOCKED")),
                    })

                if len(failure_list) >= max_samples:
                    break
            if len(failure_list) >= max_samples:
                break

        return failure_list
