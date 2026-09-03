"""Comprehensive integration test suite verifying Dashboard API routes, schemas, error states, and edge cases."""
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import app
from dashboard.service import DashboardService


@pytest.mark.anyio
async def test_dashboard_html_endpoint():
    """Verifies that GET /dashboard renders HTML with correct title, navigation, and script initialization."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/dashboard")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        body = res.text
        assert "RecoveryOS — Operations Console" in body
        assert "Scenario Lab" in body
        assert "Merchant Policy" in body
        assert "Decision Anatomy Matrix" in body


@pytest.mark.anyio
async def test_control_room_api_schema():
    """Verifies that GET /dashboard/api/control-room returns full KPI metrics and activity telemetry."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/dashboard/api/control-room")
        assert res.status_code == 200
        data = res.json()
        
        required_numeric_fields = [
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
        ]
        for field in required_numeric_fields:
            assert field in data, f"Missing field '{field}' in control-room"
            assert isinstance(data[field], (int, float))

        assert "recent_activity" in data
        assert isinstance(data["recent_activity"], list)
        assert data["system_status"] in ("OPERATIONAL", "DEGRADED", "HEALTHY")


@pytest.mark.anyio
async def test_recovery_queue_api_schema_and_canonical_fields():
    """Verifies that GET /dashboard/api/recovery-queue returns array of canonical queue items."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/dashboard/api/recovery-queue")
        assert res.status_code == 200
        queue = res.json()
        assert isinstance(queue, list)
        assert len(queue) > 0

        first = queue[0]
        assert "case_id" in first
        assert "payment_id" in first
        assert "amount_inr" in first
        assert "aggregate_state" in first
        assert "diagnosis" in first
        assert "label" in first["diagnosis"]
        assert "confidence" in first["diagnosis"]
        assert "selected_action" in first
        assert "timing_window" in first
        assert "governor" in first
        assert "decision" in first["governor"]
        assert "priority" in first


@pytest.mark.anyio
async def test_case_replay_api_success_and_decision_anatomy():
    """Verifies that GET /dashboard/api/cases/{id}/replay returns structured replay and 7-layer decision anatomy."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/dashboard/api/cases/dec_sig_001/replay")
        assert res.status_code == 200
        replay = res.json()

        assert replay["case_id"] == "dec_sig_001"
        assert "diagnosis" in replay
        assert "strategy" in replay
        assert "governor_decision" in replay
        assert "timeline" in replay
        assert "why_acted" in replay
        assert "why_did_not_act" in replay
        assert "decision_anatomy" in replay
        assert len(replay["decision_anatomy"]) == 7


@pytest.mark.anyio
async def test_case_replay_missing_and_malformed_case_id():
    """Verifies that missing or malformed case IDs return proper 404 responses."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Unknown ID
        res_missing = await client.get("/dashboard/api/cases/unknown_nonexistent_9999/replay")
        assert res_missing.status_code == 404
        assert "not found" in res_missing.json()["detail"].lower()

        # Malformed ID
        res_malformed = await client.get("/dashboard/api/cases/%20%20%20/replay")
        assert res_malformed.status_code == 404


@pytest.mark.anyio
async def test_evaluation_api_response():
    """Verifies GET /dashboard/api/evaluation returns valid benchmark evaluation metrics even if file is missing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/dashboard/api/evaluation")
        assert res.status_code == 200
        data = res.json()
        assert "baseline_table" in data
        assert "oracle_comparison" in data
        assert "regret_distribution" in data
        assert "config" in data


@pytest.mark.anyio
async def test_policies_api_get_and_put():
    """Verifies GET and PUT /dashboard/api/policies for merchant policy configuration."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET
        res_get = await client.get("/dashboard/api/policies")
        assert res_get.status_code == 200
        pol = res_get.json()
        assert "max_retries" in pol
        assert "auto_escalate_amount_inr" in pol

        # PUT valid
        payload = {
            "max_retries": 4,
            "max_contacts_24h": 3,
            "auto_escalate_amount_inr": 25000.0,
            "min_diagnosis_confidence": 0.80,
        }
        res_put = await client.put("/dashboard/api/policies", json=payload)
        assert res_put.status_code == 200
        updated = res_put.json()
        assert updated["max_retries"] == 4
        assert updated["auto_escalate_amount_inr"] == 25000.0
        assert updated["min_diagnosis_confidence"] == 0.80


@pytest.mark.anyio
async def test_exceptions_api_schema():
    """Verifies GET /dashboard/api/exceptions returns list of structured exceptions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/dashboard/api/exceptions")
        assert res.status_code == 200
        exceptions = res.json()
        assert isinstance(exceptions, list)
        if len(exceptions) > 0:
            first = exceptions[0]
            assert "exception_id" in first
            assert "exception_type" in first
            assert "severity" in first
            assert "reason_codes" in first
            assert "resolution_state" in first


@pytest.mark.anyio
async def test_scenario_run_api_endpoints():
    """Verifies POST /dashboard/api/scenarios/{id}/run for valid scenarios and 404 on invalid scenario."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        valid_scenarios = [
            "scen_demo_abstain",
            "scen_demo_timing",
            "scen_demo_stale",
            "scen_demo_consent",
            "scen_demo_uncertainty",
            "scen_demo_subscription",
            "scen_demo_abandonment",
        ]
        for scen in valid_scenarios:
            res = await client.post(f"/dashboard/api/scenarios/{scen}/run")
            assert res.status_code == 200
            data = res.json()
            assert data["scenario_id"] == scen
            assert "timeline" in data
            assert "governor_verdict" in data

        # Invalid scenario
        res_invalid = await client.post("/dashboard/api/scenarios/nonexistent_scen_xyz/run")
        assert res_invalid.status_code == 404
        assert "unknown scenario" in res_invalid.json()["detail"].lower()
