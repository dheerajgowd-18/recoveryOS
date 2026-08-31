"""Deterministic risk detection models and rules for the RecoveryOS agent loop."""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from domain.aggregates import PaymentAggregate
from domain.enums import PaymentState
from domain.events import PaymentEntity


class RiskAssessment(BaseModel):
    """Structured evaluation of revenue loss risk for a financial entity."""
    model_config = ConfigDict(extra="forbid")

    is_at_risk: bool = Field(..., description="Whether revenue is at risk of loss")
    risk_level: str = Field(..., description="Risk category (NONE, LOW, MEDIUM, HIGH, CRITICAL)")
    reason: str = Field(..., description="Diagnostic rationale for risk classification")


class RiskDetector:
    """Deterministic risk analyzer evaluating payment and subscription health."""

    def detect_payment_risk(
        self,
        payment: Optional[PaymentEntity],
        aggregate: Optional[PaymentAggregate] = None,
    ) -> RiskAssessment:
        """Evaluate if a payment entity or aggregate requires dunning intervention."""
        current_state = aggregate.current_state if aggregate else (payment.status if payment else None)

        if current_state is None:
            return RiskAssessment(
                is_at_risk=False,
                risk_level="NONE",
                reason="No payment entity or aggregate provided.",
            )

        if current_state in (PaymentState.CAPTURED, PaymentState.REFUNDED):
            return RiskAssessment(
                is_at_risk=False,
                risk_level="NONE",
                reason=f"Payment is in terminal state ({current_state.value}); no recovery risk.",
            )

        if current_state == PaymentState.FAILED:
            error_code = payment.error_code if payment else "FAILED"
            return RiskAssessment(
                is_at_risk=True,
                risk_level="HIGH",
                reason=f"Payment failed with error '{error_code}'. Active dunning risk detected.",
            )

        return RiskAssessment(
            is_at_risk=False,
            risk_level="LOW",
            reason=f"Payment state is '{current_state.value}'; no immediate recovery intervention required.",
        )
