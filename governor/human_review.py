"""Human review escalation triggers and criteria evaluation."""
from typing import Optional

from domain.aggregates import PaymentAggregate
from domain.enums import PaymentState
from governor.policy import AutomationMode, MerchantPolicy
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis
from policy.base import PolicyDecision
from simulator.config import SimulatedActionType


class HumanReviewEvaluator:
    """Evaluates whether an autonomous recovery decision requires human review escalation."""

    @staticmethod
    def evaluate_escalation(
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis],
        proposal: Optional[PolicyDecision],
        policy: MerchantPolicy,
        aggregate: Optional[PaymentAggregate] = None,
    ) -> Optional[str]:
        """Check if any human review criteria are triggered. Returns reason string if triggered, else None."""
        # 1. Merchant policy automation mode overrides
        if policy.automation_mode == AutomationMode.MANUAL:
            return "HUMAN_REVIEW_REQUIRED_BY_MANUAL_MODE: Merchant automation mode is set to MANUAL."

        if policy.automation_mode == AutomationMode.ASSISTED and proposal and proposal.action_type != SimulatedActionType.NO_ACTION:
            return "HUMAN_REVIEW_REQUIRED_BY_ASSISTED_MODE: Merchant automation mode is ASSISTED; all active interventions require confirmation."

        # 2. Transaction Amount Threshold Escalation
        if context.amount_in_paise >= policy.human_review_amount_threshold_paise:
            amount_inr = context.amount_in_paise / 100
            threshold_inr = policy.human_review_amount_threshold_paise / 100
            return (
                f"HUMAN_REVIEW_REQUIRED_BY_AMOUNT: Transaction amount ₹{amount_inr:,.2f} "
                f"exceeds merchant review threshold ₹{threshold_inr:,.2f}."
            )

        # 3. High-Value Action with Diagnosis Uncertainty
        # High value (>= 500,000 paise / ₹5,000) with low/borderline confidence or uncertainties
        if context.amount_in_paise >= 500_000:
            if diagnosis and (diagnosis.confidence < 0.70 or diagnosis.uncertainties):
                return (
                    f"HUMAN_REVIEW_REQUIRED_BY_UNCERTAINTY: High-value transaction (₹{context.amount_in_paise / 100:,.2f}) "
                    f"has borderline diagnosis confidence ({diagnosis.confidence:.2f}) or reported uncertainties."
                )

        # 4. Explicit Diagnosis Flag
        if diagnosis and diagnosis.human_review_required:
            return f"HUMAN_REVIEW_REQUIRED_BY_DIAGNOSIS: Intelligence layer flagged case for human review: {diagnosis.rationale}"

        # 5. State Ambiguity Check
        if aggregate and aggregate.current_state not in (PaymentState.CREATED, PaymentState.AUTHORIZED, PaymentState.FAILED, PaymentState.CAPTURED, PaymentState.REFUNDED):
            return f"HUMAN_REVIEW_REQUIRED_BY_STATE_AMBIGUITY: Unrecognized or ambiguous aggregate state '{aggregate.current_state}'."

        return None
