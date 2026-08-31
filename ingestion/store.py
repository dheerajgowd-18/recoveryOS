"""Event store abstractions and in-memory implementation for RecoveryOS event sourcing."""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from domain.aggregates import PaymentAggregate, SubscriptionAggregate
from domain.events import PaymentEvent


class EventStore(ABC):
    """Abstract interface for appending and querying domain events and aggregates."""

    @abstractmethod
    async def append(self, event: PaymentEvent) -> None:
        """Persist a domain event to the append-only event stream."""
        pass

    @abstractmethod
    async def get_events_for_payment(self, payment_id: str) -> List[PaymentEvent]:
        """Retrieve all events associated with a payment, ordered chronologically."""
        pass

    @abstractmethod
    async def get_events_for_subscription(self, subscription_id: str) -> List[PaymentEvent]:
        """Retrieve all events associated with a subscription, ordered chronologically."""
        pass

    @abstractmethod
    async def save_payment_aggregate(self, aggregate: PaymentAggregate) -> None:
        """Save or update a payment aggregate snapshot."""
        pass

    @abstractmethod
    async def get_payment_aggregate(self, payment_id: str) -> Optional[PaymentAggregate]:
        """Retrieve the current snapshot of a payment aggregate if present."""
        pass

    @abstractmethod
    async def save_subscription_aggregate(self, aggregate: SubscriptionAggregate) -> None:
        """Save or update a subscription aggregate snapshot."""
        pass

    @abstractmethod
    async def get_subscription_aggregate(self, subscription_id: str) -> Optional[SubscriptionAggregate]:
        """Retrieve the current snapshot of a subscription aggregate if present."""
        pass


class InMemoryEventStore(EventStore):
    """Thread-safe in-memory event store implementation for development and testing."""

    def __init__(self) -> None:
        self._events: List[PaymentEvent] = []
        self._payment_aggregates: Dict[str, PaymentAggregate] = {}
        self._subscription_aggregates: Dict[str, SubscriptionAggregate] = {}

    async def append(self, event: PaymentEvent) -> None:
        """Persist a domain event to the in-memory stream."""
        self._events.append(event)

    async def get_events_for_payment(self, payment_id: str) -> List[PaymentEvent]:
        """Retrieve events matching payment_id sorted by occurred_at."""
        matched = [
            e for e in self._events
            if e.payment and e.payment.id == payment_id
        ]
        return sorted(matched, key=lambda e: e.occurred_at)

    async def get_events_for_subscription(self, subscription_id: str) -> List[PaymentEvent]:
        """Retrieve events matching subscription_id sorted by occurred_at."""
        matched = [
            e for e in self._events
            if e.subscription and e.subscription.id == subscription_id
        ]
        return sorted(matched, key=lambda e: e.occurred_at)

    async def save_payment_aggregate(self, aggregate: PaymentAggregate) -> None:
        """Save payment aggregate snapshot in memory."""
        self._payment_aggregates[aggregate.payment_id] = aggregate.model_copy(deep=True)

    async def get_payment_aggregate(self, payment_id: str) -> Optional[PaymentAggregate]:
        """Get payment aggregate snapshot from memory."""
        agg = self._payment_aggregates.get(payment_id)
        return agg.model_copy(deep=True) if agg else None

    async def save_subscription_aggregate(self, aggregate: SubscriptionAggregate) -> None:
        """Save subscription aggregate snapshot in memory."""
        self._subscription_aggregates[aggregate.subscription_id] = aggregate.model_copy(deep=True)

    async def get_subscription_aggregate(self, subscription_id: str) -> Optional[SubscriptionAggregate]:
        """Get subscription aggregate snapshot from memory."""
        agg = self._subscription_aggregates.get(subscription_id)
        return agg.model_copy(deep=True) if agg else None
