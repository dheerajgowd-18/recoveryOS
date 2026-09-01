"""Transparent expected-value proxy scoring engine for recovery action candidates with negative uplift semantics."""
from typing import List
from pydantic import BaseModel, ConfigDict, Field

from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis
from policy.config import DeterministicPolicyConfig
from simulator.config import SimulatedActionType


class ScoredAction(BaseModel):
    """Encapsulates the transparent mathematical scoring of an intervention candidate."""
    model_config = ConfigDict(extra="forbid")

    action_type: SimulatedActionType = Field(..., description="Candidate action evaluated")
    estimated_probability: float = Field(..., ge=0.0, le=1.0, description="Estimated recovery probability")
    natural_probability: float = Field(..., ge=0.0, le=1.0, description="Estimated baseline natural recovery probability")
    expected_uplift: float = Field(..., ge=-1.0, le=1.0, description="Incremental uplift over natural recovery (can be negative)")
    expected_incremental_value_paise: int = Field(..., description="Expected incremental revenue in paise (can be negative)")
    action_cost_paise: int = Field(..., ge=0, description="Direct execution cost in paise")
    expected_net_value_paise: int = Field(..., description="Expected net recovery value (Incremental - Cost)")
    reason_codes: List[str] = Field(default_factory=list, description="Scoring audit tags")


class ExpectedValueScorer:
    """Scores candidate actions based solely on observable context, structured diagnosis, priors, and cost tables."""

    @staticmethod
    def score_candidate(
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        action: SimulatedActionType,
        config: DeterministicPolicyConfig,
    ) -> ScoredAction:
        """Calculate the expected incremental recovery and net economic value of an action with negative uplift support."""
        priors = config.estimated_action_priors.get(diagnosis.diagnosis_label, config.default_priors)
        p_action = priors.get(action, 0.0)
        p_natural = priors.get(SimulatedActionType.NO_ACTION, 0.0)

        cost = config.action_costs_paise.get(action, 0)

        if action == SimulatedActionType.NO_ACTION:
            return ScoredAction(
                action_type=action,
                estimated_probability=p_natural,
                natural_probability=p_natural,
                expected_uplift=0.0,
                expected_incremental_value_paise=0,
                action_cost_paise=0,
                expected_net_value_paise=0,
                reason_codes=["NATURAL_RECOVERY_BASELINE"],
            )

        # Allow genuine negative uplift (e.g. ill-timed actions destroying natural recovery)
        uplift = p_action - p_natural
        incremental_value = int(context.amount_in_paise * uplift)
        net_value = incremental_value - cost

        reason_codes = [
            f"PRIOR_PROB_{int(p_action * 100)}PCT",
            f"UPLIFT_{int(uplift * 100)}PCT",
            f"COST_{cost}PAISE",
        ]

        if uplift < 0:
            reason_codes.append("NEGATIVE_INCREMENTAL_UPLIFT")
        if net_value < 0:
            reason_codes.append("NEGATIVE_EXPECTED_NET_VALUE")

        return ScoredAction(
            action_type=action,
            estimated_probability=round(p_action, 4),
            natural_probability=round(p_natural, 4),
            expected_uplift=round(uplift, 4),
            expected_incremental_value_paise=incremental_value,
            action_cost_paise=cost,
            expected_net_value_paise=net_value,
            reason_codes=reason_codes,
        )

    @classmethod
    def score_all(
        cls,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        candidates: List[SimulatedActionType],
        config: DeterministicPolicyConfig,
    ) -> List[ScoredAction]:
        """Score and rank all candidate actions by expected net value descending."""
        scored = [cls.score_candidate(context, diagnosis, action, config) for action in candidates]
        return sorted(scored, key=lambda s: s.expected_net_value_paise, reverse=True)
