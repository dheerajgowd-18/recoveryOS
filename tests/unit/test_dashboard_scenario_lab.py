"""Unit and integration tests for Dashboard Scenario Lab interactive simulation API."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestDashboardScenarioLab:
    """Verifies that signature demo cases execute against backend runtime via /dashboard/api/scenarios/{id}/run."""

    def test_run_abstention_scenario(self, client: TestClient):
        """Case 1: Correct economic abstention returns real trace and ₹0.00 cost."""
        resp = client.post("/dashboard/api/scenarios/scen_demo_abstain/run")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["scenario_id"] == "scen_demo_abstain"
        assert data["scenario_type"] == "ABSTENTION"
        assert data["amount_inr"] == 1.00
        assert data["final_state"].upper() == "FAILED"
        assert data["is_recovered"] is False
        assert data["action_cost_inr"] == 0.00
        assert data["governor_verdict"]["result"] == "ABSTAIN"
        assert len(data["timeline"]) >= 5

    def test_run_timing_scenario(self, client: TestClient):
        """Case 2: Action x timing selection returns candidate rankings and +6h selection."""
        resp = client.post("/dashboard/api/scenarios/scen_demo_timing/run")
        assert resp.status_code == 200
        data = resp.json()

        assert data["scenario_id"] == "scen_demo_timing"
        assert data["scenario_type"] == "TIMING_OPTIMIZATION"
        assert data["amount_inr"] == 5000.00
        assert data["ai_proposal"]["timing_window"] == "PLUS_6H"
        assert data["governor_verdict"]["result"] == "ALLOW"
        assert len(data["candidate_rankings"]) == 5
        assert any(c["selected"] and c["timing"] == "in 6h" for c in data["candidate_rankings"])

    def test_run_stale_action_scenario(self, client: TestClient):
        """Case 3: Stale action protection invalidates delayed retry on out-of-band capture."""
        resp = client.post("/dashboard/api/scenarios/scen_demo_stale/run")
        assert resp.status_code == 200
        data = resp.json()

        assert data["scenario_id"] == "scen_demo_stale"
        assert data["scenario_type"] == "STALE_ACTION_PROTECTION"
        assert data["final_state"] == "CAPTURED"
        assert data["is_recovered"] is True
        assert data["action_cost_inr"] == 0.00
        assert "INVALIDATED" in data["scheduled_action"]["final_status"]

    def test_run_consent_block_scenario(self, client: TestClient):
        """Case 4: Customer opt-out blocks customer communication via Governor and Tool Firewall."""
        resp = client.post("/dashboard/api/scenarios/scen_demo_consent/run")
        assert resp.status_code == 200
        data = resp.json()

        assert data["scenario_id"] == "scen_demo_consent"
        assert data["scenario_type"] == "CONSENT_ENFORCEMENT"
        assert data["governor_verdict"]["result"] == "DENY"
        assert "CUSTOMER_OPTED_OUT" in str(data["governor_verdict"]["reason_codes"])
        assert data["action_cost_inr"] == 0.00

    def test_run_uncertainty_escalation_scenario(self, client: TestClient):
        """Case 5: High-value low-confidence error escalates to human review."""
        resp = client.post("/dashboard/api/scenarios/scen_demo_uncertainty/run")
        assert resp.status_code == 200
        data = resp.json()

        assert data["scenario_id"] == "scen_demo_uncertainty"
        assert data["scenario_type"] == "HUMAN_REVIEW_ESCALATION"
        assert data["amount_inr"] == 25000.00
        assert data["governor_verdict"]["result"] == "ESCALATE"
        assert data["governor_verdict"]["requires_human_approval"] is True

    def test_unknown_scenario_returns_404(self, client: TestClient):
        """Attempting to run an unregistered scenario returns 404."""
        resp = client.post("/dashboard/api/scenarios/invalid_scenario_xyz/run")
        assert resp.status_code == 404
