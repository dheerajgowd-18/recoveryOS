"""Unit tests verifying truthful provider provenance tracking and strict evaluation modes."""
from unittest.mock import MagicMock
import pytest

from evaluation.ablation import AblationPolicyCohort, AblationRunner
from evaluation.harness import EvaluationExecutionMode, EvaluationHarness
from evaluation.policies import (
    AgenticGraphRecoveryPolicy,
    DeterministicRecoveryPolicy,
    LLMDrivenRecoveryPolicy,
)
from intelligence.context import ObservableRecoveryContext
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.providers.groq_provider import GroqLLMDiagnosisProvider
from intelligence.providers.llm_provider import LLMDiagnosisProvider
from intelligence.providers.strategy_provider import (
    DeterministicStrategyProvider,
    LLMStrategyProvider,
)
from intelligence.replay_cache import LLMReplayCache
from intelligence.schemas import DiagnosisLabel, StrategyCandidateProposal, StrategyProposal, StructuredDiagnosis
from simulator.config import SimulatorConfig, SimulatedActionType
from simulator.generator import Simulator


@pytest.fixture
def sample_context() -> ObservableRecoveryContext:
    sim = Simulator()
    scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=1))
    from intelligence.context import ObservableContextBuilder
    return ObservableContextBuilder.build_from_simulated_scenario(scenarios[0])


def test_variant_a_deterministic_provenance(sample_context: ObservableRecoveryContext):
    """Variant A must report deterministic_offline for both diagnosis and strategy with 0 fallbacks."""
    cohort = AblationPolicyCohort.get_cohort()
    policy_a = cohort[0]
    assert policy_a.name == "A_DETERMINISTIC_DIAG_AND_STRAT"

    decision = policy_a.decide(sample_context)
    assert decision.diagnosis is not None
    assert decision.diagnosis.diagnosis_source == "deterministic_offline"
    assert decision.strategy_source == "deterministic_offline"

    # Harness evaluation check
    harness = EvaluationHarness()
    sim = Simulator()
    scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=5))
    res = harness.evaluate_policy(policy_a, scenarios)

    assert res.metrics.diagnosis_source_counts.get("deterministic_offline") == 5
    assert res.metrics.strategy_source_counts.get("deterministic_offline") == 5
    assert res.metrics.diagnosis_fallback_count == 0
    assert res.metrics.strategy_fallback_count == 0


def test_variant_b_mocked_llm_provenance(sample_context: ObservableRecoveryContext):
    """Variant B with a live/mocked LLM must report llm_structured for diagnosis and deterministic_offline for strategy."""
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = '{"diagnosis_label": "transient_gateway_failure", "confidence": 0.95, "rationale": "Gateway timeout", "evidence_codes": ["GATEWAY_TIMEOUT"], "uncertainties": [], "abstain_recommended": false}'
    mock_client.chat.completions.create.return_value.choices = [mock_choice]

    mock_diag_provider = LLMDiagnosisProvider(api_key="gsk_test_mock", client=mock_client)
    policy_b = LLMDrivenRecoveryPolicy(diagnosis_provider=mock_diag_provider)
    policy_b.name = "B_LLM_DIAG_DETERMINISTIC_STRAT"

    decision = policy_b.decide(sample_context)
    assert decision.diagnosis is not None
    assert decision.diagnosis.diagnosis_source == "llm_structured"
    assert decision.strategy_source == "deterministic_offline"

    harness = EvaluationHarness()
    sim = Simulator()
    scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=3))
    res = harness.evaluate_policy(policy_b, scenarios)

    assert res.metrics.diagnosis_live_call_count + res.metrics.diagnosis_cache_hit_count == 3
    assert res.metrics.strategy_source_counts.get("deterministic_offline") == 3
    assert res.metrics.diagnosis_fallback_count == 0
    assert res.metrics.strategy_fallback_count == 0


def test_variant_c_mocked_llm_provenance(sample_context: ObservableRecoveryContext):
    """Variant C with mocked LLM must report llm_structured for both diagnosis and strategy."""
    mock_client_diag = MagicMock()
    mock_choice_diag = MagicMock()
    mock_choice_diag.message.content = '{"diagnosis_label": "insufficient_funds", "confidence": 0.92, "rationale": "Soft balance decline", "evidence_codes": ["LOW_BALANCE"], "uncertainties": [], "abstain_recommended": false}'
    mock_client_diag.chat.completions.create.return_value.choices = [mock_choice_diag]

    mock_client_strat = MagicMock()
    mock_choice_strat = MagicMock()
    mock_choice_strat.message.content = '{"primary_recommendation": "payment_link", "strategic_summary": "Issue link", "proposals": [{"action_type": "payment_link", "mechanism": "payment_link", "confidence": 0.88, "rationale": "High conversion rail", "is_abstention": false, "preferred_timing_direction": "immediate", "why_better_than_abstain": "Recovers funds", "why_alternative_inferior": "Direct retry fails", "supporting_evidence": [], "risk_notes": []}]}'
    mock_client_strat.chat.completions.create.return_value.choices = [mock_choice_strat]

    policy_c = AgenticGraphRecoveryPolicy()
    policy_c.diagnosis_agent.provider = LLMDiagnosisProvider(api_key="gsk_test", client=mock_client_diag)
    policy_c.strategy_agent.provider = LLMStrategyProvider(api_key="gsk_test", client=mock_client_strat)
    policy_c.name = "C_LLM_DIAG_AND_LLM_STRAT"

    decision = policy_c.decide(sample_context)
    assert decision.diagnosis is not None
    assert decision.diagnosis.diagnosis_source == "llm_structured"
    assert decision.strategy_source == "llm_structured"

    harness = EvaluationHarness()
    sim = Simulator()
    scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=2))
    res = harness.evaluate_policy(policy_c, scenarios)

    assert res.metrics.diagnosis_live_call_count + res.metrics.diagnosis_cache_hit_count == 2
    assert res.metrics.strategy_live_call_count + res.metrics.strategy_cache_hit_count == 2
    assert res.metrics.diagnosis_fallback_count == 0
    assert res.metrics.strategy_fallback_count == 0


def test_strict_no_fallback_raises_error_when_offline(sample_context: ObservableRecoveryContext):
    """In STRICT_NO_FALLBACK mode, missing API key must raise RuntimeError rather than silently falling back."""
    strict_diag = LLMDiagnosisProvider(api_key=None, client=None, strict_no_fallback=True)
    with pytest.raises(RuntimeError, match="Strict LLM execution failed in LLMDiagnosisProvider"):
        strict_diag.diagnose_sync(sample_context)

    fake_diag = StructuredDiagnosis(
        diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
        confidence=0.9,
        rationale="Test",
        diagnosis_source="llm_structured",
        model_version="test",
    )
    strict_strat = LLMStrategyProvider(api_key=None, client=None, strict_no_fallback=True)
    with pytest.raises(RuntimeError, match="Strict LLM execution failed in LLMStrategyProvider"):
        strict_strat.propose_sync(sample_context, fake_diag)


def test_replay_cache_provenance_marking(sample_context: ObservableRecoveryContext):
    """Responses retrieved from replay cache must be explicitly marked cached_llm."""
    cache = LLMReplayCache()
    fp_diag = cache.compute_fingerprint("model-v1", "diag-prompt-v1", sample_context.model_dump(exclude_none=True))
    cache.set_diagnosis(
        fp_diag,
        StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.9,
            rationale="Cached reason",
            diagnosis_source="llm_structured",
            model_version="model-v1",
        ),
    )

    provider = LLMDiagnosisProvider(
        api_key=None,
        client=None,
        model_name="model-v1",
        replay_cache=cache,
    )
    provider.prompt_version = "diag-prompt-v1"

    diag = provider.diagnose_sync(sample_context)
    assert diag.diagnosis_source == "cached_llm"
    assert provider.cached_hits == 1
    assert provider.fallback_count == 0
