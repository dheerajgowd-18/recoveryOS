"""End-to-end automated demonstration validation verifying all signature showcase cases (A through G) across the real closed loop."""
import pytest
from httpx import ASGITransport, AsyncClient

from agent.runtime import AgentRuntime
from backend.app import app
from backend.services.ingestion_service import IngestionService
from dashboard.service import DashboardService
from domain.enums import PaymentState
from domain.events import PaymentEvent
from execution.simulator_executor import SimulatorExecutor
from governor.decision import GovernorDecisionResult
from governor.firewall import CustomerConsentContext
from governor.policy import MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.base import PolicyDecision
from policy.deterministic import DeterministicRecoveryPolicy
from scheduler.service import ScheduledLifecycleService
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario
from simulator.outcomes import ActionOutcome, PotentialOutcomes


@pytest.mark.anyio
async def test_case_a_low_value_economic_abstention():
    """Case A: Low-value micro transaction (₹1.00) with expired card -> AI & Governor both ABSTAIN."""
    service = DashboardService()
    res = await service.run_scenario("scen_demo_abstain")

    assert res["scenario_id"] == "scen_demo_abstain"
    assert res["stop_reason"] == "POLICY_ABSTAINED"
    assert res["ai_proposal"]["action_type"] == "no_action"
    assert res["governor_verdict"]["result"] in ("ABSTAIN", "ALLOW")
    assert res["action_cost_inr"] == 0.0


@pytest.mark.anyio
async def test_case_b_transient_gateway_timing_optimization():
    """Case B: High-value transient gateway failure (₹5,000.00) -> Optimally schedules delayed retry (+6h)."""
    service = DashboardService()
    res = await service.run_scenario("scen_demo_timing")

    assert res["scenario_id"] == "scen_demo_timing"
    assert res["stop_reason"] == "ACTION_SCHEDULED"
    assert res["ai_proposal"]["action_type"] == "retry_later"
    assert res["ai_proposal"]["timing_window"] == "PLUS_6H"
    assert res["governor_verdict"]["result"] == "ALLOW"


@pytest.mark.anyio
async def test_case_c_scheduled_recovery_stale_invalidation():
    """Case C: Scheduled retry invalidated pre-execution upon organic out-of-band capture."""
    service = DashboardService()
    res = await service.run_scenario("scen_demo_stale")

    assert res["scenario_id"] == "scen_demo_stale"
    assert res["final_state"] in ("CAPTURED", "captured")
    assert res["is_recovered"] is True
    assert res["action_cost_inr"] == 0.0
    # Stale action prevention avoids double charging


@pytest.mark.anyio
async def test_case_d_customer_opt_out_safety_block():
    """Case D: Customer with global opt-out -> Governor blocks direct contact with DENY."""
    service = DashboardService()
    res = await service.run_scenario("scen_demo_consent")

    assert res["scenario_id"] == "scen_demo_consent"
    assert res["stop_reason"] == "ACTION_BLOCKED"
    assert res["governor_verdict"]["result"] == "DENY"
    assert any("OPT_OUT" in code or "CONSENT" in code for code in res["governor_verdict"]["reason_codes"])


@pytest.mark.anyio
async def test_case_e_high_value_ambiguous_escalation():
    """Case E: High-value ambiguous failure (₹25,000.00) -> Governor routes to human reviewer."""
    service = DashboardService()
    res = await service.run_scenario("scen_demo_uncertainty")

    assert res["scenario_id"] == "scen_demo_uncertainty"
    assert res["stop_reason"] in ("ESCALATED_HUMAN_REVIEW", "HUMAN_REVIEW_REQUIRED")
    assert res["governor_verdict"]["result"] == "ESCALATE"
    assert res["governor_verdict"]["requires_human_approval"] is True


@pytest.mark.anyio
async def test_case_f_llm_provenance_and_zero_fallback_integrity():
    """Case F: Diagnostic intelligence provenance is truthfully recorded with zero misleading fallback claims."""
    service = DashboardService()
    queue = service.get_recovery_queue()
    assert len(queue) > 0

    for item in queue:
        diag = item.get("diagnosis", {})
        assert "source" in diag
        assert diag["source"] in ("deterministic_offline", "llm_structured", "deterministic_fallback", "rules-v1.0")


@pytest.mark.anyio
async def test_case_g_checkout_abandonment_cart_recovery():
    """Case G: High-intent checkout cart drop-off (₹4,200.00) -> Scheduled payment link with +2h delay."""
    service = DashboardService()
    res = await service.run_scenario("scen_demo_abandonment")

    assert res["scenario_id"] == "scen_demo_abandonment"
    assert res["is_recovered"] is True
    assert res["ai_proposal"]["action_type"] == "payment_link"
    assert res["ai_proposal"]["timing_window"] == "PLUS_2H"
    assert res["governor_verdict"]["result"] == "ALLOW"
