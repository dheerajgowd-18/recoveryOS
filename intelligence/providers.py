"""Diagnosis provider abstraction, offline deterministic provider, and LLM boundary."""
from abc import ABC, abstractmethod
import json
import os
from typing import Optional
from pydantic import ValidationError

from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from simulator.config import SimulatedActionType


class BaseDiagnosisProvider(ABC):
    """Abstract interface for intelligence diagnosis engines."""

    @abstractmethod
    async def diagnose(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        """Produce a structured diagnosis from observable context asynchronously."""
        pass

    @abstractmethod
    def diagnose_sync(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        """Produce a structured diagnosis from observable context synchronously."""
        pass


class DeterministicDiagnosisProvider(BaseDiagnosisProvider):
    """Deterministic offline diagnosis provider inferring root causes via transparent rule engines.

    Operates purely offline with 0 external API dependencies and guaranteed bit-level reproducibility.
    """

    async def diagnose(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        return self.diagnose_sync(context)

    def diagnose_sync(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        error_code = (context.error_code or "").upper()
        error_desc = (context.error_description or "").lower()
        error_reason = (context.error_reason or "").lower()
        error_source = (context.error_source or "").lower()
        error_step = (context.error_step or "").lower()

        # 1. Expired Payment Method / Revoked Mandate Check
        if (
            "expired" in error_reason
            or "expired" in error_desc
            or (error_reason == "card_expired")
            or (error_code == "BAD_REQUEST_ERROR" and "expired" in error_desc)
        ):
            return StructuredDiagnosis(
                diagnosis_label=DiagnosisLabel.EXPIRED_PAYMENT_METHOD,
                confidence=0.90,
                evidence_codes=["OBS_CARD_EXPIRED_REASON", "OBS_AUTHENTICATION_STEP_FAILURE"],
                uncertainties=[],
                recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK],
                recommended_timing_hint="immediate",
                human_review_required=False,
                abstain_recommended=False,
                rationale="Payment instrument is expired or revoked. Retries are physically impossible; payment link required.",
                diagnosis_source="deterministic_offline",
                model_version="rules-v1.0",
            )

        # 2. Transient Gateway / Bank Network Failure Check
        if (
            error_code == "GATEWAY_ERROR"
            or error_source == "gateway"
            or "timeout" in error_reason
            or "timeout" in error_desc
            or "network" in error_desc
            or error_reason == "gateway_timeout"
        ):
            return StructuredDiagnosis(
                diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
                confidence=0.85,
                evidence_codes=["OBS_GATEWAY_ERROR", "OBS_GATEWAY_SOURCE", "OBS_NETWORK_TIMEOUT"],
                uncertainties=[],
                recommended_candidate_actions=[
                    SimulatedActionType.RETRY_LATER,
                    SimulatedActionType.RETRY_NOW,
                ],
                recommended_timing_hint="delay_2h",
                human_review_required=False,
                abstain_recommended=False,
                rationale="Transient gateway or bank timeout observed. Automated delayed retry has high expected uplift.",
                diagnosis_source="deterministic_offline",
                model_version="rules-v1.0",
            )

        # 3. Insufficient Funds Check
        if (
            error_reason == "insufficient_funds"
            or "insufficient" in error_desc
            or "balance" in error_desc
            or error_code == "INSUFFICIENT_FUNDS"
        ):
            return StructuredDiagnosis(
                diagnosis_label=DiagnosisLabel.INSUFFICIENT_FUNDS,
                confidence=0.80,
                evidence_codes=["OBS_INSUFFICIENT_FUNDS_REASON", "OBS_BANK_DECLINE"],
                uncertainties=[],
                recommended_candidate_actions=[
                    SimulatedActionType.RETRY_LATER,
                    SimulatedActionType.PAYMENT_LINK,
                    SimulatedActionType.REMINDER,
                ],
                recommended_timing_hint="delay_6h",
                human_review_required=False,
                abstain_recommended=False,
                rationale="Customer account has insufficient funds. Delayed retry or proactive payment link recommended.",
                diagnosis_source="deterministic_offline",
                model_version="rules-v1.0",
            )

        # 4. Authentication Failure / OTP Timeout Check
        if (
            error_code in ("AUTH_FAILED", "AUTHENTICATION_ERROR")
            or "authentication" in error_step
            or "otp" in error_desc
            or "auth" in error_reason
        ):
            return StructuredDiagnosis(
                diagnosis_label=DiagnosisLabel.AUTHENTICATION_FAILURE,
                confidence=0.75,
                evidence_codes=["OBS_AUTHENTICATION_STEP", "OBS_AUTH_FAILURE_CODE"],
                uncertainties=["CUSTOMER_ABANDONMENT_POSSIBLE"],
                recommended_candidate_actions=[
                    SimulatedActionType.PAYMENT_LINK,
                    SimulatedActionType.REMINDER,
                ],
                recommended_timing_hint="immediate",
                human_review_required=False,
                abstain_recommended=False,
                rationale="Authentication failed or timed out during 3DS OTP verification.",
                diagnosis_source="deterministic_offline",
                model_version="rules-v1.0",
            )

        # 5. Mandate Issue Check
        if "mandate" in error_code or "mandate" in error_desc or "mandate" in error_reason:
            return StructuredDiagnosis(
                diagnosis_label=DiagnosisLabel.MANDATE_ISSUE,
                confidence=0.85,
                evidence_codes=["OBS_MANDATE_INACTIVE"],
                uncertainties=[],
                recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK],
                recommended_timing_hint="immediate",
                human_review_required=False,
                abstain_recommended=False,
                rationale="Subscription recurring mandate is inactive or modified; customer payment link required.",
                diagnosis_source="deterministic_offline",
                model_version="rules-v1.0",
            )

        # 6. Unrecognized / Ambiguous Observable Evidence -> Safe Fallback / Abstain
        return StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.UNKNOWN_FAILURE,
            confidence=0.30,
            evidence_codes=["OBS_UNRECOGNIZED_SIGNATURE"],
            uncertainties=["UNRECOGNIZED_ERROR_SIGNATURE", "AMBIGUOUS_EVIDENCE"],
            recommended_candidate_actions=[SimulatedActionType.NO_ACTION],
            recommended_timing_hint=None,
            human_review_required=True,
            abstain_recommended=True,
            rationale="Observable error signature is unclassified or ambiguous; recommending safe abstention and operator review.",
            diagnosis_source="deterministic_offline",
            model_version="rules-v1.0",
        )


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
            # Re-attribute source to deterministic_fallback
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
        # In case of any exception or invalid schema, fall back safely.
        try:
            # Placeholder for external HTTP call (if network access available)
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
