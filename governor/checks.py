"""Deterministic governance checks evaluated in strict priority order with Action × Timing validation."""
from typing import List, Optional, Tuple

from domain.aggregates import PaymentAggregate
from domain.enums import PaymentState
from governor.decision import GovernorDecision, GovernorDecisionResult
from governor.firewall import CustomerConsentContext
from governor.human_review import HumanReviewEvaluator
from governor.policy import MerchantPolicy
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis
from policy.base import PolicyDecision
from simulator.config import SimulatedActionType


class GovernanceChecker:
    """Ordered deterministic rules engine evaluating candidate actions and timing against merchant policies."""

    @staticmethod
    def evaluate_all(
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis],
        proposal: Optional[PolicyDecision],
        policy: Optional[MerchantPolicy] = None,
        aggregate: Optional[PaymentAggregate] = None,
        consent: Optional[CustomerConsentContext] = None,
        policy_healthy: bool = True,
    ) -> GovernorDecision:
        """Run all governance checks in deterministic order and return an authoritative GovernorDecision."""
        # Check 0: Policy health / availability check
        if not policy_healthy or policy is None:
            return GovernorDecision(
                decision_result=GovernorDecisionResult.DENY,
                selected_action=SimulatedActionType.NO_ACTION,
                reason_codes=["POLICY_UNAVAILABLE_FAIL_CLOSED"],
                policy_version=policy.policy_version if policy else "unknown",
                diagnosis_confidence=diagnosis.confidence if diagnosis else 0.0,
                stop_reason="POLICY_OUTAGE",
                rationale="Merchant policy or governance engine unavailable. Failing closed.",
            )

        active_policy = policy
        action = proposal.action_type if proposal else SimulatedActionType.NO_ACTION
        diag_conf = diagnosis.confidence if diagnosis else (proposal.confidence if proposal else 1.0)
        incr_val = proposal.expected_incremental_value_paise if proposal and proposal.expected_incremental_value_paise is not None else 0
        net_val = proposal.expected_net_value_paise if proposal and proposal.expected_net_value_paise is not None else 0
        timing_hint = diagnosis.recommended_timing_hint if diagnosis else None

        # Timing extraction
        timing_window = proposal.timing_window if proposal and proposal.timing_window else (
            "PLUS_24H" if action == SimulatedActionType.RETRY_LATER else ("IMMEDIATE" if action != SimulatedActionType.NO_ACTION else None)
        )
        delay_seconds = proposal.delay_seconds if proposal and proposal.delay_seconds else (
            86400 if action == SimulatedActionType.RETRY_LATER else 0
        )

        # Check 1: State Validity & Terminal State
        if aggregate:
            if aggregate.is_terminal:
                if aggregate.current_state == PaymentState.CAPTURED:
                    return GovernorDecision(
                        decision_result=GovernorDecisionResult.DENY,
                        selected_action=SimulatedActionType.NO_ACTION,
                        reason_codes=["REVENUE_ALREADY_RECOVERED", "TERMINAL_STATE_REACHED"],
                        policy_version=active_policy.policy_version,
                        diagnosis_confidence=diag_conf,
                        stop_reason="TERMINAL_STATE_REACHED",
                        rationale="Payment is already captured. Recovery intervention denied to prevent duplicate charge.",
                    )
                return GovernorDecision(
                    decision_result=GovernorDecisionResult.DENY,
                    selected_action=SimulatedActionType.NO_ACTION,
                    reason_codes=["STATE_INVALID", "TERMINAL_STATE_REACHED"],
                    policy_version=active_policy.policy_version,
                    diagnosis_confidence=diag_conf,
                    stop_reason="TERMINAL_STATE_REACHED",
                    rationale=f"Payment is in terminal state '{aggregate.current_state.value}'. Intervention denied.",
                )

        # Check 2: Recovery Window Expiry & Timing Recovery Window Bound
        max_recovery_seconds = active_policy.recovery_window_hours * 3600
        if context.time_since_failure_seconds > max_recovery_seconds:
            return GovernorDecision(
                decision_result=GovernorDecisionResult.DENY,
                selected_action=SimulatedActionType.NO_ACTION,
                reason_codes=["RECOVERY_WINDOW_EXPIRED"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                stop_reason="RECOVERY_WINDOW_EXPIRED",
                rationale=f"Failure occurred {context.time_since_failure_seconds}s ago, exceeding policy window of {active_policy.recovery_window_hours}h.",
            )

        if delay_seconds > 0 and (context.time_since_failure_seconds + delay_seconds) > max_recovery_seconds:
            return GovernorDecision(
                decision_result=GovernorDecisionResult.DENY,
                selected_action=SimulatedActionType.NO_ACTION,
                timing_window=timing_window,
                delay_seconds=delay_seconds,
                reason_codes=["TIMING_OUTSIDE_RECOVERY_WINDOW", "RECOVERY_WINDOW_EXPIRED"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                stop_reason="RECOVERY_WINDOW_EXPIRED",
                rationale=f"Scheduled execution at +{delay_seconds}s would exceed merchant recovery window of {active_policy.recovery_window_hours}h ({context.time_since_failure_seconds + delay_seconds}s > {max_recovery_seconds}s).",
            )

        # Check 3: Customer Consent & Communication Opt-Out
        is_opted_out = context.consent_opted_out or (consent and consent.is_globally_opted_out)
        if is_opted_out and action in (SimulatedActionType.PAYMENT_LINK, SimulatedActionType.REMINDER):
            return GovernorDecision(
                decision_result=GovernorDecisionResult.DENY,
                selected_action=SimulatedActionType.NO_ACTION,
                reason_codes=["CUSTOMER_OPTED_OUT", "CONSENT_INVALID"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                stop_reason="ACTION_BLOCKED",
                rationale=f"Customer has globally opted out of dunning communications. Direct action '{action.value}' denied.",
            )

        # Check 4: Action Whitelist & Timing Policy Permission
        if action not in active_policy.allowed_action_types:
            return GovernorDecision(
                decision_result=GovernorDecisionResult.DENY,
                selected_action=SimulatedActionType.NO_ACTION,
                reason_codes=["ACTION_NOT_ALLOWED_BY_POLICY"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                stop_reason="ACTION_BLOCKED",
                rationale=f"Action '{action.value}' is not in merchant approved action whitelist.",
            )

        if delay_seconds > 0 and not active_policy.allow_delayed_execution:
            return GovernorDecision(
                decision_result=GovernorDecisionResult.DENY,
                selected_action=SimulatedActionType.NO_ACTION,
                timing_window=timing_window,
                delay_seconds=delay_seconds,
                reason_codes=["TIMING_NOT_PERMITTED_BY_POLICY"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                stop_reason="ACTION_BLOCKED",
                rationale="Merchant policy forbids delayed/scheduled execution.",
            )

        # Check 5: Maximum Amount Cap
        if context.amount_in_paise > active_policy.max_automatic_action_amount_paise:
            return GovernorDecision(
                decision_result=GovernorDecisionResult.DENY,
                selected_action=SimulatedActionType.NO_ACTION,
                reason_codes=["AMOUNT_ABOVE_AUTO_LIMIT"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                stop_reason="ACTION_BLOCKED",
                rationale=f"Transaction amount ₹{context.amount_in_paise / 100:,.2f} exceeds automatic limit ₹{active_policy.max_automatic_action_amount_paise / 100:,.2f}.",
            )

        # Check 6: Retry Limit Check
        if action in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER):
            if context.attempt_count > active_policy.max_retries:
                return GovernorDecision(
                    decision_result=GovernorDecisionResult.DENY,
                    selected_action=SimulatedActionType.NO_ACTION,
                    reason_codes=["RETRY_LIMIT_REACHED"],
                    policy_version=active_policy.policy_version,
                    diagnosis_confidence=diag_conf,
                    stop_reason="RETRY_LIMIT_REACHED",
                    rationale=f"Attempt count {context.attempt_count} exceeds maximum allowed retries ({active_policy.max_retries}).",
                )

        # Check 7: Contact Limits Check
        if action in (SimulatedActionType.PAYMENT_LINK, SimulatedActionType.REMINDER):
            if context.contacts_in_last_24h >= active_policy.max_contacts_24h:
                codes = ["CONTACT_LIMIT_REACHED"]
                if delay_seconds > 0:
                    codes.insert(0, "TIMING_VIOLATES_CONTACT_LIMIT")
                return GovernorDecision(
                    decision_result=GovernorDecisionResult.DENY,
                    selected_action=SimulatedActionType.NO_ACTION,
                    timing_window=timing_window,
                    delay_seconds=delay_seconds,
                    reason_codes=codes,
                    policy_version=active_policy.policy_version,
                    diagnosis_confidence=diag_conf,
                    stop_reason="CONTACT_LIMIT_REACHED",
                    rationale=f"Customer received {context.contacts_in_last_24h} contacts in 24h, reaching limit of {active_policy.max_contacts_24h}.",
                )
            if context.contacts_in_last_7d >= active_policy.max_contacts_7d:
                codes = ["CONTACT_LIMIT_REACHED"]
                if delay_seconds > 0:
                    codes.insert(0, "TIMING_VIOLATES_CONTACT_LIMIT")
                return GovernorDecision(
                    decision_result=GovernorDecisionResult.DENY,
                    selected_action=SimulatedActionType.NO_ACTION,
                    timing_window=timing_window,
                    delay_seconds=delay_seconds,
                    reason_codes=codes,
                    policy_version=active_policy.policy_version,
                    diagnosis_confidence=diag_conf,
                    stop_reason="CONTACT_LIMIT_REACHED",
                    rationale=f"Customer received {context.contacts_in_last_7d} contacts in 7d, reaching limit of {active_policy.max_contacts_7d}.",
                )

        # Check 8: Cooldown Active & Timing Violates Cooldown
        if action != SimulatedActionType.NO_ACTION and context.time_since_last_contact_seconds is not None:
            if context.time_since_last_contact_seconds < active_policy.cooldown_seconds:
                if delay_seconds == 0:
                    return GovernorDecision(
                        decision_result=GovernorDecisionResult.DEFER,
                        selected_action=SimulatedActionType.NO_ACTION,
                        timing_window=timing_window,
                        delay_seconds=delay_seconds,
                        reason_codes=["COOLDOWN_ACTIVE"],
                        policy_version=active_policy.policy_version,
                        diagnosis_confidence=diag_conf,
                        stop_reason="COOLDOWN_ACTIVE",
                        rationale=f"Cooldown active ({context.time_since_last_contact_seconds}s < {active_policy.cooldown_seconds}s). Deferring action.",
                    )
                elif (context.time_since_last_contact_seconds + delay_seconds) < active_policy.cooldown_seconds:
                    return GovernorDecision(
                        decision_result=GovernorDecisionResult.DEFER,
                        selected_action=SimulatedActionType.NO_ACTION,
                        timing_window=timing_window,
                        delay_seconds=delay_seconds,
                        reason_codes=["TIMING_VIOLATES_COOLDOWN", "COOLDOWN_ACTIVE"],
                        policy_version=active_policy.policy_version,
                        diagnosis_confidence=diag_conf,
                        stop_reason="COOLDOWN_ACTIVE",
                        rationale=f"Scheduled execution at +{delay_seconds}s still violates cooldown ({context.time_since_last_contact_seconds + delay_seconds}s < {active_policy.cooldown_seconds}s).",
                    )

        # Check 9: Human Review Escalation
        escalation_reason = HumanReviewEvaluator.evaluate_escalation(
            context=context,
            diagnosis=diagnosis,
            proposal=proposal,
            policy=active_policy,
            aggregate=aggregate,
        )
        if escalation_reason:
            trigger_code = escalation_reason.split(":")[0]
            return GovernorDecision(
                decision_result=GovernorDecisionResult.ESCALATE,
                selected_action=SimulatedActionType.NO_ACTION,
                reason_codes=[trigger_code, "HUMAN_REVIEW_REQUIRED"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                human_review_reason=escalation_reason,
                stop_reason="HUMAN_REVIEW_REQUIRED",
                rationale=f"Autonomous action halted: {escalation_reason}",
            )

        # Check 10: Diagnosis Confidence Threshold
        if diagnosis and diagnosis.confidence < active_policy.min_diagnosis_confidence:
            return GovernorDecision(
                decision_result=GovernorDecisionResult.ABSTAIN,
                selected_action=SimulatedActionType.NO_ACTION,
                reason_codes=["DIAGNOSIS_CONFIDENCE_TOO_LOW", "ABSTAIN_LOW_CONFIDENCE_DIAGNOSIS"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                stop_reason="POLICY_ABSTAINED",
                rationale=f"Diagnosis confidence ({diagnosis.confidence:.2f}) below threshold ({active_policy.min_diagnosis_confidence:.2f}). Abstaining safely.",
            )

        if delay_seconds > 0 and diag_conf < active_policy.min_delayed_diagnosis_confidence:
            return GovernorDecision(
                decision_result=GovernorDecisionResult.ABSTAIN,
                selected_action=SimulatedActionType.NO_ACTION,
                timing_window=timing_window,
                delay_seconds=delay_seconds,
                reason_codes=["DIAGNOSIS_CONFIDENCE_TOO_LOW", "TIMING_NOT_PERMITTED_BY_POLICY"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                stop_reason="POLICY_ABSTAINED",
                rationale=f"Diagnosis confidence ({diag_conf:.2f}) below threshold ({active_policy.min_delayed_diagnosis_confidence:.2f}) for scheduled execution.",
            )

        # Check 11: Economic Value & Negative Uplift
        if action == SimulatedActionType.NO_ACTION:
            return GovernorDecision(
                decision_result=GovernorDecisionResult.ABSTAIN,
                selected_action=SimulatedActionType.NO_ACTION,
                timing_window="IMMEDIATE",
                delay_seconds=0,
                reason_codes=proposal.reason_codes if proposal else ["ABSTAIN_PROPOSED"],
                policy_version=active_policy.policy_version,
                diagnosis_confidence=diag_conf,
                expected_incremental_value_paise=incr_val,
                expected_net_value_paise=net_val,
                stop_reason="POLICY_ABSTAINED",
                rationale="Policy proposed abstention; Governor confirms zero-intervention baseline.",
            )

        if proposal:
            if "ABSTAIN_NEGATIVE_UPLIFT" in proposal.reason_codes or "NEGATIVE_INCREMENTAL_UPLIFT" in proposal.reason_codes or incr_val < 0:
                return GovernorDecision(
                    decision_result=GovernorDecisionResult.ABSTAIN,
                    selected_action=SimulatedActionType.NO_ACTION,
                    timing_window=timing_window,
                    delay_seconds=delay_seconds,
                    reason_codes=["NEGATIVE_INCREMENTAL_UPLIFT", "ABSTAIN_NEGATIVE_UPLIFT"],
                    policy_version=active_policy.policy_version,
                    diagnosis_confidence=diag_conf,
                    expected_incremental_value_paise=incr_val,
                    expected_net_value_paise=net_val,
                    stop_reason="POLICY_ABSTAINED",
                    rationale="Proposed action produces negative incremental uplift vs natural recovery. Abstaining to preserve value.",
                )

            if incr_val < active_policy.min_expected_incremental_value_paise or net_val < 0:
                return GovernorDecision(
                    decision_result=GovernorDecisionResult.ABSTAIN,
                    selected_action=SimulatedActionType.NO_ACTION,
                    timing_window=timing_window,
                    delay_seconds=delay_seconds,
                    reason_codes=["EXPECTED_VALUE_BELOW_THRESHOLD", "ABSTAIN_LOW_EXPECTED_VALUE"],
                    policy_version=active_policy.policy_version,
                    diagnosis_confidence=diag_conf,
                    expected_incremental_value_paise=incr_val,
                    expected_net_value_paise=net_val,
                    stop_reason="POLICY_ABSTAINED",
                    rationale=f"Expected net return (₹{net_val / 100:.2f}) or incremental value (₹{incr_val / 100:.2f}) does not meet threshold.",
                )

        # Check 12: All Checks Passed -> ALLOW
        return GovernorDecision(
            decision_result=GovernorDecisionResult.ALLOW,
            selected_action=action,
            timing_hint=timing_hint,
            timing_window=timing_window,
            delay_seconds=delay_seconds,
            reason_codes=["GOVERNOR_ACTION_ALLOWED"],
            policy_version=active_policy.policy_version,
            diagnosis_confidence=diag_conf,
            expected_incremental_value_paise=incr_val,
            expected_net_value_paise=net_val,
            stop_reason=None,
            rationale=f"Governor approved action '{action.value}' (timing: {timing_window or 'immediate'}) under policy {active_policy.policy_version} (Exp Net Value: ₹{net_val / 100:.2f}).",
        )
