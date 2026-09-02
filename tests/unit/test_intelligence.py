"""Unit tests for ObservableRecoveryContext, StructuredDiagnosis, and Diagnosis Providers."""
import pytest

from evaluation.harness import EvaluationHarness
from evaluation.policies import (
    AlwaysRetryPolicy,
    NoActionPolicy,
    ProbabilityOnlyPolicy,
    StaticRulePolicy,
)
from intelligence.context import ObservableContextBuilder, ObservableRecoveryContext
from intelligence.providers import DeterministicDiagnosisProvider, LLMDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.base import PolicyDecision
from policy.candidates import CandidateGenerator
from policy.config import DeterministicPolicyConfig
from policy.deterministic import DeterministicRecoveryPolicy
from policy.scoring import ExpectedValueScorer
from simulator.config import FailureClass, SimulatedActionType, SimulatorConfig
from simulator.generator import Simulator


@pytest.fixture
def simulator_batch():
    """Generates 50 reproducible scenarios."""
    sim = Simulator()
    return sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=50))


class TestObservableContextBoundary:
    """Validates that ObservableRecoveryContext strictly excludes all secret simulator truth."""

    def test_observable_context_excludes_hidden_fields(self, simulator_batch):
        for scenario in simulator_batch:
            ctx = ObservableContextBuilder.build_from_simulated_scenario(scenario)

            # Strict absence of latent/secret simulation artifacts
            assert hasattr(ctx, "failure_class") is False
            assert hasattr(ctx, "archetype") is False
            assert hasattr(ctx, "customer_archetype") is False
            assert hasattr(ctx, "hidden_outcomes") is False
            assert hasattr(ctx, "potential_outcomes") is False
            assert hasattr(ctx, "ground_truth") is False
            assert hasattr(ctx, "oracle_best_action") is False

    def test_observable_context_contains_required_evidence_fields(self, simulator_batch):
        scenario = simulator_batch[0]
        ctx = ObservableContextBuilder.build_from_simulated_scenario(scenario)

        assert isinstance(ctx, ObservableRecoveryContext)
        assert ctx.scenario_id == scenario.scenario_id
        assert ctx.amount_in_paise == scenario.event.payment.amount
        assert ctx.currency == "INR"
        assert ctx.attempt_count >= 1
        assert ctx.error_code is not None or ctx.error_reason is not None


class TestDeterministicDiagnosisProvider:
    """Validates transparent offline rule-based diagnosis inference."""

    def setup_method(self):
        self.provider = DeterministicDiagnosisProvider()

    def test_transient_gateway_inference(self):
        ctx = ObservableRecoveryContext(
            scenario_id="scen_gw",
            amount_in_paise=50000,
            error_code="GATEWAY_ERROR",
            error_source="gateway",
            error_reason="gateway_timeout",
        )
        diag = self.provider.diagnose_sync(ctx)
        assert diag.diagnosis_label == DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE
        assert diag.confidence >= 0.80
        assert "OBS_GATEWAY_ERROR" in diag.evidence_codes
        assert SimulatedActionType.RETRY_LATER in diag.recommended_candidate_actions
        assert diag.diagnosis_source == "deterministic_offline"

    def test_insufficient_funds_inference(self):
        ctx = ObservableRecoveryContext(
            scenario_id="scen_funds",
            amount_in_paise=50000,
            error_code="BAD_REQUEST_ERROR",
            error_source="bank",
            error_reason="insufficient_funds",
            error_description="Insufficient funds in card account",
        )
        diag = self.provider.diagnose_sync(ctx)
        assert diag.diagnosis_label == DiagnosisLabel.INSUFFICIENT_FUNDS
        assert diag.confidence >= 0.75
        assert "OBS_INSUFFICIENT_FUNDS_REASON" in diag.evidence_codes

    def test_expired_payment_method_inference(self):
        ctx = ObservableRecoveryContext(
            scenario_id="scen_exp",
            amount_in_paise=50000,
            error_code="BAD_REQUEST_ERROR",
            error_source="bank",
            error_reason="card_expired",
            error_description="Card is expired",
        )
        diag = self.provider.diagnose_sync(ctx)
        assert diag.diagnosis_label == DiagnosisLabel.EXPIRED_PAYMENT_METHOD
        assert diag.confidence >= 0.85
        assert SimulatedActionType.PAYMENT_LINK in diag.recommended_candidate_actions
        assert SimulatedActionType.RETRY_NOW not in diag.recommended_candidate_actions

    def test_unknown_or_ambiguous_evidence_produces_low_confidence(self):
        ctx = ObservableRecoveryContext(
            scenario_id="scen_unknown",
            amount_in_paise=50000,
            error_code="RANDOM_ERR_999",
            error_description="Unspecified bank glitch",
        )
        diag = self.provider.diagnose_sync(ctx)
        assert diag.diagnosis_label == DiagnosisLabel.UNKNOWN_FAILURE
        assert diag.confidence <= 0.50
        assert diag.abstain_recommended is True
        assert diag.human_review_required is True


class TestLLMDiagnosisProviderBoundary:
    """Validates schema enforcement and fail-safe fallback behavior."""

    def test_unavailable_llm_falls_back_safely(self):
        from intelligence.replay_cache import LLMReplayCache
        provider = LLMDiagnosisProvider(api_key="", replay_cache=LLMReplayCache())
        ctx = ObservableRecoveryContext(
            scenario_id="scen_llm_fallback",
            amount_in_paise=100000,
            error_code="GATEWAY_ERROR",
            error_source="gateway",
        )
        diag = provider.diagnose_sync(ctx)
        assert diag.diagnosis_label == DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE
        assert diag.diagnosis_source == "deterministic_fallback"
        assert provider.fallback_count == 1

    def test_valid_llm_json_parsed_correctly(self):
        provider = LLMDiagnosisProvider(api_key="mock_key")
        raw_json = """
        {
            "diagnosis_label": "insufficient_funds",
            "confidence": 0.88,
            "evidence_codes": ["OBS_INSUFFICIENT_FUNDS"],
            "uncertainties": [],
            "recommended_candidate_actions": ["retry_later", "payment_link"],
            "recommended_timing_hint": "delay_6h",
            "human_review_required": false,
            "abstain_recommended": false,
            "rationale": "LLM reasoned that error indicates temporary balance issue",
            "model_version": "gpt-4o-mini"
        }
        """
        diag = provider.parse_and_validate_response(raw_json)
        assert diag.diagnosis_label == DiagnosisLabel.INSUFFICIENT_FUNDS
        assert diag.confidence == 0.88
        assert diag.diagnosis_source == "llm_structured"

    def test_invalid_llm_json_rejected(self):
        provider = LLMDiagnosisProvider(api_key="mock_key")
        invalid_json = """
        {
            "diagnosis_label": "invalid_hallucinated_label",
            "confidence": 1.5,
            "rationale": "bad"
        }
        """
        with pytest.raises(ValueError) as exc:
            provider.parse_and_validate_response(invalid_json)
        assert "LLM output validation error" in str(exc.value)
        assert provider.invalid_output_count == 1


class TestPolicyAndNegativeUplift:
    """Validates negative uplift semantics and low-confidence abstention guards."""

    def test_negative_uplift_causes_abstention(self):
        config = DeterministicPolicyConfig(
            estimated_action_priors={
                DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE: {
                    SimulatedActionType.NO_ACTION: 0.80,  # Natural recovery is very high (80%)
                    SimulatedActionType.RETRY_NOW: 0.30,   # Bad retry action has lower recovery (30%)
                    SimulatedActionType.RETRY_LATER: 0.40,
                    SimulatedActionType.PAYMENT_LINK: 0.50,
                    SimulatedActionType.REMINDER: 0.20,
                }
            }
        )
        ctx = ObservableRecoveryContext(
            scenario_id="scen_neg_uplift",
            amount_in_paise=100000,
            error_code="GATEWAY_ERROR",
            error_source="gateway",
        )
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.90,
            rationale="High natural recovery environment",
            diagnosis_source="deterministic_offline",
        )
        # Verify negative uplift is computed by scorer
        scored = ExpectedValueScorer.score_candidate(ctx, diag, SimulatedActionType.RETRY_NOW, config)
        assert scored.expected_uplift < 0.0
        assert "NEGATIVE_INCREMENTAL_UPLIFT" in scored.reason_codes
        assert scored.expected_incremental_value_paise < 0

        # Verify policy abstains
        policy = DeterministicRecoveryPolicy(config=config)
        decision = policy.decide(ctx, diagnosis=diag)
        assert decision.action_type == SimulatedActionType.NO_ACTION
        assert "ABSTAIN_NEGATIVE_UPLIFT" in decision.reason_codes or "ABSTAIN_LOW_EXPECTED_VALUE" in decision.reason_codes

    def test_low_confidence_diagnosis_triggers_safe_abstention(self):
        policy = DeterministicRecoveryPolicy()
        ctx = ObservableRecoveryContext(
            scenario_id="scen_low_conf",
            amount_in_paise=100000,
            error_code="UNKNOWN_ERR",
        )
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.UNKNOWN_FAILURE,
            confidence=0.30,
            abstain_recommended=True,
            human_review_required=True,
            rationale="Ambiguous evidence",
            diagnosis_source="deterministic_offline",
        )
        decision = policy.decide(ctx, diagnosis=diag)
        assert decision.action_type == SimulatedActionType.NO_ACTION
        assert "ABSTAIN_LOW_CONFIDENCE_DIAGNOSIS" in decision.reason_codes or "ABSTAIN_UNKNOWN_DIAGNOSIS" in decision.reason_codes


class TestEvaluationAndBaselines:
    """Validates baseline policies and evaluator-side diagnosis accuracy calculation."""

    def test_baselines_execute_under_observable_context(self, simulator_batch):
        ctx = ObservableContextBuilder.build_from_simulated_scenario(simulator_batch[0])

        assert NoActionPolicy().decide(ctx).action_type == SimulatedActionType.NO_ACTION
        assert AlwaysRetryPolicy().decide(ctx).action_type == SimulatedActionType.RETRY_NOW
        assert StaticRulePolicy().decide(ctx).action_type in set(SimulatedActionType)
        assert ProbabilityOnlyPolicy().decide(ctx).action_type in set(SimulatedActionType)

    def test_evaluation_computes_diagnosis_accuracy(self, simulator_batch):
        harness = EvaluationHarness()
        policy = DeterministicRecoveryPolicy()

        result = harness.evaluate_policy(policy, simulator_batch)
        assert result.metrics.diagnosis_accuracy > 0.90
        assert "deterministic_offline" in result.metrics.diagnosis_source_counts
        assert result.metrics.actions_avoided_count >= 0
