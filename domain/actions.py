"""Strict Pydantic v2 models for RecoveryOS decisions, actions, and governance guardrails."""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from domain.enums import ActionStatus, ActionType, DecisionType


class ActionParams(BaseModel):
    """Strongly-typed parameters for autonomous recovery actions."""
    model_config = ConfigDict(extra="forbid")

    retry_delay_seconds: Optional[int] = Field(default=None, ge=0, description="Delay before retrying invoice payment")
    communication_channel: Optional[str] = Field(default=None, description="Notification channel (email, sms, whatsapp)")
    template_id: Optional[str] = Field(default=None, description="Communication template identifier")
    custom_message: Optional[str] = Field(default=None, description="Custom message or context to include")
    discount_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Dunning discount incentive")
    target_amount: Optional[int] = Field(default=None, ge=0, description="Overridden amount in smallest currency unit")
    reason: Optional[str] = Field(default=None, description="Operator or agent reason for action")


class Action(BaseModel):
    """Autonomous or governed action definition to be executed by an adapter."""
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., description="Unique action identifier")
    action_type: ActionType = Field(..., description="Type of recovery action")
    target_id: str = Field(..., description="Target identifier (e.g. invoice_id, payment_id, sub_id)")
    parameters: ActionParams = Field(default_factory=ActionParams, description="Execution parameters")
    scheduled_at: Optional[datetime] = Field(default=None, description="Scheduled UTC execution timestamp")
    status: ActionStatus = Field(default=ActionStatus.PENDING, description="Current execution state")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="UTC creation timestamp")


class GuardrailCheckResult(BaseModel):
    """Guardrail compliance validation result for a recovery decision."""
    model_config = ConfigDict(extra="forbid")

    rule_name: str = Field(..., description="Name of safety guardrail rule")
    passed: bool = Field(..., description="Whether rule check passed")
    reason: Optional[str] = Field(default=None, description="Details or failure reason")


class Decision(BaseModel):
    """Autonomous governance decision produced by the recovery agent."""
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(..., description="Unique decision identifier")
    event_id: str = Field(..., description="ID of source event triggering this decision")
    customer_id: Optional[str] = Field(default=None, description="Customer account ID")
    decision_type: DecisionType = Field(..., description="Categorical recovery decision")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="AI model confidence between 0.0 and 1.0")
    rationale: str = Field(..., min_length=1, description="Audit rationale explaining why decision was taken")
    chosen_action: Optional[Action] = Field(default=None, description="Resulting action if decision triggers one")
    guardrail_checks: List[GuardrailCheckResult] = Field(default_factory=list, description="Audit trail of safety checks")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="UTC timestamp of decision")
