"""Unit tests for Subscription and Recurring Revenue Recovery."""
from datetime import datetime, timezone
import pytest

from domain.aggregates import SubscriptionAggregate
from domain.enums import ActionType, PaymentState, SubscriptionState
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
from governor.decision import GovernorDecisionResult
from governor.recovery_governor import RecoveryGovernor
from ingestion.reconciler import StateReconciler
from intelligence.context import ObservableContextBuilder
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.schemas import DiagnosisLabel
from policy.deterministic import DeterministicRecoveryPolicy
from simulator.config import SimulatedActionType


def create_subscription_event(
    event_type: str,
    sub_id: str = "sub_test_001",
    status: SubscriptionState = SubscriptionState.ACTIVE,
    error_code: str = "MANDATE_INVALID",
) -> PaymentEvent:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sub = SubscriptionEntity(
        id=sub_id,
        entity="subscription",
        plan_id="plan_pro_monthly",
        customer_id="cust_sub_01",
        status=status,
        current_start=int(now.timestamp()),
        current_end=int(now.timestamp()) + 2592000,
        ended_at=None,
        quantity=1,
        notes={},
        charge_at=int(now.timestamp()),
        start_at=int(now.timestamp()),
        end_at=int(now.timestamp()) + 31536000,
        auth_attempts=1,
        total_count=12,
        paid_count=2,
        remaining_count=10,
        short_url=None,
        has_scheduled_changes=False,
        change_scheduled_at=None,
        source="api",
        payment_method="card",
        created_at=int(now.timestamp()),
    )
    payment = PaymentEntity(
        id=f"pay_{sub_id}_cycle3",
        entity="payment",
        amount=199900,  # ₹1,999.00
        currency="INR",
        status=PaymentState.FAILED,
        order_id="order_sub_01",
        invoice_id="inv_sub_01",
        international=False,
        method="card",
        amount_refunded=0,
        refund_status=None,
        captured=False,
        description="Subscription renewal charge",
        error=ErrorDetail(
            code=error_code,
            description="Recurring mandate is inactive or revoked",
            source="bank",
            step="mandate_execution",
            reason="mandate_revoked",
        ),
        created_at=int(now.timestamp()),
    )
    return PaymentEvent(
        event_id=f"evt_{sub_id}_{event_type}",
        event_type=event_type,
        account_id="acc_merchant_01",
        occurred_at=now,
        payment=payment,
        subscription=sub,
    )


class TestSubscriptionRecovery:
    """Validates recurring payment failure handling, mandate recovery, and subscription state lifecycle."""

    def test_subscription_state_reconciliation(self):
        reconciler = StateReconciler()
        evt_created = create_subscription_event("subscription.created", status=SubscriptionState.CREATED)
        agg = reconciler.reconcile_subscription(None, evt_created)
        assert agg.current_state == SubscriptionState.CREATED
        assert agg.version == 1

        # Advance to authenticated
        evt_auth = create_subscription_event("subscription.authenticated", status=SubscriptionState.AUTHENTICATED)
        agg = reconciler.reconcile_subscription(agg, evt_auth)
        assert agg.current_state == SubscriptionState.AUTHENTICATED
        assert agg.version == 2

        # Advance to active
        evt_act = create_subscription_event("subscription.activated", status=SubscriptionState.ACTIVE)
        agg = reconciler.reconcile_subscription(agg, evt_act)
        assert agg.current_state == SubscriptionState.ACTIVE

    def test_mandate_failure_diagnosis_and_recovery_policy(self):
        """When a recurring charge fails due to mandate issue, system diagnoses MANDATE_ISSUE and selects PAYMENT_LINK."""
        event = create_subscription_event("subscription.halted", status=SubscriptionState.HALTED, error_code="MANDATE_REVOKED")
        context = ObservableContextBuilder.build_from_payment_event(event=event)

        diag_provider = DeterministicDiagnosisProvider()
        diagnosis = diag_provider.diagnose_sync(context)

        assert diagnosis.diagnosis_label == DiagnosisLabel.MANDATE_ISSUE
        assert SimulatedActionType.PAYMENT_LINK in diagnosis.recommended_candidate_actions

        policy = DeterministicRecoveryPolicy()
        decision = policy.decide(context, diagnosis=diagnosis)

        assert decision.action_type == SimulatedActionType.PAYMENT_LINK
        assert decision.expected_net_value_paise > 0

        governor = RecoveryGovernor()
        gov_decision = governor.evaluate(context, diagnosis, decision)
        assert gov_decision.decision_result == GovernorDecisionResult.ALLOW
        assert gov_decision.selected_action == SimulatedActionType.PAYMENT_LINK
