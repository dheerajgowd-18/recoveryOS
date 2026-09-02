"""Scheduled action lifecycle manager, state revalidation service, and stale-action invalidator."""
from typing import List, Optional, Tuple

from domain.aggregates import PaymentAggregate
from domain.enums import PaymentState
from governor.exceptions import DuplicateExecutionError
from governor.firewall import CustomerConsentContext
from governor.policy import MerchantPolicy
from intelligence.context import ObservableRecoveryContext
from planner.timing import TimingWindow
from policy.base import PolicyDecision
from scheduler.models import ScheduledAction, ScheduledActionStatus
from scheduler.store import InMemoryScheduledStore
from simulator.config import SimulatedActionType


class ScheduledLifecycleService:
    """Orchestrates scheduled action creation, state version binding, pre-execution revalidation, and invalidation."""

    def __init__(self, store: Optional[InMemoryScheduledStore] = None) -> None:
        self.store = store or InMemoryScheduledStore()

    def get_pending_actions(self) -> List[ScheduledAction]:
        """Returns all currently pending or due scheduled actions."""
        return self.store.list_pending()

    def schedule_action(
        self,
        decision: PolicyDecision,
        context: ObservableRecoveryContext,
        aggregate: Optional[PaymentAggregate],
        policy: MerchantPolicy,
        current_epoch: int,
        timing_window: TimingWindow = TimingWindow.PLUS_6H,
        delay_seconds: Optional[int] = None,
    ) -> ScheduledAction:
        """Create and persist a pending scheduled action bound to current aggregate state version."""
        delay = delay_seconds if delay_seconds is not None else timing_window.delay_seconds
        scheduled_at = current_epoch + delay
        max_recovery_seconds = policy.recovery_window_hours * 3600
        expires_at = current_epoch + max_recovery_seconds
        expected_version = aggregate.version if aggregate else 1

        idempotency_key = f"sched_{context.payment_id}_{decision.action_type.value}_{scheduled_at}"

        # Idempotency check: Reject duplicate active schedules
        existing = self.store.get_by_idempotency_key(idempotency_key)
        if existing and existing.status in (ScheduledActionStatus.PENDING, ScheduledActionStatus.DUE, ScheduledActionStatus.EXECUTED):
            raise DuplicateExecutionError(
                f"Duplicate scheduled action detected for idempotency key '{idempotency_key}' in state '{existing.status.value}'."
            )

        scheduled_action_id = f"act_sched_{context.payment_id}_{int(scheduled_at)}"

        action = ScheduledAction(
            scheduled_action_id=scheduled_action_id,
            decision_id=f"dec_{context.scenario_id}_{decision.action_type.value}_{current_epoch}",
            payment_id=context.payment_id,
            action_type=decision.action_type,
            timing_window=timing_window,
            delay_seconds=delay,
            scheduled_at_epoch=scheduled_at,
            expires_at_epoch=expires_at,
            expected_state_version=expected_version,
            idempotency_key=idempotency_key,
            status=ScheduledActionStatus.PENDING,
            reason_codes=["ACTION_SCHEDULED", f"TIMING_{timing_window.value}", f"STATE_V{expected_version}"],
            created_at=current_epoch,
        )

        self.store.save(action)
        return action

    def revalidate_and_check_executable(
        self,
        scheduled_action: ScheduledAction,
        current_aggregate: Optional[PaymentAggregate],
        consent: Optional[CustomerConsentContext] = None,
        current_epoch: Optional[int] = None,
        policy: Optional[MerchantPolicy] = None,
    ) -> Tuple[bool, Optional[str], List[str]]:
        """Verify whether a scheduled action is still valid, safe, and permitted to execute.

        Checks:
        1. Action expiration beyond recovery window.
        2. Terminal or already-recovered payment state.
        3. Payment aggregate state version drift / mismatch.
        4. Customer communication opt-out / consent change.
        """
        # 1. Action expiration check
        if current_epoch is not None and current_epoch > scheduled_action.expires_at_epoch:
            return (
                False,
                f"Scheduled action expired (epoch {current_epoch} > expiry {scheduled_action.expires_at_epoch}).",
                ["TIMING_EXPIRED_BEFORE_EXECUTION", "ACTION_EXPIRED"],
            )

        # 2. Terminal state check
        if current_aggregate and current_aggregate.is_terminal:
            if current_aggregate.current_state == PaymentState.CAPTURED:
                return (
                    False,
                    "Payment is already captured. Revenue recovered; cancelling scheduled action.",
                    ["REVENUE_ALREADY_RECOVERED", "STALE_OR_INVALID_SCHEDULED_ACTION"],
                )
            return (
                False,
                f"Payment is in terminal state '{current_aggregate.current_state.value}'.",
                ["STATE_INVALID", "STALE_OR_INVALID_SCHEDULED_ACTION"],
            )

        # 3. State version drift check
        if current_aggregate and current_aggregate.version != scheduled_action.expected_state_version:
            return (
                False,
                f"State version mismatch: current aggregate version is v{current_aggregate.version}, "
                f"expected v{scheduled_action.expected_state_version}.",
                ["STATE_VERSION_MISMATCH", "STALE_OR_INVALID_SCHEDULED_ACTION"],
            )

        # 4. Consent opt-out check
        if consent and consent.is_globally_opted_out:
            if scheduled_action.action_type in (SimulatedActionType.PAYMENT_LINK, SimulatedActionType.REMINDER):
                return (
                    False,
                    "Customer has opted out of direct dunning communications.",
                    ["CUSTOMER_OPTED_OUT", "CONSENT_INVALID", "STALE_OR_INVALID_SCHEDULED_ACTION"],
                )

        return (True, None, ["REVALIDATION_SUCCESSFUL"])

    def invalidate_action(
        self,
        scheduled_action_id: str,
        reason: str,
        reason_codes: Optional[List[str]] = None,
    ) -> Optional[ScheduledAction]:
        """Mark a pending scheduled action as INVALIDATED due to stale state or policy changes."""
        action = self.store.get(scheduled_action_id)
        if not action:
            return None

        codes = list(action.reason_codes)
        if reason_codes:
            for c in reason_codes:
                if c not in codes:
                    codes.append(c)
        if "STALE_OR_INVALID_SCHEDULED_ACTION" not in codes:
            codes.append("STALE_OR_INVALID_SCHEDULED_ACTION")

        updated = ScheduledAction(
            scheduled_action_id=action.scheduled_action_id,
            decision_id=action.decision_id,
            payment_id=action.payment_id,
            action_type=action.action_type,
            timing_window=action.timing_window,
            delay_seconds=action.delay_seconds,
            scheduled_at_epoch=action.scheduled_at_epoch,
            expires_at_epoch=action.expires_at_epoch,
            expected_state_version=action.expected_state_version,
            idempotency_key=action.idempotency_key,
            status=ScheduledActionStatus.INVALIDATED,
            reason_codes=codes,
            created_at=action.created_at,
            invalidation_reason=reason,
            execution_key=action.execution_key,
        )
        self.store.save(updated)
        return updated

    def expire_action(
        self,
        scheduled_action_id: str,
        reason: str = "Recovery window expired before scheduled execution",
    ) -> Optional[ScheduledAction]:
        """Mark a pending scheduled action as EXPIRED."""
        action = self.store.get(scheduled_action_id)
        if not action:
            return None

        codes = list(action.reason_codes)
        if "TIMING_EXPIRED_BEFORE_EXECUTION" not in codes:
            codes.append("TIMING_EXPIRED_BEFORE_EXECUTION")

        updated = ScheduledAction(
            scheduled_action_id=action.scheduled_action_id,
            decision_id=action.decision_id,
            payment_id=action.payment_id,
            action_type=action.action_type,
            timing_window=action.timing_window,
            delay_seconds=action.delay_seconds,
            scheduled_at_epoch=action.scheduled_at_epoch,
            expires_at_epoch=action.expires_at_epoch,
            expected_state_version=action.expected_state_version,
            idempotency_key=action.idempotency_key,
            status=ScheduledActionStatus.EXPIRED,
            reason_codes=codes,
            created_at=action.created_at,
            invalidation_reason=reason,
            execution_key=action.execution_key,
        )
        self.store.save(updated)
        return updated

    def mark_executed(
        self,
        scheduled_action_id: str,
        execution_key: str,
    ) -> Optional[ScheduledAction]:
        """Mark a scheduled action as EXECUTED with its execution idempotency key."""
        action = self.store.get(scheduled_action_id)
        if not action:
            return None

        codes = list(action.reason_codes)
        if "SCHEDULED_ACTION_EXECUTED" not in codes:
            codes.append("SCHEDULED_ACTION_EXECUTED")

        updated = ScheduledAction(
            scheduled_action_id=action.scheduled_action_id,
            decision_id=action.decision_id,
            payment_id=action.payment_id,
            action_type=action.action_type,
            timing_window=action.timing_window,
            delay_seconds=action.delay_seconds,
            scheduled_at_epoch=action.scheduled_at_epoch,
            expires_at_epoch=action.expires_at_epoch,
            expected_state_version=action.expected_state_version,
            idempotency_key=action.idempotency_key,
            status=ScheduledActionStatus.EXECUTED,
            reason_codes=codes,
            created_at=action.created_at,
            invalidation_reason=None,
            execution_key=execution_key,
        )
        self.store.save(updated)
        return updated
