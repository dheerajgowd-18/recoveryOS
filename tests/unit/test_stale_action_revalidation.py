"""Unit and integration tests for stale-action protection, out-of-band state changes, and event store revalidation."""
import time
import pytest

from agent.runtime import AgentRuntime
from backend.services.ingestion_service import IngestionService
from domain.aggregates import PaymentAggregate
from domain.enums import PaymentState
from domain.events import (
    ErrorDetail,
    PaymentContainer,
    PaymentEntity,
    PaymentEvent,
    WebhookPayload,
    WebhookPayloadContent,
)
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from scheduler.models import ScheduledAction, ScheduledActionStatus
from scheduler.service import ScheduledLifecycleService
from simulator.config import SimulatorConfig
from simulator.generator import Simulator


@pytest.fixture
def lifecycle_service() -> ScheduledLifecycleService:
    return ScheduledLifecycleService()


class TestStaleActionProtectionAndEventReconciliation:
    """Verifies that state changes happening between scheduling and execution invalidate actions without incurring cost."""

    @pytest.mark.anyio
    async def test_scheduled_action_invalidated_upon_out_of_band_capture(self, lifecycle_service):
        sim = Simulator()
        scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=5))
        scenario = scenarios[0]
        payment_id = scenario.event.payment.id

        ingestion = IngestionService()
        runtime = AgentRuntime(
            ingestion_service=ingestion,
            scheduler=lifecycle_service,
            diagnosis_provider=DeterministicDiagnosisProvider(),
        )

        # 1. Ingest initial failure event
        res = await runtime.run_recovery_loop(scenario)
        assert res.stop_reason in ("ACTION_SCHEDULED", "TERMINAL_STATE_REACHED", "NO_RISK_DETECTED", "CYCLE_COMPLETED")

        # 2. Customer settles payment out-of-band (captured webhook arrives)
        now_epoch = int(time.time())
        captured_entity = PaymentEntity(
            id=payment_id,
            amount=scenario.event.payment.amount,
            currency="INR",
            status=PaymentState.CAPTURED,
            method="upi",
            captured=True,
            created_at=now_epoch,
        )
        captured_payload = WebhookPayload(
            account_id="acc_test_merchant",
            event="payment.captured",
            created_at=now_epoch,
            contains=["payment"],
            payload=WebhookPayloadContent(
                payment=PaymentContainer(entity=captured_entity)
            ),
        )
        await ingestion.process_webhook(captured_payload)

        aggregate = await ingestion.event_store.get_payment_aggregate(payment_id)
        assert aggregate is not None
        assert aggregate.current_state == PaymentState.CAPTURED

        # 3. Simulate delayed action execution
        pending_actions = lifecycle_service.get_pending_actions()
        if pending_actions:
            action = pending_actions[0]
            is_valid, reason, reason_codes = lifecycle_service.revalidate_and_check_executable(
                scheduled_action=action,
                current_aggregate=aggregate,
                current_epoch=action.scheduled_at_epoch,
            )
            assert is_valid is False
            assert "REVENUE_ALREADY_RECOVERED" in reason_codes

    @pytest.mark.anyio
    async def test_duplicate_webhook_event_idempotency(self):
        """Verifies duplicate webhook payloads are rejected and state is not corrupted."""
        ingestion = IngestionService()
        now_epoch = int(time.time())
        failed_entity = PaymentEntity(
            id="pay_dup_01",
            amount=100000,
            currency="INR",
            status=PaymentState.FAILED,
            method="card",
            created_at=now_epoch,
            error_code="BAD_REQUEST_ERROR",
            error_description="Card declined",
        )
        payload = WebhookPayload(
            account_id="acc_test_merchant",
            event="payment.failed",
            created_at=now_epoch,
            contains=["payment"],
            payload=WebhookPayloadContent(
                payment=PaymentContainer(entity=failed_entity)
            ),
        )

        # First ingestion succeeds
        r1 = await ingestion.process_webhook(payload)
        assert r1.is_duplicate is False

        # Duplicate ingestion recognized
        r2 = await ingestion.process_webhook(payload)
        assert r2.is_duplicate is True
