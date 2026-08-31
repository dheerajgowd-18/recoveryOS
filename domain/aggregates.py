"""Aggregate root domain models for payments and subscriptions with event history and state tracking."""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from domain.enums import PaymentState, SubscriptionState
from domain.events import ErrorDetail, PaymentEntity, PaymentEvent, SubscriptionEntity


class PaymentAggregate(BaseModel):
    """Aggregate root managing payment lifecycle, state transitions, and audit timeline."""
    model_config = ConfigDict(extra="forbid")

    payment_id: str = Field(..., description="Unique payment identifier (e.g. pay_123)")
    customer_id: Optional[str] = Field(default=None, description="Customer ID")
    order_id: Optional[str] = Field(default=None, description="Order ID")
    invoice_id: Optional[str] = Field(default=None, description="Invoice ID")
    amount: int = Field(..., ge=0, description="Amount in paise")
    currency: str = Field(default="INR", min_length=3, max_length=3)
    current_state: PaymentState = Field(..., description="Reconciled current payment state")
    version: int = Field(default=1, ge=1, description="Aggregate version incremented on state mutations")
    timeline: List[PaymentEvent] = Field(default_factory=list, description="Chronologically sorted event history")
    error_history: List[ErrorDetail] = Field(default_factory=list, description="Historical error details")
    late_events_count: int = Field(default=0, ge=0, description="Number of late/out-of-order events absorbed")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")

    @property
    def is_terminal(self) -> bool:
        """Indicate whether payment has reached a terminal financial state."""
        return self.current_state in (PaymentState.CAPTURED, PaymentState.REFUNDED)


class SubscriptionAggregate(BaseModel):
    """Aggregate root managing subscription lifecycle, dunning states, and recovery attempts."""
    model_config = ConfigDict(extra="forbid")

    subscription_id: str = Field(..., description="Unique subscription identifier (e.g. sub_123)")
    customer_id: Optional[str] = Field(default=None, description="Customer ID")
    plan_id: str = Field(..., description="Plan ID")
    current_state: SubscriptionState = Field(..., description="Reconciled current subscription state")
    version: int = Field(default=1, ge=1, description="Aggregate version incremented on state mutations")
    timeline: List[PaymentEvent] = Field(default_factory=list, description="Chronologically sorted event history")
    auth_attempts: int = Field(default=0, ge=0, description="Authorization attempts count")
    total_count: int = Field(default=0, ge=0, description="Total billing cycles")
    paid_count: int = Field(default=0, ge=0, description="Paid billing cycles")
    remaining_count: int = Field(default=0, ge=0, description="Remaining billing cycles")
    late_events_count: int = Field(default=0, ge=0, description="Number of late/out-of-order events absorbed")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")

    @property
    def is_terminal(self) -> bool:
        """Indicate whether subscription has reached a terminal lifecycle state."""
        return self.current_state in (
            SubscriptionState.CANCELLED,
            SubscriptionState.COMPLETED,
            SubscriptionState.EXPIRED,
        )
