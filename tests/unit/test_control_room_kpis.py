"""Unit tests verifying exact mathematical truthfulness of Control Room KPIs."""
import pytest

from audit.decision_log import DecisionLogStore, DecisionRecord
from dashboard.service import DashboardService
from governor.policy import AutomationMode, MerchantPolicy
from simulator.config import SimulatedActionType


def test_control_room_exact_kpi_mathematics():
    """Verifies that all Control Room KPIs are computed dynamically and truthfully without hardcoding."""
    log_store = DecisionLogStore()

    # Record 1: Open failed payment (₹5,000.00), no action, abstained
    log_store.save_record(DecisionRecord(
        decision_id="dec_01",
        scenario_id="scen_01",
        payment_id="pay_01",
        iteration=1,
        timestamp_epoch=1000,
        policy_name="TEST_POLICY",
        policy_version="v1.0.0",
        diagnosis_label="low_value_negative_uplift",
        diagnosis_confidence=0.9,
        diagnosis_source="deterministic_offline",
        evidence_codes=["LOW_VALUE"],
        governor_decision="ABSTAIN",
        governor_reason_codes=["NEGATIVE_UPLIFT"],
        amount_in_paise=500000,  # ₹5,000.00
        aggregate_state_before="FAILED",
        aggregate_state_after="FAILED",
        aggregate_state="FAILED",
        risk_level="LOW",
        selected_action=SimulatedActionType.NO_ACTION,
        timing_window="IMMEDIATE",
        delay_seconds=0,
        confidence=0.9,
        rationale="Abstained due to economics",
        reason_codes=["NEGATIVE_UPLIFT"],
        execution_result_success=True,
        recovered=False,
        action_cost_paise=0,
        recovered_amount_paise=0,
        stop_reason="CONVERGED_NO_ACTION",
    ))

    # Record 2: Successfully recovered payment via active retry (₹10,000.00), action cost ₹2.00 (200 paise)
    log_store.save_record(DecisionRecord(
        decision_id="dec_02",
        scenario_id="scen_02",
        payment_id="pay_02",
        iteration=1,
        timestamp_epoch=1010,
        policy_name="TEST_POLICY",
        policy_version="v1.0.0",
        diagnosis_label="transient_gateway_failure",
        diagnosis_confidence=0.95,
        diagnosis_source="deterministic_offline",
        evidence_codes=["GATEWAY_TIMEOUT"],
        governor_decision="ALLOW",
        governor_reason_codes=["POLICY_ALLOW"],
        amount_in_paise=1000000,  # ₹10,000.00
        aggregate_state_before="FAILED",
        aggregate_state_after="CAPTURED",
        aggregate_state="CAPTURED",
        risk_level="LOW",
        selected_action=SimulatedActionType.RETRY_LATER,
        timing_window="PLUS_6H",
        delay_seconds=21600,
        confidence=0.95,
        rationale="Delayed retry executed",
        reason_codes=["OPTIMAL_TIMING"],
        execution_result_success=True,
        recovered=True,
        action_cost_paise=200,  # ₹2.00
        recovered_amount_paise=1000000,  # ₹10,000.00
        stop_reason="ACTION_EXECUTED",
    ))

    # Record 3: Organic recovery without active intervention (₹2,000.00), action cost ₹0.00
    log_store.save_record(DecisionRecord(
        decision_id="dec_03",
        scenario_id="scen_03",
        payment_id="pay_03",
        iteration=1,
        timestamp_epoch=1020,
        policy_name="TEST_POLICY",
        policy_version="v1.0.0",
        diagnosis_label="insufficient_funds",
        diagnosis_confidence=0.85,
        diagnosis_source="deterministic_offline",
        evidence_codes=["LOW_BALANCE"],
        governor_decision="ABSTAIN",
        governor_reason_codes=["POLICY_ABSTAIN"],
        amount_in_paise=200000,  # ₹2,000.00
        aggregate_state_before="FAILED",
        aggregate_state_after="CAPTURED",
        aggregate_state="CAPTURED",
        risk_level="LOW",
        selected_action=SimulatedActionType.NO_ACTION,
        timing_window="IMMEDIATE",
        delay_seconds=0,
        confidence=0.85,
        rationale="Organic capture detected",
        reason_codes=["ORGANIC_RECOVERY"],
        execution_result_success=True,
        recovered=True,
        action_cost_paise=0,
        recovered_amount_paise=200000,  # ₹2,000.00
        stop_reason="ORGANIC_CAPTURE_DETECTED",
    ))

    # Record 4: Policy Block / Consent Deny (₹3,000.00), open case
    log_store.save_record(DecisionRecord(
        decision_id="dec_04",
        scenario_id="scen_04",
        payment_id="pay_04",
        iteration=1,
        timestamp_epoch=1030,
        policy_name="TEST_POLICY",
        policy_version="v1.0.0",
        diagnosis_label="expired_card",
        diagnosis_confidence=0.99,
        diagnosis_source="deterministic_offline",
        evidence_codes=["OPTED_OUT"],
        governor_decision="DENY",
        governor_reason_codes=["CUSTOMER_OPTED_OUT"],
        amount_in_paise=300000,  # ₹3,000.00
        aggregate_state_before="FAILED",
        aggregate_state_after="OPTED_OUT",
        aggregate_state="OPTED_OUT",
        risk_level="HIGH",
        selected_action=SimulatedActionType.PAYMENT_LINK,
        timing_window="IMMEDIATE",
        delay_seconds=0,
        confidence=0.99,
        rationale="Blocked by consent gate",
        reason_codes=["GOVERNOR_CONSENT_BLOCK"],
        execution_result_success=False,
        recovered=False,
        action_cost_paise=0,
        recovered_amount_paise=0,
        stop_reason="GOVERNOR_DENIAL",
    ))

    # Record 5: High-value human review escalation (₹15,000.00), open case
    log_store.save_record(DecisionRecord(
        decision_id="dec_05",
        scenario_id="scen_05",
        payment_id="pay_05",
        iteration=1,
        timestamp_epoch=1040,
        policy_name="TEST_POLICY",
        policy_version="v1.0.0",
        diagnosis_label="unusual_auth_decline",
        diagnosis_confidence=0.6,
        diagnosis_source="deterministic_offline",
        evidence_codes=["HIGH_VALUE"],
        governor_decision="ESCALATE",
        governor_reason_codes=["HUMAN_REVIEW_REQUIRED"],
        amount_in_paise=1500000,  # ₹15,000.00
        aggregate_state_before="FAILED",
        aggregate_state_after="ESCALATED",
        aggregate_state="ESCALATED",
        risk_level="HIGH",
        selected_action=SimulatedActionType.NO_ACTION,
        timing_window="IMMEDIATE",
        delay_seconds=0,
        confidence=0.6,
        rationale="Escalated to human review",
        reason_codes=["HUMAN_REVIEW_ESCALATION"],
        execution_result_success=True,
        recovered=False,
        action_cost_paise=0,
        recovered_amount_paise=0,
        stop_reason="ESCALATED_HUMAN_REVIEW",
    ))

    policy = MerchantPolicy(automation_mode=AutomationMode.AUTONOMOUS)
    service = DashboardService(decision_log=log_store, merchant_policy=policy, reports_dir="non_existent_reports_dir")

    data = service.get_control_room_data()

    # Revenue at risk = dec_01 (₹5,000) + dec_05 (₹15,000) = ₹20,000.00
    assert data["revenue_at_risk_inr"] == 20000.00

    # Gross recovered = dec_02 (₹10,000) + dec_03 (₹2,000) = ₹12,000.00
    assert data["gross_recovered_inr"] == 12000.00

    # Incremental recovered = gross (₹12,000) - natural (₹2,000) - cost (₹2.00) = ₹9,998.00
    assert data["incremental_recovered_inr"] == 9998.00

    # Net adjusted recovery = incremental (₹9,998) - churn penalty (₹0) = ₹9,998.00
    assert data["net_adjusted_recovery_inr"] == 9998.00

    # Open opportunities = dec_01 (FAILED) + dec_05 (ESCALATED) = 2
    assert data["open_recovery_opportunities"] == 2

    # Actions executed = dec_02 = 1
    assert data["actions_executed"] == 1

    # Actions avoided = dec_01 (NO_ACTION) + dec_03 (NO_ACTION) + dec_05 (NO_ACTION) = 3
    assert data["actions_avoided"] == 3

    # Human reviews = dec_05 = 1
    assert data["human_reviews"] == 1

    # Policy blocks = dec_04 = 1
    assert data["policy_blocks"] == 1

    # Total exceptions = policy blocks (1) + human reviews (1) + invalidations (0) = 2
    assert data["exceptions_count"] == 2

    # System status & agent mode
    assert data["system_status"] == "OPERATIONAL"
    assert data["agent_mode"] == "AUTONOMOUS"
