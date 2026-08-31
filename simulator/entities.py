"""Synthetic entity generators emitting valid domain models for simulation and stress testing."""
from datetime import datetime, timezone
import random
from typing import Tuple
from pydantic import BaseModel, ConfigDict, Field

from domain.enums import PaymentState, SubscriptionState
from domain.events import (
    ErrorDetail,
    PaymentContainer,
    PaymentEntity,
    PaymentEvent,
    SubscriptionContainer,
    SubscriptionEntity,
    WebhookPayload,
    WebhookPayloadContent,
)
from simulator.archetypes import FAILURE_CLASS_BEHAVIORS
from simulator.config import CustomerArchetype, ScenarioConfig


class SimulatedCustomer(BaseModel):
    """Simulated customer profile representation."""
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    name: str
    email: str
    contact: str
    archetype: CustomerArchetype


class SyntheticEntityGenerator:
    """Generates strictly typed domain entities and Razorpay webhook payloads."""

    FIRST_NAMES = ["Aarav", "Aditi", "Rohan", "Priya", "Vikram", "Sneha", "Karan", "Ananya", "Rahul", "Pooja"]
    LAST_NAMES = ["Sharma", "Verma", "Patel", "Mehta", "Iyer", "Nair", "Reddy", "Gupta", "Deshmukh", "Singh"]
    DOMAINS = ["gmail.com", "outlook.com", "enterprise.in", "acme.corp", "startup.co"]

    def generate_customer(self, rng: random.Random, customer_id: str, archetype: CustomerArchetype) -> SimulatedCustomer:
        """Create a synthetic customer identity."""
        first = rng.choice(self.FIRST_NAMES)
        last = rng.choice(self.LAST_NAMES)
        domain = rng.choice(self.DOMAINS)
        email = f"{first.lower()}.{last.lower()}_{rng.randint(10, 99)}@{domain}"
        contact = f"+9198{rng.randint(10000000, 99999999)}"

        return SimulatedCustomer(
            customer_id=customer_id,
            name=f"{first} {last}",
            email=email,
            contact=contact,
            archetype=archetype,
        )

    def generate_payment_scenario(
        self,
        rng: random.Random,
        scenario: ScenarioConfig,
        customer: SimulatedCustomer,
        created_at_epoch: int,
    ) -> Tuple[PaymentEvent, WebhookPayload]:
        """Generate a synthetic failed payment event and matching Razorpay WebhookPayload."""
        payment_id = f"pay_sim_{scenario.scenario_id}_{rng.randint(1000, 9999)}"
        order_id = f"order_sim_{scenario.scenario_id}"
        invoice_id = f"inv_sim_{scenario.scenario_id}"
        card_id = f"card_sim_{rng.randint(100, 999)}"

        failure_behavior = FAILURE_CLASS_BEHAVIORS[scenario.failure_class]
        occurred_at = datetime.fromtimestamp(created_at_epoch, tz=timezone.utc).replace(tzinfo=None)

        error_detail = ErrorDetail(
            code=failure_behavior.base_error_code,
            description=failure_behavior.base_error_description,
            source=failure_behavior.error_source,
            step=failure_behavior.error_step,
            reason=failure_behavior.error_reason,
        )

        payment_entity = PaymentEntity(
            id=payment_id,
            entity="payment",
            amount=scenario.amount_in_paise,
            currency=scenario.currency,
            status=PaymentState.FAILED,
            order_id=order_id,
            invoice_id=invoice_id,
            international=False,
            method="card",
            amount_refunded=0,
            refund_status=None,
            captured=False,
            description=f"Subscription Recovery Simulation - Attempt {scenario.attempt_count}",
            card_id=card_id,
            bank=None,
            wallet=None,
            vpa=None,
            email=customer.email,
            contact=customer.contact,
            customer_id=customer.customer_id,
            error_code=error_detail.code,
            error_description=error_detail.description,
            error_source=error_detail.source,
            error_step=error_detail.step,
            error_reason=error_detail.reason,
            error=error_detail,
            created_at=created_at_epoch,
        )

        webhook_payload = WebhookPayload(
            entity="event",
            account_id=scenario.merchant_account_id,
            event="payment.failed",
            contains=["payment"],
            payload=WebhookPayloadContent(
                payment=PaymentContainer(entity=payment_entity)
            ),
            created_at=created_at_epoch,
        )

        event_id = f"evt_{scenario.merchant_account_id}_{payment_id}_payment.failed_{created_at_epoch}"
        payment_event = PaymentEvent(
            event_id=event_id,
            event_type="payment.failed",
            account_id=scenario.merchant_account_id,
            occurred_at=occurred_at,
            payment=payment_entity,
            subscription=None,
        )

        return payment_event, webhook_payload
