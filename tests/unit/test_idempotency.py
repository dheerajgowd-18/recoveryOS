"""Unit tests for IdempotencyTracker and EventStore in-memory abstractions."""
import asyncio
from datetime import datetime, timedelta
import pytest

from domain.aggregates import PaymentAggregate, SubscriptionAggregate
from domain.enums import PaymentState, SubscriptionState
from domain.events import PaymentEntity, PaymentEvent, SubscriptionEntity
from ingestion.idempotency import InMemoryIdempotencyTracker
from ingestion.store import InMemoryEventStore


class TestIdempotencyTracker:
    """Test suite for IdempotencyTracker operations."""

    def test_idempotency_tracker_lifecycle(self) -> None:
        async def _run() -> None:
            tracker = InMemoryIdempotencyTracker()
            event_id = "evt_test_123"

            # 1. Verify initially not processed
            assert await tracker.is_processed(event_id) is False
            assert await tracker.get_record(event_id) is None

            # 2. Mark as processed
            cached_data = {"status": "ok", "reconciled_state": "failed", "aggregate_version": "1"}
            record = await tracker.mark_processed(
                event_id=event_id,
                event_type="payment.failed",
                cached_response=cached_data,
            )

            assert record.event_id == event_id
            assert record.event_type == "payment.failed"
            assert record.cached_response == cached_data

            # 3. Verify subsequent check returns True and fetches record
            assert await tracker.is_processed(event_id) is True
            fetched = await tracker.get_record(event_id)
            assert fetched is not None
            assert fetched.event_id == event_id
            assert fetched.cached_response["reconciled_state"] == "failed"

        asyncio.run(_run())


class TestEventStore:
    """Test suite for InMemoryEventStore persistence and ordering."""

    def test_event_store_chronological_ordering(self) -> None:
        async def _run() -> None:
            store = InMemoryEventStore()
            t0 = datetime(2026, 1, 1, 10, 0, 0)
            t1 = t0 + timedelta(minutes=5)
            t2 = t0 + timedelta(minutes=10)

            evt1 = PaymentEvent(
                event_id="evt_early",
                event_type="payment.authorized",
                account_id="acc_1",
                occurred_at=t0,
                payment=PaymentEntity(
                    id="pay_ordered_1",
                    amount=1000,
                    status=PaymentState.AUTHORIZED,
                    created_at=int(t0.timestamp()),
                ),
            )
            evt2 = PaymentEvent(
                event_id="evt_late",
                event_type="payment.captured",
                account_id="acc_1",
                occurred_at=t2,
                payment=PaymentEntity(
                    id="pay_ordered_1",
                    amount=1000,
                    status=PaymentState.CAPTURED,
                    created_at=int(t2.timestamp()),
                ),
            )
            evt3 = PaymentEvent(
                event_id="evt_middle",
                event_type="payment.created",
                account_id="acc_1",
                occurred_at=t1,
                payment=PaymentEntity(
                    id="pay_ordered_1",
                    amount=1000,
                    status=PaymentState.CREATED,
                    created_at=int(t1.timestamp()),
                ),
            )

            # Append out of order
            await store.append(evt2)
            await store.append(evt1)
            await store.append(evt3)

            # Retrieve and check sorting
            events = await store.get_events_for_payment("pay_ordered_1")
            assert len(events) == 3
            assert events[0].event_id == "evt_early"
            assert events[1].event_id == "evt_middle"
            assert events[2].event_id == "evt_late"

        asyncio.run(_run())

    def test_payment_and_subscription_aggregate_snapshots(self) -> None:
        async def _run() -> None:
            store = InMemoryEventStore()

            # Payment snapshot
            payment_agg = PaymentAggregate(
                payment_id="pay_snap_1",
                amount=5000,
                current_state=PaymentState.CAPTURED,
                version=2,
            )
            await store.save_payment_aggregate(payment_agg)
            retrieved_pay = await store.get_payment_aggregate("pay_snap_1")
            assert retrieved_pay is not None
            assert retrieved_pay.payment_id == "pay_snap_1"
            assert retrieved_pay.current_state == PaymentState.CAPTURED
            assert retrieved_pay.version == 2

            # Subscription snapshot
            sub_agg = SubscriptionAggregate(
                subscription_id="sub_snap_1",
                plan_id="plan_pro",
                current_state=SubscriptionState.ACTIVE,
                version=1,
            )
            await store.save_subscription_aggregate(sub_agg)
            retrieved_sub = await store.get_subscription_aggregate("sub_snap_1")
            assert retrieved_sub is not None
            assert retrieved_sub.subscription_id == "sub_snap_1"
            assert retrieved_sub.current_state == SubscriptionState.ACTIVE

        asyncio.run(_run())
