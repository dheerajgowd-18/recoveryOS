"""Unit tests verifying that EvaluationExecutionMode is strictly enforced across EvaluationHarness, BenchmarkRunner, and AblationRunner."""
import json
from unittest.mock import MagicMock
import pytest

from evaluation.ablation import AblationPolicyCohort, AblationRunner
from evaluation.benchmark_runner import BenchmarkConfig, BenchmarkRunner
from evaluation.harness import EvaluationExecutionMode, EvaluationHarness
from evaluation.policies import AgenticGraphRecoveryPolicy, LLMDrivenRecoveryPolicy
from intelligence.context import ObservableRecoveryContext
from intelligence.providers.llm_provider import LLMDiagnosisProvider
from intelligence.providers.strategy_provider import LLMStrategyProvider
from intelligence.replay_cache import LLMReplayCache
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from simulator.config import SimulatedActionType, SimulatorConfig
from simulator.generator import Simulator


@pytest.fixture
def sample_scenarios():
    sim = Simulator()
    return sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=3))


class TestEvaluationExecutionModeEnforcement:
    """Verifies that EvaluationExecutionMode controls provider configuration and runtime behavior."""

    def test_offline_replay_mode_prevents_live_network_calls(self, sample_scenarios):
        """In OFFLINE_REPLAY mode, providers must NOT invoke live HTTP completions."""
        harness = EvaluationHarness(mode=EvaluationExecutionMode.OFFLINE_REPLAY)
        policy = LLMDrivenRecoveryPolicy()
        
        # Policy diagnosis provider is an LLMDiagnosisProvider
        res = harness.evaluate_policy(policy, sample_scenarios)
        
        # Must have offline_replay_only = True
        assert policy.diagnosis_provider.offline_replay_only is True
        assert policy.diagnosis_provider.strict_no_fallback is False
        assert policy.diagnosis_provider.llm_calls == 0  # Zero live network calls
        assert res.metrics.deterministic_fallback_count >= 0

    def test_live_llm_mode_allows_live_calls_and_tracks_telemetry(self, sample_scenarios):
        """In LIVE_LLM mode, live provider calls are executed and telemetry tracked."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content=json.dumps({
                            "diagnosis_label": "transient_gateway_failure",
                            "confidence": 0.90,
                            "evidence_codes": ["OBS_GATEWAY_TIMEOUT"],
                            "uncertainties": [],
                            "recommended_candidate_actions": ["retry_later"],
                            "recommended_timing_hint": "delay_2h",
                            "human_review_required": False,
                            "abstain_recommended": False,
                            "rationale": "Live mock diagnosis",
                        })
                    )
                )
            ]
        )
        provider = LLMDiagnosisProvider(api_key="mock_live_key", client=mock_client, replay_cache=LLMReplayCache())
        policy = LLMDrivenRecoveryPolicy(diagnosis_provider=provider)

        harness = EvaluationHarness(mode=EvaluationExecutionMode.LIVE_LLM)
        res = harness.evaluate_policy(policy, sample_scenarios)

        assert provider.offline_replay_only is False
        assert provider.strict_no_fallback is False
        assert provider.llm_calls > 0
        assert provider.llm_successes > 0
        assert res.metrics.diagnosis_source_counts.get("llm_structured", 0) > 0

    def test_strict_no_fallback_mode_raises_on_cache_miss_or_failure(self, sample_scenarios):
        """In STRICT_NO_FALLBACK mode, missing API key or cache miss MUST raise RuntimeError without fallback."""
        harness = EvaluationHarness(mode=EvaluationExecutionMode.STRICT_NO_FALLBACK)
        provider = LLMDiagnosisProvider(api_key="", client=None, replay_cache=LLMReplayCache())
        policy = LLMDrivenRecoveryPolicy(diagnosis_provider=provider)

        with pytest.raises(RuntimeError, match="Strict LLM execution failed"):
            harness.evaluate_policy(policy, sample_scenarios)

    def test_agentic_policy_inherits_strict_mode_in_harness(self, sample_scenarios):
        """AgenticGraphRecoveryPolicy diagnosis and strategy providers inherit strict_no_fallback in STRICT_NO_FALLBACK mode."""
        harness = EvaluationHarness(mode=EvaluationExecutionMode.STRICT_NO_FALLBACK)
        policy = AgenticGraphRecoveryPolicy()
        policy.diagnosis_agent.provider = LLMDiagnosisProvider(api_key="", client=None, replay_cache=LLMReplayCache())
        policy.strategy_agent.provider = LLMStrategyProvider(api_key="", client=None, replay_cache=LLMReplayCache())

        with pytest.raises(RuntimeError, match="Strict LLM execution failed"):
            harness.evaluate_policy(policy, sample_scenarios)

    def test_benchmark_runner_propagates_execution_mode(self):
        """BenchmarkRunner correctly initializes EvaluationHarness with configured execution mode."""
        cfg = BenchmarkConfig(
            num_scenarios=2,
            dev_seeds=[42],
            holdout_seeds=[],
            include_holdout=False,
            execution_mode=EvaluationExecutionMode.OFFLINE_REPLAY,
        )
        runner = BenchmarkRunner(config=cfg)
        assert runner.harness.mode == EvaluationExecutionMode.OFFLINE_REPLAY

    def test_ablation_runner_propagates_execution_mode(self):
        """AblationRunner propagates STRICT_NO_FALLBACK to EvaluationHarness."""
        runner = AblationRunner(mode=EvaluationExecutionMode.STRICT_NO_FALLBACK)
        assert runner.harness.mode == EvaluationExecutionMode.STRICT_NO_FALLBACK
        assert runner.strict_no_fallback is True
