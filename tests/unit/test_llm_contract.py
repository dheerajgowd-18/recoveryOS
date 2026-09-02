"""Contract tests for LLM providers: telemetry, retries, token tracking, and async execution."""
from unittest.mock import MagicMock
import pytest

from intelligence.context import ObservableRecoveryContext
from intelligence.providers.llm_provider import LLMDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis


@pytest.fixture
def sample_context():
    return ObservableRecoveryContext(
        scenario_id="scen_contract_01",
        payment_id="pay_contract_01",
        amount_in_paise=250000,
        error_code="GATEWAY_ERROR",
        error_source="gateway",
        error_reason="gateway_timeout",
    )


class TestLLMProviderContract:
    """Validates LLM provider interface contract, telemetry, and execution fidelity."""

    def test_telemetry_tracking_on_success(self, sample_context):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content='''{
                            "diagnosis_label": "transient_gateway_failure",
                            "confidence": 0.90,
                            "evidence_codes": ["OBS_GATEWAY_TIMEOUT"],
                            "uncertainties": [],
                            "recommended_candidate_actions": ["retry_later"],
                            "recommended_timing_hint": "delay_2h",
                            "human_review_required": false,
                            "abstain_recommended": false,
                            "rationale": "Transient gateway outage"
                        }'''
                    )
                )
            ]
        )

        provider = LLMDiagnosisProvider(api_key="test_key", client=mock_client)
        diag = provider.diagnose_sync(sample_context)

        assert diag.diagnosis_label == DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE
        assert diag.diagnosis_source == "llm_structured"
        assert provider.total_invocations == 1
        assert provider.llm_calls == 1
        assert provider.llm_successes == 1
        assert provider.fallback_count == 0
        assert provider.last_latency_ms >= 0.0
        assert provider.fallback_rate == 0.0

    def test_async_diagnose_contract(self, sample_context):
        import asyncio
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content='''{
                            "diagnosis_label": "insufficient_funds",
                            "confidence": 0.85,
                            "evidence_codes": ["OBS_INSUFFICIENT_FUNDS"],
                            "uncertainties": [],
                            "recommended_candidate_actions": ["payment_link"],
                            "recommended_timing_hint": "immediate",
                            "human_review_required": false,
                            "abstain_recommended": false,
                            "rationale": "Insufficient balance observed"
                        }'''
                    )
                )
            ]
        )

        provider = LLMDiagnosisProvider(api_key="test_key", client=mock_client)
        diag = asyncio.run(provider.diagnose(sample_context))

        assert diag.diagnosis_label == DiagnosisLabel.INSUFFICIENT_FUNDS
        assert provider.llm_successes == 1

    def test_retry_on_transient_failure_succeeds(self, sample_context):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            TimeoutError("First attempt timed out"),
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='''{
                                "diagnosis_label": "transient_gateway_failure",
                                "confidence": 0.85,
                                "evidence_codes": [],
                                "uncertainties": [],
                                "recommended_candidate_actions": ["retry_later"],
                                "recommended_timing_hint": "delay_2h",
                                "human_review_required": false,
                                "abstain_recommended": false,
                                "rationale": "Recovered on retry"
                            }'''
                        )
                    )
                ]
            ),
        ]

        provider = LLMDiagnosisProvider(api_key="test_key", client=mock_client, max_retries=1)
        diag = provider.diagnose_sync(sample_context)

        assert diag.diagnosis_label == DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE
        assert diag.diagnosis_source == "llm_structured"
        assert provider.llm_successes == 1
        assert provider.timeout_count == 1
