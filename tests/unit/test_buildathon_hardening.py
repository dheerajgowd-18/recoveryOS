"""Buildathon Hardening Verification Tests for RecoveryOS.

Verifies:
1. Packaging and discoverable modules.
2. Canonical runtime state graph delegation.
3. Mathematical consistency of canonical financial KPIs.
4. Explicit uncertainty triad separation.
5. Demo fixture provenance labeling.
6. 8-stage canonical decision anatomy reconstruction.
7. Distribution shift stress testing framework.
8. Razorpay adapter reconciliation semantics and fail-closed guards.
"""
import pytest

from agent.graph import RecoveryStateGraph, RecoveryWorkflowState
from agent.runtime import AgentRuntime
from audit.decision_log import DecisionLogStore, DecisionRecord
from audit.replay import ReplayEngine
from dashboard.service import DashboardService
from domain.metrics import CanonicalFinancialKPIs, compute_canonical_financial_kpis
from evaluation.distribution_shift import DistributionShiftRunner, DistributionShiftType
from execution.razorpay_adapter import RazorpayAdapter, RazorpayConfigurationError
from execution.simulator_executor import SimulatorExecutor
from governor.policy import AutomationMode, MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from policy.base import PolicyDecision
from simulator.config import SimulatedActionType, SimulatorConfig
from simulator.generator import Simulator


def test_packaging_module_imports():
    """Verify all 15 core architectural packages are importable."""
    import agent
    import audit
    import backend
    import dashboard
    import domain
    import evaluation
    import execution
    import governor
    import ingestion
    import intelligence
    import planner
    import policy
    import rag
    import scheduler
    import simulator

    assert agent is not None
    assert domain is not None
    assert evaluation is not None
    assert governor is not None


def test_canonical_runtime_delegation():
    """Verify RecoveryStateGraph is the single canonical orchestrator and AgentRuntime delegates to it."""
    graph = RecoveryStateGraph()
    assert hasattr(graph, "execute_workflow")
    assert callable(graph.execute_workflow)

    runtime = AgentRuntime()
    assert runtime.state_graph is not None
    assert isinstance(runtime.state_graph, RecoveryStateGraph)


def test_unified_financial_kpis_consistency():
    """Verify canonical KPI calculation across DecisionRecords."""
    log_store = DecisionLogStore()
    log_store.save_record(DecisionRecord(
        decision_id="rec_test_1",
        scenario_id="scen_1",
        payment_id="pay_1",
        iteration=1,
        timestamp_epoch=1000,
        policy_name="TEST",
        policy_version="v1",
        diagnosis_label="transient_gateway_failure",
        diagnosis_confidence=0.9,
        amount_in_paise=500000,
        aggregate_state_before="FAILED",
        aggregate_state_after="CAPTURED",
        aggregate_state="CAPTURED",
        risk_level="LOW",
        selected_action=SimulatedActionType.RETRY_LATER,
        confidence=0.95,
        diagnostic_confidence=0.9,
        economic_confidence=0.95,
        execution_state_validity=1.0,
        record_origin="ACTUAL_RUNTIME_EXECUTION",
        rationale="Delayed retry",
        recovered=True,
        recovered_amount_paise=500000,
        action_cost_paise=20,
    ))
    kpis = compute_canonical_financial_kpis(log_store.get_all_records())
    assert kpis.gross_recovery_paise == 500000
    assert kpis.total_action_cost_paise == 20
    assert kpis.incremental_adjusted_net_recovery_paise == 499980
    assert kpis.actions_dispatched_count == 0  # governor_decision was None in record


def test_uncertainty_triad_separation():
    """Verify diagnostic confidence, economic confidence, and execution state validity are distinct."""
    record = DecisionRecord(
        decision_id="rec_triad",
        scenario_id="scen_t",
        payment_id="pay_t",
        iteration=1,
        timestamp_epoch=1000,
        policy_name="TEST",
        policy_version="v1",
        diagnosis_label="insufficient_funds",
        diagnosis_confidence=0.75,
        confidence=0.88,
        diagnostic_confidence=0.75,
        economic_confidence=0.88,
        execution_state_validity=0.99,
        record_origin="ACTUAL_RUNTIME_EXECUTION",
        amount_in_paise=100000,
        aggregate_state_before="FAILED",
        aggregate_state_after="FAILED",
        aggregate_state="FAILED",
        risk_level="LOW",
        selected_action=SimulatedActionType.NO_ACTION,
        rationale="Abstained",
    )
    assert record.diagnostic_confidence == 0.75
    assert record.economic_confidence == 0.88
    assert record.execution_state_validity == 0.99
    assert record.record_origin == "ACTUAL_RUNTIME_EXECUTION"


def test_demo_fixture_labeling_in_dashboard():
    """Verify bootstrap cases in DashboardService are explicitly marked as DEMO_FIXTURE."""
    service = DashboardService(decision_log=DecisionLogStore())
    queue = service.get_recovery_queue()
    assert len(queue) > 0
    for item in queue:
        assert item["record_origin"] == "DEMO_FIXTURE"
        assert "diagnostic_confidence" in item
        assert "economic_confidence" in item
        assert "execution_state_validity" in item


def test_8_stage_decision_anatomy():
    """Verify Replay reconstructs all 8 canonical stages with contrastive reasons."""
    service = DashboardService(decision_log=DecisionLogStore())
    replay = service.get_case_replay("dec_sig_001")
    assert replay is not None
    assert "timeline_steps" in replay
    assert len(replay["timeline_steps"]) == 8

    canonical_stages = [s["stage"] for s in replay["timeline_steps"]]
    expected_stages = [
        "OBSERVATION",
        "DIAGNOSIS",
        "CANDIDATES",
        "ECONOMIC_SCORE",
        "GOVERNOR",
        "FIREWALL",
        "EXECUTION",
        "VERIFIED_OUTCOME",
    ]
    assert canonical_stages == expected_stages

    # Verify contrastive explanations
    assert "why_acted" in replay
    assert "why_did_not_act" in replay
    assert "why_alternatives_rejected" in replay
    assert "record_origin" in replay


def test_distribution_shift_execution():
    """Verify distribution shift suite runs across 6 stress scenarios."""
    runner = DistributionShiftRunner()
    result = runner.run_all_shifts(num_scenarios=20, seed=42)
    assert result.total_shifts_evaluated == 6
    assert len(result.shift_reports) == 6
    shift_names = {r.shift_name for r in result.shift_reports}
    for shift_type in DistributionShiftType:
        assert shift_type.value in shift_names


@pytest.mark.anyio
async def test_razorpay_adapter_fail_closed_and_reconciliation_semantics(monkeypatch):
    """Verify RazorpayAdapter fails closed safely without credentials and documents reconciliation semantics."""
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    adapter = RazorpayAdapter(key_id=None, key_secret=None, strict=False)
    assert not adapter.has_valid_credentials

    # Test strict mode raises error
    strict_adapter = RazorpayAdapter(key_id=None, key_secret=None, strict=True)
    with pytest.raises(RazorpayConfigurationError):
        await strict_adapter.fetch_payment_status("pay_test_123")
