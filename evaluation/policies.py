"""Baseline policy implementations for RecoveryOS evaluation."""
from typing import Dict, Optional

from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis
from policy.base import BasePolicy, PolicyDecision
from simulator.config import SimulatedActionType

__all__ = [
    "BasePolicy",
    "PolicyDecision",
    "NoActionPolicy",
    "AlwaysRetryPolicy",
    "StaticRulePolicy",
    "ProbabilityOnlyPolicy",
]


class NoActionPolicy(BasePolicy):
    """Baseline 0: Always abstain from intervening, relying purely on organic natural recovery."""

    def __init__(self) -> None:
        super().__init__(
            name="baseline_0_no_action",
            description="Abstain from all interventions; capture natural recovery baseline.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            action_type=SimulatedActionType.NO_ACTION,
            confidence=1.0,
            rationale="Baseline 0: Organic recovery control (no intervention).",
            policy_name=self.name,
            reason_codes=["BASELINE_0_ABSTAIN"],
            expected_net_value_paise=0,
            expected_incremental_value_paise=0,
            diagnosis=diagnosis,
        )


class AlwaysRetryPolicy(BasePolicy):
    """Baseline 1: Always retry invoice payment immediately whenever a failure occurs."""

    def __init__(self) -> None:
        super().__init__(
            name="baseline_1_always_retry",
            description="Unconditionally retry failed transactions immediately.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            action_type=SimulatedActionType.RETRY_NOW,
            confidence=1.0,
            rationale="Baseline 1: Immediate retry heuristic without root-cause differentiation.",
            policy_name=self.name,
            reason_codes=["BASELINE_1_UNCONDITIONAL_RETRY"],
            diagnosis=diagnosis,
        )


class StaticRulePolicy(BasePolicy):
    """Baseline 2: Rule-based heuristic branching on observable error codes and source steps."""

    def __init__(self) -> None:
        super().__init__(
            name="baseline_2_static_rules",
            description="Rule-based heuristic mapping observable error codes to targeted actions.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        error_code = context.error_code or context.failure_code or ""
        error_source = context.error_source or ""
        error_desc = (context.error_description or "").lower()

        # Hard failure on expired / bad payment method: naive rule engine dispatches link on BAD_REQUEST_ERROR
        if error_code == "BAD_REQUEST_ERROR" or "expired" in error_desc:
            return PolicyDecision(
                action_type=SimulatedActionType.PAYMENT_LINK,
                confidence=0.90,
                rationale="Static Rule: Expired payment method requires customer payment link to update credentials.",
                policy_name=self.name,
                reason_codes=["RULE_EXPIRED_PAYMENT_METHOD"],
                diagnosis=diagnosis,
            )

        # Gateway network error: immediate retry is optimal
        if error_code == "GATEWAY_ERROR" or error_source == "gateway":
            return PolicyDecision(
                action_type=SimulatedActionType.RETRY_NOW,
                confidence=0.85,
                rationale="Static Rule: Transient gateway error diagnosed; executing immediate retry.",
                policy_name=self.name,
                reason_codes=["RULE_TRANSIENT_GATEWAY"],
                diagnosis=diagnosis,
            )

        # Insufficient funds: delayed retry gives time for account replenishment
        if error_code == "INSUFFICIENT_FUNDS" or context.error_reason == "insufficient_funds":
            return PolicyDecision(
                action_type=SimulatedActionType.RETRY_LATER,
                confidence=0.75,
                rationale="Static Rule: Insufficient funds diagnosed; scheduling delayed retry.",
                policy_name=self.name,
                reason_codes=["RULE_INSUFFICIENT_FUNDS"],
                diagnosis=diagnosis,
            )

        # Default fallback
        return PolicyDecision(
            action_type=SimulatedActionType.PAYMENT_LINK,
            confidence=0.60,
            rationale="Static Rule: Default fallback to payment link dispatch.",
            policy_name=self.name,
            reason_codes=["RULE_DEFAULT_FALLBACK"],
            diagnosis=diagnosis,
        )


class ProbabilityOnlyPolicy(BasePolicy):
    """Baseline 3: Selects action with highest raw estimated recovery probability, ignoring costs and churn."""

    ESTIMATED_PRIORS: Dict[str, Dict[SimulatedActionType, float]] = {
        "BAD_REQUEST_ERROR": {
            SimulatedActionType.NO_ACTION: 0.05,
            SimulatedActionType.RETRY_NOW: 0.00,
            SimulatedActionType.RETRY_LATER: 0.00,
            SimulatedActionType.PAYMENT_LINK: 0.75,
            SimulatedActionType.REMINDER: 0.50,
        },
        "GATEWAY_ERROR": {
            SimulatedActionType.NO_ACTION: 0.30,
            SimulatedActionType.RETRY_NOW: 0.85,
            SimulatedActionType.RETRY_LATER: 0.75,
            SimulatedActionType.PAYMENT_LINK: 0.60,
            SimulatedActionType.REMINDER: 0.50,
        },
        "INSUFFICIENT_FUNDS": {
            SimulatedActionType.NO_ACTION: 0.20,
            SimulatedActionType.RETRY_NOW: 0.20,
            SimulatedActionType.RETRY_LATER: 0.70,
            SimulatedActionType.PAYMENT_LINK: 0.65,
            SimulatedActionType.REMINDER: 0.60,
        },
    }

    DEFAULT_PRIORS: Dict[SimulatedActionType, float] = {
        SimulatedActionType.NO_ACTION: 0.15,
        SimulatedActionType.RETRY_NOW: 0.40,
        SimulatedActionType.RETRY_LATER: 0.55,
        SimulatedActionType.PAYMENT_LINK: 0.65,
        SimulatedActionType.REMINDER: 0.50,
    }

    def __init__(self) -> None:
        super().__init__(
            name="baseline_3_probability_only",
            description="Greedy probability maximizer picking argmax P(recovery|action) without cost or uplift consideration.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        error_code = context.error_code or context.failure_code or ""
        priors = self.ESTIMATED_PRIORS.get(error_code, self.DEFAULT_PRIORS)

        # Pick action with maximum estimated raw recovery probability
        best_action = max(priors.items(), key=lambda item: item[1])[0]
        max_prob = priors[best_action]

        return PolicyDecision(
            action_type=best_action,
            confidence=round(max_prob, 2),
            rationale=f"Baseline 3: Greedy probability selection maximizing raw recovery P={max_prob:.2f} (ignoring costs/churn).",
            policy_name=self.name,
            reason_codes=["BASELINE_3_GREEDY_MAX_PROB"],
            diagnosis=diagnosis,
        )
