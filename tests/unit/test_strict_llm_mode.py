"""Unit tests verifying strict LLM no-fallback mode and provenance integrity across sync and async execution paths."""
import json
from unittest.mock import AsyncMock, MagicMock
import pytest

from intelligence.context import ObservableRecoveryContext
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.providers.llm_provider import LLMDiagnosisProvider
from intelligence.providers.strategy_provider import DeterministicStrategyProvider, LLMStrategyProvider
from intelligence.replay_cache import LLMReplayCache
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from simulator.config import SimulatedActionType


@pytest.fixture
def sample_context():
    return ObservableRecoveryContext(
        scenario_id="scen_strict_01",
        payment_id="pay_strict_01",
        customer_id="cust_strict_01",
        amount_in_paise=350000,
        currency="INR",
        payment_method="card",
        attempt_count=1,
        error_code="GATEWAY_TIMEOUT",
        error_description="Bank gateway timed out during processing",
        error_source="gateway",
        error_reason="gateway_timeout",
    )


@pytest.fixture
def sample_diagnosis():
    return StructuredDiagnosis(
        diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
        confidence=0.88,
        evidence_codes=["OBS_GATEWAY_TIMEOUT"],
        uncertainties=[],
        recommended_candidate_actions=[SimulatedActionType.RETRY_LATER, SimulatedActionType.RETRY_NOW],
        recommended_timing_hint="delay_2h",
        human_review_required=False,
        abstain_recommended=False,
        rationale="Transient gateway timeout observed.",
        diagnosis_source="llm_structured",
        model_version="groq-openai/gpt-oss-120b",
    )


class TestStrictLLMDiagnosisProvider:
    """Proves that strict_no_fallback=True guarantees hard failure without silent fallback across all error conditions."""

    def test_strict_sync_diagnosis_fails_on_missing_credentials(self, sample_context):
        provider = LLMDiagnosisProvider(api_key="", client=None, replay_cache=LLMReplayCache(), strict_no_fallback=True)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*No API key"):
            provider.diagnose_sync(sample_context)

    @pytest.mark.anyio
    async def test_strict_async_diagnosis_fails_on_missing_credentials(self, sample_context):
        provider = LLMDiagnosisProvider(api_key="", client=None, replay_cache=LLMReplayCache(), strict_no_fallback=True)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*No API key"):
            await provider.diagnose(sample_context)

    def test_strict_sync_diagnosis_fails_on_timeout(self, sample_context):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("Request timed out after 5.0s")
        provider = LLMDiagnosisProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*TimeoutError"):
            provider.diagnose_sync(sample_context)

    @pytest.mark.anyio
    async def test_strict_async_diagnosis_fails_on_timeout(self, sample_context):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("Async request timed out")
        provider = LLMDiagnosisProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*TimeoutError"):
            await provider.diagnose(sample_context)

    def test_strict_sync_diagnosis_fails_on_malformed_json(self, sample_context):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="INVALID_NOT_JSON {{{"))]
        )
        provider = LLMDiagnosisProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*ValueError"):
            provider.diagnose_sync(sample_context)

    @pytest.mark.anyio
    async def test_strict_async_diagnosis_fails_on_malformed_json(self, sample_context):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="INVALID_NOT_JSON {{{"))]
        )
        provider = LLMDiagnosisProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*ValueError"):
            await provider.diagnose(sample_context)

    def test_strict_sync_diagnosis_fails_on_schema_validation_error(self, sample_context):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"diagnosis_label": "invalid_unknown_label_xyz"})))]
        )
        provider = LLMDiagnosisProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*ValueError"):
            provider.diagnose_sync(sample_context)

    @pytest.mark.anyio
    async def test_strict_async_diagnosis_fails_on_schema_validation_error(self, sample_context):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"diagnosis_label": "invalid_unknown_label_xyz"})))]
        )
        provider = LLMDiagnosisProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*ValueError"):
            await provider.diagnose(sample_context)


class TestStrictLLMStrategyProvider:
    """Proves that LLMStrategyProvider enforces hard failure when strict_no_fallback=True."""

    def test_strict_sync_strategy_fails_on_missing_credentials(self, sample_context, sample_diagnosis):
        provider = LLMStrategyProvider(api_key="", client=None, replay_cache=LLMReplayCache(), strict_no_fallback=True)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*No API key"):
            provider.propose_sync(sample_context, sample_diagnosis)

    @pytest.mark.anyio
    async def test_strict_async_strategy_fails_on_missing_credentials(self, sample_context, sample_diagnosis):
        provider = LLMStrategyProvider(api_key="", client=None, replay_cache=LLMReplayCache(), strict_no_fallback=True)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*No API key"):
            await provider.propose(sample_context, sample_diagnosis)

    def test_strict_sync_strategy_fails_on_timeout(self, sample_context, sample_diagnosis):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("Strategy API call timed out")
        provider = LLMStrategyProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*TimeoutError"):
            provider.propose_sync(sample_context, sample_diagnosis)

    @pytest.mark.anyio
    async def test_strict_async_strategy_fails_on_timeout(self, sample_context, sample_diagnosis):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("Strategy async API call timed out")
        provider = LLMStrategyProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*TimeoutError"):
            await provider.propose(sample_context, sample_diagnosis)

    def test_strict_sync_strategy_fails_on_malformed_json(self, sample_context, sample_diagnosis):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="MALFORMED_NON_JSON"))]
        )
        provider = LLMStrategyProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*ValueError"):
            provider.propose_sync(sample_context, sample_diagnosis)

    @pytest.mark.anyio
    async def test_strict_async_strategy_fails_on_malformed_json(self, sample_context, sample_diagnosis):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="MALFORMED_NON_JSON"))]
        )
        provider = LLMStrategyProvider(api_key="mock_key", client=mock_client, replay_cache=LLMReplayCache(), strict_no_fallback=True, max_retries=0)
        with pytest.raises(RuntimeError, match="Strict LLM execution failed.*ValueError"):
            await provider.propose(sample_context, sample_diagnosis)


class TestNonStrictFallbackAndProvenance:
    """Verifies that non-strict mode preserves safe fallback behavior and accurate provenance tags."""

    def test_non_strict_sync_diagnosis_falls_back_safely(self, sample_context):
        provider = LLMDiagnosisProvider(api_key="", client=None, replay_cache=LLMReplayCache(), strict_no_fallback=False)
        diag = provider.diagnose_sync(sample_context)
        assert diag.diagnosis_source == "deterministic_fallback"
        assert "FALLBACK_NO_API_KEY" in diag.evidence_codes
        assert provider.fallback_count == 1

    @pytest.mark.anyio
    async def test_non_strict_async_diagnosis_falls_back_safely(self, sample_context):
        provider = LLMDiagnosisProvider(api_key="", client=None, replay_cache=LLMReplayCache(), strict_no_fallback=False)
        diag = await provider.diagnose(sample_context)
        assert diag.diagnosis_source == "deterministic_fallback"
        assert "FALLBACK_NO_API_KEY" in diag.evidence_codes
        assert provider.fallback_count == 1

    def test_non_strict_sync_strategy_falls_back_safely(self, sample_context, sample_diagnosis):
        provider = LLMStrategyProvider(api_key="", client=None, replay_cache=LLMReplayCache(), strict_no_fallback=False)
        proposal = provider.propose_sync(sample_context, sample_diagnosis)
        assert proposal.strategy_source == "deterministic_fallback"
        assert provider.fallback_count == 1

    @pytest.mark.anyio
    async def test_non_strict_async_strategy_falls_back_safely(self, sample_context, sample_diagnosis):
        provider = LLMStrategyProvider(api_key="", client=None, replay_cache=LLMReplayCache(), strict_no_fallback=False)
        proposal = await provider.propose(sample_context, sample_diagnosis)
        assert proposal.strategy_source == "deterministic_fallback"
        assert provider.fallback_count == 1

    def test_replay_cache_provenance(self, sample_context, sample_diagnosis):
        cache = LLMReplayCache()
        fp = cache.compute_fingerprint(
            model_version="openai/gpt-oss-120b",
            prompt_version="v2.0",
            observable_context=sample_context.model_dump(exclude_none=True),
        )
        cache.set_diagnosis(fp, sample_diagnosis)
        cached = cache.get_diagnosis(fp)
        assert cached is not None
        assert cached.diagnosis_source == "cached_llm"
