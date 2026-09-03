import pytest
from httpx import ASGITransport, AsyncClient
from backend.app import app


@pytest.mark.anyio
async def test_llm_status_endpoint_safe_metadata_and_no_secrets():
    """Verify GET /dashboard/api/llm/status returns safe provider/model metadata without leaking secrets."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get("/dashboard/api/llm/status")
        assert res.status_code == 200
        data = res.json()
        assert "mode" in data
        assert "provider" in data
        assert "model" in data
        assert "configured" in data
        assert "strict_no_fallback" in data
        assert "status" in data
        assert data["strict_no_fallback"] is True
        # Ensure zero API keys or secrets are exposed in response
        assert "api_key" not in data
        assert "groq_api_key" not in data
        assert "secret" not in data


@pytest.mark.anyio
async def test_scenario_run_deterministic_mode():
    """Verify running a scenario in DETERMINISTIC mode populates source badges and decision anatomy."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.post("/dashboard/api/scenarios/scen_demo_abstain/run?mode=DETERMINISTIC")
        assert res.status_code == 200
        data = res.json()
        assert data["scenario_id"] == "scen_demo_abstain"
        assert data["execution_mode"] == "DETERMINISTIC"
        assert data["status"] == "success"
        assert "ai_proposal" in data
        assert data["ai_proposal"]["diagnosis_source"] == "deterministic_offline"
        assert "governor_verdict" in data
        assert data["governor_verdict"]["result"] == "ABSTAIN"
        assert "decision_anatomy" in data
        assert len(data["decision_anatomy"]) == 7
        assert "llm_telemetry" in data


@pytest.mark.anyio
async def test_scenario_run_live_llm_mode_fail_closed_or_executed():
    """Verify running scenario in LIVE_LLM mode executes or strictly fails closed with zero fallback."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.post("/dashboard/api/scenarios/scen_demo_timing/run?mode=LIVE_LLM")
        assert res.status_code == 200
        data = res.json()
        assert data["execution_mode"] == "LIVE_LLM"
        if data["status"] == "error":
            # Failed closed safely without silent fallback
            assert data["error_type"] == "LLM_PROVIDER_ERROR"
            assert data["fallback_used"] is False
            assert data["no_financial_action_executed"] is True
            assert data["final_state"] == "HALTED_ERROR"
        else:
            # Executed via live LLM
            assert data["status"] == "success"
            assert data["ai_proposal"]["diagnosis_source"] in ("live_llm", "llm_structured", "groq_llm_structured")
            assert data["llm_telemetry"]["execution_source"] == "live_llm"
            assert data["llm_telemetry"]["fallback_used"] is False


@pytest.mark.anyio
async def test_live_demo_run_endpoint():
    """Verify POST /dashboard/api/live-demo/run executes end-to-end recovery pipeline."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.post("/dashboard/api/live-demo/run?scenario_key=scen_demo_abstain&mode=DETERMINISTIC")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["scenario_id"] == "scen_demo_abstain"
        assert "ai_proposal" in data
        assert "governor_verdict" in data
