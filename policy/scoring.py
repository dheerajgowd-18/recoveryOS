"""Transparent expected-value proxy scoring engine for recovery action candidates."""
from typing import List
from pydantic import BaseModel, ConfigDict, Field

from policy.config import DeterministicPolicyConfig
from policy.public_view import PublicScenarioView
from simulator.config import SimulatedActionType


class ScoredAction(BaseModel):
    """Encapsulates the transparent mathematical scoring of an intervention candidate."""
    model_config = ConfigDict(extra="forbid")

    action_type: SimulatedActionType = Field(..., description="Candidate action evaluated")
    estimated_probability: float = Field(..., ge=0.0, le=1.0, description="Estimated recovery probability")
    natural_probability: float = Field(..., ge=0.0, le=1.0, description="Estimated baseline natural recovery probability")
    expected_uplift: float = Field(..., ge=0.0, le=1.0, description="Incremental uplift over natural recovery")
    expected_incremental_value_paise: int = Field(..., description="Expected incremental revenue in paise")
    action_cost_paise: int = Field(..., ge=0, description="Direct execution cost in paise")
    expected_net_value_paise: int = Field(..., description="Expected net recovery value (Incremental - Cost)")
    reason_codes: List[str] = Field(default_factory=list, description="Scoring audit tags")


class ExpectedValueScorer:
    """Scores candidate actions based solely on public scenario parameters, priors, and cost tables."""

    @staticmethod
    def score_candidate(
        view: PublicScenarioView,
        action: SimulatedActionType,
        config: DeterministicPolicyConfig,
    ) -> ScoredAction:
        """Calculate the expected incremental recovery and net economic value of an action."""
        priors = config.estimated_action_priors.get(view.failure_class, config.default_priors)
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

        uplift = max(0.0, p_action - p_natural)
        incremental_value = int(view.amount_in_paise * uplift)
        net_value = incremental_value - cost

        reason_codes = [
            f"PRIOR_PROB_{int(p_action * 100)}PCT",
            f"UPLIFT_{int(uplift * 100)}PCT",
            f"COST_{cost}PAISE",
        ]

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
        view: PublicScenarioView,
        candidates: List[SimulatedActionType],
        config: DeterministicPolicyConfig,
    ) -> List[ScoredAction]:
        """Score and rank all candidate actions by expected net value descending."""
        scored = [cls.score_candidate(view, action, config) for action in candidates]
        return sorted(scored, key=lambda s: s.expected_net_value_paise, reverse=True)
