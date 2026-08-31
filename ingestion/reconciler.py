"""State reconciliation engine resolving out-of-order, duplicate, and late events to compute deterministic financial states."""
import logging
from datetime import datetime
from typing import List, Optional, Set

from domain.aggregates import PaymentAggregate, SubscriptionAggregate
from domain.enums import PaymentState, SubscriptionState
from domain.events import PaymentEntity, PaymentEvent, SubscriptionEntity

logger = logging.getLogger("recoveryos.reconciler")


class ReconciliationError(Exception):
    """Base exception for state reconciliation failures."""
    pass


class InvalidStateTransitionError(ReconciliationError):
    """Raised when an illegal state transition is attempted in forward business time."""
    def __init__(self, entity_id: str, current_state: str, attempted_state: str, event_type: str) -> None:
        self.entity_id = entity_id
        self.current_state = current_state
        self.attempted_state = attempted_state
        self.event_type = event_type
        super().__init__(
            f"Invalid state transition for entity '{entity_id}': cannot transition from "
            f"'{current_state}' to '{attempted_state}' via event '{event_type}'."
        )


class StateReconciler:
    """Deterministic state machine reconciling payment and subscription event streams."""

    # Valid forward transitions for Payment states
    VALID_PAYMENT_TRANSITIONS = {
        PaymentState.CREATED: {PaymentState.AUTHORIZED, PaymentState.CAPTURED, PaymentState.FAILED},
        PaymentState.AUTHORIZED: {PaymentState.CAPTURED, PaymentState.FAILED},
        PaymentState.FAILED: {PaymentState.AUTHORIZED, PaymentState.CAPTURED, PaymentState.FAILED},
        PaymentState.CAPTURED: {PaymentState.REFUNDED},
        PaymentState.REFUNDED: set(),  # Terminal
    }

    # Valid forward transitions for Subscription states
    VALID_SUBSCRIPTION_TRANSITIONS = {
        SubscriptionState.CREATED: {SubscriptionState.AUTHENTICATED, SubscriptionState.ACTIVE, SubscriptionState.CANCELLED},
        SubscriptionState.AUTHENTICATED: {SubscriptionState.ACTIVE, SubscriptionState.HALTED, SubscriptionState.CANCELLED},
        SubscriptionState.ACTIVE: {SubscriptionState.ACTIVE, SubscriptionState.PENDING, SubscriptionState.HALTED, SubscriptionState.CANCELLED, SubscriptionState.COMPLETED},
        SubscriptionState.PENDING: {SubscriptionState.ACTIVE, SubscriptionState.HALTED, SubscriptionState.CANCELLED},
        SubscriptionState.HALTED: {SubscriptionState.ACTIVE, SubscriptionState.CANCELLED, SubscriptionState.HALTED},
        SubscriptionState.CANCELLED: set(),  # Terminal
        SubscriptionState.COMPLETED: set(),  # Terminal
        SubscriptionState.EXPIRED: set(),    # Terminal
    }

    @staticmethod
    def map_event_to_payment_state(event_type: str) -> Optional[PaymentState]:
        """Map Razorpay event string to target PaymentState."""
        mapping = {
            "payment.created": PaymentState.CREATED,
            "payment.authorized": PaymentState.AUTHORIZED,
            "payment.captured": PaymentState.CAPTURED,
            "payment.failed": PaymentState.FAILED,
            "payment.refunded": PaymentState.REFUNDED,
        }
        return mapping.get(event_type.lower())

    @staticmethod
    def map_event_to_subscription_state(event_type: str) -> Optional[SubscriptionState]:
        """Map Razorpay event string to target SubscriptionState."""
        mapping = {
            "subscription.created": SubscriptionState.CREATED,
            "subscription.authenticated": SubscriptionState.AUTHENTICATED,
            "subscription.activated": SubscriptionState.ACTIVE,
            "subscription.charged": SubscriptionState.ACTIVE,
            "subscription.pending": SubscriptionState.PENDING,
            "subscription.halted": SubscriptionState.HALTED,
            "subscription.paused": SubscriptionState.HALTED,
            "subscription.cancelled": SubscriptionState.CANCELLED,
            "subscription.completed": SubscriptionState.COMPLETED,
            "subscription.expired": SubscriptionState.EXPIRED,
        }
        return mapping.get(event_type.lower())

    def reconcile_payment(
        self,
        aggregate: Optional[PaymentAggregate],
        event: PaymentEvent,
    ) -> PaymentAggregate:
        """Apply an incoming payment event to a payment aggregate.

        Guarantees:
        1. Historical events are sorted by occurred_at timestamp.
        2. Terminal states (CAPTURED, REFUNDED) are never corrupted by late arrival of older failure events.
        3. Valid out-of-order events trigger timeline re-sorting and state reconstruction.
        4. Illegal state transitions in forward time raise InvalidStateTransitionError.
        """
        if not event.payment:
            raise ReconciliationError(f"PaymentEvent '{event.event_id}' does not contain payment entity payload.")

        payment = event.payment
        target_state = self.map_event_to_payment_state(event.event_type) or payment.status

        # 1. Initialize aggregate if not existing
        if aggregate is None:
            return PaymentAggregate(
                payment_id=payment.id,
                customer_id=payment.customer_id,
                order_id=payment.order_id,
                invoice_id=payment.invoice_id,
                amount=payment.amount,
                currency=payment.currency,
                current_state=target_state,
                version=1,
                timeline=[event],
                error_history=[payment.error] if payment.error else [],
                late_events_count=0,
                created_at=event.occurred_at,
                updated_at=datetime.utcnow(),
            )

        # 2. Combine and sort all events by occurred_at
        all_events = list(aggregate.timeline)
        # Avoid duplicate events in timeline
        if not any(e.event_id == event.event_id for e in all_events):
            all_events.append(event)
        all_events.sort(key=lambda e: e.occurred_at)

        latest_known_event = aggregate.timeline[-1] if aggregate.timeline else event

        # Check if the incoming event is a late-arriving event older than our latest known event
        is_late_event = event.occurred_at < latest_known_event.occurred_at

        # 3. Check for late arrival against terminal state (e.g. late payment.failed arriving after payment.captured)
        if aggregate.is_terminal and is_late_event:
            logger.warning(
                "Late event '%s' (occurred at %s) received for terminal payment '%s' (state: %s). Preserving terminal state.",
                event.event_type,
                event.occurred_at,
                aggregate.payment_id,
                aggregate.current_state,
            )
            updated_errors = list(aggregate.error_history)
            if payment.error:
                updated_errors.append(payment.error)

            return aggregate.model_copy(
                update={
                    "timeline": all_events,
                    "late_events_count": aggregate.late_events_count + 1,
                    "error_history": updated_errors,
                    "updated_at": datetime.utcnow(),
                }
            )

        # 4. Reconstruct state by replaying sorted event timeline
        reconstructed_state = aggregate.timeline[0].payment.status if aggregate.timeline and aggregate.timeline[0].payment else target_state
        error_history: List = []

        for evt in all_events:
            evt_target = self.map_event_to_payment_state(evt.event_type) or (evt.payment.status if evt.payment else reconstructed_state)
            if evt.payment and evt.payment.error:
                error_history.append(evt.payment.error)

            if evt_target == reconstructed_state:
                continue

            # Validate forward transition
            allowed = self.VALID_PAYMENT_TRANSITIONS.get(reconstructed_state, set())
            if evt_target not in allowed:
                # If this is the incoming event attempting an illegal forward transition, raise error
                if evt.event_id == event.event_id:
                    raise InvalidStateTransitionError(
                        entity_id=aggregate.payment_id,
                        current_state=reconstructed_state.value,
                        attempted_state=evt_target.value,
                        event_type=evt.event_type,
                    )
                # Otherwise, if an older historical anomaly exists in stream, log warning and preserve terminal
                if reconstructed_state in (PaymentState.CAPTURED, PaymentState.REFUNDED):
                    logger.warning(
                        "Ignoring anomalous transition from terminal %s to %s for payment %s",
                        reconstructed_state,
                        evt_target,
                        aggregate.payment_id,
                    )
                    continue
            else:
                reconstructed_state = evt_target

        # 5. Determine if state changed
        state_changed = reconstructed_state != aggregate.current_state
        new_version = aggregate.version + 1 if state_changed else aggregate.version

        return aggregate.model_copy(
            update={
                "current_state": reconstructed_state,
                "version": new_version,
                "timeline": all_events,
                "error_history": error_history,
                "late_events_count": aggregate.late_events_count + (1 if is_late_event else 0),
                "updated_at": datetime.utcnow(),
            }
        )

    def reconcile_subscription(
        self,
        aggregate: Optional[SubscriptionAggregate],
        event: PaymentEvent,
    ) -> SubscriptionAggregate:
        """Apply an incoming subscription or payment event to a subscription aggregate."""
        if not event.subscription:
            raise ReconciliationError(f"PaymentEvent '{event.event_id}' does not contain subscription entity payload.")

        sub = event.subscription
        target_state = self.map_event_to_subscription_state(event.event_type) or sub.status

        # 1. Initialize aggregate if not existing
        if aggregate is None:
            return SubscriptionAggregate(
                subscription_id=sub.id,
                customer_id=sub.customer_id,
                plan_id=sub.plan_id,
                current_state=target_state,
                version=1,
                timeline=[event],
                auth_attempts=sub.auth_attempts,
                total_count=sub.total_count,
                paid_count=sub.paid_count,
                remaining_count=sub.remaining_count,
                late_events_count=0,
                created_at=event.occurred_at,
                updated_at=datetime.utcnow(),
            )

        # 2. Combine and sort all events
        all_events = list(aggregate.timeline)
        if not any(e.event_id == event.event_id for e in all_events):
            all_events.append(event)
        all_events.sort(key=lambda e: e.occurred_at)

        latest_known_event = aggregate.timeline[-1] if aggregate.timeline else event
        is_late_event = event.occurred_at < latest_known_event.occurred_at

        # 3. Check for late arrival against terminal subscription state
        if aggregate.is_terminal and is_late_event:
            logger.warning(
                "Late event '%s' received for terminal subscription '%s'. Preserving terminal state %s.",
                event.event_type,
                aggregate.subscription_id,
                aggregate.current_state,
            )
            return aggregate.model_copy(
                update={
                    "timeline": all_events,
                    "late_events_count": aggregate.late_events_count + 1,
                    "updated_at": datetime.utcnow(),
                }
            )

        # 4. Reconstruct state by replaying sorted event timeline
        reconstructed_state = aggregate.timeline[0].subscription.status if aggregate.timeline and aggregate.timeline[0].subscription else target_state

        for evt in all_events:
            evt_target = self.map_event_to_subscription_state(evt.event_type) or (evt.subscription.status if evt.subscription else reconstructed_state)
            if evt_target == reconstructed_state:
                continue

            allowed = self.VALID_SUBSCRIPTION_TRANSITIONS.get(reconstructed_state, set())
            if evt_target not in allowed:
                if evt.event_id == event.event_id:
                    raise InvalidStateTransitionError(
                        entity_id=aggregate.subscription_id,
                        current_state=reconstructed_state.value,
                        attempted_state=evt_target.value,
                        event_type=evt.event_type,
                    )
                if aggregate.is_terminal:
                    continue
            else:
                reconstructed_state = evt_target

        state_changed = reconstructed_state != aggregate.current_state
        new_version = aggregate.version + 1 if state_changed else aggregate.version

        return aggregate.model_copy(
            update={
                "current_state": reconstructed_state,
                "version": new_version,
                "timeline": all_events,
                "auth_attempts": sub.auth_attempts or aggregate.auth_attempts,
                "paid_count": sub.paid_count or aggregate.paid_count,
                "remaining_count": sub.remaining_count or aggregate.remaining_count,
                "late_events_count": aggregate.late_events_count + (1 if is_late_event else 0),
                "updated_at": datetime.utcnow(),
            }
        )
