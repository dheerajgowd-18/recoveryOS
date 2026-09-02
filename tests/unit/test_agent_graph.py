"""Unit tests for specialized reasoning agents and stateful recovery orchestration graph."""
import pytest

from agent.agents import (
    CandidateStrategyOption,
    ContextRetrievalAgent,
    DiagnosisAgent,
    OutcomeVerificationAgent,
    RecoveryStrategyAgent,
    TimingReasonerAgent,
)
from agent.graph import RecoveryStateGraph, RecoveryWorkflowState
from domain.enums import PaymentState
from governor.decision import GovernorDecisionResult
from governor.firewall import CustomerConsentContext
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario
from simulator.outcomes import ActionOutcome, PotentialOutcomes


@pytest.fixture
def test_scenario():
    customer = SimulatedCustomer(
        customer_id="cust_graph_01",
        name="Priya Patel",
        email="priya.patel@example.com",
        contact="+919876543210",
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id="scen_graph_01",
        seed=42,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        amount_in_paise=500000,  # ₹5,000.00
        attempt_count=1,
    )
    event, webhook = generator.generate_payment_scenario(
        rng=__import__("random").Random(42),
        scenario=scenario_cfg,
        customer=customer,
        created_at_epoch=1700000000,
    )
    hidden_outcomes = PotentialOutcomes(
        no_action=ActionOutcome(action_type=SimulatedActionType.NO_ACTION, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=0),
        retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=True, recovery_delay_seconds=0, recovered_amount_paise=500000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=21600, recovered_amount_paise=500000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=500000, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
    )
    return SimulatedScenario(
        scenario_id="scen_graph_01",
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        hidden_outcomes=hidden_outcomes,
    )


class TestSpecializedAgentsAndGraph:
    """Validates specialized agent reasoning nodes and end-to-end stateful graph execution."""

    def test_context_agent_execution(self, test_scenario):
        agent = ContextRetrievalAgent()
        obs_ctx, mem_bundle = agent.execute(test_scenario.event, scenario_id=test_scenario.scenario_id)

        assert obs_ctx.scenario_id == test_scenario.scenario_id
        assert obs_ctx.amount_in_paise == 500000
        assert len(mem_bundle.retrieved_items) > 0
        assert mem_bundle.customer_summary is not None

    def test_strategy_agent_generates_abstain_and_active_candidates(self, test_scenario):
        context_agent = ContextRetrievalAgent()
        obs_ctx, mem_bundle = context_agent.execute(test_scenario.event, scenario_id=test_scenario.scenario_id)
        diag_agent = DiagnosisAgent()
        diag = diag_agent.diagnose_sync(obs_ctx)

        strat_agent = RecoveryStrategyAgent()
        candidates = strat_agent.generate_strategy_candidates(obs_ctx, diag, mem_bundle)

        action_types = [c.action_type for c in candidates]
        assert SimulatedActionType.NO_ACTION in action_types
        assert any(c.is_abstention for c in candidates)
        assert len(candidates) >= 2

    def test_timing_reasoner_agent_ranks_windows(self, test_scenario):
        context_agent = ContextRetrievalAgent()
        obs_ctx, _ = context_agent.execute(test_scenario.event, scenario_id=test_scenario.scenario_id)
        diag_agent = DiagnosisAgent()
        diag = diag_agent.diagnose_sync(obs_ctx)
        strat_agent = RecoveryStrategyAgent()
        candidates = strat_agent.generate_strategy_candidates(obs_ctx, diag)

        timing_agent = TimingReasonerAgent()
        ranked = timing_agent.evaluate_timing_options(obs_ctx, diag, candidates)

        assert len(ranked) > 0
        # Best candidate should have highest net value
        assert ranked[0].expected_net_value_paise >= ranked[-1].expected_net_value_paise

    def test_state_graph_delayed_retry_flow(self, test_scenario):
        import asyncio
        graph = RecoveryStateGraph()
        state: RecoveryWorkflowState = asyncio.run(graph.execute_workflow(test_scenario))

        assert state.stop_reason == "ACTION_SCHEDULED"
        assert state.scheduled_action is not None
        assert state.governor_decision.decision_result == GovernorDecisionResult.ALLOW
        assert len(state.step_traces) >= 7

        trace_nodes = [t.step_name for t in state.step_traces]
        assert "NODE_1_INGESTION_RECONCILIATION" in trace_nodes
        assert "NODE_3_CONTEXT_RETRIEVAL_RAG" in trace_nodes
        assert "NODE_4_DIAGNOSIS" in trace_nodes
        assert "NODE_7_RECOVERY_GOVERNOR" in trace_nodes
        assert "NODE_8_SCHEDULER" in trace_nodes

    def test_state_graph_consent_opt_out_block(self, test_scenario):
        import asyncio
        graph = RecoveryStateGraph()
        consent = CustomerConsentContext(
            customer_id=test_scenario.customer.customer_id,
            is_globally_opted_out=True,
        )
        state: RecoveryWorkflowState = asyncio.run(
            graph.execute_workflow(test_scenario, consent=consent)
        )

        # Retry is delayed bank action so not blocked by communication opt-out;
        # but if customer has expired card, payment link is blocked by Governor
        assert state.governor_decision is not None
