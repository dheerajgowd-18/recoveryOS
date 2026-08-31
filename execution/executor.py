"""Abstract base classes and data contracts for autonomous recovery action execution."""
from abc import ABC, abstractmethod
from typing import Dict, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from domain.actions import Action
from domain.events import PaymentEvent, WebhookPayload
from simulator.config import SimulatedActionType
from simulator.generator import SimulatedScenario


class ExecutionContext(BaseModel):
    """Contextual metadata supplied to the recovery executor during an action dispatch."""
    model_config = ConfigDict(extra="forbid")

    scenario: SimulatedScenario = Field(..., description="Active simulation scenario context")
    attempt_count: int = Field(default=1, ge=1, description="Current dunning intervention index")
    current_epoch: int = Field(..., ge=0, description="Current simulated epoch timestamp")
    metadata: Dict[str, str] = Field(default_factory=dict, description="Arbitrary execution metadata")


class ExecutionResult(BaseModel):
    """Outcome payload emitted upon completing an action execution."""
    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="Whether action execution succeeded without infrastructure fault")
    action_type: SimulatedActionType = Field(..., description="Action dispatched")
    resulting_event: Optional[PaymentEvent] = Field(default=None, description="Resulting domain event")
    resulting_payload: Optional[WebhookPayload] = Field(default=None, description="Resulting raw webhook payload")
    recovered: bool = Field(default=False, description="Whether revenue capture was achieved")
    recovered_amount_paise: int = Field(default=0, ge=0, description="Amount successfully captured in paise")
    action_cost_paise: int = Field(default=0, ge=0, description="Direct cost of the action in paise")
    execution_timestamp_epoch: int = Field(..., ge=0, description="Epoch timestamp of execution")
    message: str = Field(default="", description="Execution summary or diagnostics")


class RecoveryExecutor(ABC):
    """Abstract interface defining the execution boundary for recovery actions."""

    @abstractmethod
    async def execute(
        self,
        action: Union[SimulatedActionType, Action],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute an autonomous recovery intervention against the gateway or simulation environment.

        Args:
            action: Selected recovery action.
            context: Scenario execution context.

        Returns:
            ExecutionResult containing resulting domain events and capture status.
        """
        pass
