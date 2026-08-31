"""Unit tests for RecoveryOS Evaluation Harness, Baseline Policies, and Metrics."""
import pytest

from evaluation.harness import EvaluationHarness, EvaluationResult
from evaluation.metrics import EvaluationMetrics, MetricCalculator, ScenarioEvaluationRecord
from evaluation.policies import (
    AlwaysRetryPolicy,
    NoActionPolicy,
    PolicyDecision,
    ProbabilityOnlyPolicy,
    StaticRulePolicy,
)
from policy.public_view import PublicScenarioView
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType, SimulatorConfig
from simulator.generator import Simulator
from simulator.outcomes import ActionOutcome


@pytest.fixture
def standard_simulator_batch():
    """Generates a standard reproducible test batch of 100 scenarios with seed 42."""
    sim = Simulator()
    return sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=100))


class TestBaselinePolicies:
    """Validates decision logic and domain boundaries for all baseline policies."""

    def test_no_action_policy_always_abstains(self, standard_simulator_batch):
        policy = NoActionPolicy()
        assert policy.name == "baseline_0_no_action"

        for scenario in standard_simulator_batch:
            view = PublicScenarioView.from_simulated_scenario(scenario)
            decision = policy.decide(view)
            assert isinstance(decision, PolicyDecision)
            assert decision.action_type == SimulatedActionType.NO_ACTION
            assert decision.confidence == 1.0
            assert decision.policy_name == "baseline_0_no_action"

    def test_always_retry_policy_always_retries(self, standard_simulator_batch):
        policy = AlwaysRetryPolicy()
        assert policy.name == "baseline_1_always_retry"

        for scenario in standard_simulator_batch:
            view = PublicScenarioView.from_simulated_scenario(scenario)
            decision = policy.decide(view)
            assert isinstance(decision, PolicyDecision)
            assert decision.action_type == SimulatedActionType.RETRY_NOW
            assert decision.confidence == 1.0
            assert decision.policy_name == "baseline_1_always_retry"

    def test_static_rule_policy_branching(self, standard_simulator_batch):
        policy = StaticRulePolicy()
        assert policy.name == "baseline_2_static_rules"

        for scenario in standard_simulator_batch:
            view = PublicScenarioView.from_simulated_scenario(scenario)
            decision = policy.decide(view)
            assert isinstance(decision, PolicyDecision)
            assert decision.policy_name == "baseline_2_static_rules"

            error_code = view.failure_code
            if error_code == "BAD_REQUEST_ERROR":
                assert decision.action_type == SimulatedActionType.PAYMENT_LINK
            elif error_code == "GATEWAY_ERROR":
                assert decision.action_type == SimulatedActionType.RETRY_NOW
            elif error_code == "INSUFFICIENT_FUNDS":
                assert decision.action_type == SimulatedActionType.RETRY_LATER

    def test_probability_only_policy_selection(self, standard_simulator_batch):
        policy = ProbabilityOnlyPolicy()
        assert policy.name == "baseline_3_probability_only"

        for scenario in standard_simulator_batch:
            view = PublicScenarioView.from_simulated_scenario(scenario)
            decision = policy.decide(view)
            assert isinstance(decision, PolicyDecision)
            assert decision.policy_name == "baseline_3_probability_only"
            assert decision.confidence > 0.0

            error_code = view.failure_code
            if error_code == "BAD_REQUEST_ERROR":
                assert decision.action_type == SimulatedActionType.PAYMENT_LINK
            elif error_code == "GATEWAY_ERROR":
                assert decision.action_type == SimulatedActionType.RETRY_NOW
            elif error_code == "INSUFFICIENT_FUNDS":
                assert decision.action_type == SimulatedActionType.RETRY_LATER


class TestEvaluationHarness:
    """Validates the batch evaluation harness and metric calculation engine."""

    def test_baseline_0_no_action_metrics(self, standard_simulator_batch):
        harness = EvaluationHarness()
        policy = NoActionPolicy()
        result = harness.evaluate_policy(policy, standard_simulator_batch)

        assert isinstance(result, EvaluationResult)
        metrics = result.metrics

        # Baseline 0 core assertions:
        # Gross Recovery == Natural Recovery
        assert metrics.gross_recovered_amount_paise == metrics.natural_recovered_amount_paise
        # Incremental Recovery is exactly 0
        assert metrics.incremental_recovered_amount_paise == 0
        # Intervention count is 0
        assert metrics.total_interventions == 0
        assert metrics.intervention_rate == 0.0
        # Action cost is 0
        assert metrics.total_action_cost_paise == 0
        # Net Recovery == Gross Recovery
        assert metrics.net_recovered_amount_paise == metrics.gross_recovered_amount_paise
        # Incremental recovery rate is 0.0
        assert metrics.incremental_recovery_rate == 0.0
        assert len(result.records) == 100

    def test_baseline_1_always_retry_metrics(self, standard_simulator_batch):
        harness = EvaluationHarness()
        policy = AlwaysRetryPolicy()
        result = harness.evaluate_policy(policy, standard_simulator_batch)

        metrics = result.metrics

        # Baseline 1 core assertions:
        # Intervention count equals total scenarios (all failed payments triggered retry)
        assert metrics.total_interventions == 100
        assert metrics.intervention_rate == 1.0
        # Action cost > 0 (each retry costs 20 paise = 2000 paise for 100 attempts)
        assert metrics.total_action_cost_paise == 100 * 20
        # Net Recovery = Gross Recovery - Total Cost
        assert metrics.net_recovered_amount_paise == metrics.gross_recovered_amount_paise - metrics.total_action_cost_paise
        # Incremental Recovery = Gross Recovery - Natural Recovery
        assert metrics.incremental_recovered_amount_paise == metrics.gross_recovered_amount_paise - metrics.natural_recovered_amount_paise

    def test_harness_determinism_same_batch(self, standard_simulator_batch):
        """Assures evaluating the same batch twice yields bit-identical metrics."""
        harness = EvaluationHarness()
        policy = StaticRulePolicy()

        run_1 = harness.evaluate_policy(policy, standard_simulator_batch)
        run_2 = harness.evaluate_policy(policy, standard_simulator_batch)

        assert run_1.metrics.model_dump() == run_2.metrics.model_dump()
        assert len(run_1.records) == len(run_2.records)
        for r1, r2 in zip(run_1.records, run_2.records):
            assert r1.model_dump() == r2.model_dump()

    def test_empty_scenario_batch_graceful_handling(self):
        harness = EvaluationHarness()
        policy = NoActionPolicy()
        result = harness.evaluate_policy(policy, [])

        metrics = result.metrics
        assert metrics.total_scenarios == 0
        assert metrics.total_interventions == 0
        assert metrics.gross_recovered_amount_paise == 0
        assert metrics.natural_recovered_amount_paise == 0
        assert metrics.net_recovered_amount_paise == 0
        assert len(result.records) == 0

    def test_evaluate_all_comparative_consistency(self, standard_simulator_batch):
        harness = EvaluationHarness()
        policies = [
            NoActionPolicy(),
            AlwaysRetryPolicy(),
            StaticRulePolicy(),
            ProbabilityOnlyPolicy(),
        ]

        results = harness.evaluate_all(policies, standard_simulator_batch)

        assert len(results) == 4
        assert "baseline_0_no_action" in results
        assert "baseline_1_always_retry" in results
        assert "baseline_2_static_rules" in results
        assert "baseline_3_probability_only" in results

        # All policies must evaluate against identical natural baseline
        natural_baseline_amount = results["baseline_0_no_action"].metrics.natural_recovered_amount_paise
        for name, res in results.items():
            assert res.metrics.natural_recovered_amount_paise == natural_baseline_amount
            assert res.metrics.total_scenarios == 100
            assert res.metrics.gross_recovered_amount_paise - res.metrics.natural_recovered_amount_paise == res.metrics.incremental_recovered_amount_paise
            assert res.metrics.gross_recovered_amount_paise - res.metrics.total_action_cost_paise == res.metrics.net_recovered_amount_paise


class TestMetricCalculatorUnits:
    """Direct unit tests for MetricCalculator arithmetic rules."""

    def test_calculator_record_creation(self):
        chosen_outcome = ActionOutcome(
            action_type=SimulatedActionType.PAYMENT_LINK,
            recovered=True,
            recovery_delay_seconds=3600,
            recovered_amount_paise=50000,
            customer_churned=False,
            fatigue_score=0.4,
            action_cost_paise=100,
        )
        natural_outcome = ActionOutcome(
            action_type=SimulatedActionType.NO_ACTION,
            recovered=False,
            recovery_delay_seconds=0,
            recovered_amount_paise=0,
            customer_churned=False,
            fatigue_score=0.0,
            action_cost_paise=0,
        )

        record = MetricCalculator.create_record(
            scenario_id="scen_test_01",
            policy_name="test_policy",
            chosen_action=SimulatedActionType.PAYMENT_LINK,
            chosen_outcome=chosen_outcome,
            natural_outcome=natural_outcome,
        )

        assert record.scenario_id == "scen_test_01"
        assert record.is_intervention is True
        assert record.recovered is True
        assert record.recovered_amount_paise == 50000
        assert record.action_cost_paise == 100
        assert record.net_value_paise == 49900
        assert record.natural_recovered is False
        assert record.natural_recovered_amount_paise == 0
        assert record.incremental_amount_paise == 50000
