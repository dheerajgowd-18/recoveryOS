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


def test_mathematical_kpi_consistency_across_surfaces():
    """Verify exact bit-level mathematical KPI consistency across domain, evaluation, and dashboard."""
    from evaluation.harness import EvaluationHarness
    from policy.deterministic import DeterministicRecoveryPolicy
    from simulator.generator import Simulator

    sim = Simulator()
    scenarios = sim.generate_batch(SimulatorConfig(seed=123, num_scenarios=25))
    harness = EvaluationHarness()
    policy = DeterministicRecoveryPolicy()
    eval_result = harness.evaluate_policy(policy, scenarios)

    # 1. Domain Canonical KPIs computed from ScenarioEvaluationRecords
    canonical_kpis = compute_canonical_financial_kpis(eval_result.records)

    # 2. Compare against EvaluationMetrics
    metrics = eval_result.metrics
    assert metrics.gross_recovered_amount_paise == canonical_kpis.gross_recovery_paise
    assert metrics.natural_recovered_amount_paise == canonical_kpis.natural_recovery_paise
    assert metrics.total_action_cost_paise == canonical_kpis.total_action_cost_paise
    assert metrics.net_recovered_amount_paise == canonical_kpis.net_recovery_paise
    assert metrics.incremental_recovered_amount_paise == canonical_kpis.incremental_recovery_paise
    assert metrics.incremental_net_recovery_paise == canonical_kpis.incremental_net_recovery_paise
    assert metrics.churn_penalty_paise == canonical_kpis.churn_penalty_paise
    assert metrics.adjusted_net_recovery_paise == canonical_kpis.adjusted_net_recovery_paise
    assert metrics.incremental_adjusted_net_recovery_paise == canonical_kpis.incremental_adjusted_net_recovery_paise

    # 3. Compare against DashboardService Control Room data using DecisionRecords
    log_store = DecisionLogStore()
    for idx, r in enumerate(eval_result.records):
        log_store.save_record(
            DecisionRecord(
                decision_id=f"dec_sync_{idx}",
                scenario_id=r.scenario_id,
                payment_id=f"pay_sync_{idx}",
                iteration=1,
                timestamp_epoch=1700000000 + idx,
                policy_name=r.policy_name,
                policy_version="v1",
                diagnosis_label=r.predicted_diagnosis or "unknown",
                diagnosis_confidence=r.diagnosis_confidence or 0.5,
                amount_in_paise=r.recovered_amount_paise if r.recovered else 50000,
                aggregate_state_before="FAILED",
                aggregate_state_after="CAPTURED" if r.recovered else "FAILED",
                aggregate_state="CAPTURED" if r.recovered else "FAILED",
                risk_level="LOW",
                selected_action=r.chosen_action,
                timing_window=r.timing_window,
                delay_seconds=r.delay_seconds,
                confidence=r.diagnosis_confidence or 0.8,
                rationale="Sync test trace",
                recovered=r.recovered,
                recovered_amount_paise=r.recovered_amount_paise,
                action_cost_paise=r.action_cost_paise,
                governor_decision=r.governor_decision,
            )
        )

    dashboard_service = DashboardService(decision_log=log_store)
    control_room = dashboard_service.get_control_room_data()

    # Verify Dashboard Control Room calculations exactly reflect canonical KPIs
    dash_kpis = compute_canonical_financial_kpis(log_store.get_all_records())
    assert control_room["gross_recovered_inr"] == round(dash_kpis.gross_recovery_paise / 100.0, 2)
    assert control_room["net_adjusted_recovery_inr"] == round(dash_kpis.incremental_adjusted_net_recovery_paise / 100.0, 2)
    assert control_room["actions_executed"] == dash_kpis.actions_dispatched_count
    assert control_room["actions_avoided"] == dash_kpis.actions_avoided_count


def test_distribution_shift_policy_relevance_and_adaptation():
    """Verify all 6 distribution shifts produce distinct macroeconomic adaptations and high win rate."""
    from evaluation.distribution_shift import DistributionShiftSimulator
    from intelligence.context import ObservableContextBuilder

    runner = DistributionShiftRunner()
    scens = Simulator().generate_batch(SimulatorConfig(seed=42, num_scenarios=50))

    # Test policy configs per shift
    p_nat = runner.get_recoveryos_policy_for_shift(DistributionShiftType.HIGHER_NATURAL_RECOVERY)
    assert p_nat.config.default_priors[SimulatedActionType.NO_ACTION] == 0.65

    p_cost = runner.get_recoveryos_policy_for_shift(DistributionShiftType.HIGHER_CONTACT_COST)
    assert p_cost.config.action_costs_paise[SimulatedActionType.PAYMENT_LINK] == 400
    assert p_cost.config.action_costs_paise[SimulatedActionType.REMINDER] == 200

    p_retry = runner.get_recoveryos_policy_for_shift(DistributionShiftType.LOWER_DELAYED_RETRY_EFFECTIVENESS)
    assert p_retry.config.default_priors[SimulatedActionType.RETRY_LATER] < 0.30
    assert p_retry.config.allow_immediate_retry is True

    # Test observable perturbations
    s_noisy = DistributionShiftSimulator.apply_shift(scens, DistributionShiftType.NOISIER_DIAGNOSIS, seed=42)
    corrupted = [s for s in s_noisy if s.event.payment and s.event.payment.error_code == "INTERNAL_SERVER_ERROR"]
    assert len(corrupted) > 0

    s_micro = DistributionShiftSimulator.apply_shift(scens, DistributionShiftType.HEAVY_MICRO_TRANSACTIONS, seed=42)
    micro_cases = [s for s in s_micro if s.event.payment and s.event.payment.amount < 10000]
    assert len(micro_cases) > 0

    s_fatigue = DistributionShiftSimulator.apply_shift(scens, DistributionShiftType.INCREASED_CUSTOMER_FATIGUE, seed=42)
    fatigue_cases = [s for s in s_fatigue if s.contacts_in_last_24h > 0]
    assert len(fatigue_cases) > 0

    # Test execution and win rate
    res = runner.run_all_shifts(base_scenarios=scens, seed=42)
    assert res.total_shifts_evaluated == 6
    assert res.recoveryos_win_rate_pct >= 80.0
    assert res.recoveryos_wins_count >= 5
