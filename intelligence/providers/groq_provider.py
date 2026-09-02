"""Groq LLM Diagnosis Provider with strict schema validation and deterministic fallback."""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from pydantic import ValidationError

from intelligence.context import ObservableRecoveryContext
from intelligence.providers.base import BaseDiagnosisProvider
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from simulator.config import SimulatedActionType

logger = logging.getLogger("recoveryos.intelligence.groq")

# Default high-performance open-weights model available on Groq
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


SYSTEM_PROMPT = """You are the RecoveryOS Diagnostic Intelligence Engine for autonomous payment recovery.
Your job is to analyze the observable transaction failure context and produce a structured root cause diagnosis.

STRICT OPERATIONAL RULES:
1. Base your diagnosis strictly on the provided observable fields (error codes, descriptions, timing, attempt counts).
2. Choose diagnosis_label from ONLY these canonical values:
   - "transient_gateway_failure"
   - "insufficient_funds"
   - "expired_payment_method"
   - "authentication_failure"
   - "mandate_issue"
   - "customer_abandonment"
   - "subscription_payment_failure"
   - "overdue_invoice"
   - "unknown_failure"
3. Choose recommended_candidate_actions from ONLY these allowed action types:
   - "no_action"
   - "retry_now"
   - "retry_later"
   - "payment_link"
   - "reminder"
4. Output MUST be a single, valid JSON object matching the requested schema. Do not include markdown codeblocks or preamble outside the JSON.

REQUIRED JSON SCHEMA:
{
  "diagnosis_label": "transient_gateway_failure",
  "confidence": 0.85,
  "evidence_codes": ["OBS_GATEWAY_ERROR", "OBS_NETWORK_TIMEOUT"],
  "uncertainties": [],
  "recommended_candidate_actions": ["retry_later", "retry_now"],
  "recommended_timing_hint": "delay_2h",
  "human_review_required": false,
  "abstain_recommended": false,
  "rationale": "Clear, concise diagnostic explanation"
}
"""


class GroqLLMDiagnosisProvider(BaseDiagnosisProvider):
    """Production-grade LLM diagnosis provider using the official Groq SDK with guaranteed fallback.

    Guarantees:
    - Never leaks hidden simulation truth or counterfactual vectors into prompt payloads.
    - Strictly requests JSON object response format.
    - Parses and validates responses against Pydantic StructuredDiagnosis model.
    - Seamlessly falls back to DeterministicDiagnosisProvider on timeout, API error, or schema violation.
    - Comprehensive telemetry tracking for latency, successes, and fallbacks.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        timeout_seconds: float = 3.0,
        fallback_provider: Optional[DeterministicDiagnosisProvider] = None,
        client: Optional[Any] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model_id = model_id or os.getenv("GROQ_MODEL_ID", DEFAULT_GROQ_MODEL)
        self.timeout_seconds = timeout_seconds
        self.fallback_provider = fallback_provider or DeterministicDiagnosisProvider()
        self._client = client

        # Operational telemetry counters
        self.llm_calls: int = 0
        self.llm_successes: int = 0
        self.llm_fallbacks: int = 0
        self.llm_latency_ms: float = 0.0
        self.total_latency_ms: float = 0.0
        self.last_latency_ms: float = 0.0

    def _get_client(self) -> Optional[Any]:
        """Lazy initialization of Groq client if not injected."""
        if self._client is not None:
            return self._client

        if not self.api_key:
            return None

        try:
            from groq import Groq
            self._client = Groq(api_key=self.api_key, timeout=self.timeout_seconds)
            return self._client
        except Exception as e:
            logger.warning(f"Failed to initialize Groq client: {e}")
            return None

    def build_user_prompt(self, context: ObservableRecoveryContext) -> str:
        """Constructs sanitized prompt containing ONLY observable context features."""
        # Convert context to clean dictionary, strictly excluding any hidden/private attributes
        obs_payload = context.model_dump(exclude_none=True)
        return (
            "Analyze the following observable transaction failure context and return the structured diagnosis JSON:\n"
            f"{json.dumps(obs_payload, indent=2)}"
        )

    def parse_and_validate(self, raw_content: str) -> StructuredDiagnosis:
        """Parses raw LLM string into validated StructuredDiagnosis model."""
        data = json.loads(raw_content)
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")

        # Validate diagnosis_label enum
        label_str = data.get("diagnosis_label", "").lower()
        try:
            diag_label = DiagnosisLabel(label_str)
        except ValueError:
            diag_label = DiagnosisLabel.UNKNOWN_FAILURE

        # Validate candidate actions
        raw_actions = data.get("recommended_candidate_actions", [])
        validated_actions = []
        for a in raw_actions:
            try:
                validated_actions.append(SimulatedActionType(str(a).lower()))
            except ValueError:
                pass
        if not validated_actions:
            validated_actions = [SimulatedActionType.NO_ACTION]

        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return StructuredDiagnosis(
            diagnosis_label=diag_label,
            confidence=confidence,
            evidence_codes=list(data.get("evidence_codes", [])),
            uncertainties=list(data.get("uncertainties", [])),
            recommended_candidate_actions=validated_actions,
            recommended_timing_hint=data.get("recommended_timing_hint"),
            human_review_required=bool(data.get("human_review_required", False)),
            abstain_recommended=bool(data.get("abstain_recommended", False)),
            rationale=str(data.get("rationale", "LLM-generated diagnostic inference")),
            diagnosis_source="llm_structured",
            model_version=f"groq-{self.model_id}",
        )

    async def diagnose(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        """Asynchronously diagnose root cause with Groq LLM and deterministic fallback."""
        return self.diagnose_sync(context)

    def diagnose_sync(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        """Synchronously diagnose root cause using Groq API with fail-closed fallback."""
        self.llm_calls += 1
        start_time = time.perf_counter()

        client = self._get_client()
        if client is None:
            # Fallback when API key or SDK is unconfigured
            self.llm_fallbacks += 1
            fallback_diag = self.fallback_provider.diagnose_sync(context)
            return self._wrap_fallback(fallback_diag, "FALLBACK_NO_API_KEY")

        try:
            user_content = self.build_user_prompt(context)
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                model=self.model_id,
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            raw_response = chat_completion.choices[0].message.content
            if not raw_response:
                raise ValueError("Empty response content received from Groq LLM")

            diagnosis = self.parse_and_validate(raw_response)

            # Record success metrics
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            self.llm_successes += 1
            self.last_latency_ms = elapsed_ms
            self.total_latency_ms += elapsed_ms
            self.llm_latency_ms = self.total_latency_ms / self.llm_successes
            return diagnosis

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            self.last_latency_ms = elapsed_ms
            self.llm_fallbacks += 1
            logger.warning(f"Groq LLM diagnosis failed ({type(e).__name__}: {e}); engaging deterministic fallback.")

            fallback_diag = self.fallback_provider.diagnose_sync(context)
            is_timeout = isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower() or "timeout" in str(e).lower()
            error_code = "FALLBACK_TIMEOUT" if is_timeout else "FALLBACK_LLM_ERROR"
            return self._wrap_fallback(fallback_diag, error_code)

    def _wrap_fallback(self, fallback_diag: StructuredDiagnosis, reason_code: str) -> StructuredDiagnosis:
        """Wraps fallback diagnosis with deterministic fallback provenance."""
        return StructuredDiagnosis(
            diagnosis_label=fallback_diag.diagnosis_label,
            confidence=fallback_diag.confidence,
            evidence_codes=fallback_diag.evidence_codes + [reason_code],
            uncertainties=fallback_diag.uncertainties,
            recommended_candidate_actions=fallback_diag.recommended_candidate_actions,
            recommended_timing_hint=fallback_diag.recommended_timing_hint,
            human_review_required=fallback_diag.human_review_required,
            abstain_recommended=fallback_diag.abstain_recommended,
            rationale=f"[Deterministic Fallback] {fallback_diag.rationale}",
            diagnosis_source="deterministic_fallback",
            model_version=f"rules-fallback-{fallback_diag.model_version or 'v1.0'}",
        )
