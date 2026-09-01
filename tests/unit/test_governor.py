"""Unit tests for Recovery Governor v1, Merchant Policy contract, and Human Review Escalation."""
import pytest

from domain.aggregates import PaymentAggregate
from domain.enums import PaymentState
from governor.decision import GovernorDecision, GovernorDecisionResult
from governor.firewall import CustomerConsentContext, ToolFirewall
from governor.policy import AutomationMode, MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.base import PolicyDecision
from simulator.config import SimulatedActionType


@pytest.fixture
def standard_policy():
    return MerchantPolicy(
        policy_version="v1.0.0",
        automation_mode=AutomationMode.AUTONOMOUS,
        max_retries=3,
        max_contacts_24h=2,
        max_contacts_7d=4,
        max_automatic_action_amount_paise=10_000_000,
        human_review_amount_threshold_paise=2_000_000,
        min_expected_incremental_value_paise=0,
        min_diagnosis_confidence=0.50,
        cooldown_seconds=3600,
    )


@pytest.fixture
def valid_context():
    return ObservableRecoveryContext(
        scenario_id="scen_gov_01",
        payment_id="pay_gov_01",
        customer_id="cust_gov_01",
        amount_in_paise=50000,  # ₹500
        currency="INR",
        attempt_count=1,
        error_code="GATEWAY_ERROR",
        error_source="gateway",
        contacts_in_last_24h=0,
        contacts_in_last_7d=0,
        time_since_last_contact_seconds=None,
    )


@pytest.fixture
def valid_diagnosis():
    return StructuredDiagnosis(
        diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
        confidence=0.85,
        evidence_codes=["OBS_GATEWAY_ERROR"],
        recommended_candidate_actions=[SimulatedActionType.RETRY_LATER],
        rationale="Transient gateway error diagnosed from observable gateway timeout signature",
        diagnosis_source="deterministic_offline",
    )


@pytest.fixture
def valid_proposal():
    return PolicyDecision(
        action_type=SimulatedActionType.RETRY_LATER,
        confidence=0.85,
        rationale="Transient gateway error; retry later",
        policy_name="RECOVERYOS_DETERMINISTIC_V0",
        reason_codes=["POSITIVE_NET_VALUE"],
        expected_incremental_value_paise=27500,
        expected_net_value_paise=27480,
    )


class TestRecoveryGovernorRules:
    """Validates deterministic ordered governance evaluation."""

    def test_governor_allows_valid_low_risk_action(self, standard_policy, valid_context, valid_diagnosis, valid_proposal):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        decision = governor.evaluate(valid_context, valid_diagnosis, valid_proposal)

        assert decision.decision_result == GovernorDecisionResult.ALLOW
        assert decision.selected_action == SimulatedActionType.RETRY_LATER
        assert "GOVERNOR_ACTION_ALLOWED" in decision.reason_codes
        assert decision.stop_reason is None

    def test_governor_denies_action_when_customer_is_opted_out(self, standard_policy, valid_context, valid_diagnosis):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        # Propose direct communication
        proposal = PolicyDecision(
            action_type=SimulatedActionType.PAYMENT_LINK,
            confidence=0.90,
            rationale="Send link",
            policy_name="POL",
            expected_incremental_value_paise=10000,
            expected_net_value_paise=9900,
        )
        consent = CustomerConsentContext(customer_id="cust_gov_01", is_globally_opted_out=True)
        decision = governor.evaluate(valid_context, valid_diagnosis, proposal, consent=consent)

        assert decision.decision_result == GovernorDecisionResult.DENY
        assert "CUSTOMER_OPTED_OUT" in decision.reason_codes
        assert decision.selected_action == SimulatedActionType.NO_ACTION
        assert decision.stop_reason == "ACTION_BLOCKED"

    def test_governor_denies_action_when_retry_limit_reached(self, standard_policy, valid_diagnosis, valid_proposal):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        # Attempt count 4 exceeds max_retries = 3
        exhausted_context = ObservableRecoveryContext(
            scenario_id="scen_gov_retry_limit",
            amount_in_paise=50000,
            attempt_count=4,
            error_code="GATEWAY_ERROR",
        )
        decision = governor.evaluate(exhausted_context, valid_diagnosis, valid_proposal)

        assert decision.decision_result == GovernorDecisionResult.DENY
        assert "RETRY_LIMIT_REACHED" in decision.reason_codes
        assert decision.selected_action == SimulatedActionType.NO_ACTION

    def test_governor_denies_action_when_contact_limit_reached(self, standard_policy, valid_diagnosis):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        proposal = PolicyDecision(
            action_type=SimulatedActionType.PAYMENT_LINK,
            confidence=0.85,
            rationale="Send payment link",
            policy_name="POL",
            expected_incremental_value_paise=10000,
            expected_net_value_paise=9900,
        )
        fatigued_context = ObservableRecoveryContext(
            scenario_id="scen_gov_contact_limit",
            amount_in_paise=50000,
            contacts_in_last_24h=2,  # Reaches max_contacts_24h = 2
            contacts_in_last_7d=2,
            error_code="BAD_REQUEST_ERROR",
        )
        decision = governor.evaluate(fatigued_context, valid_diagnosis, proposal)

        assert decision.decision_result == GovernorDecisionResult.DENY
        assert "CONTACT_LIMIT_REACHED" in decision.reason_codes
        assert decision.selected_action == SimulatedActionType.NO_ACTION

    def test_governor_denies_action_not_in_whitelist(self, standard_policy, valid_context, valid_diagnosis):
        # Disallow REMINDER in merchant policy
        restricted_policy = MerchantPolicy(
            allowed_action_types=[SimulatedActionType.NO_ACTION, SimulatedActionType.RETRY_LATER]
        )
        governor = RecoveryGovernor(merchant_policy=restricted_policy)
        proposal = PolicyDecision(
            action_type=SimulatedActionType.REMINDER,
            confidence=0.85,
            rationale="WhatsApp reminder",
            policy_name="POL",
            expected_incremental_value_paise=5000,
            expected_net_value_paise=4950,
        )
        decision = governor.evaluate(valid_context, valid_diagnosis, proposal)

        assert decision.decision_result == GovernorDecisionResult.DENY
        assert "ACTION_NOT_ALLOWED_BY_POLICY" in decision.reason_codes

    def test_governor_defers_action_when_cooldown_active(self, standard_policy, valid_diagnosis):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        proposal = PolicyDecision(
            action_type=SimulatedActionType.REMINDER,
            confidence=0.85,
            rationale="Reminder",
            policy_name="POL",
            expected_incremental_value_paise=5000,
            expected_net_value_paise=4950,
        )
        cooldown_context = ObservableRecoveryContext(
            scenario_id="scen_gov_cooldown",
            amount_in_paise=50000,
            contacts_in_last_24h=1,
            time_since_last_contact_seconds=600,  # 10 min ago < 3600s cooldown
            error_code="BAD_REQUEST_ERROR",
        )
        decision = governor.evaluate(cooldown_context, valid_diagnosis, proposal)

        assert decision.decision_result == GovernorDecisionResult.DEFER
        assert "COOLDOWN_ACTIVE" in decision.reason_codes

    def test_governor_abstains_when_negative_incremental_uplift(self, standard_policy, valid_context, valid_diagnosis):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        neg_proposal = PolicyDecision(
            action_type=SimulatedActionType.RETRY_NOW,
            confidence=0.80,
            rationale="Negative uplift retry",
            policy_name="POL",
            reason_codes=["NEGATIVE_INCREMENTAL_UPLIFT"],
            expected_incremental_value_paise=-5000,
            expected_net_value_paise=-5020,
        )
        decision = governor.evaluate(valid_context, valid_diagnosis, neg_proposal)

        assert decision.decision_result == GovernorDecisionResult.ABSTAIN
        assert "NEGATIVE_INCREMENTAL_UPLIFT" in decision.reason_codes
        assert decision.stop_reason == "POLICY_ABSTAINED"

    def test_governor_fails_closed_when_policy_engine_unhealthy(self, standard_policy, valid_context, valid_diagnosis, valid_proposal):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        decision = governor.evaluate(valid_context, valid_diagnosis, valid_proposal, policy_healthy=False)

        assert decision.decision_result == GovernorDecisionResult.DENY
        assert "POLICY_UNAVAILABLE_FAIL_CLOSED" in decision.reason_codes
        assert decision.stop_reason == "POLICY_OUTAGE"

    def test_governor_denies_execution_against_already_captured_payment(self, standard_policy, valid_context, valid_diagnosis, valid_proposal):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        captured_agg = PaymentAggregate(
            payment_id="pay_gov_01",
            current_state=PaymentState.CAPTURED,
            amount=50000,
            currency="INR",
        )
        decision = governor.evaluate(valid_context, valid_diagnosis, valid_proposal, aggregate=captured_agg)

        assert decision.decision_result == GovernorDecisionResult.DENY
        assert "REVENUE_ALREADY_RECOVERED" in decision.reason_codes
        assert decision.stop_reason == "TERMINAL_STATE_REACHED"


class TestHumanReviewEscalation:
    """Validates human review escalation triggers."""

    def test_governor_escalates_when_amount_exceeds_threshold(self, standard_policy, valid_diagnosis, valid_proposal):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        # ₹25,000 > human_review_amount_threshold_paise = ₹20,000
        high_val_context = ObservableRecoveryContext(
            scenario_id="scen_gov_high_val",
            amount_in_paise=2_500_000,  # ₹25,000
            error_code="GATEWAY_ERROR",
        )
        decision = governor.evaluate(high_val_context, valid_diagnosis, valid_proposal)

        assert decision.decision_result == GovernorDecisionResult.ESCALATE
        assert "HUMAN_REVIEW_REQUIRED_BY_AMOUNT" in decision.reason_codes
        assert decision.human_review_reason is not None
        assert "₹25,000.00 exceeds merchant review threshold" in decision.human_review_reason
        assert decision.stop_reason == "HUMAN_REVIEW_REQUIRED"

    def test_governor_escalates_when_high_value_has_diagnosis_uncertainty(self, standard_policy, valid_proposal):
        governor = RecoveryGovernor(merchant_policy=standard_policy)
        # ₹8,000 (> ₹5,000 threshold) with low confidence (0.60 < 0.70)
        high_val_context = ObservableRecoveryContext(
            scenario_id="scen_gov_uncertain",
            amount_in_paise=800_000,  # ₹8,000
            error_code="GATEWAY_ERROR",
        )
        uncertain_diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.60,
            uncertainties=["Gateway response format ambiguous"],
            recommended_candidate_actions=[SimulatedActionType.RETRY_LATER],
            rationale="Uncertain gateway diagnosis on high value transaction",
            diagnosis_source="deterministic_offline",
        )
        decision = governor.evaluate(high_val_context, uncertain_diag, valid_proposal)

        assert decision.decision_result == GovernorDecisionResult.ESCALATE
        assert "HUMAN_REVIEW_REQUIRED_BY_UNCERTAINTY" in decision.reason_codes
        assert decision.stop_reason == "HUMAN_REVIEW_REQUIRED"

    def test_governor_escalates_under_manual_automation_mode(self, valid_context, valid_diagnosis, valid_proposal):
        manual_policy = MerchantPolicy(automation_mode=AutomationMode.MANUAL)
        governor = RecoveryGovernor(merchant_policy=manual_policy)
        decision = governor.evaluate(valid_context, valid_diagnosis, valid_proposal)

        assert decision.decision_result == GovernorDecisionResult.ESCALATE
        assert "HUMAN_REVIEW_REQUIRED_BY_MANUAL_MODE" in decision.reason_codes


class TestGovernorFirewallIndependence:
    """Validates that ToolFirewall remains an independent layer of defense even if Governor allows."""

    def test_firewall_blocks_opted_out_customer_independently(self):
        firewall = ToolFirewall()
        consent = CustomerConsentContext(customer_id="cust_test", is_globally_opted_out=True)

        with pytest.raises(Exception):
            firewall.validate_and_gate(
                action=SimulatedActionType.REMINDER,
                execution_key="exec_key_01",
                consent=consent,
                policy_healthy=True,
            )
