"""Scheduled action models, statuses, and data structures."""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from planner.timing import TimingWindow
from simulator.config import SimulatedActionType


class ScheduledActionStatus(str, Enum):
    """Lifecycle status of a scheduled autonomous recovery action."""
    PENDING = "PENDING"          # Scheduled and waiting for execution window
    DUE = "DUE"                  # Execution window reached; ready for revalidation & execution
    EXECUTED = "EXECUTED"        # Successfully revalidated, passed through firewall, and executed
    CANCELLED = "CANCELLED"      # Explicitly cancelled by operator or policy
    INVALIDATED = "INVALIDATED"  # Stale state detected upon due revalidation (e.g. captured or version mismatch)
    EXPIRED = "EXPIRED"          # Recovery window expired before execution could take place


class ScheduledAction(BaseModel):
    """Immutable scheduled action entity tracking expected state version and execution timeline."""
    model_config = ConfigDict(extra="forbid")

    scheduled_action_id: str = Field(..., description="Unique scheduled action identifier")
    decision_id: str = Field(..., description="Associated policy decision identifier")
    payment_id: str = Field(..., description="Target payment identifier")
    action_type: SimulatedActionType = Field(..., description="Action mechanism scheduled for execution")
    timing_window: TimingWindow = Field(default=TimingWindow.IMMEDIATE, description="Timing window bucket")
    delay_seconds: int = Field(default=0, ge=0, description="Scheduled delay in seconds from creation")
    scheduled_at_epoch: int = Field(..., ge=0, description="Epoch timestamp at which action becomes due")
    expires_at_epoch: int = Field(..., ge=0, description="Epoch timestamp beyond which action is expired")
    expected_state_version: int = Field(default=1, ge=1, description="Expected aggregate state version at creation")
    idempotency_key: str = Field(..., description="Deduplication key preventing duplicate schedules")
    status: ScheduledActionStatus = Field(default=ScheduledActionStatus.PENDING, description="Current lifecycle state")
    reason_codes: List[str] = Field(default_factory=list, description="Audit reason codes for scheduling and invalidation")
    created_at: int = Field(..., ge=0, description="Epoch timestamp of schedule creation")
    invalidation_reason: Optional[str] = Field(default=None, description="Detailed explanation if invalidated or expired")
    execution_key: Optional[str] = Field(default=None, description="Idempotent execution key if dispatched to firewall")
