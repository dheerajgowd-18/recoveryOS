"""Governor decision contract models and outcome taxonomy."""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import SimulatedActionType


class GovernorDecisionResult(str, Enum):
    """Canonical governance outcome status."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    DEFER = "DEFER"
    ESCALATE = "ESCALATE"
    ABSTAIN = "ABSTAIN"


class GovernorDecision(BaseModel):
    """Structured, immutable decision emitted by the Recovery Governor."""
    model_config = ConfigDict(extra="forbid")

    decision_result: GovernorDecisionResult = Field(..., description="Governance outcome: ALLOW, DENY, DEFER, ESCALATE, ABSTAIN")
    selected_action: Optional[SimulatedActionType] = Field(default=None, description="Action permitted for execution if ALLOW")
    timing_hint: Optional[str] = Field(default=None, description="Execution timing directive (e.g. 'immediate', 'delay_24h')")
    reason_codes: List[str] = Field(default_factory=list, description="Machine-readable governance check reason codes")
    policy_version: str = Field(default="v1.0.0", description="Merchant governance policy version applied")
    diagnosis_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Intelligence diagnosis confidence score")
    expected_incremental_value_paise: int = Field(default=0, description="Expected incremental recovery value in paise")
    expected_net_value_paise: int = Field(default=0, description="Expected net recovery value after action cost in paise")
    human_review_reason: Optional[str] = Field(default=None, description="Detailed trigger rationale if escalated to human review")
    stop_reason: Optional[str] = Field(default=None, description="Runtime stopping status if execution is blocked or halted")
    rationale: str = Field(default="", description="Audit explanation describing the governance verdict")
