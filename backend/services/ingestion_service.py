"""Ingestion orchestration service coordinating cryptographic verification, idempotency, persistence, and state reconstruction."""
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from domain.aggregates import PaymentAggregate, SubscriptionAggregate
from domain.enums import PaymentState, SubscriptionState
from domain.events import PaymentEntity, PaymentEvent, SubscriptionEntity, WebhookPayload
from ingestion.idempotency import IdempotencyTracker, InMemoryIdempotencyTracker
from ingestion.reconciler import StateReconciler
from ingestion.store import EventStore, InMemoryEventStore


class IngestionResult(BaseModel):
    """Execution output returned by the IngestionService."""
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    event: str = Field(..., description="Razorpay event type")
    event_id: str = Field(..., description="Idempotent event identifier")
    is_duplicate: bool = Field(default=False, description="Whether event was already processed")
    entity_id: Optional[str] = Field(default=None, description="Primary entity identifier")
    reconciled_state: Optional[str] = Field(default=None, description="Resulting reconciled state")
    aggregate_version: Optional[int] = Field(default=None, description="Current aggregate version")


class IngestionService:
    """Orchestrates event intake, idempotency safeguards, and aggregate reconciliation."""

    def __init__(
        self,
        event_store: Optional[EventStore] = None,
        idempotency_tracker: Optional[IdempotencyTracker] = None,
        reconciler: Optional[StateReconciler] = None,
    ) -> None:
        self.event_store = event_store or InMemoryEventStore()
        self.idempotency_tracker = idempotency_tracker or InMemoryIdempotencyTracker()
        self.reconciler = reconciler or StateReconciler()

    def generate_event_id(self, payload: WebhookPayload) -> str:
        """Derive a deterministic unique event identifier for idempotency tracking."""
        entity_id = "unknown"
        if payload.payload.payment:
            entity_id = payload.payload.payment.entity.id
        elif payload.payload.subscription:
            entity_id = payload.payload.subscription.entity.id
        
        # Combine event name, entity ID, account ID, and epoch creation timestamp
        return f"evt_{payload.account_id}_{entity_id}_{payload.event}_{payload.created_at}"

    async def process_webhook(self, payload: WebhookPayload) -> IngestionResult:
        """Execute full idempotency-checked state reconstruction workflow.

        Steps:
        1. Check idempotency: Return cached receipt immediately if already processed.
        2. Construct canonical PaymentEvent domain model.
        3. Persist event to append-only EventStore stream.
        4. Reconcile aggregate state using deterministic StateReconciler.
        5. Persist updated aggregate state.
        6. Mark event as processed in IdempotencyTracker.
        """
        event_id = self.generate_event_id(payload)

        # 1. Idempotency Check
        if await self.idempotency_tracker.is_processed(event_id):
            record = await self.idempotency_tracker.get_record(event_id)
            cached_entity_id = record.cached_response.get("entity_id") if record else None
            cached_state = record.cached_response.get("reconciled_state") if record else None
            cached_version = int(record.cached_response.get("aggregate_version", 1)) if record and record.cached_response.get("aggregate_version") else None

            return IngestionResult(
                status="ok",
                event=payload.event,
                event_id=event_id,
                is_duplicate=True,
                entity_id=cached_entity_id,
                reconciled_state=cached_state,
                aggregate_version=cached_version,
            )

        occurred_at = datetime.fromtimestamp(payload.created_at, tz=timezone.utc).replace(tzinfo=None)

        # 2. Canonical Domain Event Construction
        payment_entity = payload.payload.payment.entity if payload.payload.payment else None
        sub_entity = payload.payload.subscription.entity if payload.payload.subscription else None

        domain_event = PaymentEvent(
            event_id=event_id,
            event_type=payload.event,
            account_id=payload.account_id,
            occurred_at=occurred_at,
            payment=payment_entity,
            subscription=sub_entity,
        )

        # 3. Append to EventStore
        await self.event_store.append(domain_event)

        reconciled_state: Optional[str] = None
        entity_id: Optional[str] = None
        aggregate_version: Optional[int] = None

        # 4 & 5. Reconcile & Persist Aggregates
        if payment_entity:
            entity_id = payment_entity.id
            existing_agg = await self.event_store.get_payment_aggregate(payment_entity.id)
            updated_agg = self.reconciler.reconcile_payment(existing_agg, domain_event)
            await self.event_store.save_payment_aggregate(updated_agg)
            reconciled_state = updated_agg.current_state.value
            aggregate_version = updated_agg.version

        elif sub_entity:
            entity_id = sub_entity.id
            existing_agg = await self.event_store.get_subscription_aggregate(sub_entity.id)
            updated_agg = self.reconciler.reconcile_subscription(existing_agg, domain_event)
            await self.event_store.save_subscription_aggregate(updated_agg)
            reconciled_state = updated_agg.current_state.value
            aggregate_version = updated_agg.version

        # 6. Mark Processed in IdempotencyTracker
        cached_response = {
            "status": "ok",
            "entity_id": str(entity_id) if entity_id else "",
            "reconciled_state": str(reconciled_state) if reconciled_state else "",
            "aggregate_version": str(aggregate_version) if aggregate_version else "1",
        }
        await self.idempotency_tracker.mark_processed(
            event_id=event_id,
            event_type=payload.event,
            cached_response=cached_response,
        )

        return IngestionResult(
            status="ok",
            event=payload.event,
            event_id=event_id,
            is_duplicate=False,
            entity_id=entity_id,
            reconciled_state=reconciled_state,
            aggregate_version=aggregate_version,
        )


# Singleton instance for dependency injection
_default_ingestion_service = IngestionService()


def get_ingestion_service() -> IngestionService:
    """Dependency provider returning singleton IngestionService."""
    return _default_ingestion_service
