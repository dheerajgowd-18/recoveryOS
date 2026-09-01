"""Unit tests for ObservableRecoveryContext, Candidate Generation, Scoring, and DeterministicRecoveryPolicy."""
import pytest

from evaluation.harness import EvaluationHarness, EvaluationResult
from evaluation.policies import PolicyDecision
from intelligence.context import ObservableContextBuilder, ObservableRecoveryContext
from intelligence.providers import DeterministicDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.candidates import CandidateGenerator
from policy.config import DeterministicPolicyConfig
from policy.deterministic import DeterministicRecoveryPolicy
from policy.public_view import PublicScenarioView
from policy.scoring import ExpectedValueScorer
from simulator.config import SimulatedActionType, SimulatorConfig
from simulator.generator import Simulator


@pytest.fixture
def standard_simulator_batch():
    """Generates a standard reproducible test batch of 100 scenarios with seed 42."""
    sim = Simulator()
    return sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=100))


class TestPublicScenarioViewBoundary:
    """Validates that PublicScenarioView / ObservableRecoveryContext strictly excludes latent variables and ground-truth counterfactuals."""

    def test_public_view_excludes_hidden_fields(self, standard_simulator_batch):
        for scenario in standard_simulator_batch:
            view = PublicScenarioView.from_simulated_scenario(scenario)

            # Strict absence of secret simulation artifacts and true failure class
            assert hasattr(view, "hidden_outcomes") is False
            assert hasattr(view, "archetype") is False
            assert hasattr(view, "customer_archetype") is False
            assert hasattr(view, "potential_outcomes") is False
            assert hasattr(view, "ground_truth") is False
            assert hasattr(view, "failure_class") is False

    def test_public_view_factory_produces_valid_model(self, standard_simulator_batch):
        scenario = standard_simulator_batch[0]
        view = PublicScenarioView.from_simulated_scenario(scenario)

        assert isinstance(view, ObservableRecoveryContext)
        assert view.scenario_id == scenario.scenario_id
        assert view.amount_in_paise == scenario.event.payment.amount
        assert view.currency == scenario.event.payment.currency
        assert view.attempt_count == 1
        assert view.error_code == scenario.event.payment.error_code


class TestCandidateGenerator:
    """Validates candidate action generation constraints."""

    def test_expired_payment_method_disallows_retries(self):
        config = DeterministicPolicyConfig()
        view = ObservableRecoveryContext(
            scenario_id="scen_expired_01",
            amount_in_paise=50000,
            attempt_count=1,
            error_code="BAD_REQUEST_ERROR",
            error_reason="card_expired",
        )
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.EXPIRED_PAYMENT_METHOD,
            confidence=0.90,
            rationale="Expired card",
        )

        candidates = CandidateGenerator.generate_candidates(view, diag, config)

        assert SimulatedActionType.NO_ACTION in candidates
        assert SimulatedActionType.PAYMENT_LINK in candidates
        assert SimulatedActionType.RETRY_NOW not in candidates
        assert SimulatedActionType.RETRY_LATER not in candidates

    def test_transient_gateway_candidates(self):
        config = DeterministicPolicyConfig(allow_immediate_retry=False)
        view = ObservableRecoveryContext(
            scenario_id="scen_gw_01",
            amount_in_paise=50000,
            attempt_count=1,
            error_code="GATEWAY_ERROR",
        )
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.85,
            rationale="Gateway timeout",
        )

        candidates = CandidateGenerator.generate_candidates(view, diag, config)
        assert SimulatedActionType.NO_ACTION in candidates
        assert SimulatedActionType.RETRY_LATER in candidates
        assert SimulatedActionType.RETRY_NOW not in candidates

    def test_attempt_limit_blocks_retries_for_insufficient_funds(self):
        config = DeterministicPolicyConfig(max_retry_attempts=3)
        view = ObservableRecoveryContext(
            scenario_id="scen_funds_01",
            amount_in_paise=50000,
            attempt_count=3,
            error_code="INSUFFICIENT_FUNDS",
        )
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.INSUFFICIENT_FUNDS,
            confidence=0.80,
            rationale="Insufficient balance",
        )

        candidates = CandidateGenerator.generate_candidates(view, diag, config)
        assert SimulatedActionType.RETRY_LATER not in candidates
        assert SimulatedActionType.PAYMENT_LINK in candidates
        assert SimulatedActionType.NO_ACTION in candidates


class TestExpectedValueScorer:
    """Validates proxy mathematical scoring and uplift calculations."""

    def test_scoring_no_action_has_zero_incremental_value(self):
        config = DeterministicPolicyConfig()
        view = ObservableRecoveryContext(
            scenario_id="scen_score_01",
            amount_in_paise=100000,
            attempt_count=1,
        )
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.85,
            rationale="Gateway issue",
        )

        scored = ExpectedValueScorer.score_candidate(view, diag, SimulatedActionType.NO_ACTION, config)
        assert scored.expected_uplift == 0.0
        assert scored.expected_incremental_value_paise == 0
        assert scored.action_cost_paise == 0
        assert scored.expected_net_value_paise == 0

    def test_scoring_positive_uplift_action(self):
        config = DeterministicPolicyConfig()
        view = ObservableRecoveryContext(
            scenario_id="scen_score_02",
            amount_in_paise=100000,  # ₹1,000
            attempt_count=1,
        )
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.85,
            rationale="Gateway issue",
        )

        # Prior: RETRY_LATER=0.80, NO_ACTION=0.25 -> uplift = 0.55 -> incremental = 55000 paise
        # Cost = 20 paise -> net = 54980 paise
        scored = ExpectedValueScorer.score_candidate(view, diag, SimulatedActionType.RETRY_LATER, config)
        assert scored.expected_uplift == pytest.approx(0.55, abs=1e-4)
        assert scored.expected_incremental_value_paise == 55000
        assert scored.action_cost_paise == 20
        assert scored.expected_net_value_paise == 54980


class TestDeterministicRecoveryPolicy:
    """Validates decision-making of the RecoveryOS policy baseline."""

    def test_deterministic_policy_returns_valid_actions(self, standard_simulator_batch):
        policy = DeterministicRecoveryPolicy()
        allowed_actions = set(SimulatedActionType)

        for scenario in standard_simulator_batch:
            view = ObservableContextBuilder.build_from_simulated_scenario(scenario)
            decision = policy.decide(view)

            assert isinstance(decision, PolicyDecision)
            assert decision.action_type in allowed_actions
            assert decision.policy_name == "RECOVERYOS_DETERMINISTIC_V0"
            assert len(decision.reason_codes) > 0

    def test_expired_payment_method_does_not_retry(self):
        policy = DeterministicRecoveryPolicy()
        view = ObservableRecoveryContext(
            scenario_id="scen_exp_test",
            amount_in_paise=99900,
            attempt_count=1,
            error_code="BAD_REQUEST_ERROR",
            error_reason="card_expired",
            error_description="Expired card",
        )

        decision = policy.decide(view)
        assert decision.action_type not in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER)
        assert decision.action_type == SimulatedActionType.PAYMENT_LINK

    def test_transient_gateway_prefers_retry_later(self):
        policy = DeterministicRecoveryPolicy()
        view = ObservableRecoveryContext(
            scenario_id="scen_gw_test",
            amount_in_paise=50000,
            attempt_count=1,
            error_code="GATEWAY_ERROR",
            error_source="gateway",
            error_reason="gateway_timeout",
        )

        decision = policy.decide(view)
        assert decision.action_type == SimulatedActionType.RETRY_LATER

    def test_attempt_limit_causes_abstention_when_retries_blocked_and_links_low_value(self):
        # Configure high min expected value threshold to force abstention when retries blocked
        config = DeterministicPolicyConfig(
            max_retry_attempts=2,
            min_expected_net_value_paise=100000,  # ₹1,000 net value threshold
        )
        policy = DeterministicRecoveryPolicy(config=config)
        view = ObservableRecoveryContext(
            scenario_id="scen_limit_test",
            amount_in_paise=50000,  # ₹500
            attempt_count=2,
            error_code="INSUFFICIENT_FUNDS",
            error_reason="insufficient_funds",
        )

        decision = policy.decide(view)
        assert decision.action_type == SimulatedActionType.NO_ACTION
        assert "ABSTAIN_LOW_EXPECTED_VALUE" in decision.reason_codes

    def test_low_expected_value_causes_abstention(self):
        # Transaction of ₹1.00 (100 paise) where payment link costs 100 paise -> negative or tiny net value
        config = DeterministicPolicyConfig(min_expected_net_value_paise=5000)
        policy = DeterministicRecoveryPolicy(config=config)
        view = ObservableRecoveryContext(
            scenario_id="scen_low_val",
            amount_in_paise=100,
            attempt_count=1,
            error_code="BAD_REQUEST_ERROR",
            error_reason="card_expired",
        )

        decision = policy.decide(view)
        assert decision.action_type == SimulatedActionType.NO_ACTION
        assert "ABSTAIN_LOW_EXPECTED_VALUE" in decision.reason_codes

    def test_determinism_same_input_yields_same_decision(self, standard_simulator_batch):
        policy = DeterministicRecoveryPolicy()
        for scenario in standard_simulator_batch[:20]:
            view = ObservableContextBuilder.build_from_simulated_scenario(scenario)
            dec_1 = policy.decide(view)
            dec_2 = policy.decide(view)
            assert dec_1.model_dump() == dec_2.model_dump()

    def test_harness_evaluates_recoveryos_deterministic_policy(self, standard_simulator_batch):
        harness = EvaluationHarness()
        policy = DeterministicRecoveryPolicy()

        result = harness.evaluate_policy(policy, standard_simulator_batch)
        assert isinstance(result, EvaluationResult)
        metrics = result.metrics

        assert metrics.policy_name == "RECOVERYOS_DETERMINISTIC_V0"
        assert metrics.total_scenarios == 100
        assert metrics.total_interventions > 0
        assert metrics.gross_recovered_amount_paise > metrics.natural_recovered_amount_paise
        assert metrics.incremental_recovered_amount_paise > 0
        assert metrics.net_recovered_amount_paise > 0
