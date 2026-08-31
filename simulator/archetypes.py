"""Customer behavioral archetypes, failure class modifiers, and probability matrices."""
from typing import Dict
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import CustomerArchetype, FailureClass, SimulatedActionType


class ArchetypeBehavior(BaseModel):
    """Behavioral parameters governing customer reactions to dunning and recovery interventions."""
    model_config = ConfigDict(extra="forbid")

    base_action_success: Dict[SimulatedActionType, float] = Field(
        ..., description="Baseline recovery probability per action before failure class and amount adjustments"
    )
    base_churn_probability: float = Field(..., ge=0.0, le=1.0, description="Inherent customer churn risk")
    contact_churn_penalty: float = Field(..., ge=0.0, le=1.0, description="Additional churn probability penalty incurred per direct notification")
    amount_sensitivity_factor: float = Field(default=0.15, ge=0.0, le=1.0, description="Elasticity of recovery success relative to transaction amount")
    attempt_decay_rate: float = Field(default=0.10, ge=0.0, le=0.5, description="Success probability degradation rate per preceding attempt")


class FailureClassBehavior(BaseModel):
    """Failure-specific multipliers and physical constraints applied to recovery actions."""
    model_config = ConfigDict(extra="forbid")

    action_multipliers: Dict[SimulatedActionType, float] = Field(
        ..., description="Multiplier applied to action success probability (0.0 represents hard failure)"
    )
    base_error_code: str = Field(..., description="Razorpay canonical error code")
    base_error_description: str = Field(..., description="Simulated gateway error description")
    error_source: str = Field(..., description="Error origin layer (bank, gateway, customer)")
    error_step: str = Field(..., description="Payment processing step where failure occurred")
    error_reason: str = Field(..., description="Detailed failure reason")


ARCHETYPE_PROFILES: Dict[CustomerArchetype, ArchetypeBehavior] = {
    CustomerArchetype.HIGHLY_RESPONSIVE: ArchetypeBehavior(
        base_action_success={
            SimulatedActionType.NO_ACTION: 0.25,
            SimulatedActionType.RETRY_NOW: 0.50,
            SimulatedActionType.RETRY_LATER: 0.70,
            SimulatedActionType.PAYMENT_LINK: 0.90,
            SimulatedActionType.REMINDER: 0.85,
        },
        base_churn_probability=0.02,
        contact_churn_penalty=0.01,
        amount_sensitivity_factor=0.10,
        attempt_decay_rate=0.05,
    ),
    CustomerArchetype.NATURAL_RECOVERER: ArchetypeBehavior(
        base_action_success={
            SimulatedActionType.NO_ACTION: 0.75,
            SimulatedActionType.RETRY_NOW: 0.60,
            SimulatedActionType.RETRY_LATER: 0.85,
            SimulatedActionType.PAYMENT_LINK: 0.80,
            SimulatedActionType.REMINDER: 0.78,
        },
        base_churn_probability=0.01,
        contact_churn_penalty=0.02,
        amount_sensitivity_factor=0.08,
        attempt_decay_rate=0.05,
    ),
    CustomerArchetype.CONTACT_FATIGUED: ArchetypeBehavior(
        base_action_success={
            SimulatedActionType.NO_ACTION: 0.30,
            SimulatedActionType.RETRY_NOW: 0.45,
            SimulatedActionType.RETRY_LATER: 0.60,
            SimulatedActionType.PAYMENT_LINK: 0.40,
            SimulatedActionType.REMINDER: 0.25,
        },
        base_churn_probability=0.05,
        contact_churn_penalty=0.35,  # High churn risk if repeatedly messaged
        amount_sensitivity_factor=0.20,
        attempt_decay_rate=0.15,
    ),
    CustomerArchetype.NON_RESPONSIVE: ArchetypeBehavior(
        base_action_success={
            SimulatedActionType.NO_ACTION: 0.05,
            SimulatedActionType.RETRY_NOW: 0.40,
            SimulatedActionType.RETRY_LATER: 0.50,
            SimulatedActionType.PAYMENT_LINK: 0.05,
            SimulatedActionType.REMINDER: 0.05,
        },
        base_churn_probability=0.10,
        contact_churn_penalty=0.02,
        amount_sensitivity_factor=0.25,
        attempt_decay_rate=0.20,
    ),
}


FAILURE_CLASS_BEHAVIORS: Dict[FailureClass, FailureClassBehavior] = {
    FailureClass.TRANSIENT_GATEWAY: FailureClassBehavior(
        action_multipliers={
            SimulatedActionType.NO_ACTION: 0.30,
            SimulatedActionType.RETRY_NOW: 0.95,
            SimulatedActionType.RETRY_LATER: 0.90,
            SimulatedActionType.PAYMENT_LINK: 0.70,
            SimulatedActionType.REMINDER: 0.50,
        },
        base_error_code="GATEWAY_ERROR",
        base_error_description="Temporary gateway or bank network timeout occurred.",
        error_source="gateway",
        error_step="payment_authorization",
        error_reason="gateway_timeout",
    ),
    FailureClass.INSUFFICIENT_FUNDS: FailureClassBehavior(
        action_multipliers={
            SimulatedActionType.NO_ACTION: 0.40,
            SimulatedActionType.RETRY_NOW: 0.15,
            SimulatedActionType.RETRY_LATER: 0.80,
            SimulatedActionType.PAYMENT_LINK: 0.70,
            SimulatedActionType.REMINDER: 0.75,
        },
        base_error_code="BAD_REQUEST_ERROR",
        base_error_description="Payment failed due to insufficient funds in customer card account.",
        error_source="bank",
        error_step="payment_authorization",
        error_reason="insufficient_funds",
    ),
    FailureClass.EXPIRED_PAYMENT_METHOD: FailureClassBehavior(
        action_multipliers={
            SimulatedActionType.NO_ACTION: 0.02,
            SimulatedActionType.RETRY_NOW: 0.00,  # Hard zero: retrying expired instrument cannot succeed
            SimulatedActionType.RETRY_LATER: 0.00,  # Hard zero
            SimulatedActionType.PAYMENT_LINK: 0.85,  # Allows customer to supply new payment instrument
            SimulatedActionType.REMINDER: 0.65,
        },
        base_error_code="BAD_REQUEST_ERROR",
        base_error_description="Payment instrument is expired or mandate has been revoked.",
        error_source="bank",
        error_step="payment_authentication",
        error_reason="card_expired",
    ),
}
