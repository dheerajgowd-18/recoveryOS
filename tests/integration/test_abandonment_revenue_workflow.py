"""Integration tests verifying the Checkout Abandonment & High-Intent Cart Revenue Recovery Workflow."""
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import app
from dashboard.service import DashboardService, dashboard_service
from domain.enums import RevenueState
from intelligence.schemas import DiagnosisLabel
from simulator.config import SimulatedActionType


@pytest.mark.anyio
async def test_checkout_abandonment_scenario_execution():
    """Verifies that the Checkout Drop-Off & Cart Abandonment revenue recovery workflow executes through the full runtime."""
    service = DashboardService()
    res = await service.run_scenario("scen_demo_abandonment")

    assert res["scenario_id"] == "scen_demo_abandonment"
    assert res["scenario_type"] == "CHECKOUT_ABANDONMENT"
    assert res["amount_inr"] == 4200.00
    assert res["is_recovered"] is True
    assert res["net_value_inr"] > 0
    assert res["ai_proposal"]["diagnosis_label"] == "customer_abandonment"
    assert res["ai_proposal"]["action_type"] == "payment_link"
    assert res["ai_proposal"]["timing_window"] == "PLUS_2H"
    assert res["governor_verdict"]["result"] == "ALLOW"
    assert len(res["timeline"]) >= 6


@pytest.mark.anyio
async def test_checkout_abandonment_scenario_api_endpoint():
    """Verifies that POST /dashboard/api/scenarios/scen_demo_abandonment/run returns 200 with full trace schema."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/dashboard/api/scenarios/scen_demo_abandonment/run")
        assert res.status_code == 200
        data = res.json()
        assert data["scenario_id"] == "scen_demo_abandonment"
        assert data["scenario_type"] == "CHECKOUT_ABANDONMENT"
        assert data["amount_inr"] == 4200.00
        assert "ai_proposal" in data
        assert "governor_verdict" in data
        assert "timeline" in data
