"""Unit tests for domain enums, models, and mock adapter."""
import asyncio
from datetime import datetime
import pytest
from pydantic import ValidationError

from domain.actions import Action, ActionParams, Decision, GuardrailCheckResult
from domain.enums import (
    ActionStatus,
    ActionType,
    DecisionType,
    PaymentState,
    RevenueState,
    SubscriptionState,
)
from domain.events import (
    PaymentContainer,
    PaymentEntity,
    PaymentEvent,
    SubscriptionContainer,
    SubscriptionEntity,
    WebhookPayload,
    WebhookPayloadContent,
)
from execution.mock_adapter import MockAdapter


class TestDomainEnums:
    """Test domain enumeration definitions and string semantics."""

    def test_revenue_states(self) -> None:
        assert RevenueState.HEALTHY == "healthy"
        assert RevenueState.AT_RISK == "at_risk"
        assert RevenueState.CRITICAL == "critical"
        assert RevenueState.LOST == "lost"
        assert RevenueState.RECOVERED == "recovered"
        assert len(RevenueState) == 5

    def test_payment_states(self) -> None:
        assert PaymentState.CREATED == "created"
        assert PaymentState.AUTHORIZED == "authorized"
        assert PaymentState.CAPTURED == "captured"
        assert PaymentState.REFUNDED == "refunded"
        assert PaymentState.FAILED == "failed"
        assert len(PaymentState) == 5

    def test_subscription_states(self) -> None:
        expected = ["created", "authenticated", "active", "pending", "halted", "cancelled", "completed", "expired"]
        for val in expected:
            assert SubscriptionState(val).value == val
        assert len(SubscriptionState) == 8

    def test_action_types(self) -> None:
        assert ActionType.RETRY_PAYMENT == "retry_payment"
        assert ActionType.SEND_DUNNING_EMAIL == "send_dunning_email"
        assert ActionType.SEND_WHATSAPP_REMINDER == "send_whatsapp_reminder"
        assert ActionType.PAUSE_SUBSCRIPTION == "pause_subscription"
        assert ActionType.CANCEL_SUBSCRIPTION == "cancel_subscription"
        assert ActionType.OFFER_DISCOUNT == "offer_discount"

    def test_decision_types(self) -> None:
        assert DecisionType.IMMEDIATE_RETRY == "immediate_retry"
        assert DecisionType.SCHEDULED_RETRY == "scheduled_retry"
        assert DecisionType.NOTIFY_CUSTOMER == "notify_customer"
        assert DecisionType.ESCALATE_TO_HUMAN == "escalate_to_human"
        assert DecisionType.HALT_RECOVERY == "halt_recovery"
        assert DecisionType.OFFER_INCENTIVE == "offer_incentive"

    def test_action_statuses(self) -> None:
        assert ActionStatus.PENDING == "pending"
        assert ActionStatus.EXECUTED == "executed"
        assert ActionStatus.FAILED == "failed"
        assert ActionStatus.CANCELLED == "cancelled"


class TestDomainModels:
    """Test Pydantic domain models parsing and validation boundaries."""

    def test_payment_entity_valid(self) -> None:
        payment = PaymentEntity(
            id="pay_test_123",
            amount=150000,
            currency="INR",
            status=PaymentState.FAILED,
            created_at=1700000000,
            error_code="BAD_REQUEST_ERROR",
            error_description="Card declined",
        )
        assert payment.id == "pay_test_123"
        assert payment.amount == 150000
        assert payment.status == PaymentState.FAILED
        assert payment.currency == "INR"

    def test_payment_entity_invalid_amount(self) -> None:
        with pytest.raises(ValidationError):
            PaymentEntity(
                id="pay_test_123",
                amount=-50,
                currency="INR",
                status=PaymentState.FAILED,
                created_at=1700000000,
            )

    def test_payment_entity_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            PaymentEntity(
                id="pay_test_123",
                amount=5000,
                currency="INR",
                status="unknown_status",  # type: ignore
                created_at=1700000000,
            )

    def test_subscription_entity_valid(self) -> None:
        sub = SubscriptionEntity(
            id="sub_test_123",
            plan_id="plan_monthly_pro",
            customer_id="cust_test_456",
            status=SubscriptionState.ACTIVE,
            created_at=1700000000,
        )
        assert sub.id == "sub_test_123"
        assert sub.status == SubscriptionState.ACTIVE
        assert sub.quantity == 1

    def test_subscription_entity_invalid_quantity(self) -> None:
        with pytest.raises(ValidationError):
            SubscriptionEntity(
                id="sub_test_123",
                plan_id="plan_monthly_pro",
                status=SubscriptionState.ACTIVE,
                quantity=0,
                created_at=1700000000,
            )

    def test_webhook_payload_valid(self) -> None:
        raw = {
            "entity": "event",
            "account_id": "acc_test_merchant",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test_001",
                        "entity": "payment",
                        "amount": 299900,
                        "currency": "INR",
                        "status": "failed",
                        "created_at": 1700000000,
                        "email": "user@example.com",
                    }
                }
            },
            "created_at": 1700000000,
        }
        parsed = WebhookPayload.model_validate(raw)
        assert parsed.account_id == "acc_test_merchant"
        assert parsed.event == "payment.failed"
        assert parsed.payload.payment is not None
        assert parsed.payload.payment.entity.id == "pay_test_001"
        assert parsed.payload.payment.entity.status == PaymentState.FAILED

    def test_webhook_payload_invalid_structure(self) -> None:
        with pytest.raises(ValidationError):
            WebhookPayload.model_validate({"entity": "event", "account_id": "acc_123"})

    def test_payment_event_valid(self) -> None:
        event = PaymentEvent(
            event_id="evt_unique_123",
            event_type="payment.failed",
            account_id="acc_merchant_1",
            occurred_at=datetime.utcnow(),
            payment=PaymentEntity(
                id="pay_evt_1",
                amount=10000,
                currency="INR",
                status=PaymentState.FAILED,
                created_at=1700000000,
            ),
        )
        assert event.event_id == "evt_unique_123"
        assert event.payment is not None

    def test_payment_event_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            PaymentEvent(
                event_id="evt_1",
                event_type="payment.failed",
                account_id="acc_1",
                occurred_at=datetime.utcnow(),
                extra_unknown_field="not_allowed",  # type: ignore
            )

    def test_action_and_decision_valid(self) -> None:
        action = Action(
            action_id="act_retry_1",
            action_type=ActionType.RETRY_PAYMENT,
            target_id="inv_test_1",
            parameters=ActionParams(retry_delay_seconds=3600),
            status=ActionStatus.PENDING,
        )
        assert action.status == ActionStatus.PENDING
        assert action.parameters.retry_delay_seconds == 3600

        decision = Decision(
            decision_id="dec_001",
            event_id="evt_001",
            customer_id="cust_001",
            decision_type=DecisionType.SCHEDULED_RETRY,
            confidence_score=0.92,
            rationale="Temporary insufficient funds detected; high recovery probability on automated retry.",
            chosen_action=action,
            guardrail_checks=[
                GuardrailCheckResult(rule_name="max_retries_per_invoice", passed=True, reason="1/3 attempts used"),
                GuardrailCheckResult(rule_name="cooling_off_period", passed=True, reason="Sufficient interval"),
            ],
        )
        assert decision.confidence_score == 0.92
        assert len(decision.guardrail_checks) == 2
        assert decision.chosen_action is not None

    def test_decision_invalid_confidence_range(self) -> None:
        with pytest.raises(ValidationError):
            Decision(
                decision_id="dec_001",
                event_id="evt_001",
                decision_type=DecisionType.IMMEDIATE_RETRY,
                confidence_score=1.5,  # Exceeds max 1.0
                rationale="Invalid confidence score",
            )


class TestMockAdapter:
    """Test MockAdapter implementation against interface specifications."""

    def test_fetch_existing_and_missing_payment(self) -> None:
        async def _run():
            adapter = MockAdapter()
            payment = await adapter.fetch_payment("pay_mock_12345")
            assert payment is not None
            assert payment.id == "pay_mock_12345"
            assert payment.status == PaymentState.FAILED

            missing = await adapter.fetch_payment("pay_non_existent")
            assert missing is None

        asyncio.run(_run())

    def test_fetch_existing_and_missing_subscription(self) -> None:
        async def _run():
            adapter = MockAdapter()
            sub = await adapter.fetch_subscription("sub_mock_12345")
            assert sub is not None
            assert sub.id == "sub_mock_12345"
            assert sub.status == SubscriptionState.ACTIVE

            missing = await adapter.fetch_subscription("sub_non_existent")
            assert missing is None

        asyncio.run(_run())

    def test_retry_invoice_payment(self) -> None:
        async def _run():
            adapter = MockAdapter()
            result = await adapter.retry_invoice_payment("inv_mock_999")
            assert result is True
            assert "inv_mock_999" in adapter.retry_requests

        asyncio.run(_run())

    def test_pause_and_cancel_subscription(self) -> None:
        async def _run():
            adapter = MockAdapter()
            paused = await adapter.pause_subscription("sub_mock_12345")
            assert paused is not None
            assert paused.status == SubscriptionState.HALTED

            # Test pause non-existent
            assert await adapter.pause_subscription("sub_non_existent") is None

            cancelled = await adapter.cancel_subscription("sub_mock_12345")
            assert cancelled is not None
            assert cancelled.status == SubscriptionState.CANCELLED
            assert cancelled.ended_at is not None

            # Test cancel non-existent
            assert await adapter.cancel_subscription("sub_non_existent") is None

        asyncio.run(_run())

    def test_execute_action(self) -> None:
        async def _run():
            adapter = MockAdapter()
            action = Action(
                action_id="act_exec_001",
                action_type=ActionType.RETRY_PAYMENT,
                target_id="inv_mock_123",
                parameters=ActionParams(retry_delay_seconds=0),
            )
            executed = await adapter.execute_action(action)
            assert executed.status == ActionStatus.EXECUTED
            assert len(adapter.executed_actions) == 1
            assert "inv_mock_123" in adapter.retry_requests

        asyncio.run(_run())
