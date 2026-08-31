"""Configuration models and enumerations for the RecoveryOS Synthetic Simulator."""
from enum import Enum
from typing import Dict
from pydantic import BaseModel, ConfigDict, Field


class CustomerArchetype(str, Enum):
    """Behavioral customer archetype profiles defining dunning and response dynamics."""
    HIGHLY_RESPONSIVE = "highly_responsive"
    NATURAL_RECOVERER = "natural_recoverer"
    CONTACT_FATIGUED = "contact_fatigued"
    NON_RESPONSIVE = "non_responsive"


class FailureClass(str, Enum):
    """Root cause classification for transaction or subscription charges."""
    TRANSIENT_GATEWAY = "transient_gateway"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    EXPIRED_PAYMENT_METHOD = "expired_payment_method"


class SimulatedActionType(str, Enum):
    """The discrete set of possible intervention actions evaluated counterfactually."""
    NO_ACTION = "no_action"
    RETRY_NOW = "retry_now"
    RETRY_LATER = "retry_later"
    PAYMENT_LINK = "payment_link"
    REMINDER = "reminder"


class ScenarioConfig(BaseModel):
    """Configuration parameters for a single simulated recovery scenario."""
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., description="Unique scenario identifier")
    seed: int = Field(..., description="Deterministic pseudo-random generator seed")
    archetype: CustomerArchetype = Field(..., description="Customer behavioral archetype")
    failure_class: FailureClass = Field(..., description="Underlying failure root cause")
    amount_in_paise: int = Field(..., ge=100, description="Transaction amount in smallest currency unit")
    attempt_count: int = Field(default=1, ge=1, description="Current dunning attempt index")
    currency: str = Field(default="INR", min_length=3, max_length=3)
    merchant_account_id: str = Field(default="acc_sim_merchant_001")


class SimulatorConfig(BaseModel):
    """Global configuration for batch synthetic environment generation."""
    model_config = ConfigDict(extra="forbid")

    seed: int = Field(default=42, description="Global random generator seed for reproducibility")
    num_scenarios: int = Field(default=100, ge=1, description="Total number of scenarios to generate")
    amount_min_paise: int = Field(default=49900, ge=100, description="Minimum amount in paise (e.g. Rs 499)")
    amount_max_paise: int = Field(default=999900, ge=100, description="Maximum amount in paise (e.g. Rs 9,999)")
    currency: str = Field(default="INR")
    merchant_account_id: str = Field(default="acc_sim_merchant_001")
    archetype_distribution: Dict[CustomerArchetype, float] = Field(
        default={
            CustomerArchetype.HIGHLY_RESPONSIVE: 0.35,
            CustomerArchetype.NATURAL_RECOVERER: 0.25,
            CustomerArchetype.CONTACT_FATIGUED: 0.20,
            CustomerArchetype.NON_RESPONSIVE: 0.20,
        },
        description="Probability distribution over customer archetypes",
    )
    failure_class_distribution: Dict[FailureClass, float] = Field(
        default={
            FailureClass.INSUFFICIENT_FUNDS: 0.50,
            FailureClass.TRANSIENT_GATEWAY: 0.30,
            FailureClass.EXPIRED_PAYMENT_METHOD: 0.20,
        },
        description="Probability distribution over failure classes",
    )
