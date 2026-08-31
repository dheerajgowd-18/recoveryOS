"""Deterministic RecoveryOS Policy v0 with candidate generation, proxy scoring, and abstention."""
from typing import Optional

from policy.base import BasePolicy, PolicyDecision
from policy.candidates import CandidateGenerator
from policy.config import DeterministicPolicyConfig
from policy.public_view import PublicScenarioView
from policy.scoring import ExpectedValueScorer
from simulator.config import FailureClass, SimulatedActionType


class DeterministicRecoveryPolicy(BasePolicy):
    """Deterministic, transparent, cost-aware RecoveryOS policy baseline (v0).

    Operates strictly on sanitized PublicScenarioView inputs.
    Employs candidate filtering, expected net value proxy scoring, and explicit abstention guards.
    """

    def __init__(self, config: Optional[DeterministicPolicyConfig] = None) -> None:
        self.config = config or DeterministicPolicyConfig()
        super().__init__(
            name="RECOVERYOS_DETERMINISTIC_V0",
            description="Deterministic cost-aware RecoveryOS policy optimizing expected incremental recovery value.",
        )

    def decide(self, scenario: PublicScenarioView) -> PolicyDecision:
        """Evaluate a public scenario view and produce an optimal, bounded recovery decision."""
        # 1. Candidate Action Generation
        candidates = CandidateGenerator.generate_candidates(scenario, self.config)

        # 2. Transparent Expected Value Scoring
        scored_candidates = ExpectedValueScorer.score_all(scenario, candidates, self.config)

        # 3. Filter candidates by operational constraints
        admissible_scored = []
        for scored in scored_candidates:
            # Enforce max retry attempts constraint
            if (
                scored.action_type in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER)
                and scenario.attempt_count >= self.config.max_retry_attempts
            ):
                continue

            # Enforce hard block on retrying expired payment methods
            if (
                scored.action_type in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER)
                and scenario.failure_class == FailureClass.EXPIRED_PAYMENT_METHOD
            ):
                continue

            admissible_scored.append(scored)

        # If no non-NO_ACTION candidates are admissible or highest admissible has net value below threshold -> Abstain
        best_candidate = admissible_scored[0] if admissible_scored else None

        if (
            best_candidate is None
            or best_candidate.action_type == SimulatedActionType.NO_ACTION
            or best_candidate.expected_net_value_paise < self.config.min_expected_net_value_paise
        ):
            # Explicit Abstention
            reason_codes = ["ABSTAIN_LOW_EXPECTED_VALUE"]
            if scenario.attempt_count >= self.config.max_retry_attempts:
                reason_codes.append("ABSTAIN_ATTEMPT_LIMIT_EXCEEDED")

            return PolicyDecision(
                action_type=SimulatedActionType.NO_ACTION,
                confidence=1.0,
                rationale="Abstaining: Expected incremental recovery value does not justify intervention cost or risk.",
                policy_name=self.name,
                reason_codes=reason_codes,
                expected_net_value_paise=0,
                expected_incremental_value_paise=0,
            )

        # 4. Optimal Active Intervention Selection
        reason_codes = [
            "OPTIMAL_EXPECTED_NET_VALUE",
            f"DIAGNOSIS_{scenario.failure_class.name}",
        ] + best_candidate.reason_codes

        rationale = (
            f"Diagnosed {scenario.failure_class.value}. Selected {best_candidate.action_type.value} "
            f"yielding expected net value ₹{best_candidate.expected_net_value_paise / 100:.2f} "
            f"(uplift {best_candidate.expected_uplift * 100:.1f}% over natural baseline)."
        )

        return PolicyDecision(
            action_type=best_candidate.action_type,
            confidence=best_candidate.estimated_probability,
            rationale=rationale,
            policy_name=self.name,
            reason_codes=reason_codes,
            expected_net_value_paise=best_candidate.expected_net_value_paise,
            expected_incremental_value_paise=best_candidate.expected_incremental_value_paise,
        )
