"""Domain enums for RecoveryOS."""
from enum import Enum


class RevenueState(str, Enum):
    """High-level revenue health state of a customer account or subscription."""
    HEALTHY = "healthy"
    AT_RISK = "at_risk"
    CRITICAL = "critical"
    LOST = "lost"
    RECOVERED = "recovered"


class PaymentState(str, Enum):
    """Razorpay payment status states."""
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    FAILED = "failed"


class SubscriptionState(str, Enum):
    """Razorpay subscription lifecycle states."""
    CREATED = "created"
    AUTHENTICATED = "authenticated"
    ACTIVE = "active"
    PENDING = "pending"
    HALTED = "halted"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    EXPIRED = "expired"


class ActionType(str, Enum):
    """Types of autonomous recovery actions that can be triggered."""
    RETRY_PAYMENT = "retry_payment"
    SEND_DUNNING_EMAIL = "send_dunning_email"
    SEND_WHATSAPP_REMINDER = "send_whatsapp_reminder"
    PAUSE_SUBSCRIPTION = "pause_subscription"
    CANCEL_SUBSCRIPTION = "cancel_subscription"
    OFFER_DISCOUNT = "offer_discount"


class DecisionType(str, Enum):
    """Autonomous governance decisions produced by the recovery agent."""
    IMMEDIATE_RETRY = "immediate_retry"
    SCHEDULED_RETRY = "scheduled_retry"
    NOTIFY_CUSTOMER = "notify_customer"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    HALT_RECOVERY = "halt_recovery"
    OFFER_INCENTIVE = "offer_incentive"


class ActionStatus(str, Enum):
    """Execution status of an action."""
    PENDING = "pending"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"
