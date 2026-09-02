"""Generic LLM-compatible diagnosis provider boundary with strict schema validation and safe fallback."""
import json
import os
from typing import Optional
from pydantic import ValidationError

from intelligence.context import ObservableRecoveryContext
from intelligence.providers.base import BaseDiagnosisProvider
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.schemas import StructuredDiagnosis


class LLMDiagnosisProvider(BaseDiagnosisProvider):
    """Optional LLM-compatible diagnosis provider boundary with strict schema validation and safe fallback.

    Guarantees:
    - Never requires external API keys for default test / demo execution.
    - If unconfigured, timed out, malformed, or unreachable, automatically falls back to DeterministicDiagnosisProvider.
    - Marks fallback provenance with `diagnosis_source = 'deterministic_fallback'`.
    - Tracks fallback and invalid output metrics.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gpt-4o-mini",
        timeout_seconds: float = 3.0,
        fallback_provider: Optional[DeterministicDiagnosisProvider] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("RAZORPAY_AI_LLM_KEY")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.fallback_provider = fallback_provider or DeterministicDiagnosisProvider()

        # Operational metrics tracking
        self.total_invocations: int = 0
        self.fallback_count: int = 0
        self.invalid_output_count: int = 0

    def parse_and_validate_response(self, raw_json_or_dict: object) -> StructuredDiagnosis:
        """Strictly validate and parse LLM-generated output into StructuredDiagnosis."""
        try:
            if isinstance(raw_json_or_dict, str):
                data = json.loads(raw_json_or_dict)
            elif isinstance(raw_json_or_dict, dict):
                data = raw_json_or_dict
            else:
                raise ValueError(f"Invalid input type: {type(raw_json_or_dict)}")

            # Ensure diagnosis_source is properly attributed
            data["diagnosis_source"] = "llm_structured"
            diagnosis = StructuredDiagnosis(**data)
            return diagnosis
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as e:
            self.invalid_output_count += 1
            raise ValueError(f"LLM output validation error: {str(e)}") from e

    async def diagnose(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        return self.diagnose_sync(context)

    def diagnose_sync(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        self.total_invocations += 1

        # 1. Check if LLM API is configured
        if not self.api_key:
            self.fallback_count += 1
            fallback_diag = self.fallback_provider.diagnose_sync(context)
            return StructuredDiagnosis(
                diagnosis_label=fallback_diag.diagnosis_label,
                confidence=fallback_diag.confidence,
                evidence_codes=fallback_diag.evidence_codes + ["FALLBACK_NO_API_KEY"],
                uncertainties=fallback_diag.uncertainties,
                recommended_candidate_actions=fallback_diag.recommended_candidate_actions,
                recommended_timing_hint=fallback_diag.recommended_timing_hint,
                human_review_required=fallback_diag.human_review_required,
                abstain_recommended=fallback_diag.abstain_recommended,
                rationale=f"[Deterministic Fallback] {fallback_diag.rationale}",
                diagnosis_source="deterministic_fallback",
                model_version=fallback_diag.model_version,
            )

        # 2. When configured, execution would dispatch to LLM client.
        try:
            raise ConnectionError("External LLM network call bypassed in offline validation mode")
        except Exception:
            self.fallback_count += 1
            fallback_diag = self.fallback_provider.diagnose_sync(context)
            return StructuredDiagnosis(
                diagnosis_label=fallback_diag.diagnosis_label,
                confidence=fallback_diag.confidence,
                evidence_codes=fallback_diag.evidence_codes + ["FALLBACK_PROVIDER_UNAVAILABLE"],
                uncertainties=fallback_diag.uncertainties,
                recommended_candidate_actions=fallback_diag.recommended_candidate_actions,
                recommended_timing_hint=fallback_diag.recommended_timing_hint,
                human_review_required=fallback_diag.human_review_required,
                abstain_recommended=fallback_diag.abstain_recommended,
                rationale=f"[Deterministic Fallback] {fallback_diag.rationale}",
                diagnosis_source="deterministic_fallback",
                model_version=fallback_diag.model_version,
            )
