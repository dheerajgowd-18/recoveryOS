"""Unit test suite for Phase 15: RecoveryOS Operations Console & Dashboard."""
import json
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from dashboard.service import DashboardService


@pytest.fixture
def test_client():
    return TestClient(app)


class TestDashboardRoutesAndAPIs:
    """Validates FastAPI HTML dashboard routes and JSON telemetry endpoints."""

    def test_dashboard_html_route_renders_200(self, test_client: TestClient):
        """GET /dashboard must return HTTP 200 and valid HTML containing Operations Console markup."""
        response = test_client.get("/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        content = response.text
        assert "RecoveryOS — Operations Console" in content
        assert "Control Room" in content
        assert "Recovery Queue" in content
        assert "Case Replay" in content
        assert "Evaluation Lab" in content
        assert "Exceptions &amp; Audit" in content or "Exceptions & Audit" in content

    def test_control_room_api_structure(self, test_client: TestClient):
        """GET /dashboard/api/control-room must return all canonical executive KPI metrics."""
        response = test_client.get("/dashboard/api/control-room")
        assert response.status_code == 200
        data = response.json()

        expected_keys = [
            "revenue_at_risk_inr",
            "gross_recovered_inr",
            "incremental_recovered_inr",
            "net_adjusted_recovery_inr",
            "open_recovery_opportunities",
            "actions_executed",
            "actions_avoided",
            "human_reviews",
            "policy_blocks",
            "exceptions_count",
            "recent_activity",
            "system_status",
            "agent_mode",
        ]
        for key in expected_keys:
            assert key in data, f"Missing key '{key}' in control room response"

        assert isinstance(data["recent_activity"], list)
        assert data["system_status"] == "OPERATIONAL"

    def test_recovery_queue_api(self, test_client: TestClient):
        """GET /dashboard/api/recovery-queue must return prioritized operational queue items."""
        response = test_client.get("/dashboard/api/recovery-queue")
        assert response.status_code == 200
        queue = response.json()
        assert isinstance(queue, list)
        assert len(queue) >= 5, "Bootstrap queue must contain signature demo cases"

        first_item = queue[0]
        required_fields = [
            "case_id",
            "payment_id",
            "amount_inr",
            "current_state",
            "diagnosis_label",
            "diagnosis_confidence",
            "recommended_action",
            "timing_window",
            "expected_incremental_value_inr",
            "priority",
            "governance_status",
        ]
        for field in required_fields:
            assert field in first_item, f"Missing field '{field}' in queue item"

    def test_case_replay_api_success_and_not_found(self, test_client: TestClient):
        """GET /dashboard/api/cases/{case_id}/replay must return step-by-step audit trace or 404."""
        # Test valid case
        response = test_client.get("/dashboard/api/cases/dec_sig_001/replay")
        assert response.status_code == 200
        replay = response.json()

        assert replay["case_id"] == "dec_sig_001"
        assert "why_acted" in replay
        assert "why_did_not_act" in replay
        assert isinstance(replay["steps"], list)
        assert len(replay["steps"]) in (7, 8)

        # Test non-existent case ID
        err_res = test_client.get("/dashboard/api/cases/non_existent_case_999/replay")
        assert err_res.status_code == 404
        assert "not found" in err_res.json()["detail"].lower()

    def test_evaluation_api(self, test_client: TestClient):
        """GET /dashboard/api/evaluation must return benchmark comparisons and regret statistics."""
        response = test_client.get("/dashboard/api/evaluation")
        assert response.status_code == 200
        eval_data = response.json()

        assert "status" in eval_data
        if eval_data["status"] == "AVAILABLE":
            assert "baseline_table" in eval_data
            assert "oracle_comparison" in eval_data
            assert "regret_distribution" in eval_data
            assert "sensitivity_analysis" in eval_data
            assert isinstance(eval_data["baseline_table"], list)

    def test_policies_api(self, test_client: TestClient):
        """GET /dashboard/api/policies must return read-only merchant governance rules."""
        response = test_client.get("/dashboard/api/policies")
        assert response.status_code == 200
        pol = response.json()

        assert "policy_version" in pol
        assert "max_retry_attempts_total" in pol
        assert "contact_limit_24h" in pol
        assert "max_autonomous_amount_inr" in pol
        assert "automation_mode" in pol

    def test_exceptions_api(self, test_client: TestClient):
        """GET /dashboard/api/exceptions must return operational audit exceptions."""
        response = test_client.get("/dashboard/api/exceptions")
        assert response.status_code == 200
        exceptions = response.json()
        assert isinstance(exceptions, list)
        if exceptions:
            first_exc = exceptions[0]
            assert "exception_id" in first_exc
            assert "case_id" in first_exc
            assert "severity" in first_exc
            assert "exception_type" in first_exc


class TestDashboardPrivacyAndDataIntegrity:
    """Validates that no unobservable counterfactual simulation data leaks into dashboard APIs."""

    def test_no_hidden_simulator_fields_leak_into_dashboard_apis(self, test_client: TestClient):
        """Dashboard endpoints must strictly respect the Observable Context Boundary."""
        endpoints = [
            "/dashboard/api/control-room",
            "/dashboard/api/recovery-queue",
            "/dashboard/api/cases/dec_sig_001/replay",
            "/dashboard/api/cases/dec_sig_002/replay",
            "/dashboard/api/exceptions",
        ]

        forbidden_leak_keys = [
            "hidden_outcomes",
            "potential_outcomes",
            "customer_archetype",
            "archetype_profile",
            "secret_recovery_prob",
            "natural_recoverer",
            "non_responsive",
        ]

        for ep in endpoints:
            res = test_client.get(ep)
            assert res.status_code == 200
            text_payload = res.text.lower()
            for key in forbidden_leak_keys:
                assert key not in text_payload, f"Forbidden simulation truth key '{key}' leaked in endpoint {ep}"
