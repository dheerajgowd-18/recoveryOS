"""Integration tests verifying Merchant Policy demo controls API and subsequent Governor enforcement."""
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import app
from dashboard.service import DashboardService, dashboard_service
from governor.decision import GovernorDecisionResult
from governor.policy import MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.base import PolicyDecision
from simulator.config import SimulatedActionType


@pytest.mark.anyio
async def test_get_and_update_policies_api():
    """Verifies that GET /dashboard/api/policies returns the policy schema and PUT /dashboard/api/policies updates runtime state."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fetch default policies
        res = await client.get("/dashboard/api/policies")
        assert res.status_code == 200
        data = res.json()
        assert "policy_version" in data
        assert "max_retries" in data
        assert "max_contacts_24h" in data
        assert "auto_escalate_amount_inr" in data
        assert "min_diagnosis_confidence" in data

        # 2. Update policy parameters via PUT
        update_payload = {
            "max_retries": 5,
            "max_contacts_24h": 3,
            "auto_escalate_amount_inr": 15000.0,
            "min_diagnosis_confidence": 0.75,
            "min_cooldown_hours": 4.0,
        }
        res_put = await client.put("/dashboard/api/policies", json=update_payload)
        assert res_put.status_code == 200
        updated = res_put.json()

        assert updated["max_retries"] == 5
        assert updated["max_contacts_24h"] == 3
        assert updated["auto_escalate_amount_inr"] == 15000.0
        assert updated["min_diagnosis_confidence"] == 0.75
        assert updated["cooldown_seconds"] == 14400


@pytest.mark.anyio
async def test_policy_update_alters_subsequent_governor_verdicts():
    """Verifies that lowering the auto-escalate threshold immediately causes the Governor to ESCALATE a transaction that was previously allowed."""
    service = DashboardService()
    
    # Context: ₹5,000 transaction with high confidence diagnosis
    context = ObservableRecoveryContext(
        scenario_id="scen_test_pol",
        payment_id="pay_test_pol_001",
        amount_in_paise=500000,  # ₹5,000.00
        attempt_count=1,
        error_code="GATEWAY_ERROR",
    )
    diagnosis = StructuredDiagnosis(
        diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
        confidence=0.85,
        evidence_codes=["GATEWAY_TIMEOUT"],
        uncertainties=[],
        recommended_candidate_actions=[SimulatedActionType.RETRY_LATER],
        human_review_required=False,
        abstain_recommended=False,
        rationale="Transient gateway timeout.",
        diagnosis_source="rules-v1.0",
        model_version="rules-v1.0",
    )
    proposal = PolicyDecision(
        action_type=SimulatedActionType.RETRY_LATER,
        confidence=0.85,
        rationale="Retry later scheduled.",
        policy_name="RECOVERYOS_DETERMINISTIC_V0",
        timing_window="PLUS_6H",
        expected_incremental_value_paise=275000,
        expected_net_value_paise=274980,
    )

    # 1. Default threshold (₹100,000 / human review ₹20,000) -> Verdict is ALLOW
    governor = RecoveryGovernor(merchant_policy=service.merchant_policy)
    verdict_initial = governor.evaluate(context, diagnosis, proposal)
    assert verdict_initial.decision_result == GovernorDecisionResult.ALLOW

    # 2. Update policy to lower human review threshold to ₹2,000 (200,000 paise)
    service.update_merchant_policy({
        "auto_escalate_amount_inr": 2000.0,
    })

    # 3. Subsequent evaluation with updated merchant policy -> Verdict becomes ESCALATE
    governor_updated = RecoveryGovernor(merchant_policy=service.merchant_policy)
    verdict_updated = governor_updated.evaluate(context, diagnosis, proposal)
    assert verdict_updated.decision_result == GovernorDecisionResult.ESCALATE
    assert "HUMAN_REVIEW_REQUIRED_BY_AMOUNT" in verdict_updated.reason_codes
