"""Deterministic offline diagnosis provider inferring root causes via transparent rule engines."""
from typing import Optional
from intelligence.context import ObservableRecoveryContext
from intelligence.providers.base import BaseDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from rag.schemas import BoundedContextBundle
from simulator.config import SimulatedActionType


class DeterministicDiagnosisProvider(BaseDiagnosisProvider):
    """Deterministic offline diagnosis provider inferring root causes via transparent rule engines.

    Operates purely offline with 0 external API dependencies and guaranteed bit-level reproducibility.
    """

    async def diagnose(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StructuredDiagnosis:
        return self.diagnose_sync(context, memory_bundle)

    def diagnose_sync(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StructuredDiagnosis:
        error_code = (context.error_code or "").upper()
        error_code_lower = (context.error_code or "").lower()
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
        if "mandate" in error_code_lower or "mandate" in error_desc or "mandate" in error_reason:
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
