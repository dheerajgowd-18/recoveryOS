"""In-memory store for scheduled recovery actions with idempotency tracking."""
from typing import Dict, List, Optional

from scheduler.models import ScheduledAction, ScheduledActionStatus


class InMemoryScheduledStore:
    """Thread-safe in-memory repository for scheduled actions and idempotency records."""

    def __init__(self) -> None:
        self._actions: Dict[str, ScheduledAction] = {}
        self._idempotency_map: Dict[str, str] = {}  # idempotency_key -> scheduled_action_id

    def save(self, action: ScheduledAction) -> None:
        """Persist or update a scheduled action."""
        self._actions[action.scheduled_action_id] = action
        self._idempotency_map[action.idempotency_key] = action.scheduled_action_id

    def get(self, scheduled_action_id: str) -> Optional[ScheduledAction]:
        """Lookup a scheduled action by ID."""
        return self._actions.get(scheduled_action_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[ScheduledAction]:
        """Lookup a scheduled action by its deduplication idempotency key."""
        action_id = self._idempotency_map.get(idempotency_key)
        if action_id:
            return self._actions.get(action_id)
        return None

    def list_all(self) -> List[ScheduledAction]:
        """List all registered scheduled actions."""
        return list(self._actions.values())

    def list_pending(self) -> List[ScheduledAction]:
        """List all currently pending or due scheduled actions."""
        return [
            a for a in self._actions.values()
            if a.status in (ScheduledActionStatus.PENDING, ScheduledActionStatus.DUE)
        ]

    def list_by_payment_id(self, payment_id: str) -> List[ScheduledAction]:
        """Retrieve all scheduled actions for a given payment entity."""
        return [a for a in self._actions.values() if a.payment_id == payment_id]
