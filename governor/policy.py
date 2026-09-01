"""Merchant governance policy contract defining operational limits, thresholds, and safety boundaries."""
from enum import Enum
from typing import List, Optional, Set
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import SimulatedActionType


class AutomationMode(str, Enum):
    """Merchant automation posture."""
    AUTONOMOUS = "AUTONOMOUS"  # Full auto-execution of approved actions within limits
    ASSISTED = "ASSISTED"      # High-value actions require human confirmation
    MANUAL = "MANUAL"          # All actions require manual human review


class MerchantPolicy(BaseModel):
    """Versioned merchant operational policy governing autonomous recovery limits and thresholds."""
    model_config = ConfigDict(extra="forbid")

    policy_version: str = Field(default="v1.0.0", description="Policy version identifier")
    automation_mode: AutomationMode = Field(default=AutomationMode.AUTONOMOUS, description="Operational automation level")
    max_retries: int = Field(default=3, ge=0, description="Maximum automated payment retries allowed per invoice")
    max_contacts_24h: int = Field(default=2, ge=0, description="Maximum direct customer communications in 24 hours")
    max_contacts_7d: int = Field(default=4, ge=0, description="Maximum direct customer communications in 7 days")
    max_automatic_action_amount_paise: int = Field(default=10_000_000, ge=0, description="Absolute maximum amount in paise permitted for autonomous actions (₹100,000)")
    human_review_amount_threshold_paise: int = Field(default=2_000_000, ge=0, description="Transaction amount in paise triggering human review escalation (₹20,000)")
    min_expected_incremental_value_paise: int = Field(default=0, description="Minimum incremental recovery value required to justify intervention")
    min_diagnosis_confidence: float = Field(default=0.50, ge=0.0, le=1.0, description="Minimum diagnosis confidence required for autonomous execution")
    recovery_window_hours: int = Field(default=72, ge=1, description="Maximum duration in hours an invoice remains eligible for recovery")
    cooldown_seconds: int = Field(default=3600, ge=0, description="Minimum cooldown in seconds between consecutive dunning attempts")
    allowed_action_types: List[SimulatedActionType] = Field(
        default_factory=lambda: [
            SimulatedActionType.NO_ACTION,
            SimulatedActionType.RETRY_NOW,
            SimulatedActionType.RETRY_LATER,
            SimulatedActionType.PAYMENT_LINK,
            SimulatedActionType.REMINDER,
        ],
        description="Whitelist of recovery action types approved by merchant",
    )
    consent_behavior: str = Field(default="STRICT_OPT_OUT", description="Consent enforcement mode (e.g. STRICT_OPT_OUT)")
