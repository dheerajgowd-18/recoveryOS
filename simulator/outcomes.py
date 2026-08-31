"""Hidden potential outcome models computing counterfactual states Y(a) across the action space."""
import random
from typing import Dict
from pydantic import BaseModel, ConfigDict, Field

from simulator.archetypes import ARCHETYPE_PROFILES, FAILURE_CLASS_BEHAVIORS, ArchetypeBehavior, FailureClassBehavior
from simulator.config import ScenarioConfig, SimulatedActionType


class ActionOutcome(BaseModel):
    """Counterfactual outcome state representing the result if a specific action was selected."""
    model_config = ConfigDict(extra="forbid")

    action_type: SimulatedActionType = Field(..., description="Action evaluated")
    recovered: bool = Field(..., description="Whether revenue is successfully captured under this action")
    recovery_delay_seconds: int = Field(..., ge=0, description="Time delay until recovery realization")
    recovered_amount_paise: int = Field(..., ge=0, description="Amount successfully collected in paise")
    customer_churned: bool = Field(..., description="Whether customer churns/cancels as a byproduct of this action")
    fatigue_score: float = Field(..., ge=0.0, le=1.0, description="Customer contact fatigue score [0.0, 1.0]")
    action_cost_paise: int = Field(..., ge=0, description="Direct cost of executing the action in paise")


class PotentialOutcomes(BaseModel):
    """Encapsulates the complete counterfactual outcome vector Y(a) for all candidate actions."""
    model_config = ConfigDict(extra="forbid")

    no_action: ActionOutcome
    retry_now: ActionOutcome
    retry_later: ActionOutcome
    payment_link: ActionOutcome
    reminder: ActionOutcome

    def get_outcome(self, action: SimulatedActionType) -> ActionOutcome:
        """Lookup specific outcome by action type."""
        mapping = {
            SimulatedActionType.NO_ACTION: self.no_action,
            SimulatedActionType.RETRY_NOW: self.retry_now,
            SimulatedActionType.RETRY_LATER: self.retry_later,
            SimulatedActionType.PAYMENT_LINK: self.payment_link,
            SimulatedActionType.REMINDER: self.reminder,
        }
        return mapping[action]


class PotentialOutcomeEngine:
    """Computes deterministic counterfactual outcomes based on archetype, failure physics, and amount."""

    ACTION_COSTS: Dict[SimulatedActionType, int] = {
        SimulatedActionType.NO_ACTION: 0,
        SimulatedActionType.RETRY_NOW: 20,       # 0.20 INR gateway attempt cost
        SimulatedActionType.RETRY_LATER: 20,     # 0.20 INR gateway attempt cost
        SimulatedActionType.PAYMENT_LINK: 100,   # 1.00 INR payment link dispatch cost
        SimulatedActionType.REMINDER: 50,        # 0.50 INR WhatsApp/SMS notification cost
    }

    ACTION_DELAYS: Dict[SimulatedActionType, tuple[int, int]] = {
        SimulatedActionType.NO_ACTION: (86400, 259200),      # 1 to 3 days
        SimulatedActionType.RETRY_NOW: (60, 900),            # 1 to 15 minutes
        SimulatedActionType.RETRY_LATER: (86400, 172800),    # 24 to 48 hours
        SimulatedActionType.PAYMENT_LINK: (1800, 43200),     # 30 min to 12 hours
        SimulatedActionType.REMINDER: (3600, 86400),         # 1 to 24 hours
    }

    def compute_outcomes(self, rng: random.Random, scenario: ScenarioConfig) -> PotentialOutcomes:
        """Compute the full counterfactual vector Y(a) for a given scenario."""
        archetype_behavior = ARCHETYPE_PROFILES[scenario.archetype]
        failure_behavior = FAILURE_CLASS_BEHAVIORS[scenario.failure_class]

        outcomes: Dict[SimulatedActionType, ActionOutcome] = {}

        # Amount elasticity factor
        amount_penalty = max(
            0.0,
            1.0 - (archetype_behavior.amount_sensitivity_factor * min(1.0, (scenario.amount_in_paise - 49900) / 1000000.0)),
        )

        # Attempt decay factor
        attempt_penalty = max(
            0.1,
            (1.0 - archetype_behavior.attempt_decay_rate) ** (scenario.attempt_count - 1),
        )

        for action_type in SimulatedActionType:
            base_p = archetype_behavior.base_action_success[action_type]
            multiplier = failure_behavior.action_multipliers[action_type]

            # Structural recovery probability
            final_p = max(0.0, min(1.0, base_p * multiplier * amount_penalty * attempt_penalty))

            # Simulate recovery
            is_recovered = rng.random() < final_p

            # Simulate delay
            min_delay, max_delay = self.ACTION_DELAYS[action_type]
            delay = rng.randint(min_delay, max_delay) if is_recovered else 0

            # Simulate churn
            is_contact_action = action_type in (SimulatedActionType.PAYMENT_LINK, SimulatedActionType.REMINDER)
            contact_penalty = archetype_behavior.contact_churn_penalty if is_contact_action else 0.0
            churn_p = min(1.0, archetype_behavior.base_churn_probability + contact_penalty)
            is_churned = rng.random() < churn_p

            # Calculate fatigue
            fatigue = min(1.0, 0.2 * (scenario.attempt_count - 1) + (0.4 if is_contact_action else 0.0))

            outcomes[action_type] = ActionOutcome(
                action_type=action_type,
                recovered=is_recovered,
                recovery_delay_seconds=delay,
                recovered_amount_paise=scenario.amount_in_paise if is_recovered else 0,
                customer_churned=is_churned,
                fatigue_score=round(fatigue, 2),
                action_cost_paise=self.ACTION_COSTS[action_type],
            )

        return PotentialOutcomes(
            no_action=outcomes[SimulatedActionType.NO_ACTION],
            retry_now=outcomes[SimulatedActionType.RETRY_NOW],
            retry_later=outcomes[SimulatedActionType.RETRY_LATER],
            payment_link=outcomes[SimulatedActionType.PAYMENT_LINK],
            reminder=outcomes[SimulatedActionType.REMINDER],
        )
