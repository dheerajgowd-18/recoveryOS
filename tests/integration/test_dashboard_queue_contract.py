"""Integration tests verifying the recovery queue API/UI contract."""
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import app
from dashboard.service import DashboardService


@pytest.mark.anyio
async def test_recovery_queue_canonical_api_contract():
    """Verifies that /dashboard/api/recovery-queue returns the exact canonical schema expected by the frontend."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/dashboard/api/recovery-queue")
        assert response.status_code == 200
        items = response.json()
        assert isinstance(items, list)
        assert len(items) >= 5

        for item in items:
            # Core identification and financial fields
            assert "case_id" in item and isinstance(item["case_id"], str)
            assert "payment_id" in item and isinstance(item["payment_id"], str)
            assert "amount_inr" in item and isinstance(item["amount_inr"], (int, float))
            assert item["amount_inr"] >= 0

            # State fields
            assert "aggregate_state" in item and isinstance(item["aggregate_state"], str)

            # Diagnosis contract
            assert "diagnosis" in item and isinstance(item["diagnosis"], dict)
            assert "label" in item["diagnosis"] and isinstance(item["diagnosis"]["label"], str)
            assert "confidence" in item["diagnosis"] and isinstance(item["diagnosis"]["confidence"], (int, float))
            assert 0.0 <= item["diagnosis"]["confidence"] <= 1.0
            assert "source" in item["diagnosis"] and isinstance(item["diagnosis"]["source"], str)

            # Action and timing contract
            assert "selected_action" in item and isinstance(item["selected_action"], str)
            assert "timing_window" in item and isinstance(item["timing_window"], str)

            # Governor contract
            assert "governor" in item and isinstance(item["governor"], dict)
            assert "decision" in item["governor"] and isinstance(item["governor"]["decision"], str)
            assert "reason_codes" in item["governor"] and isinstance(item["governor"]["reason_codes"], list)

            # Prioritization and economics
            assert "priority" in item and item["priority"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
            assert "expected_incremental_value_inr" in item and isinstance(item["expected_incremental_value_inr"], (int, float))
