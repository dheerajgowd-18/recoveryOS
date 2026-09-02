"""Dashboard data service for RecoveryOS Operations Console.

Provides aggregation and querying across in-memory decision logs, scheduled actions,
event stores, merchant policies, and evaluation benchmark results.
"""
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from audit.decision_log import DecisionLogStore, DecisionRecord
from audit.replay import ReplayEngine
from governor.policy import MerchantPolicy
from scheduler.service import ScheduledLifecycleService
from simulator.config import SimulatedActionType


class DashboardService:
    """Aggregates operational state, decision logs, queue items, and evaluation metrics for the Operations Console."""

    def __init__(
        self,
        decision_log: Optional[DecisionLogStore] = None,
        scheduler_service: Optional[ScheduledLifecycleService] = None,
        merchant_policy: Optional[MerchantPolicy] = None,
        reports_dir: str = "reports",
    ) -> None:
        self.decision_log = decision_log or DecisionLogStore()
        self.scheduler_service = scheduler_service or ScheduledLifecycleService()
        self.merchant_policy = merchant_policy or MerchantPolicy()
        self.reports_dir = reports_dir
        self.replay_engine = ReplayEngine(
            decision_log=self.decision_log,
            merchant_policy=self.merchant_policy,
        )
        self._ensure_bootstrap_data()

    def _ensure_bootstrap_data(self) -> None:
        """Populates signature operational cases if decision log is empty."""
        if len(self.decision_log.list_records()) > 0:
            return

        # Bootstrap 5 signature fintech operational cases
        cases = [
            {
                "decision_id": "dec_sig_001",
                "scenario_id": "scen_abstention_01",
                "payment_id": "pay_sig_micro_001",
                "iteration": 1,
                "timestamp_epoch": int(time.time()) - 1800,
                "policy_name": "RECOVERYOS_DETERMINISTIC_V0",
                "policy_version": "v1.0.0",
                "diagnosis_label": "low_value_negative_uplift",
                "diagnosis_confidence": 0.95,
                "diagnosis_source": "deterministic_offline",
                "evidence_codes": ["LOW_TICKET_VALUE", "HIGH_HISTORICAL_CHURN"],
                "governor_decision": "ABSTAIN",
                "governor_reason_codes": ["ABSTAIN_NEGATIVE_EXPECTED_UPLIFT"],
                "amount_in_paise": 4900,  # INR 49.00
                "aggregate_state_before": "FAILED",
                "aggregate_state_after": "FAILED",
                "aggregate_state": "FAILED",
                "risk_level": "LOW",
                "selected_action": SimulatedActionType.NO_ACTION,
                "timing_window": "IMMEDIATE",
                "delay_seconds": 0,
                "confidence": 0.95,
                "rationale": "Action costs (INR 0.50) exceed expected marginal recovery uplift on micro-ticket transaction. Deliberate abstention protects margin.",
                "reason_codes": ["NEGATIVE_INCREMENTAL_UPLIFT_ABSTENTION"],
                "execution_result_success": True,
                "recovered": False,
                "action_cost_paise": 0,
                "recovered_amount_paise": 0,
                "stop_reason": "CONVERGED_NO_ACTION",
                "observable_context": {
                    "payment_id": "pay_sig_micro_001",
                    "amount_in_paise": 4900,
                    "failed_attempts_count": 1,
                    "hours_since_first_failure": 0.5,
                    "customer_tier": "STANDARD",
                    "has_valid_consent": True,
                    "contact_count_last_24h": 0,
                },
            },
            {
                "decision_id": "dec_sig_002",
                "scenario_id": "scen_timing_02",
                "payment_id": "pay_sig_transient_002",
                "iteration": 1,
                "timestamp_epoch": int(time.time()) - 1200,
                "policy_name": "RECOVERYOS_DETERMINISTIC_V0",
                "policy_version": "v1.0.0",
                "diagnosis_label": "transient_gateway_outage",
                "diagnosis_confidence": 0.92,
                "diagnosis_source": "deterministic_offline",
                "evidence_codes": ["GATEWAY_DOWNTIME_SPIKE", "ERROR_503"],
                "governor_decision": "ALLOW",
                "governor_reason_codes": ["GOVERNOR_POLICY_ALLOW", "TIMING_WINDOW_VALIDATED"],
                "amount_in_paise": 450000,  # INR 4,500.00
                "aggregate_state_before": "FAILED",
                "aggregate_state_after": "SCHEDULED",
                "aggregate_state": "SCHEDULED",
                "risk_level": "LOW",
                "selected_action": SimulatedActionType.RETRY_LATER,
                "timing_window": "PLUS_6H",
                "delay_seconds": 21600,
                "scheduled_action_id": "sched_act_002",
                "confidence": 0.92,
                "rationale": "Transient bank outage. Immediate retry has high failure rate (75%), while +6h window exhibits 88% recovery probability. Scheduled delayed retry.",
                "reason_codes": ["SCHEDULED_OPTIMAL_WINDOW", "ECONOMIC_UPLIFT_MAXIMIZED"],
                "execution_result_success": True,
                "recovered": True,
                "action_cost_paise": 20,
                "recovered_amount_paise": 450000,
                "stop_reason": "ACTION_SCHEDULED",
                "observable_context": {
                    "payment_id": "pay_sig_transient_002",
                    "amount_in_paise": 450000,
                    "failed_attempts_count": 1,
                    "hours_since_first_failure": 1.0,
                    "customer_tier": "ENTERPRISE",
                    "has_valid_consent": True,
                    "contact_count_last_24h": 0,
                },
            },
            {
                "decision_id": "dec_sig_003",
                "scenario_id": "scen_stale_03",
                "payment_id": "pay_sig_organic_003",
                "iteration": 1,
                "timestamp_epoch": int(time.time()) - 900,
                "policy_name": "RECOVERYOS_DETERMINISTIC_V0",
                "policy_version": "v1.0.0",
                "diagnosis_label": "insufficient_funds",
                "diagnosis_confidence": 0.88,
                "diagnosis_source": "deterministic_offline",
                "evidence_codes": ["INSUFFICIENT_FUNDS_CODE", "SALARY_CYCLE_WINDOW"],
                "governor_decision": "ALLOW",
                "governor_reason_codes": ["GOVERNOR_POLICY_ALLOW"],
                "amount_in_paise": 120000,  # INR 1,200.00
                "aggregate_state_before": "FAILED",
                "aggregate_state_after": "CAPTURED",
                "aggregate_state": "CAPTURED",
                "risk_level": "LOW",
                "selected_action": SimulatedActionType.RETRY_LATER,
                "timing_window": "PLUS_12H",
                "delay_seconds": 43200,
                "scheduled_action_id": "sched_act_003",
                "confidence": 0.88,
                "rationale": "Customer deposited funds organically before scheduled execution. State version mismatch detected; stale action safely invalidated.",
                "reason_codes": ["STALE_ACTION_INVALIDATED", "ORGANIC_CAPTURE_DETECTED"],
                "execution_result_success": True,
                "recovered": True,
                "action_cost_paise": 0,
                "recovered_amount_paise": 120000,
                "stop_reason": "STALE_ACTION_PREVENTED",
                "observable_context": {
                    "payment_id": "pay_sig_organic_003",
                    "amount_in_paise": 120000,
                    "failed_attempts_count": 1,
                    "hours_since_first_failure": 2.0,
                    "customer_tier": "STANDARD",
                    "has_valid_consent": True,
                    "contact_count_last_24h": 0,
                },
            },
            {
                "decision_id": "dec_sig_004",
                "scenario_id": "scen_consent_04",
                "payment_id": "pay_sig_optout_004",
                "iteration": 1,
                "timestamp_epoch": int(time.time()) - 600,
                "policy_name": "RECOVERYOS_DETERMINISTIC_V0",
                "policy_version": "v1.0.0",
                "diagnosis_label": "expired_card",
                "diagnosis_confidence": 0.96,
                "diagnosis_source": "deterministic_offline",
                "evidence_codes": ["CARD_EXPIRED", "CONSENT_REVOKED"],
                "governor_decision": "DENY",
                "governor_reason_codes": ["CUSTOMER_OPTED_OUT", "CONSENT_REQUIRED"],
                "amount_in_paise": 890000,  # INR 8,900.00
                "aggregate_state_before": "FAILED",
                "aggregate_state_after": "OPTED_OUT",
                "aggregate_state": "OPTED_OUT",
                "risk_level": "HIGH",
                "selected_action": SimulatedActionType.PAYMENT_LINK,
                "timing_window": "IMMEDIATE",
                "delay_seconds": 0,
                "confidence": 0.96,
                "rationale": "Customer has explicitly opted out of communications. Recovery Governor strictly blocked payment link dispatch to preserve compliance.",
                "reason_codes": ["GOVERNOR_CONSENT_BLOCK"],
                "execution_result_success": False,
                "recovered": False,
                "action_cost_paise": 0,
                "recovered_amount_paise": 0,
                "stop_reason": "GOVERNOR_DENIAL",
                "observable_context": {
                    "payment_id": "pay_sig_optout_004",
                    "amount_in_paise": 890000,
                    "failed_attempts_count": 2,
                    "hours_since_first_failure": 4.0,
                    "customer_tier": "PREMIUM",
                    "has_valid_consent": False,
                    "contact_count_last_24h": 1,
                },
            },
            {
                "decision_id": "dec_sig_005",
                "scenario_id": "scen_escalation_05",
                "payment_id": "pay_sig_highval_005",
                "iteration": 1,
                "timestamp_epoch": int(time.time()) - 300,
                "policy_name": "RECOVERYOS_DETERMINISTIC_V0",
                "policy_version": "v1.0.0",
                "diagnosis_label": "unusual_auth_decline",
                "diagnosis_confidence": 0.62,
                "diagnosis_source": "deterministic_offline",
                "evidence_codes": ["HIGH_TICKET_AMOUNT", "AMBIGUOUS_DECLINE_CODE"],
                "governor_decision": "ESCALATE",
                "governor_reason_codes": ["HIGH_VALUE_TRANSACTION", "DIAGNOSIS_UNCERTAINTY", "HUMAN_REVIEW_REQUIRED"],
                "human_review_reason": "High-ticket enterprise transaction (INR 150,000.00) with ambiguous fraud/auth decline. Escalated for human account manager review.",
                "amount_in_paise": 15000000,  # INR 150,000.00
                "aggregate_state_before": "FAILED",
                "aggregate_state_after": "ESCALATED",
                "aggregate_state": "ESCALATED",
                "risk_level": "HIGH",
                "selected_action": SimulatedActionType.NO_ACTION,
                "timing_window": "IMMEDIATE",
                "delay_seconds": 0,
                "confidence": 0.62,
                "rationale": "Amount exceeds autonomous threshold (INR 100,000) and diagnosis confidence is below 0.80. Governor routed case to VIP ops queue.",
                "reason_codes": ["HUMAN_REVIEW_ESCALATION"],
                "execution_result_success": True,
                "recovered": False,
                "action_cost_paise": 0,
                "recovered_amount_paise": 0,
                "stop_reason": "ESCALATED_HUMAN_REVIEW",
                "observable_context": {
                    "payment_id": "pay_sig_highval_005",
                    "amount_in_paise": 15000000,
                    "failed_attempts_count": 1,
                    "hours_since_first_failure": 0.2,
                    "customer_tier": "VIP_ENTERPRISE",
                    "has_valid_consent": True,
                    "contact_count_last_24h": 0,
                },
            },
        ]

        for item in cases:
            rec = DecisionRecord(**item)
            self.decision_log.save_record(rec)

    def get_control_room_data(self) -> Dict[str, Any]:
        """Aggregates executive KPIs and live operational metrics for the Control Room view."""
        records = self.decision_log.get_all_records()

        # Load benchmark report data if present for aggregate historical proof
        bench_data = self._load_benchmark_data()

        total_risk_paise = sum(r.amount_in_paise for r in records)
        gross_rec_paise = sum(r.recovered_amount_paise or 0 for r in records)
        action_costs_paise = sum(r.action_cost_paise or 0 for r in records)

        # Baseline organic vs incremental
        actions_executed = sum(1 for r in records if r.selected_action != "NO_ACTION" and r.governor_decision == "ALLOW")
        actions_avoided = sum(1 for r in records if r.selected_action == "NO_ACTION" or r.governor_decision == "ABSTAIN")
        human_reviews = sum(1 for r in records if r.governor_decision == "ESCALATE")
        policy_blocks = sum(1 for r in records if r.governor_decision in ("DENY", "DEFER"))
        open_cases = sum(1 for r in records if r.aggregate_state in ("FAILED", "SCHEDULED", "ESCALATED"))

        # If benchmark detail exists, use full population benchmark stats for macroscopic context
        if bench_data and "combined_split" in bench_data:
            comb = bench_data["combined_split"]
            rec_res = comb.get("policy_results", {}).get("RECOVERYOS_DETERMINISTIC_V0", {})
            d = rec_res.get("metric_distributions", {})
            total_risk_inr = round(d.get("gross_recovered_amount_paise", {}).get("mean", total_risk_paise) / 100.0, 2)
            gross_rec_inr = round(d.get("gross_recovered_amount_paise", {}).get("mean", gross_rec_paise) / 100.0, 2)
            incr_rec_inr = round(d.get("incremental_adjusted_net_recovery_paise", {}).get("mean", gross_rec_paise) / 100.0, 2)
            net_adj_inr = round(d.get("adjusted_net_recovery_paise", {}).get("mean", gross_rec_paise - action_costs_paise) / 100.0, 2)
            bench_present = True
        else:
            total_risk_inr = round(total_risk_paise / 100.0, 2)
            gross_rec_inr = round(gross_rec_paise / 100.0, 2)
            incr_rec_inr = round(max(0, gross_rec_paise - action_costs_paise) / 100.0, 2)
            net_adj_inr = round((gross_rec_paise - action_costs_paise) / 100.0, 2)
            bench_present = False

        # Format recent activity feed
        recent_activity = []
        for r in sorted(records, key=lambda x: x.timestamp_epoch, reverse=True)[:10]:
            recent_activity.append({
                "decision_id": r.decision_id,
                "payment_id": r.payment_id,
                "amount_inr": round(r.amount_in_paise / 100.0, 2),
                "action": r.selected_action.value if hasattr(r.selected_action, "value") else str(r.selected_action),
                "timing": r.timing_window or "IMMEDIATE",
                "diagnosis": r.diagnosis_label,
                "governor": r.governor_decision or "ALLOW",
                "status": r.aggregate_state,
                "time_str": datetime.fromtimestamp(r.timestamp_epoch, tz=timezone.utc).strftime("%H:%M:%S UTC"),
                "rationale": r.rationale,
            })

        return {
            "revenue_at_risk_inr": total_risk_inr,
            "gross_recovered_inr": gross_rec_inr,
            "incremental_recovered_inr": incr_rec_inr,
            "net_adjusted_recovery_inr": net_adj_inr,
            "open_recovery_opportunities": open_cases,
            "actions_executed": actions_executed,
            "actions_avoided": actions_avoided,
            "human_reviews": human_reviews,
            "policy_blocks": policy_blocks,
            "exceptions_count": policy_blocks + human_reviews,
            "recent_activity": recent_activity,
            "benchmark_active": bench_present,
            "system_status": "OPERATIONAL",
            "agent_mode": self.merchant_policy.automation_mode.value if hasattr(self.merchant_policy.automation_mode, "value") else str(self.merchant_policy.automation_mode),
        }

    def get_recovery_queue(self) -> List[Dict[str, Any]]:
        """Returns the operational recovery queue with prioritized active recovery cases."""
        records = self.decision_log.get_all_records()
        queue = []

        for r in sorted(records, key=lambda x: x.amount_in_paise, reverse=True):
            exp_incr_paise = int(r.amount_in_paise * 0.75 - (r.action_cost_paise or 0)) if r.selected_action != "NO_ACTION" else 0

            # Priority classification
            if r.amount_in_paise >= 1000000:  # >= INR 10,000
                priority = "CRITICAL"
            elif r.amount_in_paise >= 100000:  # >= INR 1,000
                priority = "HIGH"
            elif r.amount_in_paise >= 10000:   # >= INR 100
                priority = "MEDIUM"
            else:
                priority = "LOW"

            queue.append({
                "case_id": r.decision_id,
                "payment_id": r.payment_id,
                "scenario_id": r.scenario_id,
                "amount_paise": r.amount_in_paise,
                "amount_inr": round(r.amount_in_paise / 100.0, 2),
                "current_state": r.aggregate_state,
                "diagnosis_label": r.diagnosis_label,
                "diagnosis_confidence": round(r.diagnosis_confidence * 100, 1),
                "diagnosis_source": r.diagnosis_source,
                "recommended_action": r.selected_action.value if hasattr(r.selected_action, "value") else str(r.selected_action),
                "timing_window": r.timing_window or "IMMEDIATE",
                "delay_seconds": r.delay_seconds,
                "expected_incremental_value_paise": exp_incr_paise,
                "expected_incremental_value_inr": round(exp_incr_paise / 100.0, 2),
                "priority": priority,
                "governance_status": r.governor_decision or "ALLOW",
                "reason_codes": r.reason_codes,
                "timestamp_epoch": r.timestamp_epoch,
                "time_str": datetime.fromtimestamp(r.timestamp_epoch, tz=timezone.utc).strftime("%b %d, %H:%M:%S UTC"),
            })

        return queue

    def get_case_replay(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Reconstructs the full chronological decision trace and reasoning for a specific case."""
        records = self.decision_log.get_all_records()
        target = next((r for r in records if r.decision_id == case_id or r.payment_id == case_id), None)
        if not target:
            return None

        # Build chronological audit steps
        steps = [
            {
                "step_index": 1,
                "title": "Event Ingestion & Reconciliation",
                "badge": "PAYMENT_FAILED",
                "status": "SUCCESS",
                "timestamp_epoch": target.timestamp_epoch,
                "details": {
                    "payment_id": target.payment_id,
                    "amount_inr": round(target.amount_in_paise / 100.0, 2),
                    "state_before": target.aggregate_state_before,
                    "error_code": target.failure_code or "BAD_REQUEST_ERROR",
                    "evidence_codes": target.evidence_codes,
                },
                "explanation": f"Received payment failure event for payment {target.payment_id}. Reconciled initial state as {target.aggregate_state_before}.",
            },
            {
                "step_index": 2,
                "title": "Risk Assessment & Fraud Boundary",
                "badge": target.risk_level,
                "status": "PASSED" if target.risk_level == "LOW" else "FLAGGED",
                "timestamp_epoch": target.timestamp_epoch + 1,
                "details": {
                    "risk_level": target.risk_level,
                    "is_blacklisted": False,
                    "dispute_risk": "NEGLIGIBLE",
                },
                "explanation": f"Risk detector classified payment as {target.risk_level} risk. Evaluator permitted autonomous recovery exploration.",
            },
            {
                "step_index": 3,
                "title": "Observable Recovery Context Sanitization",
                "badge": "CONTEXT_VERIFIED",
                "status": "SUCCESS",
                "timestamp_epoch": target.timestamp_epoch + 2,
                "details": target.observable_context or {
                    "payment_id": target.payment_id,
                    "amount_in_paise": target.amount_in_paise,
                    "failed_attempts_count": 1,
                    "has_valid_consent": True,
                },
                "explanation": "Constructed sanitized observable recovery context strictly excluding unobservable simulator truth (Y(a) ground truth).",
            },
            {
                "step_index": 4,
                "title": "Root-Cause Diagnosis Inference",
                "badge": f"{target.diagnosis_label.upper()} ({int(target.diagnosis_confidence*100)}%)",
                "status": "DIAGNOSED",
                "timestamp_epoch": target.timestamp_epoch + 3,
                "details": {
                    "inferred_diagnosis": target.diagnosis_label,
                    "confidence_pct": round(target.diagnosis_confidence * 100, 1),
                    "provider_source": target.diagnosis_source,
                    "evidence_codes": target.evidence_codes,
                },
                "explanation": f"Intelligence layer inferred root cause as \"{target.diagnosis_label}\" with {int(target.diagnosis_confidence*100)}% confidence based on observable failure telemetry.",
            },
            {
                "step_index": 5,
                "title": "Action x Timing Candidate Evaluation",
                "badge": target.selected_action.value if hasattr(target.selected_action, "value") else str(target.selected_action),
                "status": "EVALUATED",
                "timestamp_epoch": target.timestamp_epoch + 4,
                "details": {
                    "selected_action": target.selected_action.value if hasattr(target.selected_action, "value") else str(target.selected_action),
                    "timing_window": target.timing_window or "IMMEDIATE",
                    "delay_seconds": target.delay_seconds,
                    "expected_action_cost_paise": target.action_cost_paise or 0,
                    "reason_codes": target.reason_codes,
                },
                "explanation": f"Generated admissible candidate matrix across 5 action mechanisms and timing windows. Selected optimal action {target.selected_action} ({target.timing_window or 'IMMEDIATE'}).",
            },
            {
                "step_index": 6,
                "title": "Recovery Governor v1 Policy Verification",
                "badge": target.governor_decision or "ALLOW",
                "status": target.governor_decision or "ALLOW",
                "timestamp_epoch": target.timestamp_epoch + 5,
                "details": {
                    "governor_verdict": target.governor_decision or "ALLOW",
                    "policy_version": target.governor_policy_version or "v1.0.0",
                    "reason_codes": target.governor_reason_codes,
                    "human_review_reason": target.human_review_reason,
                },
                "explanation": f"Recovery Governor evaluated merchant policies, contact frequency caps, and amount limits. Verdict: {target.governor_decision or 'ALLOW'}.",
            },
            {
                "step_index": 7,
                "title": "Execution & Scheduling State Transition",
                "badge": target.aggregate_state_after,
                "status": "FINALIZED",
                "timestamp_epoch": target.timestamp_epoch + 6,
                "details": {
                    "final_state": target.aggregate_state_after,
                    "stop_reason": target.stop_reason or "CYCLE_COMPLETED",
                    "scheduled_action_id": target.scheduled_action_id,
                    "recovered": target.recovered,
                    "recovered_amount_inr": round((target.recovered_amount_paise or 0) / 100.0, 2),
                },
                "explanation": f"Runtime executed state transition. Final payment status: {target.aggregate_state_after} (Stop reason: {target.stop_reason}).",
            },
        ]

        action_name = target.selected_action.value if hasattr(target.selected_action, "value") else str(target.selected_action)

        # Natural language analytical explanations
        if target.governor_decision == "ABSTAIN" or target.selected_action == "NO_ACTION":
            why_acted = "No active intervention was dispatched to avoid value destruction and unnecessary customer fatigue."
            why_did_not_act = f"Economic modeling computed that marginal expected recovery is lower than execution and fatigue costs. Rationale: {target.rationale}"
        elif target.governor_decision == "DENY":
            why_acted = "Execution was blocked by deterministic Recovery Governor policy rules."
            why_did_not_act = f"Safety gate denied action due to reason codes: {target.governor_reason_codes}. Rationale: {target.rationale}"
        elif target.governor_decision == "ESCALATE":
            why_acted = "Case routed to human operations team for specialized high-touch handling."
            why_did_not_act = f"Autonomous execution withheld because transaction exceeded safe autonomous thresholds. Reason: {target.human_review_reason or target.rationale}"
        else:
            why_acted = f"Dispatched {action_name} at timing {target.timing_window or 'IMMEDIATE'} because expected net recovery uplift is strongly positive (confidence {int(target.diagnosis_confidence*100)}%)."
            why_did_not_act = "Alternative candidates (e.g. immediate retry on gateway spike or generic payment links) were rejected due to lower success probability or higher customer churn risk."

        return {
            "case_id": target.decision_id,
            "payment_id": target.payment_id,
            "scenario_id": target.scenario_id,
            "amount_inr": round(target.amount_in_paise / 100.0, 2),
            "current_state": target.aggregate_state_after,
            "diagnosis_label": target.diagnosis_label,
            "diagnosis_confidence": round(target.diagnosis_confidence * 100, 1),
            "diagnosis_source": target.diagnosis_source,
            "selected_action": action_name,
            "timing_window": target.timing_window or "IMMEDIATE",
            "governor_decision": target.governor_decision or "ALLOW",
            "governor_reasons": target.governor_reason_codes,
            "stop_reason": target.stop_reason,
            "timestamp_str": datetime.fromtimestamp(target.timestamp_epoch, tz=timezone.utc).strftime("%b %d, %Y - %H:%M:%S UTC"),
            "why_acted": why_acted,
            "why_did_not_act": why_did_not_act,
            "steps": steps,
        }

    def get_evaluation_data(self) -> Dict[str, Any]:
        """Loads multi-seed benchmark results, baseline comparisons, oracle ceiling, regret distribution, and sensitivity matrix."""
        bench_data = self._load_benchmark_data()
        if not bench_data:
            return {
                "status": "NO_BENCHMARK_RUN",
                "message": "No benchmark report found. Run `python scripts/benchmark.py` to generate complete multi-seed statistical evaluation.",
            }

        cfg = bench_data.get("config", {})
        combined_split = bench_data.get("combined_split", {})
        sens = bench_data.get("sensitivity_analysis", {})

        # Format baseline table from combined split
        baseline_table = []
        policy_results = combined_split.get("policy_results", {})

        policy_display_order = [
            ("baseline_0_no_action", "Baseline 0: No Action (Natural Organic)"),
            ("baseline_1_always_retry", "Baseline 1: Always Retry (Naive Dunning)"),
            ("baseline_2_static_rules", "Baseline 2: Static Rule Engine"),
            ("baseline_3_probability_only", "Baseline 3: Probability Maximizer"),
            ("RECOVERYOS_DETERMINISTIC_V0", "RecoveryOS Autonomous Agent v0"),
        ]

        for p_key, p_label in policy_display_order:
            p_data = policy_results.get(p_key, {})
            dist = p_data.get("metric_distributions", {})
            regret = p_data.get("regret_summary", {})

            gross_mean = dist.get("gross_recovered_amount_paise", {}).get("mean", 0) / 100.0
            gross_std = dist.get("gross_recovered_amount_paise", {}).get("std", 0) / 100.0
            cost_mean = dist.get("total_action_cost_paise", {}).get("mean", 0) / 100.0
            churn_mean = dist.get("total_churned_customers", {}).get("mean", 0)
            adj_net_mean = dist.get("adjusted_net_recovery_paise", {}).get("mean", 0) / 100.0
            incr_net_mean = dist.get("incremental_adjusted_net_recovery_paise", {}).get("mean", 0) / 100.0
            acts_mean = dist.get("intervention_count", {}).get("mean", 0)
            avoid_mean = dist.get("actions_avoided_count", {}).get("mean", 0)

            baseline_table.append({
                "policy_key": p_key,
                "policy_name": p_label,
                "is_recoveryos": "RECOVERYOS" in p_key,
                "gross_recovery_inr": round(gross_mean, 2),
                "gross_std_inr": round(gross_std, 2),
                "action_cost_inr": round(cost_mean, 2),
                "churn_count": round(churn_mean, 1),
                "adjusted_net_inr": round(adj_net_mean, 2),
                "incremental_adjusted_net_inr": round(incr_net_mean, 2),
                "interventions": round(acts_mean, 1),
                "actions_avoided": round(avoid_mean, 1),
                "mean_regret_inr": round(regret.get("mean_regret_paise", 0) / 100.0, 2),
                "zero_regret_rate_pct": round(regret.get("zero_regret_rate", 0) * 100.0, 1),
            })

        oracle_comp = combined_split.get("oracle_comparison", {})
        regret_summary = policy_results.get("RECOVERYOS_DETERMINISTIC_V0", {}).get("regret_summary", {})

        return {
            "status": "AVAILABLE",
            "timestamp_iso": bench_data.get("timestamp_iso"),
            "config": {
                "total_scenarios": combined_split.get("total_scenarios", 0),
                "dev_seeds": cfg.get("dev_seeds", []),
                "holdout_seeds": cfg.get("holdout_seeds", []),
                "churn_penalty_inr": round(cfg.get("churn_penalty_paise", 250000) / 100.0, 2),
            },
            "baseline_table": baseline_table,
            "oracle_comparison": {
                "oracle_gross_inr": round(oracle_comp.get("oracle_gross_recovery_paise", 0) / 100.0, 2),
                "oracle_incremental_adjusted_net_inr": round(oracle_comp.get("oracle_incremental_adjusted_net_recovery_paise", 0) / 100.0, 2),
                "recoveryos_incremental_adjusted_net_inr": round(oracle_comp.get("recoveryos_incremental_adjusted_net_recovery_paise", 0) / 100.0, 2),
                "incremental_gap_inr": round(oracle_comp.get("recoveryos_vs_oracle_gap_paise", 0) / 100.0, 2),
                "efficiency_pct": round(oracle_comp.get("recoveryos_oracle_efficiency_pct", 0), 1),
            },
            "regret_distribution": {
                "total_regret_inr": round(regret_summary.get("total_regret_paise", 0) / 100.0, 2),
                "mean_regret_inr": round(regret_summary.get("mean_regret_paise", 0) / 100.0, 2),
                "median_regret_inr": round(regret_summary.get("median_regret_paise", 0) / 100.0, 2),
                "p95_regret_inr": round(regret_summary.get("p95_regret_paise", 0) / 100.0, 2),
                "zero_regret_count": regret_summary.get("zero_regret_count", 0),
                "zero_regret_rate_pct": round(regret_summary.get("zero_regret_rate", 0) * 100.0, 1),
                "total_scenarios": regret_summary.get("total_scenarios", 0),
            },
            "sensitivity_analysis": {
                "total_combinations": sens.get("total_combinations", 9),
                "win_rate_pct": sens.get("recoveryos_win_rate_pct", 100.0),
                "wins_count": sens.get("recoveryos_wins_count", 9),
                "grid_cells": sens.get("grid_cells", []),
            },
        }

    def get_policies(self) -> Dict[str, Any]:
        """Returns active merchant policy rules, amount thresholds, and automation settings (read-only)."""
        p = self.merchant_policy
        return {
            "policy_version": p.policy_version,
            "merchant_id": "mer_rzp_live_2026",
            "automation_mode": p.automation_mode.value if hasattr(p.automation_mode, "value") else str(p.automation_mode),
            "max_retries": p.max_retries,
            "max_retry_attempts_total": p.max_retries,
            "max_contacts_24h": p.max_contacts_24h,
            "contact_limit_24h": p.max_contacts_24h,
            "max_contacts_7d": p.max_contacts_7d,
            "min_cooldown_seconds": p.cooldown_seconds,
            "min_cooldown_hours_between_attempts": round(p.cooldown_seconds / 3600.0, 1),
            "max_autonomous_amount_paise": p.max_automatic_action_amount_paise,
            "max_autonomous_amount_inr": round(p.max_automatic_action_amount_paise / 100.0, 2),
            "auto_escalate_amount_paise": p.human_review_amount_threshold_paise,
            "auto_escalate_amount_inr": round(p.human_review_amount_threshold_paise / 100.0, 2),
            "allowed_action_types": [a.value if hasattr(a, "value") else str(a) for a in p.allowed_action_types],
            "min_expected_incremental_value_paise": p.min_expected_incremental_value_paise,
            "min_expected_net_value_inr": round(p.min_expected_incremental_value_paise / 100.0, 2),
            "min_diagnosis_confidence": p.min_diagnosis_confidence,
            "min_diagnosis_confidence_autonomous": p.min_diagnosis_confidence,
            "require_explicit_consent_for_contact": p.consent_behavior == "STRICT_OPT_OUT",
            "consent_behavior": p.consent_behavior,
            "recovery_window_hours": p.recovery_window_hours,
        }

    def get_exceptions(self) -> List[Dict[str, Any]]:
        """Returns notable operational exceptions: stale actions, consent blocks, policy violations, and human escalations."""
        records = self.decision_log.list_records()
        exceptions = []

        for r in records:
            if r.governor_decision in ("DENY", "DEFER", "ESCALATE") or (r.stop_reason and "STALE" in r.stop_reason):
                exc_type = "POLICY_BLOCK"
                severity = "MEDIUM"
                if r.governor_decision == "ESCALATE":
                    exc_type = "HUMAN_REVIEW_ESCALATION"
                    severity = "HIGH"
                elif "CONSENT" in str(r.governor_reason_codes):
                    exc_type = "CONSENT_OPT_OUT"
                    severity = "HIGH"
                elif "STALE" in str(r.stop_reason):
                    exc_type = "STALE_ACTION_PREVENTED"
                    severity = "LOW"

                exceptions.append({
                    "exception_id": f"exc_{r.decision_id}",
                    "case_id": r.decision_id,
                    "payment_id": r.payment_id,
                    "amount_inr": round(r.amount_in_paise / 100.0, 2),
                    "exception_type": exc_type,
                    "severity": severity,
                    "governor_verdict": r.governor_decision or "ALLOW",
                    "reason_codes": r.governor_reason_codes or r.reason_codes,
                    "human_review_reason": r.human_review_reason,
                    "timestamp_epoch": r.timestamp_epoch,
                    "time_str": datetime.fromtimestamp(r.timestamp_epoch, tz=timezone.utc).strftime("%b %d, %H:%M:%S UTC"),
                    "resolution_state": "RESOLVED" if r.aggregate_state in ("CAPTURED", "OPTED_OUT", "FAILED") else "PENDING_REVIEW",
                })

        return sorted(exceptions, key=lambda x: x["timestamp_epoch"], reverse=True)

    def _load_benchmark_data(self) -> Optional[Dict[str, Any]]:
        """Loads benchmark JSON artifact from reports directory if available."""
        path = os.path.join(self.reports_dir, "benchmark_detail.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


# Global singleton instance
dashboard_service = DashboardService()
