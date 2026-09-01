"""Configuration models and static priors for the deterministic RecoveryOS policy."""
from typing import Dict
from pydantic import BaseModel, ConfigDict, Field

from intelligence.schemas import DiagnosisLabel
from simulator.config import SimulatedActionType


class DeterministicPolicyConfig(BaseModel):
    """Tunable thresholds, priors, and cost tables for deterministic recovery decisioning."""
    model_config = ConfigDict(extra="forbid")

    policy_version: str = Field(default="deterministic-v1", description="Policy version identifier")
    min_expected_net_value_paise: int = Field(
        default=50,
        description="Minimum expected net recovery value in paise required to justify active intervention",
    )
    confidence_threshold: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description="Minimum diagnosis confidence required before considering active interventions",
    )
    max_retry_attempts: int = Field(
        default=3,
        ge=1,
        description="Maximum number of automated retries before abstaining or falling back to links",
    )
    high_value_threshold_paise: int = Field(
        default=200000,
        ge=100,
        description="High transaction value threshold in paise (e.g. >= ₹2,000)",
    )
    allow_immediate_retry: bool = Field(
        default=False,
        description="Whether RETRY_NOW is permitted for transient gateway errors (default prefers RETRY_LATER)",
    )
    action_costs_paise: Dict[SimulatedActionType, int] = Field(
        default={
            SimulatedActionType.NO_ACTION: 0,
            SimulatedActionType.RETRY_NOW: 20,
            SimulatedActionType.RETRY_LATER: 20,
            SimulatedActionType.PAYMENT_LINK: 100,
            SimulatedActionType.REMINDER: 50,
        },
        description="Execution cost per action type in paise",
    )
    estimated_action_priors: Dict[DiagnosisLabel, Dict[SimulatedActionType, float]] = Field(
        default={
            DiagnosisLabel.EXPIRED_PAYMENT_METHOD: {
                SimulatedActionType.NO_ACTION: 0.05,
                SimulatedActionType.RETRY_NOW: 0.00,
                SimulatedActionType.RETRY_LATER: 0.00,
                SimulatedActionType.PAYMENT_LINK: 0.70,
                SimulatedActionType.REMINDER: 0.40,
            },
            DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE: {
                SimulatedActionType.NO_ACTION: 0.25,
                SimulatedActionType.RETRY_NOW: 0.75,
                SimulatedActionType.RETRY_LATER: 0.80,
                SimulatedActionType.PAYMENT_LINK: 0.55,
                SimulatedActionType.REMINDER: 0.45,
            },
            DiagnosisLabel.INSUFFICIENT_FUNDS: {
                SimulatedActionType.NO_ACTION: 0.15,
                SimulatedActionType.RETRY_NOW: 0.15,
                SimulatedActionType.RETRY_LATER: 0.65,
                SimulatedActionType.PAYMENT_LINK: 0.60,
                SimulatedActionType.REMINDER: 0.50,
            },
            DiagnosisLabel.AUTHENTICATION_FAILURE: {
                SimulatedActionType.NO_ACTION: 0.10,
                SimulatedActionType.RETRY_NOW: 0.20,
                SimulatedActionType.RETRY_LATER: 0.35,
                SimulatedActionType.PAYMENT_LINK: 0.75,
                SimulatedActionType.REMINDER: 0.60,
            },
            DiagnosisLabel.MANDATE_ISSUE: {
                SimulatedActionType.NO_ACTION: 0.05,
                SimulatedActionType.RETRY_NOW: 0.00,
                SimulatedActionType.RETRY_LATER: 0.10,
                SimulatedActionType.PAYMENT_LINK: 0.80,
                SimulatedActionType.REMINDER: 0.55,
            },
            DiagnosisLabel.UNKNOWN_FAILURE: {
                SimulatedActionType.NO_ACTION: 0.15,
                SimulatedActionType.RETRY_NOW: 0.20,
                SimulatedActionType.RETRY_LATER: 0.50,
                SimulatedActionType.PAYMENT_LINK: 0.55,
                SimulatedActionType.REMINDER: 0.40,
            },
        },
        description="Static recovery probability priors per diagnosis label",
    )
    default_priors: Dict[SimulatedActionType, float] = Field(
        default={
            SimulatedActionType.NO_ACTION: 0.15,
            SimulatedActionType.RETRY_NOW: 0.20,
            SimulatedActionType.RETRY_LATER: 0.50,
            SimulatedActionType.PAYMENT_LINK: 0.55,
            SimulatedActionType.REMINDER: 0.40,
        },
        description="Fallback probability priors for unclassified or unknown errors",
    )
