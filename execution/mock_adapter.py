"""Mock implementation of RazorpayAdapter for testing and offline simulation without network calls."""
from datetime import datetime
from typing import Dict, List, Optional

from domain.actions import Action
from domain.enums import ActionStatus, ActionType, PaymentState, SubscriptionState
from domain.events import PaymentEntity, SubscriptionEntity
from execution.base import RazorpayAdapter


class MockAdapter(RazorpayAdapter):
    """In-memory mock adapter simulating Razorpay API behaviors."""

    def __init__(self) -> None:
        self._payments: Dict[str, PaymentEntity] = {}
        self._subscriptions: Dict[str, SubscriptionEntity] = {}
        self._executed_actions: List[Action] = []
        self._retry_requests: List[str] = []
        self._seed_default_data()

    def _seed_default_data(self) -> None:
        """Seed initial simulated records."""
        sample_payment = PaymentEntity(
            id="pay_mock_12345",
            entity="payment",
            amount=499900,
            currency="INR",
            status=PaymentState.FAILED,
            order_id="order_mock_123",
            invoice_id="inv_mock_123",
            international=False,
            method="card",
            amount_refunded=0,
            refund_status=None,
            captured=False,
            description="Monthly SaaS Pro Plan",
            card_id="card_mock_987",
            bank=None,
            wallet=None,
            vpa=None,
            email="founder@acme.corp",
            contact="+919876543210",
            customer_id="cust_mock_001",
            error_code="BAD_REQUEST_ERROR",
            error_description="Payment failed due to insufficient funds in customer card account.",
            error_source="bank",
            error_step="payment_authorization",
            error_reason="insufficient_funds",
            created_at=int(datetime.utcnow().timestamp()),
        )
        self._payments[sample_payment.id] = sample_payment

        sample_sub = SubscriptionEntity(
            id="sub_mock_12345",
            entity="subscription",
            plan_id="plan_mock_pro",
            customer_id="cust_mock_001",
            status=SubscriptionState.ACTIVE,
            current_start=int(datetime.utcnow().timestamp()) - 2592000,
            current_end=int(datetime.utcnow().timestamp()),
            ended_at=None,
            quantity=1,
            charge_at=int(datetime.utcnow().timestamp()),
            start_at=int(datetime.utcnow().timestamp()) - 2592000,
            end_at=None,
            auth_attempts=1,
            total_count=12,
            paid_count=1,
            remaining_count=11,
            created_at=int(datetime.utcnow().timestamp()) - 2592000,
        )
        self._subscriptions[sample_sub.id] = sample_sub

    def add_payment(self, payment: PaymentEntity) -> None:
        """Helper to seed/inject a payment entity into mock state."""
        self._payments[payment.id] = payment

    def add_subscription(self, subscription: SubscriptionEntity) -> None:
        """Helper to seed/inject a subscription entity into mock state."""
        self._subscriptions[subscription.id] = subscription

    @property
    def executed_actions(self) -> List[Action]:
        """Inspect executed actions history."""
        return list(self._executed_actions)

    @property
    def retry_requests(self) -> List[str]:
        """Inspect invoice retry requests history."""
        return list(self._retry_requests)

    async def fetch_payment(self, payment_id: str) -> Optional[PaymentEntity]:
        """Fetch payment details from mock store."""
        return self._payments.get(payment_id)

    async def fetch_subscription(self, subscription_id: str) -> Optional[SubscriptionEntity]:
        """Fetch subscription details from mock store."""
        return self._subscriptions.get(subscription_id)

    async def retry_invoice_payment(self, invoice_id: str) -> bool:
        """Simulate triggering a payment retry for an invoice."""
        self._retry_requests.append(invoice_id)
        return True

    async def pause_subscription(self, subscription_id: str) -> Optional[SubscriptionEntity]:
        """Simulate pausing a subscription."""
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            return None

        updated = sub.model_copy(update={"status": SubscriptionState.HALTED})
        self._subscriptions[subscription_id] = updated
        return updated

    async def cancel_subscription(self, subscription_id: str) -> Optional[SubscriptionEntity]:
        """Simulate cancelling a subscription."""
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            return None

        now = int(datetime.utcnow().timestamp())
        updated = sub.model_copy(update={"status": SubscriptionState.CANCELLED, "ended_at": now})
        self._subscriptions[subscription_id] = updated
        return updated

    async def execute_action(self, action: Action) -> Action:
        """Simulate execution of an autonomous recovery action."""
        if action.action_type == ActionType.RETRY_PAYMENT:
            await self.retry_invoice_payment(action.target_id)
        elif action.action_type == ActionType.PAUSE_SUBSCRIPTION:
            await self.pause_subscription(action.target_id)
        elif action.action_type == ActionType.CANCEL_SUBSCRIPTION:
            await self.cancel_subscription(action.target_id)
        
        executed_action = action.model_copy(update={"status": ActionStatus.EXECUTED})
        self._executed_actions.append(executed_action)
        return executed_action
