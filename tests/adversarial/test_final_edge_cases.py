"""Exhaustive Adversarial Edge-Case Suite for Final Submission Freeze (Phase 17).

Covers all mandatory adversarial scenarios:
1. Late authorization invalidating scheduled retries.
2. Customer opt-out blocking customer-facing dunning at Governor and Firewall.
3. LLM/Policy engine outage failing closed safely to conservative abstention.
4. Duplicate webhook delivery with strict idempotency deduplication.
5. Out-of-order event reconciliation and state guardrails.
6. High-value transactions triggering human review escalation.
7. Negative uplift economic abstention eliminating destructive fees.
"""
import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from backend.services.ingestion_service import IngestionService
from domain.actions import Action
from domain.aggregates import PaymentAggregate
from domain.enums import ActionType, PaymentState, RevenueState
from domain.events import (
    ErrorDetail,
    PaymentContainer,
    PaymentEntity,
    PaymentEvent,
    WebhookPayload,
    WebhookPayloadContent,
)
from execution.simulator_executor import ExecutionFaultConfig, SimulatorExecutor
from governor.decision import GovernorDecisionResult
from governor.exceptions import (
    ActionBlockedError,
    ConsentViolationError,
    DuplicateExecutionError,
    PolicyOutageError,
)
from governor.firewall import CustomerConsentContext, ToolFirewall
from governor.policy import AutomationMode, MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from ingestion.idempotency import InMemoryIdempotencyTracker
from ingestion.reconciler import InvalidStateTransitionError, StateReconciler
from ingestion.store import InMemoryEventStore
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from planner.timing import ActionMechanism, TimingWindow
from policy.base import PolicyDecision
from policy.deterministic import DeterministicRecoveryPolicy
from scheduler.models import ScheduledAction, ScheduledActionStatus
from scheduler.service import ScheduledLifecycleService
from scheduler.store import InMemoryScheduledStore
from simulator.config import CustomerArchetype, FailureClass, SimulatedActionType, SimulatorConfig
from simulator.generator import Simulator


def create_mock_payment_failed_payload(
    event_id: str = "evt_adv_fail_01",
    payment_id: str = "pay_adv_001",
    amount: int = 150000,
    created_at: int = 1717200000,
) -> WebhookPayload:
    """Creates a mock payment.failed WebhookPayload."""
    return WebhookPayload(
        entity="event",
        account_id="acc_rzp_merchant_01",
        event="payment.failed",
        contains=["payment"],
        payload=WebhookPayloadContent(
            payment=PaymentContainer(
                entity=PaymentEntity(
                    id=payment_id,
                    amount=amount,
                    currency="INR",
                    status=PaymentState.FAILED,
                    created_at=created_at,
                    error=ErrorDetail(
                        code="GATEWAY_ERROR",
                        description="Bank gateway timeout",
                        source="bank",
                        step="payment_authorization",
                        reason="GATEWAY_TIMEOUT",
                    ),
                )
            )
        ),
        created_at=created_at,
    )


def create_mock_payment_captured_payload(
    event_id: str = "evt_adv_cap_01",
    payment_id: str = "pay_adv_001",
    amount: int = 150000,
    created_at: int = 1717200500,
) -> WebhookPayload:
    """Creates a mock payment.captured WebhookPayload."""
    return WebhookPayload(
        entity="event",
        account_id="acc_rzp_merchant_01",
        event="payment.captured",
        contains=["payment"],
        payload=WebhookPayloadContent(
            payment=PaymentContainer(
                entity=PaymentEntity(
                    id=payment_id,
                    amount=amount,
                    currency="INR",
                    status=PaymentState.CAPTURED,
                    captured=True,
                    created_at=created_at,
                )
            )
        ),
        created_at=created_at,
    )


class TestFinalAdversarialEdgeCases:
    """Mandatory adversarial test suite for Phase 17."""

    def test_late_authorization_invalidates_scheduled_retry(self):
        """A scheduled retry is invalidated when a late capture webhook is received prior to execution."""
        store = InMemoryScheduledStore()
        service = ScheduledLifecycleService(store=store)

        proposal = PolicyDecision(
            action_type=SimulatedActionType.RETRY_LATER,
            confidence=0.85,
            rationale="Delayed retry candidate",
            policy_name="POL_ADV",
            expected_incremental_value_paise=25000,
            expected_net_value_paise=24980,
        )
        context = ObservableRecoveryContext(
            scenario_id="scen_adv_stale",
            payment_id="pay_adv_stale_01",
            amount_in_paise=150000,
            attempt_count=1,
        )
        agg_v1 = PaymentAggregate(
            payment_id="pay_adv_stale_01",
            current_state=PaymentState.FAILED,
            amount=150000,
            currency="INR",
            version=1,
            created_at=datetime.fromtimestamp(1717200000, tz=timezone.utc).replace(tzinfo=None),
            updated_at=datetime.fromtimestamp(1717200000, tz=timezone.utc).replace(tzinfo=None),
        )
        policy = MerchantPolicy(max_retries=3)

        # 1. Schedule a delayed retry
        scheduled_action = service.schedule_action(
            decision=proposal,
            context=context,
            aggregate=agg_v1,
            policy=policy,
            current_epoch=1717200000,
            timing_window=TimingWindow.PLUS_2H,
        )
        assert scheduled_action.status == ScheduledActionStatus.PENDING

        # 2. Payment captured out-of-band: aggregate updated to version 2, state CAPTURED
        captured_aggregate = PaymentAggregate(
            payment_id="pay_adv_stale_01",
            current_state=PaymentState.CAPTURED,
            amount=150000,
            currency="INR",
            version=2,
            created_at=datetime.fromtimestamp(1717200000, tz=timezone.utc).replace(tzinfo=None),
            updated_at=datetime.fromtimestamp(1717203600, tz=timezone.utc).replace(tzinfo=None),
        )

        # 3. Attempt revalidation -> Must detect terminal state and return valid=False
        is_valid, reason, reason_codes = service.revalidate_and_check_executable(
            scheduled_action=scheduled_action,
            current_aggregate=captured_aggregate,
            consent=CustomerConsentContext(customer_id="cust_01"),
            current_epoch=1717207200,
        )
        assert is_valid is False
        assert "REVENUE_ALREADY_RECOVERED" in reason_codes

        # 4. Invalidate action
        inv_action = service.invalidate_action(scheduled_action.scheduled_action_id, reason, reason_codes)
        assert inv_action.status == ScheduledActionStatus.INVALIDATED

    def test_customer_opt_out_blocked_at_governor_and_firewall(self):
        """Customer opt-out blocks customer-facing payment links at both Governor and ToolFirewall."""
        governor = RecoveryGovernor(merchant_policy=MerchantPolicy(max_retries=3, max_contacts_24h=2))
        firewall = ToolFirewall()

        context = ObservableRecoveryContext(
            scenario_id="scen_optout_01",
            payment_id="pay_optout_01",
            customer_id="cust_optout_01",
            amount_in_paise=50000,
            attempt_count=1,
            contacts_in_last_24h=0,
            contacts_in_last_7d=0,
        )
        diagnosis = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.INSUFFICIENT_FUNDS,
            confidence=0.85,
            evidence_codes=["OBS_INSUFFICIENT_FUNDS"],
            recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK],
            rationale="Insufficient funds diagnosis",
            diagnosis_source="deterministic_offline",
        )
        proposal = PolicyDecision(
            action_type=SimulatedActionType.PAYMENT_LINK,
            confidence=0.85,
            rationale="Send link",
            policy_name="POL_ADV",
            expected_incremental_value_paise=10000,
            expected_net_value_paise=9900,
        )

        opted_out_consent = CustomerConsentContext(
            customer_id="cust_optout_01",
            is_globally_opted_out=True,
        )

        # 1. Recovery Governor evaluation
        gov_dec = governor.evaluate(context, diagnosis, proposal, consent=opted_out_consent)
        assert gov_dec.decision_result == GovernorDecisionResult.DENY
        assert "CUSTOMER_OPTED_OUT" in gov_dec.reason_codes
        assert gov_dec.selected_action == SimulatedActionType.NO_ACTION

        # 2. Tool Firewall independent gating
        with pytest.raises(ConsentViolationError):
            firewall.validate_and_gate(
                action=Action(action_id="act_01", action_type=ActionType.SEND_DUNNING_EMAIL, target_id="pay_01"),
                consent=opted_out_consent,
                execution_key="idemp_optout_01",
            )

    def test_policy_engine_outage_fails_closed_safely(self):
        """When the policy engine or LLM raises an outage, the system fails closed safely to NO_ACTION."""
        governor = RecoveryGovernor()

        context = ObservableRecoveryContext(
            scenario_id="scen_outage_01",
            payment_id="pay_outage_01",
            amount_in_paise=50000,
            attempt_count=1,
        )
        diagnosis = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.85,
            evidence_codes=["OBS_GATEWAY_ERROR"],
            recommended_candidate_actions=[SimulatedActionType.RETRY_LATER],
            rationale="Transient gateway error",
            diagnosis_source="deterministic_offline",
        )
        proposal = PolicyDecision(
            action_type=SimulatedActionType.RETRY_LATER,
            confidence=0.85,
            rationale="Retry later",
            policy_name="POL_ADV",
            expected_incremental_value_paise=15000,
            expected_net_value_paise=14980,
        )

        decision = governor.evaluate(
            context=context,
            diagnosis=diagnosis,
            proposal=proposal,
            policy_healthy=False,
        )
        assert decision.decision_result == GovernorDecisionResult.DENY
        assert "POLICY_UNAVAILABLE_FAIL_CLOSED" in decision.reason_codes
        assert decision.stop_reason == "POLICY_OUTAGE"

    def test_duplicate_webhook_idempotency_safeguard(self):
        """Delivering the exact same webhook twice is deduplicated without mutating state or triggering duplicate actions."""
        event_store = InMemoryEventStore()
        tracker = InMemoryIdempotencyTracker()
        ingestion = IngestionService(
            event_store=event_store,
            idempotency_tracker=tracker,
        )

        payload = create_mock_payment_failed_payload(event_id="evt_dup_001", payment_id="pay_dup_001")

        # First ingestion
        res1 = asyncio.run(ingestion.process_webhook(payload))
        assert res1.status == "ok"
        assert res1.is_duplicate is False
        assert res1.aggregate_version == 1

        # Second ingestion of same payload
        res2 = asyncio.run(ingestion.process_webhook(payload))
        assert res2.status == "ok"
        assert res2.is_duplicate is True
        assert res2.aggregate_version == 1

        # Verify only 1 event in store
        events = asyncio.run(event_store.get_events_for_payment("pay_dup_001"))
        assert len(events) == 1

    def test_out_of_order_event_reconciliation(self):
        """StateReconciler rejects invalid state transitions (e.g., FAILED after CAPTURED)."""
        reconciler = StateReconciler()

        cap_payload = create_mock_payment_captured_payload(payment_id="pay_ooo_01", created_at=1717200100)
        fail_payload = create_mock_payment_failed_payload(payment_id="pay_ooo_01", created_at=1717200200)

        # 1. Ingest captured event
        cap_event = PaymentEvent(
            event_id="evt_cap_01",
            event_type="payment.captured",
            account_id="acc_01",
            occurred_at=datetime.fromtimestamp(1717200100, tz=timezone.utc).replace(tzinfo=None),
            payment=cap_payload.payload.payment.entity,
        )
        agg1 = reconciler.reconcile_payment(None, cap_event)
        assert agg1.current_state == PaymentState.CAPTURED

        # 2. Ingest failure event on already captured payment -> Must raise InvalidStateTransitionError
        fail_event = PaymentEvent(
            event_id="evt_fail_01",
            event_type="payment.failed",
            account_id="acc_01",
            occurred_at=datetime.fromtimestamp(1717200200, tz=timezone.utc).replace(tzinfo=None),
            payment=fail_payload.payload.payment.entity,
        )
        with pytest.raises(InvalidStateTransitionError):
            reconciler.reconcile_payment(agg1, fail_event)

    def test_high_value_transaction_human_review_escalation(self):
        """Transactions exceeding the high-value merchant threshold are escalated to human review."""
        policy = MerchantPolicy(
            human_review_amount_threshold_paise=500000,  # ₹5,000 threshold
            max_automatic_action_amount_paise=10000000,   # ₹100,000 cap
        )
        governor = RecoveryGovernor(merchant_policy=policy)

        context = ObservableRecoveryContext(
            scenario_id="scen_high_val_01",
            payment_id="pay_high_val_01",
            amount_in_paise=1000000,  # ₹10,000 > ₹5,000 threshold
            attempt_count=1,
            error_code="GATEWAY_ERROR",
        )
        diagnosis = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.85,
            evidence_codes=["OBS_GATEWAY_ERROR"],
            recommended_candidate_actions=[SimulatedActionType.RETRY_LATER],
            rationale="High value gateway retry",
            diagnosis_source="deterministic_offline",
        )
        proposal = PolicyDecision(
            action_type=SimulatedActionType.RETRY_LATER,
            confidence=0.85,
            rationale="Retry high value",
            policy_name="POL_ADV",
            expected_incremental_value_paise=50000,
            expected_net_value_paise=49980,
        )

        decision = governor.evaluate(context, diagnosis, proposal)
        assert decision.decision_result == GovernorDecisionResult.ESCALATE
        assert "HUMAN_REVIEW_REQUIRED_BY_AMOUNT" in decision.reason_codes
        assert decision.human_review_reason is not None

    def test_negative_uplift_causes_governor_abstention(self):
        """Actions with negative expected incremental uplift trigger deliberate ABSTAIN."""
        governor = RecoveryGovernor()

        context = ObservableRecoveryContext(
            scenario_id="scen_neg_uplift_01",
            payment_id="pay_neg_uplift_01",
            amount_in_paise=1000,  # ₹10 micro-transaction
            attempt_count=1,
            error_code="GATEWAY_ERROR",
        )
        diagnosis = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.80,
            evidence_codes=["OBS_GATEWAY_ERROR"],
            recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK],
            rationale="High confidence diagnosis but negative net uplift",
            diagnosis_source="deterministic_offline",
        )
        proposal = PolicyDecision(
            action_type=SimulatedActionType.PAYMENT_LINK,
            confidence=0.80,
            rationale="Negative net return",
            policy_name="POL_ADV",
            reason_codes=["NEGATIVE_INCREMENTAL_UPLIFT"],
            expected_incremental_value_paise=-50,
            expected_net_value_paise=-150,
        )

        decision = governor.evaluate(context, diagnosis, proposal)
        assert decision.decision_result == GovernorDecisionResult.ABSTAIN
        assert "NEGATIVE_INCREMENTAL_UPLIFT" in decision.reason_codes
        assert decision.stop_reason == "POLICY_ABSTAINED"
