"""Unit tests verifying all 6 signature demo scenarios execute cleanly through dashboard service."""
import pytest
from dashboard.service import dashboard_service


class TestSignatureDemoScenarios:
    """Validates all 6 signature demo scenarios wired to real backend endpoints."""

    @pytest.mark.anyio
    async def test_all_six_scenarios_execute(self):
        scenario_keys = ["abstain", "timing", "stale", "consent", "uncertainty", "subscription"]

        for key in scenario_keys:
            res = await dashboard_service.run_scenario(key)
            assert res is not None
            assert "scenario_id" in res
            assert "scenario_name" in res
            assert "timeline" in res
            assert len(res["timeline"]) >= 4
            assert "sovereignty_rule" in res
            assert "ai_proposal" in res
            assert "governor_verdict" in res
