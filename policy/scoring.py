from typing import List, Optional
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
    expected_gross_recovery_paise: int = Field(default=0, ge=0, description="Expected total gross recovered amount in paise")
    expected_natural_recovery_paise: int = Field(default=0, ge=0, description="Expected organic recovery without intervention")
    expected_incremental_value_paise: int = Field(..., description="Expected incremental revenue in paise (can be negative)")
    action_cost_paise: int = Field(..., ge=0, description="Direct execution cost in paise")
    customer_friction_penalty_paise: int = Field(default=0, ge=0, description="Estimated customer contact fatigue cost")
    expected_net_value_paise: int = Field(..., description="Expected net recovery value (Incremental - Cost - Friction)")
    timing_window: Optional[str] = Field(default=None, description="Timing window bucket")
    delay_seconds: int = Field(default=0, ge=0, description="Delay in seconds")
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
        amount = context.amount_in_paise

        natural_val = int(amount * p_natural)
        gross_val = int(amount * p_action)

        if action == SimulatedActionType.NO_ACTION:
            return ScoredAction(
                action_type=action,
                estimated_probability=round(p_natural, 4),
                natural_probability=round(p_natural, 4),
                expected_uplift=0.0,
                expected_gross_recovery_paise=natural_val,
                expected_natural_recovery_paise=natural_val,
                expected_incremental_value_paise=0,
                action_cost_paise=0,
                customer_friction_penalty_paise=0,
                expected_net_value_paise=0,
                reason_codes=["NATURAL_RECOVERY_BASELINE"],
            )

        # Compute friction penalty based on customer contact frequency
        friction_penalty = 0
        if action in (SimulatedActionType.PAYMENT_LINK, SimulatedActionType.REMINDER):
            if context.contacts_in_last_24h > 0:
                friction_penalty = 500  # ₹5 fatigue penalty for consecutive contact
            if context.contacts_in_last_7d >= 2:
                friction_penalty += 1000  # ₹10 fatigue penalty for high weekly frequency

        # Allow genuine negative uplift (e.g. ill-timed actions destroying natural recovery)
        uplift = round(p_action - p_natural, 4)
        incremental_value = int(amount * uplift)
        net_value = incremental_value - cost - friction_penalty

        reason_codes = [
            f"PRIOR_PROB_{int(p_action * 100)}PCT",
            f"UPLIFT_{int(uplift * 100)}PCT",
            f"COST_{cost}PAISE",
        ]

        if friction_penalty > 0:
            reason_codes.append(f"FRICTION_PENALTY_{friction_penalty}PAISE")
        if uplift < 0:
            reason_codes.append("NEGATIVE_INCREMENTAL_UPLIFT")
        if net_value < 0:
            reason_codes.append("NEGATIVE_EXPECTED_NET_VALUE")

        return ScoredAction(
            action_type=action,
            estimated_probability=round(p_action, 4),
            natural_probability=round(p_natural, 4),
            expected_uplift=uplift,
            expected_gross_recovery_paise=gross_val,
            expected_natural_recovery_paise=natural_val,
            expected_incremental_value_paise=incremental_value,
            action_cost_paise=cost,
            customer_friction_penalty_paise=friction_penalty,
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
