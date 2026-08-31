"""Strict Pydantic v2 event models for Razorpay webhook ingestion and financial state tracking."""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from domain.enums import PaymentState, SubscriptionState


class ErrorDetail(BaseModel):
    """Detailed error metadata returned by Razorpay for failed transactions."""
    model_config = ConfigDict(extra="ignore")

    code: Optional[str] = Field(default=None, description="Razorpay error code")
    description: Optional[str] = Field(default=None, description="Human readable failure reason")
    source: Optional[str] = Field(default=None, description="Source of error, e.g. bank, gateway")
    step: Optional[str] = Field(default=None, description="Payment step where failure occurred")
    reason: Optional[str] = Field(default=None, description="Underlying gateway failure reason")


class PaymentEntity(BaseModel):
    """Razorpay Payment Entity structure."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique payment identifier (e.g., pay_123456)")
    entity: str = Field(default="payment", description="Entity type name")
    amount: int = Field(..., ge=0, description="Amount in smallest currency unit (e.g. paise)")
    currency: str = Field(default="INR", min_length=3, max_length=3, description="ISO currency code")
    status: PaymentState = Field(..., description="Current payment state")
    order_id: Optional[str] = Field(default=None, description="Associated Razorpay order ID")
    invoice_id: Optional[str] = Field(default=None, description="Associated Razorpay invoice ID")
    international: bool = Field(default=False, description="Whether international card/method")
    method: Optional[str] = Field(default=None, description="Payment method (card, netbanking, upi, etc.)")
    amount_refunded: int = Field(default=0, ge=0, description="Amount refunded in smallest unit")
    refund_status: Optional[str] = Field(default=None, description="Refund status if refunded")
    captured: bool = Field(default=False, description="Whether the payment is captured")
    description: Optional[str] = Field(default=None, description="Payment description or reference")
    card_id: Optional[str] = Field(default=None, description="Masked card identifier")
    bank: Optional[str] = Field(default=None, description="Bank code")
    wallet: Optional[str] = Field(default=None, description="Wallet code")
    vpa: Optional[str] = Field(default=None, description="Virtual Payment Address for UPI")
    email: Optional[str] = Field(default=None, description="Customer email address")
    contact: Optional[str] = Field(default=None, description="Customer contact phone number")
    customer_id: Optional[str] = Field(default=None, description="Razorpay customer ID")
    error_code: Optional[str] = Field(default=None, description="Top-level error code")
    error_description: Optional[str] = Field(default=None, description="Top-level error description")
    error_source: Optional[str] = Field(default=None, description="Error source")
    error_step: Optional[str] = Field(default=None, description="Error step")
    error_reason: Optional[str] = Field(default=None, description="Error reason")
    error: Optional[ErrorDetail] = Field(default=None, description="Nested error details if present")
    created_at: int = Field(..., description="Epoch timestamp of payment creation")


class SubscriptionEntity(BaseModel):
    """Razorpay Subscription Entity structure."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique subscription identifier (e.g., sub_123456)")
    entity: str = Field(default="subscription", description="Entity type name")
    plan_id: str = Field(..., description="Razorpay plan ID")
    customer_id: Optional[str] = Field(default=None, description="Razorpay customer ID")
    status: SubscriptionState = Field(..., description="Current subscription state")
    current_start: Optional[int] = Field(default=None, description="Start timestamp of current billing cycle")
    current_end: Optional[int] = Field(default=None, description="End timestamp of current billing cycle")
    ended_at: Optional[int] = Field(default=None, description="Timestamp when subscription ended")
    quantity: int = Field(default=1, ge=1, description="Subscription seat/quantity count")
    charge_at: Optional[int] = Field(default=None, description="Next scheduled charge timestamp")
    start_at: Optional[int] = Field(default=None, description="Subscription start timestamp")
    end_at: Optional[int] = Field(default=None, description="Subscription expiry timestamp")
    auth_attempts: int = Field(default=0, ge=0, description="Number of authorization attempts")
    total_count: int = Field(default=0, ge=0, description="Total billing cycles")
    paid_count: int = Field(default=0, ge=0, description="Paid billing cycles")
    remaining_count: int = Field(default=0, ge=0, description="Remaining billing cycles")
    created_at: int = Field(..., description="Epoch timestamp of subscription creation")


class PaymentContainer(BaseModel):
    """Payload container for payment entity inside webhook."""
    model_config = ConfigDict(extra="ignore")
    entity: PaymentEntity


class SubscriptionContainer(BaseModel):
    """Payload container for subscription entity inside webhook."""
    model_config = ConfigDict(extra="ignore")
    entity: SubscriptionEntity


class WebhookPayloadContent(BaseModel):
    """Encapsulates the nested entities sent inside a Razorpay webhook."""
    model_config = ConfigDict(extra="ignore")

    payment: Optional[PaymentContainer] = Field(default=None, description="Payment wrapper if contained")
    subscription: Optional[SubscriptionContainer] = Field(default=None, description="Subscription wrapper if contained")


class WebhookPayload(BaseModel):
    """Top-level Razorpay Webhook Payload structure."""
    model_config = ConfigDict(extra="ignore")

    entity: str = Field(default="event", description="Entity type (usually 'event')")
    account_id: str = Field(..., description="Merchant Razorpay Account ID")
    event: str = Field(..., description="Event name (e.g., payment.failed, subscription.halted)")
    contains: List[str] = Field(..., min_length=1, description="List of contained entities in payload")
    payload: WebhookPayloadContent = Field(..., description="Nested entities map")
    created_at: int = Field(..., description="Event emission epoch timestamp")


class PaymentEvent(BaseModel):
    """Normalized internal Domain Event representation for RecoveryOS processing."""
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., description="Unique idempotency identifier for the event")
    event_type: str = Field(..., description="Razorpay event type string")
    account_id: str = Field(..., description="Merchant account ID")
    occurred_at: datetime = Field(..., description="Normalized UTC timestamp of event")
    payment: Optional[PaymentEntity] = Field(default=None, description="Associated payment entity")
    subscription: Optional[SubscriptionEntity] = Field(default=None, description="Associated subscription entity")
