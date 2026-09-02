"""Integration tests verifying the Case Replay API/UI canonical contract across all decision verdicts."""
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import app


@pytest.mark.anyio
@pytest.mark.parametrize("case_id,expected_verdict,expected_action", [
    ("dec_sig_001", "ABSTAIN", "no_action"),
    ("dec_sig_002", "ALLOW", "retry_later"),
    ("dec_sig_003", "ALLOW", "retry_later"),  # stale invalidation scenario
    ("dec_sig_004", "DENY", "payment_link"),
    ("dec_sig_005", "ESCALATE", "no_action"),
])
async def test_case_replay_canonical_contract_for_all_verdicts(case_id, expected_verdict, expected_action):
    """Verifies that /dashboard/api/cases/{case_id}/replay returns the unified contract across ALLOW, DENY, ABSTAIN, ESCALATE, and stale actions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/dashboard/api/cases/{case_id}/replay")
        assert response.status_code == 200
        data = response.json()

        # Core identification and financial metrics
        assert data["case_id"] == case_id
        assert "payment_id" in data and isinstance(data["payment_id"], str)
        assert "amount_inr" in data and isinstance(data["amount_inr"], (int, float))
        assert "aggregate_state" in data

        # Diagnosis contract
        assert "diagnosis" in data and isinstance(data["diagnosis"], dict)
        assert "label" in data["diagnosis"] and isinstance(data["diagnosis"]["label"], str)
        assert "confidence" in data["diagnosis"] and 0.0 <= data["diagnosis"]["confidence"] <= 1.0
        assert "source" in data["diagnosis"]

        # Strategy & Candidates contract
        assert "strategy" in data and isinstance(data["strategy"], dict)
        assert "selected_action" in data["strategy"]
        assert "candidate_ranking" in data["strategy"] and isinstance(data["strategy"]["candidate_ranking"], list)
        assert data["selected_action"].lower() == expected_action.lower()

        # Governor contract
        assert "governor" in data and isinstance(data["governor"], dict)
        assert data["governor"]["decision"] == expected_verdict
        assert "reason_codes" in data["governor"] and isinstance(data["governor"]["reason_codes"], list)
        assert "governor_decision" in data
        assert data["governor_decision"]["result"] == expected_verdict

        # Timeline contract
        assert "timeline_steps" in data and len(data["timeline_steps"]) == 7
        assert "steps" in data and len(data["steps"]) == 7
        for step in data["timeline_steps"]:
            assert "step" in step
            assert "name" in step
            assert "status" in step
            assert "detail" in step

        # Execution & stopping contract
        assert "execution" in data and isinstance(data["execution"], dict)
        assert "stop_reason" in data and isinstance(data["stop_reason"], str)

        # Decision Anatomy Matrix Contract
        assert "decision_anatomy" in data and isinstance(data["decision_anatomy"], dict)
        anatomy = data["decision_anatomy"]
        assert "observable_event" in anatomy
        assert "inferred_diagnosis" in anatomy
        assert "candidate_scoring_matrix" in anatomy
        assert "governor_safety_gate" in anatomy
        assert "tool_firewall_gate" in anatomy
        assert "state_version_binding" in anatomy
        assert "final_audit" in anatomy

        # Analytical explanations contract
        assert "why_acted" in data and len(data["why_acted"]) > 0
        assert "why_did_not_act" in data and len(data["why_did_not_act"]) > 0


@pytest.mark.anyio
async def test_case_replay_404_on_unknown_id():
    """Verifies that non-existent case IDs return standard 404 with helpful error."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/dashboard/api/cases/dec_non_existent_999/replay")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
