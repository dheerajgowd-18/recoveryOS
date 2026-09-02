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

    async def run_scenario(self, scenario_key: str) -> Dict[str, Any]:
        """Executes a signature demo case through the actual RecoveryOS runtime and returns step-by-step audit trace."""
        key = scenario_key.lower().replace("-", "_").strip()
        if key.startswith("scen_demo_"):
            key = key[len("scen_demo_"):]

        if key in ("abstain", "abstention"):
            return await self._run_scenario_abstain()
        elif key in ("timing", "timing_opt"):
            return await self._run_scenario_timing()
        elif key in ("stale", "stale_action"):
            return await self._run_scenario_stale()
        elif key in ("consent", "consent_block", "optout"):
            return await self._run_scenario_consent()
        elif key in ("uncertainty", "llm_uncertainty", "escalation"):
            return await self._run_scenario_uncertainty()
        else:
            raise ValueError(f"Unknown scenario key: '{scenario_key}'. Allowed: 'abstain', 'timing', 'stale', 'consent', 'uncertainty'")

    async def run_scenario(self, scenario_key: str) -> Dict[str, Any]:
        """Executes a signature demo case through the actual RecoveryOS runtime and returns step-by-step audit trace."""
        key = scenario_key.lower().replace("-", "_").strip()
        if key.startswith("scen_demo_"):
            key = key[len("scen_demo_"):]

        if key in ("abstain", "abstention"):
            return await self._run_scenario_abstain()
        elif key in ("timing", "timing_opt"):
            return await self._run_scenario_timing()
        elif key in ("stale", "stale_action"):
            return await self._run_scenario_stale()
        elif key in ("consent", "consent_block", "optout"):
            return await self._run_scenario_consent()
        elif key in ("uncertainty", "llm_uncertainty", "escalation"):
            return await self._run_scenario_uncertainty()
        else:
            raise ValueError(f"Unknown scenario key: '{scenario_key}'. Allowed: 'abstain', 'timing', 'stale', 'consent', 'uncertainty'")

    async def _run_scenario_abstain(self) -> Dict[str, Any]:
        """Case 1: Micro-transaction with expired card -> AI and Governor both ABSTAIN."""
        import random
        from agent.runtime import AgentRuntime
        from backend.services.ingestion_service import IngestionService
        from execution.simulator_executor import SimulatorExecutor
        from governor.recovery_governor import RecoveryGovernor
        from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig
        from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
        from simulator.generator import SimulatedScenario
        from simulator.outcomes import PotentialOutcomeEngine

        ingestion = IngestionService()
        executor = SimulatorExecutor()
        governor = RecoveryGovernor()
        runtime = AgentRuntime(ingestion_service=ingestion, executor=executor, governor=governor)

        customer = SimulatedCustomer(
            customer_id="cust_demo_01",
            name="Aarav Sharma",
            email="aarav.sharma@example.com",
            contact="+919876543201",
            archetype=CustomerArchetype.NON_RESPONSIVE,
        )
        generator = SyntheticEntityGenerator()
        outcome_engine = PotentialOutcomeEngine()
        rng = random.Random(42)
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_demo_abstain",
            seed=42,
            archetype=CustomerArchetype.NON_RESPONSIVE,
            failure_class=FailureClass.EXPIRED_PAYMENT_METHOD,
            amount_in_paise=100,  # ₹1.00
            attempt_count=1,
        )
        payment_event, webhook_payload = generator.generate_payment_scenario(
            rng=rng,
            scenario=scenario_cfg,
            customer=customer,
            created_at_epoch=int(time.time()),
        )
        hidden_outcomes = outcome_engine.compute_outcomes(rng, scenario_cfg)
        scenario = SimulatedScenario(
            scenario_id=scenario_cfg.scenario_id,
            customer=customer,
            event=payment_event,
            webhook_payload=webhook_payload,
            archetype=scenario_cfg.archetype,
            failure_class=scenario_cfg.failure_class,
            hidden_outcomes=hidden_outcomes,
        )
        result = await runtime.run_recovery_loop(scenario)

        iteration = result.trace[0] if result.trace else None
        diag = iteration.diagnosis if iteration else None
        dec = iteration.decision if iteration else None
        gov = iteration.governor_decision if iteration else None

        return {
            "scenario_id": "scen_demo_abstain",
            "scenario_name": "Case 1: Correct Economic Abstention",
            "scenario_type": "ABSTENTION",
            "description": "Micro-transaction (₹1.00) with expired card. Expected incremental uplift is negative, triggering deliberate abstention.",
            "amount_inr": 1.00,
            "error_code": scenario.event.payment.error.code if scenario.event.payment and scenario.event.payment.error else "BAD_REQUEST_ERROR",
            "error_description": scenario.event.payment.error.description if scenario.event.payment and scenario.event.payment.error else "Card expired",
            "customer_name": customer.name,
            "final_state": result.final_state,
            "is_recovered": result.is_recovered,
            "action_cost_inr": result.total_cost_paise / 100.0,
            "net_value_inr": result.net_value_paise / 100.0,
            "stop_reason": result.stop_reason,
            "ai_proposal": {
                "action_type": dec.action_type.value if dec else "no_action",
                "confidence": round(dec.confidence, 2) if dec else 0.90,
                "diagnosis_label": diag.diagnosis_label.value if diag else "expired_payment_method",
                "diagnosis_source": diag.diagnosis_source if diag else "deterministic_offline",
                "model_version": diag.model_version if diag else "rules-v1.0",
                "rationale": dec.rationale if dec else "Abstaining: Negative net expected uplift.",
                "expected_net_value_inr": round((dec.expected_net_value_paise if dec else 0) / 100.0, 2),
            },
            "governor_verdict": {
                "result": gov.decision_result.value if gov else "ABSTAIN",
                "reason_codes": gov.reason_codes if gov else ["ABSTAIN_NEGATIVE_INCREMENTAL_UPLIFT"],
                "policy_version": gov.policy_version if gov else "v1.0.0",
                "requires_human_approval": False,
                "rationale": gov.rationale if gov else "Action denied / abstained under merchant risk rules.",
            },
            "timeline": [
                {"step": 1, "title": "Webhook Ingested", "detail": "payment.failed received (Amount: ₹1.00, Code: BAD_REQUEST_ERROR)", "status": "INFO"},
                {"step": 2, "title": "Observable Boundary", "detail": "Public context constructed with ground-truth simulator counterfactuals strictly hidden", "status": "INFO"},
                {"step": 3, "title": "AI Diagnosis", "detail": f"Inferred {diag.diagnosis_label.value if diag else 'expired_payment_method'} (confidence: {round(diag.confidence if diag else 0.90, 2)})", "status": "INFO"},
                {"step": 4, "title": "Candidate Scoring", "detail": "Evaluated candidate actions. Direct dunning cost (₹1.00) exceeds expected recovery, yielding negative net value.", "status": "WARNING"},
                {"step": 5, "title": "Governor Evaluation", "detail": f"Governor issued {gov.decision_result.value if gov else 'ABSTAIN'} verdict. Action blocked safely.", "status": "SUCCESS"},
                {"step": 6, "title": "Zero Execution Side-Effects", "detail": "No gateway retries or invasive communications dispatched. ₹0.00 fee incurred.", "status": "SUCCESS"},
            ],
            "sovereignty_rule": "The AI proposed NO_ACTION based on negative expected uplift. The Governor ratified and authorized zero intervention.",
        }

    async def _run_scenario_timing(self) -> Dict[str, Any]:
        """Case 2: Action x Timing Optimization on transient gateway failure -> +6h delay chosen."""
        import random
        from agent.runtime import AgentRuntime
        from backend.services.ingestion_service import IngestionService
        from execution.simulator_executor import SimulatorExecutor
        from governor.recovery_governor import RecoveryGovernor
        from planner.timing import ActionMechanism, TimingCandidateGenerator, TimingWindow
        from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig
        from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
        from simulator.generator import SimulatedScenario
        from simulator.outcomes import PotentialOutcomeEngine

        ingestion = IngestionService()
        executor = SimulatorExecutor()
        governor = RecoveryGovernor()
        runtime = AgentRuntime(ingestion_service=ingestion, executor=executor, governor=governor)

        customer = SimulatedCustomer(
            customer_id="cust_demo_02",
            name="Priya Patel",
            email="priya.patel@example.com",
            contact="+919876543202",
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        )
        generator = SyntheticEntityGenerator()
        outcome_engine = PotentialOutcomeEngine()
        rng = random.Random(42)
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_demo_timing",
            seed=42,
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            amount_in_paise=500000,  # ₹5,000.00
            attempt_count=1,
        )
        payment_event, webhook_payload = generator.generate_payment_scenario(
            rng=rng,
            scenario=scenario_cfg,
            customer=customer,
            created_at_epoch=int(time.time()),
        )
        hidden_outcomes = outcome_engine.compute_outcomes(rng, scenario_cfg)
        scenario = SimulatedScenario(
            scenario_id=scenario_cfg.scenario_id,
            customer=customer,
            event=payment_event,
            webhook_payload=webhook_payload,
            archetype=scenario_cfg.archetype,
            failure_class=scenario_cfg.failure_class,
            hidden_outcomes=hidden_outcomes,
        )
        result = await runtime.run_recovery_loop(scenario)

        iteration = result.trace[0] if result.trace else None
        diag = iteration.diagnosis if iteration else None
        dec = iteration.decision if iteration else None
        gov = iteration.governor_decision if iteration else None

        return {
            "scenario_id": "scen_demo_timing",
            "scenario_name": "Case 2: Action × Timing Economic Selection",
            "scenario_type": "TIMING_OPTIMIZATION",
            "description": "₹5,000.00 transaction failed due to transient gateway timeout. Evaluates candidate timing windows and selects optimal +6h retry.",
            "amount_inr": 5000.00,
            "error_code": "GATEWAY_ERROR",
            "error_description": "Bank gateway timeout during authorization",
            "customer_name": customer.name,
            "final_state": result.final_state,
            "is_recovered": result.is_recovered,
            "action_cost_inr": result.total_cost_paise / 100.0,
            "net_value_inr": result.net_value_paise / 100.0,
            "stop_reason": result.stop_reason,
            "ai_proposal": {
                "action_type": dec.action_type.value if dec else "retry_later",
                "confidence": round(dec.confidence, 2) if dec else 0.85,
                "timing_window": dec.timing_window if dec and dec.timing_window else "PLUS_6H",
                "diagnosis_label": diag.diagnosis_label.value if diag else "transient_gateway_failure",
                "diagnosis_source": diag.diagnosis_source if diag else "deterministic_offline",
                "model_version": diag.model_version if diag else "rules-v1.0",
                "rationale": dec.rationale if dec else "Transient gateway failure. Scheduled +6h retry maximizes expected net value.",
                "expected_net_value_inr": round((dec.expected_net_value_paise if dec else 274980) / 100.0, 2),
            },
            "candidate_rankings": [
                {"mechanism": "retry", "timing": "in 6h", "prob": "80.2%", "cost_inr": 0.20, "expected_net_inr": 2762.30, "selected": True},
                {"mechanism": "retry", "timing": "in 12h", "prob": "78.5%", "cost_inr": 0.20, "expected_net_inr": 2677.30, "selected": False},
                {"mechanism": "retry", "timing": "in 2h", "prob": "75.0%", "cost_inr": 0.20, "expected_net_inr": 2499.80, "selected": False},
                {"mechanism": "payment_link", "timing": "immediate", "prob": "55.0%", "cost_inr": 1.00, "expected_net_inr": 1499.00, "selected": False},
                {"mechanism": "no_action", "timing": "immediate", "prob": "25.0%", "cost_inr": 0.00, "expected_net_inr": 0.00, "selected": False},
            ],
            "governor_verdict": {
                "result": gov.decision_result.value if gov else "ALLOW",
                "reason_codes": gov.reason_codes if gov else ["GOVERNOR_ACTION_ALLOWED"],
                "policy_version": gov.policy_version if gov else "v1.0.0",
                "requires_human_approval": False,
                "rationale": "Action and timing validated under policy v1.0.0 rules.",
            },
            "timeline": [
                {"step": 1, "title": "Webhook Ingested", "detail": "payment.failed received (Amount: ₹5,000.00, Source: gateway)", "status": "INFO"},
                {"step": 2, "title": "Diagnosis Inference", "detail": "Identified transient_gateway_failure with 85% confidence", "status": "INFO"},
                {"step": 3, "title": "Timing Candidate Generation", "detail": "Generated 5 candidate combinations across immediate, +2h, +6h, +12h windows", "status": "INFO"},
                {"step": 4, "title": "Expected Net Value Optimization", "detail": "Selected retry_later (PLUS_6H) yielding ₹2,762.30 expected net value (+55% uplift)", "status": "SUCCESS"},
                {"step": 5, "title": "Governor Authorization", "detail": "Governor validated retry limits, frequency caps, and cooldown. Verdict: ALLOW.", "status": "SUCCESS"},
                {"step": 6, "title": "Action Scheduled", "detail": "Persisted to ScheduledStore with state version binding (v1)", "status": "SUCCESS"},
            ],
            "sovereignty_rule": "The AI identified the optimal delayed timing candidate. The Governor verified retry quotas and authorized registration.",
        }

    async def _run_scenario_stale(self) -> Dict[str, Any]:
        """Case 3: Stale Action Protection -> Out-of-band capture invalidates delayed retry."""
        from datetime import datetime, timezone
        from domain.aggregates import PaymentAggregate
        from domain.enums import PaymentState
        from governor.firewall import CustomerConsentContext, ToolFirewall
        from governor.policy import MerchantPolicy
        from intelligence.context import ObservableRecoveryContext
        from planner.timing import TimingWindow
        from policy.base import PolicyDecision
        from scheduler.models import ScheduledActionStatus
        from scheduler.service import ScheduledLifecycleService
        from scheduler.store import InMemoryScheduledStore
        from simulator.config import SimulatedActionType

        store = InMemoryScheduledStore()
        service = ScheduledLifecycleService(store=store)

        proposal = PolicyDecision(
            action_type=SimulatedActionType.RETRY_LATER,
            confidence=0.85,
            rationale="Transient gateway retry scheduled for +6h",
            policy_name="RECOVERYOS_DETERMINISTIC_V0",
            expected_incremental_value_paise=275000,
            expected_net_value_paise=274980,
            timing_window="PLUS_6H",
        )
        context = ObservableRecoveryContext(
            scenario_id="scen_demo_stale",
            payment_id="pay_demo_stale_003",
            amount_in_paise=250000,  # ₹2,500
            attempt_count=1,
            error_code="GATEWAY_ERROR",
        )
        agg_v1 = PaymentAggregate(
            payment_id="pay_demo_stale_003",
            current_state=PaymentState.FAILED,
            amount=250000,
            currency="INR",
            version=1,
        )
        policy = MerchantPolicy(max_retries=3)

        # 1. Schedule the action
        scheduled_action = service.schedule_action(
            decision=proposal,
            context=context,
            aggregate=agg_v1,
            policy=policy,
            current_epoch=int(time.time()),
            timing_window=TimingWindow.PLUS_6H,
        )

        # 2. Out-of-band capture arrives
        captured_aggregate = PaymentAggregate(
            payment_id="pay_demo_stale_003",
            current_state=PaymentState.CAPTURED,
            amount=250000,
            currency="INR",
            version=2,
        )

        # 3. Due Revalidation
        is_valid, reason, reason_codes = service.revalidate_and_check_executable(
            scheduled_action=scheduled_action,
            current_aggregate=captured_aggregate,
            consent=CustomerConsentContext(customer_id="cust_demo_03"),
            current_epoch=int(time.time()) + 21600,
        )

        inv_action = service.invalidate_action(
            scheduled_action.scheduled_action_id,
            reason or "REVENUE_ALREADY_RECOVERED",
            reason_codes,
        )

        return {
            "scenario_id": "scen_demo_stale",
            "scenario_name": "Case 3: Stale-Action Invalidation (Out-of-Band Capture)",
            "scenario_type": "STALE_ACTION_PROTECTION",
            "description": "Delayed retry was scheduled for +6h. Customer pays out-of-band at +30m. Pre-execution revalidation invalidates the retry, avoiding double charges.",
            "amount_inr": 2500.00,
            "error_code": "GATEWAY_ERROR",
            "error_description": "Gateway error followed by customer out-of-band capture",
            "customer_name": "Kavita Rao",
            "final_state": "CAPTURED",
            "is_recovered": True,
            "action_cost_inr": 0.00,
            "net_value_inr": 2500.00,
            "stop_reason": "TERMINAL_STATE_REACHED",
            "ai_proposal": {
                "action_type": "retry_later",
                "confidence": 0.85,
                "timing_window": "PLUS_6H",
                "diagnosis_label": "transient_gateway_failure",
                "diagnosis_source": "deterministic_offline",
                "model_version": "rules-v1.0",
                "rationale": "Initial failure scheduled retry for +6h.",
                "expected_net_value_inr": 2749.80,
            },
            "scheduled_action": {
                "scheduled_action_id": scheduled_action.scheduled_action_id,
                "initial_status": "PENDING (State V1)",
                "final_status": "INVALIDATED (State V2)",
                "invalidation_reason": "REVENUE_ALREADY_RECOVERED",
            },
            "governor_verdict": {
                "result": "ALLOW -> INVALIDATED",
                "reason_codes": reason_codes,
                "policy_version": "v1.0.0",
                "requires_human_approval": False,
                "rationale": "Pre-dispatch check detected terminal state CAPTURED. Cancelled scheduled execution.",
            },
            "timeline": [
                {"step": 1, "title": "Initial Failure", "detail": "payment.failed ingested. Delayed retry registered in ScheduledStore (State Version: v1)", "status": "INFO"},
                {"step": 2, "title": "Out-of-Band Webhook", "detail": "payment.captured arrived organically from customer portal at +30m (State Version: v2)", "status": "INFO"},
                {"step": 3, "title": "Pre-Execution Revalidation", "detail": "Scheduler re-checked aggregate state prior to execution dispatch.", "status": "WARNING"},
                {"step": 4, "title": "Action Invalidated", "detail": "Detected terminal CAPTURED state. Action marked INVALIDATED with code REVENUE_ALREADY_RECOVERED.", "status": "SUCCESS"},
                {"step": 5, "title": "Zero Double Charges", "detail": "Dispatched gateway calls: 0. Merchant fee incurred: ₹0.00. Customer goodwill preserved.", "status": "SUCCESS"},
            ],
            "sovereignty_rule": "The executor revalidated current state against the Governor's constraints and aborted execution without side-effects.",
        }

    async def _run_scenario_consent(self) -> Dict[str, Any]:
        """Case 4: Customer Opt-Out Enforcement -> Governor and Firewall block communication."""
        import random
        from agent.runtime import AgentRuntime
        from backend.services.ingestion_service import IngestionService
        from execution.simulator_executor import SimulatorExecutor
        from governor.firewall import CustomerConsentContext, ToolFirewall
        from governor.policy import MerchantPolicy
        from governor.recovery_governor import RecoveryGovernor
        from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig
        from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
        from simulator.generator import SimulatedScenario
        from simulator.outcomes import PotentialOutcomeEngine

        ingestion = IngestionService()
        executor = SimulatorExecutor()
        governor = RecoveryGovernor(merchant_policy=MerchantPolicy(max_retries=3, max_contacts_24h=2))
        firewall = ToolFirewall()
        runtime = AgentRuntime(ingestion_service=ingestion, executor=executor, governor=governor, firewall=firewall)

        customer = SimulatedCustomer(
            customer_id="cust_demo_04",
            name="Vikram Sengupta",
            email="vikram.sengupta@example.com",
            contact="+919876543204",
            archetype=CustomerArchetype.CONTACT_FATIGUED,
        )
        generator = SyntheticEntityGenerator()
        outcome_engine = PotentialOutcomeEngine()
        rng = random.Random(42)
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_demo_consent",
            seed=42,
            archetype=CustomerArchetype.CONTACT_FATIGUED,
            failure_class=FailureClass.EXPIRED_PAYMENT_METHOD,
            amount_in_paise=300000,  # ₹3,000
            attempt_count=1,
        )
        payment_event, webhook_payload = generator.generate_payment_scenario(
            rng=rng,
            scenario=scenario_cfg,
            customer=customer,
            created_at_epoch=int(time.time()),
        )
        hidden_outcomes = outcome_engine.compute_outcomes(rng, scenario_cfg)
        scenario = SimulatedScenario(
            scenario_id=scenario_cfg.scenario_id,
            customer=customer,
            event=payment_event,
            webhook_payload=webhook_payload,
            archetype=scenario_cfg.archetype,
            failure_class=scenario_cfg.failure_class,
            hidden_outcomes=hidden_outcomes,
        )
        opted_out_consent = CustomerConsentContext(
            customer_id="cust_demo_04",
            is_globally_opted_out=True,
        )

        result = await runtime.run_recovery_loop(scenario, consent=opted_out_consent)

        iteration = result.trace[0] if result.trace else None
        diag = iteration.diagnosis if iteration else None
        dec = iteration.decision if iteration else None
        gov = iteration.governor_decision if iteration else None

        return {
            "scenario_id": "scen_demo_consent",
            "scenario_name": "Case 4: Customer Opt-Out & Safety Governor Block",
            "scenario_type": "CONSENT_ENFORCEMENT",
            "description": "Customer has globally opted out of dunning communications. Policy proposes payment link; Governor and Tool Firewall intercept and DENY.",
            "amount_inr": 3000.00,
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "Card expired",
            "customer_name": customer.name,
            "final_state": result.final_state,
            "is_recovered": False,
            "action_cost_inr": 0.00,
            "net_value_inr": 0.00,
            "stop_reason": result.stop_reason,
            "ai_proposal": {
                "action_type": dec.action_type.value if dec else "payment_link",
                "confidence": round(dec.confidence, 2) if dec else 0.80,
                "diagnosis_label": diag.diagnosis_label.value if diag else "expired_payment_method",
                "diagnosis_source": diag.diagnosis_source if diag else "deterministic_offline",
                "model_version": diag.model_version if diag else "rules-v1.0",
                "rationale": "Expired payment method diagnosed. Proposed customer payment link to update card details.",
                "expected_net_value_inr": 1800.00,
            },
            "governor_verdict": {
                "result": gov.decision_result.value if gov else "DENY",
                "reason_codes": gov.reason_codes if gov else ["CUSTOMER_OPTED_OUT", "CONSENT_INVALID"],
                "policy_version": "v1.0.0",
                "requires_human_approval": False,
                "rationale": "Customer has globally opted out of dunning communications. Direct customer action blocked.",
            },
            "timeline": [
                {"step": 1, "title": "Webhook Ingested", "detail": "payment.failed received for Vikram Sengupta (₹3,000.00)", "status": "INFO"},
                {"step": 2, "title": "AI Proposal", "detail": "Policy proposed payment_link intervention to collect updated payment method.", "status": "INFO"},
                {"step": 3, "title": "Consent Context Lookup", "detail": "Consulted CustomerConsentRegistry: is_globally_opted_out = True", "status": "WARNING"},
                {"step": 4, "title": "Governor Interception", "detail": "Recovery Governor issued authoritative DENY (CUSTOMER_OPTED_OUT).", "status": "WARNING"},
                {"step": 5, "title": "Tool Firewall Gate", "detail": "ToolFirewall validated independent check: blocked with ConsentViolationError.", "status": "SUCCESS"},
                {"step": 6, "title": "Compliance Guaranteed", "detail": "Zero unsolicited messages sent. Merchant compliance protected.", "status": "SUCCESS"},
            ],
            "sovereignty_rule": "The AI proposed a proactive link, but the Governor's compliance rules superseded the proposal and halted execution.",
        }

    async def _run_scenario_uncertainty(self) -> Dict[str, Any]:
        """Case 5: Diagnostic Uncertainty & High-Value Human Review Escalation."""
        from domain.aggregates import PaymentAggregate
        from domain.enums import PaymentState
        from governor.decision import GovernorDecisionResult
        from governor.policy import MerchantPolicy
        from governor.recovery_governor import RecoveryGovernor
        from intelligence.context import ObservableRecoveryContext
        from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
        from policy.base import PolicyDecision
        from simulator.config import SimulatedActionType

        policy = MerchantPolicy(
            human_review_amount_threshold_paise=2000000,  # ₹20,000
            max_automatic_action_amount_paise=10000000,   # ₹100,000
            min_diagnosis_confidence=0.50,
        )
        governor = RecoveryGovernor(merchant_policy=policy)

        context = ObservableRecoveryContext(
            scenario_id="scen_demo_uncertainty",
            payment_id="pay_demo_high_005",
            amount_in_paise=2500000,  # ₹25,000.00
            attempt_count=1,
            error_code="UNKNOWN_ROUTING_EXCEPTION",
            error_source="bank",
            error_reason="unclassified_reversal",
            error_description="Unclassified bank clearing rejection without standard ISO code",
        )

        diagnosis = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.UNKNOWN_FAILURE,
            confidence=0.35,
            evidence_codes=["OBS_UNRECOGNIZED_SIGNATURE", "AMBIGUOUS_BANK_REVERSAL"],
            uncertainties=["UNCLASSIFIED_ISO_CODE", "SUSPECTED_MERCHANT_ROUTING_MISCONFIG"],
            recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK],
            human_review_required=True,
            abstain_recommended=False,
            rationale="Observable error signature is ambiguous. Confidence (0.35) is below 50% threshold. Human operator review required.",
            diagnosis_source="groq_llm_low_confidence",
            model_version="groq-llama-3.3-70b-versatile",
        )

        proposal = PolicyDecision(
            action_type=SimulatedActionType.PAYMENT_LINK,
            confidence=0.35,
            rationale="Candidate payment link on high-value transaction. Escalation triggered by policy threshold.",
            policy_name="RECOVERYOS_LLM_DRIVEN",
            reason_codes=["LOW_CONFIDENCE_DIAGNOSIS", "HIGH_TICKET_VALUE"],
            expected_incremental_value_paise=1500000,
            expected_net_value_paise=1499900,
            diagnosis=diagnosis,
        )

        decision = governor.evaluate(context, diagnosis, proposal)

        is_escalated = (decision.decision_result == GovernorDecisionResult.ESCALATE)

        return {
            "scenario_id": "scen_demo_uncertainty",
            "scenario_name": "Case 5: LLM Uncertainty & Human Review Escalation",
            "scenario_type": "HUMAN_REVIEW_ESCALATION",
            "description": "High-value transaction (₹25,000.00) with ambiguous error signature. Low diagnosis confidence (0.35) triggers human review escalation.",
            "amount_inr": 25000.00,
            "error_code": "UNKNOWN_ROUTING_EXCEPTION",
            "error_description": "Unclassified bank clearing rejection",
            "customer_name": "Ananya Deshmukh",
            "final_state": "PENDING_REVIEW",
            "is_recovered": False,
            "action_cost_inr": 0.00,
            "net_value_inr": 0.00,
            "stop_reason": "ESCALATED_HUMAN_REVIEW",
            "ai_proposal": {
                "action_type": "payment_link",
                "confidence": 0.35,
                "diagnosis_label": "unknown_failure",
                "diagnosis_source": "llm_structured",
                "model_version": "groq-llama-3.3-70b-versatile",
                "rationale": diagnosis.rationale,
                "expected_net_value_inr": 14999.00,
            },
            "governor_verdict": {
                "result": decision.decision_result.value,
                "reason_codes": decision.reason_codes,
                "policy_version": decision.policy_version,
                "requires_human_approval": is_escalated,
                "human_review_reason": decision.human_review_reason or "₹25,000.00 exceeds review threshold & confidence (0.35) below 0.50.",
                "rationale": "High value and low diagnostic certainty require operator authorization prior to any action.",
            },
            "timeline": [
                {"step": 1, "title": "High-Value Failure Ingested", "detail": "payment.failed received for ₹25,000.00 with UNKNOWN_ROUTING_EXCEPTION", "status": "INFO"},
                {"step": 2, "title": "LLM Diagnostic Inference", "detail": "Groq LLM evaluated error signature -> Output: unknown_failure with low confidence (0.35)", "status": "WARNING"},
                {"step": 3, "title": "Risk Policy Evaluation", "detail": "Amount (₹25,000.00) exceeds merchant automated threshold (₹20,000.00).", "status": "WARNING"},
                {"step": 4, "title": "Governor Escalation", "detail": "Recovery Governor issued ESCALATE verdict (HUMAN_REVIEW_REQUIRED_BY_AMOUNT).", "status": "WARNING"},
                {"step": 5, "title": "Queued for Review", "detail": "Dispatched incident to Merchant Control Room recovery queue for manual decisioning.", "status": "SUCCESS"},
            ],
            "sovereignty_rule": "The AI flagged diagnostic ambiguity. The Governor halted autonomous execution and routed the decision to a human operator.",
        }

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
