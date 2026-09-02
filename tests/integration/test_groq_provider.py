"""Tests for Groq LLM Diagnosis Provider, strict fallback behavior, and hidden boundary verification."""
import json
from unittest.mock import MagicMock
import pytest

from intelligence.context import ObservableContextBuilder, ObservableRecoveryContext
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.providers.groq_provider import GroqLLMDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType, SimulatorConfig
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import Simulator


class MockGroqMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class MockGroqChoice:
    def __init__(self, message: MockGroqMessage) -> None:
        self.message = message


class MockGroqCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [MockGroqChoice(MockGroqMessage(content))]


@pytest.fixture
def sample_context() -> ObservableRecoveryContext:
    return ObservableRecoveryContext(
        scenario_id="scen_groq_test_01",
        payment_id="pay_groq_test_01",
        customer_id="cust_groq_01",
        amount_in_paise=500000,  # ₹5,000
        currency="INR",
        payment_method="card",
        attempt_count=1,
        error_code="GATEWAY_ERROR",
        error_description="Bank gateway timeout during 3DS processing",
        error_source="gateway",
        error_reason="gateway_timeout",
    )


class TestGroqLLMDiagnosisProvider:
    """Validates Groq LLM integration, schema parsing, fail-safe fallback, and security invariants."""

    def test_groq_provider_returns_valid_structured_diagnosis(self, sample_context):
        """When Groq returns a compliant JSON response, provider constructs valid StructuredDiagnosis."""
        valid_json_response = json.dumps({
            "diagnosis_label": "transient_gateway_failure",
            "confidence": 0.88,
            "evidence_codes": ["OBS_GATEWAY_ERROR", "OBS_GATEWAY_TIMEOUT"],
            "uncertainties": [],
            "recommended_candidate_actions": ["retry_later", "retry_now"],
            "recommended_timing_hint": "delay_2h",
            "human_review_required": False,
            "abstain_recommended": False,
            "rationale": "High confidence transient gateway failure; retry in 2 hours.",
        })

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MockGroqCompletion(valid_json_response)

        provider = GroqLLMDiagnosisProvider(
            api_key="gsk_mock_valid_key",
            model_id="llama-3.3-70b-versatile",
            client=mock_client,
        )

        diagnosis = provider.diagnose_sync(sample_context)

        assert isinstance(diagnosis, StructuredDiagnosis)
        assert diagnosis.diagnosis_label == DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE
        assert diagnosis.confidence == 0.88
        assert diagnosis.diagnosis_source == "llm_structured"
        assert "groq-llama-3.3-70b-versatile" in diagnosis.model_version
        assert SimulatedActionType.RETRY_LATER in diagnosis.recommended_candidate_actions
        assert provider.llm_calls == 1
        assert provider.llm_successes == 1
        assert provider.llm_fallbacks == 0
        assert provider.last_latency_ms >= 0.0

    def test_groq_provider_falls_back_safely_on_invalid_json(self, sample_context):
        """When Groq returns non-JSON or invalid schema, provider falls back to deterministic rules seamlessly."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MockGroqCompletion("This is not JSON {invalid:")

        provider = GroqLLMDiagnosisProvider(
            api_key="gsk_mock_key",
            client=mock_client,
        )

        diagnosis = provider.diagnose_sync(sample_context)

        assert isinstance(diagnosis, StructuredDiagnosis)
        assert diagnosis.diagnosis_source == "deterministic_fallback"
        assert diagnosis.diagnosis_label == DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE
        assert "FALLBACK_LLM_ERROR" in diagnosis.evidence_codes
        assert provider.llm_calls == 1
        assert provider.llm_successes == 0
        assert provider.llm_fallbacks == 1

    def test_groq_provider_falls_back_safely_on_timeout(self, sample_context):
        """When the Groq API call times out or throws an error, provider catches and engages deterministic fallback."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("Request timed out after 3.0s")

        provider = GroqLLMDiagnosisProvider(
            api_key="gsk_mock_key",
            timeout_seconds=1.0,
            client=mock_client,
        )

        diagnosis = provider.diagnose_sync(sample_context)

        assert isinstance(diagnosis, StructuredDiagnosis)
        assert diagnosis.diagnosis_source == "deterministic_fallback"
        assert "FALLBACK_TIMEOUT" in diagnosis.evidence_codes
        assert provider.llm_fallbacks == 1

    def test_groq_provider_falls_back_when_no_api_key(self, sample_context):
        """When unconfigured without an API key, provider cleanly falls back with no exceptions."""
        provider = GroqLLMDiagnosisProvider(api_key=None)

        diagnosis = provider.diagnose_sync(sample_context)

        assert isinstance(diagnosis, StructuredDiagnosis)
        assert diagnosis.diagnosis_source == "deterministic_fallback"
        assert "FALLBACK_NO_API_KEY" in diagnosis.evidence_codes
        assert provider.llm_calls == 1
        assert provider.llm_fallbacks == 1

    def test_hidden_truth_strictly_absent_from_groq_prompt_payload(self):
        """Mathematical boundary proof: private simulator counterfactuals, archetypes, and Y(a) are NEVER sent in LLM prompt."""
        sim = Simulator()
        scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=5))
        scenario = scenarios[0]

        # Build sanitized public context
        context = ObservableContextBuilder.build_from_simulated_scenario(scenario)
        provider = GroqLLMDiagnosisProvider(api_key="gsk_test")
        prompt = provider.build_user_prompt(context)

        # Strict boundary assertions
        assert "CONTACT_FATIGUED" not in prompt
        assert "contact_fatigued" not in prompt
        assert "CustomerArchetype" not in prompt
        assert "counterfactual" not in prompt.lower()
        assert "potential_outcomes" not in prompt
        assert "p_natural_recovery" not in prompt
        assert "y_no_action" not in prompt.lower()

        # Observable fields must be present
        assert scenario.scenario_id in prompt
        assert str(context.amount_in_paise) in prompt
