"""Idempotency tracking abstractions and in-memory implementation to guarantee exactly-once processing."""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class IdempotencyRecord(BaseModel):
    """Metadata record tracking processed event execution and cached response."""
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., description="Unique event identifier")
    processed_at: datetime = Field(default_factory=datetime.utcnow, description="UTC processed timestamp")
    event_type: str = Field(..., description="Razorpay event type")
    cached_response: Dict[str, str] = Field(default_factory=dict, description="Cached acknowledgment payload")


class IdempotencyTracker(ABC):
    """Abstract interface for checking and marking event processing idempotency."""

    @abstractmethod
    async def is_processed(self, event_id: str) -> bool:
        """Check if an event_id has already been processed."""
        pass

    @abstractmethod
    async def get_record(self, event_id: str) -> Optional[IdempotencyRecord]:
        """Retrieve the cached processing record for an event if it exists."""
        pass

    @abstractmethod
    async def mark_processed(
        self,
        event_id: str,
        event_type: str,
        cached_response: Optional[Dict[str, str]] = None,
    ) -> IdempotencyRecord:
        """Mark an event as successfully processed and cache its response."""
        pass


class InMemoryIdempotencyTracker(IdempotencyTracker):
    """In-memory idempotency tracker store."""

    def __init__(self) -> None:
        self._records: Dict[str, IdempotencyRecord] = {}

    async def is_processed(self, event_id: str) -> bool:
        """Check if event_id is registered."""
        return event_id in self._records

    async def get_record(self, event_id: str) -> Optional[IdempotencyRecord]:
        """Fetch cached record."""
        return self._records.get(event_id)

    async def mark_processed(
        self,
        event_id: str,
        event_type: str,
        cached_response: Optional[Dict[str, str]] = None,
    ) -> IdempotencyRecord:
        """Store record in memory."""
        record = IdempotencyRecord(
            event_id=event_id,
            processed_at=datetime.utcnow(),
            event_type=event_type,
            cached_response=cached_response or {"status": "ok", "idempotent_replay": "true"},
        )
        self._records[event_id] = record
        return record
