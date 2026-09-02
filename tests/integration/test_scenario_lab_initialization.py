"""Integration tests verifying Scenario Lab execution endpoints and initialization contracts."""
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import app


@pytest.mark.anyio
@pytest.mark.parametrize("scenario_key,expected_type,expected_verdict", [
    ("scen_demo_abstain", "ABSTENTION", "ABSTAIN"),
    ("scen_demo_timing", "TIMING_OPTIMIZATION", "ALLOW"),
    ("scen_demo_stale", "STALE_ACTION_PROTECTION", "ALLOW -> INVALIDATED"),
    ("scen_demo_consent", "CONSENT_ENFORCEMENT", "DENY"),
    ("scen_demo_uncertainty", "HUMAN_REVIEW_ESCALATION", "ESCALATE"),
    ("scen_demo_subscription", "SUBSCRIPTION_RECOVERY", "ALLOW"),
])
async def test_scenario_lab_endpoints_and_render_contracts(scenario_key, expected_type, expected_verdict):
    """Verifies that each signature scenario endpoint runs cleanly via POST and GET and returns all required rendering fields."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test POST
        res_post = await client.post(f"/dashboard/api/scenarios/{scenario_key}/run")
        assert res_post.status_code == 200
        data = res_post.json()

        # Required fields for UI summary strip
        assert "scenario_id" in data
        assert "scenario_name" in data and len(data["scenario_name"]) > 0
        assert "scenario_type" in data and data["scenario_type"] == expected_type
        assert "amount_inr" in data and isinstance(data["amount_inr"], (int, float))
        assert "stop_reason" in data

        # AI Proposal Card Contract
        assert "ai_proposal" in data and isinstance(data["ai_proposal"], dict)
        ai_prop = data["ai_proposal"]
        assert "action_type" in ai_prop
        assert "confidence" in ai_prop and 0.0 <= ai_prop["confidence"] <= 1.0
        assert "diagnosis_label" in ai_prop
        assert "model_version" in ai_prop
        assert "rationale" in ai_prop
        assert "expected_net_value_inr" in ai_prop

        # Governor Verdict Card Contract
        assert "governor_verdict" in data and isinstance(data["governor_verdict"], dict)
        gov = data["governor_verdict"]
        assert "result" in gov and gov["result"] == expected_verdict
        assert "reason_codes" in gov and isinstance(gov["reason_codes"], list)
        assert "requires_human_approval" in gov and isinstance(gov["requires_human_approval"], bool)

        # Timeline Contract
        assert "timeline" in data and isinstance(data["timeline"], list)
        assert len(data["timeline"]) >= 4
        for step in data["timeline"]:
            assert "step" in step
            assert "title" in step
            assert "detail" in step
            assert "status" in step and step["status"] in ("INFO", "WARNING", "SUCCESS", "ERROR")

        # Test GET compatibility
        res_get = await client.get(f"/dashboard/api/scenarios/{scenario_key}/run")
        assert res_get.status_code == 200
