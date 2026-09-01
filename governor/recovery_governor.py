"""Recovery Governor orchestrator evaluating candidate recovery actions against merchant policies and safety thresholds."""
from typing import Optional

from domain.aggregates import PaymentAggregate
from governor.checks import GovernanceChecker
from governor.decision import GovernorDecision, GovernorDecisionResult
from governor.firewall import CustomerConsentContext
from governor.policy import MerchantPolicy
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis
from policy.base import PolicyDecision


class RecoveryGovernor:
    """Deterministic authority engine governing all autonomous recovery proposals prior to execution."""

    def __init__(self, merchant_policy: Optional[MerchantPolicy] = None) -> None:
        self.merchant_policy = merchant_policy or MerchantPolicy()

    def evaluate(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
        proposal: Optional[PolicyDecision] = None,
        aggregate: Optional[PaymentAggregate] = None,
        consent: Optional[CustomerConsentContext] = None,
        policy_healthy: bool = True,
    ) -> GovernorDecision:
        """Evaluate proposal through deterministic governance checks and return authoritative GovernorDecision."""
        return GovernanceChecker.evaluate_all(
            context=context,
            diagnosis=diagnosis,
            proposal=proposal,
            policy=self.merchant_policy,
            aggregate=aggregate,
            consent=consent,
            policy_healthy=policy_healthy,
        )
