"""Unit tests for DecisionLogStore, ReplayEngine, churn-adjusted metrics, and CLI demo execution."""
import pytest

from agent.runtime import AgentRunResult, AgentRuntime
from audit.decision_log import CandidateScore, DecisionLogStore, DecisionRecord
from audit.replay import ReplayEngine, ReplayRecord
from evaluation.harness import EvaluationHarness
from evaluation.metrics import DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER, EvaluationMetrics, MetricCalculator, ScenarioEvaluationRecord
from evaluation.policies import AlwaysRetryPolicy, NoActionPolicy, ProbabilityOnlyPolicy, StaticRulePolicy
from execution.simulator_executor import SimulatorExecutor
from policy.deterministic import DeterministicRecoveryPolicy
from scripts.demo import (
    demo_case_1_abstention,
    demo_case_2_delayed_retry_economic_selection,
    demo_case_3_late_state_change,
    demo_case_4_safety_block,
    demo_case_5_batch_benchmark,
)
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType, SimulatorConfig
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario, Simulator
from simulator.outcomes import ActionOutcome, PotentialOutcomes


class TestAuditAndReplay:
    """Validates decision log persistence, historical replay reconstruction, and churn calculations."""

    def test_decision_record_storage_and_query(self):
        """DecisionLogStore must store and query records deterministically."""
        store = DecisionLogStore()
        record = DecisionRecord(
            decision_id="dec_test_01",
            scenario_id="scen_test_01",
            payment_id="pay_test_01",
            iteration=1,
            timestamp_epoch=1700000000,
            policy_name="TEST_POLICY",
            policy_version="v1.0.0",
            model_version="deterministic-proxy-v1",
            diagnosis_label="transient_gateway_failure",
            diagnosis_confidence=0.90,
            diagnosis_source="deterministic_offline",
            evidence_codes=["OBS_GATEWAY_ERROR"],
            failure_class="transient_gateway",
            failure_code="GATEWAY_ERROR",
            amount_in_paise=50000,
            aggregate_state_before="FAILED",
            aggregate_state_after="CAPTURED",
            aggregate_state="CAPTURED",
            risk_level="HIGH",
            candidate_scores=[
                CandidateScore(
                    action_type=SimulatedActionType.NO_ACTION,
                    is_admissible=True,
                    expected_recovery_prob=0.25,
                    action_cost_paise=0,
                    expected_net_value_paise=0,
                    incremental_uplift_paise=0,
                ),
                CandidateScore(
                    action_type=SimulatedActionType.RETRY_LATER,
                    is_admissible=True,
                    expected_recovery_prob=0.8,
                    action_cost_paise=20,
                    expected_net_value_paise=39980,
                    incremental_uplift_paise=39980,
                ),
            ],
            selected_action=SimulatedActionType.RETRY_LATER,
            confidence=0.9,
            rationale="High expected value retry",
            reason_codes=["POSITIVE_NET_VALUE"],
            execution_result_success=True,
            recovered=True,
            action_cost_paise=20,
            recovered_amount_paise=50000,
            stop_reason="REVENUE_RECOVERED",
        )

        store.save_record(record)

        queried = store.get_record("dec_test_01")
        assert queried is not None
        assert queried.decision_id == "dec_test_01"
        assert queried.selected_action == SimulatedActionType.RETRY_LATER
        assert queried.aggregate_state_before == "FAILED"
        assert queried.aggregate_state_after == "CAPTURED"
        assert queried.recovered is True
        assert len(store.get_records_for_scenario("scen_test_01")) == 1
        assert len(store.list_records()) == 1

    def test_replay_selected_score_not_first_in_candidates(self):
        """ReplayEngine must retrieve the selected action's score even if it is not the first candidate."""
        store = DecisionLogStore()
        record = DecisionRecord(
            decision_id="dec_non_first_01",
            scenario_id="scen_non_first_01",
            payment_id="pay_non_first_01",
            iteration=1,
            timestamp_epoch=1700000000,
            policy_name="TEST_POLICY",
            policy_version="v1.0.0",
            model_version="deterministic-proxy-v1",
            diagnosis_label="transient_gateway_failure",
            diagnosis_confidence=0.90,
            diagnosis_source="deterministic_offline",
            evidence_codes=["OBS_GATEWAY_ERROR"],
            failure_class="transient_gateway",
            failure_code="GATEWAY_ERROR",
            amount_in_paise=50000,
            aggregate_state_before="FAILED",
            aggregate_state_after="CAPTURED",
            aggregate_state="CAPTURED",
            risk_level="HIGH",
            candidate_scores=[
                CandidateScore(
                    action_type=SimulatedActionType.NO_ACTION,
                    is_admissible=True,
                    expected_recovery_prob=0.25,
                    action_cost_paise=0,
                    expected_net_value_paise=0,
                    incremental_uplift_paise=0,
                ),
                CandidateScore(
                    action_type=SimulatedActionType.RETRY_LATER,
                    is_admissible=True,
                    expected_recovery_prob=0.8,
                    action_cost_paise=20,
                    expected_net_value_paise=39980,
                    incremental_uplift_paise=39980,
                ),
            ],
            selected_action=SimulatedActionType.RETRY_LATER,
            confidence=0.9,
            rationale="High expected value retry",
            reason_codes=["POSITIVE_NET_VALUE"],
            execution_result_success=True,
            recovered=True,
            action_cost_paise=20,
            recovered_amount_paise=50000,
            stop_reason="REVENUE_RECOVERED",
        )
        store.save_record(record)
        engine = ReplayEngine(decision_log=store)

        replayed = engine.replay_decision("dec_non_first_01")
        assert replayed is not None
        assert replayed.decision.action_type == SimulatedActionType.RETRY_LATER
        assert replayed.decision.expected_net_value_paise == 39980
        assert replayed.decision.expected_incremental_value_paise == 39980
        assert replayed.aggregate_state_before == "FAILED"
        assert replayed.aggregate_state_after == "CAPTURED"

    def test_churn_penalty_and_adjusted_net_recovery_calculation(self):
        """MetricCalculator must calculate churn penalty and adjusted net recovery correctly."""
        records = [
            ScenarioEvaluationRecord(
                scenario_id="s1",
                policy_name="POL",
                chosen_action=SimulatedActionType.PAYMENT_LINK,
                is_intervention=True,
                is_abstention=False,
                recovered=True,
                recovered_amount_paise=100000,  # Rs 1,000
                action_cost_paise=100,          # Rs 1.00
                net_value_paise=99900,
                recovery_delay_seconds=60,
                customer_churned=True,          # 1 churned
                fatigue_score=0.4,
                natural_recovered=False,
                natural_recovered_amount_paise=0,
                natural_customer_churned=False,
                incremental_amount_paise=100000,
            ),
            ScenarioEvaluationRecord(
                scenario_id="s2",
                policy_name="POL",
                chosen_action=SimulatedActionType.NO_ACTION,
                is_intervention=False,
                is_abstention=True,
                recovered=False,
                recovered_amount_paise=0,
                action_cost_paise=0,
                net_value_paise=0,
                recovery_delay_seconds=0,
                customer_churned=False,
                fatigue_score=0.0,
                natural_recovered=False,
                natural_recovered_amount_paise=0,
                natural_customer_churned=False,
                incremental_amount_paise=0,
            ),
        ]

        metrics = MetricCalculator.compute_metrics(
            policy_name="POL",
            records=records,
            churn_penalty_paise_per_customer=250_000,  # Rs 2,500
        )

        assert metrics.gross_recovered_amount_paise == 100000
        assert metrics.total_action_cost_paise == 100
        assert metrics.net_recovered_amount_paise == 99900
        assert metrics.total_churned_customers == 1
        assert metrics.churn_penalty_paise == 250000
        # Adjusted Net = 99,900 - 250,000 = -150,100
        assert metrics.adjusted_net_recovery_paise == -150100
        assert metrics.intervention_count == 1
        assert metrics.actions_avoided_count == 1
        assert metrics.abstention_count == 1

    def test_actions_avoided_counter(self):
        """A policy returning NO_ACTION must increment actions_avoided_count."""
        records = [
            ScenarioEvaluationRecord(
                scenario_id="s1",
                policy_name="POL",
                chosen_action=SimulatedActionType.NO_ACTION,
                is_intervention=False,
                is_abstention=True,
                recovered=False,
                recovered_amount_paise=0,
                action_cost_paise=0,
                net_value_paise=0,
                recovery_delay_seconds=0,
                customer_churned=False,
                fatigue_score=0.0,
                natural_recovered=False,
                natural_recovered_amount_paise=0,
                natural_customer_churned=False,
                incremental_amount_paise=0,
            )
        ]
        metrics = MetricCalculator.compute_metrics("POL", records)
        assert metrics.actions_avoided_count == 1
        assert metrics.intervention_count == 0

    @pytest.mark.anyio
    async def test_replay_engine_reconstruction(self):
        """ReplayEngine must faithfully reconstruct decision traces from runtime outputs."""
        runtime = AgentRuntime()
        replay_engine = ReplayEngine()

        customer = SimulatedCustomer(
            customer_id="cust_replay_01",
            name="Test User",
            email="test@example.com",
            contact="+919876543299",
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        )
        generator = SyntheticEntityGenerator()
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_replay_01",
            seed=42,
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            amount_in_paise=10000,
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
            retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=True, recovery_delay_seconds=60, recovered_amount_paise=10000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=86400, recovered_amount_paise=10000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=10000, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
            reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
        )
        scenario = SimulatedScenario(
            scenario_id="scen_replay_01",
            customer=customer,
            event=event,
            webhook_payload=webhook,
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            hidden_outcomes=hidden_outcomes,
        )

        result = await runtime.run_recovery_loop(scenario)
        records = replay_engine.record_run(result, scenario)

        assert len(records) >= 1
        first_decision_id = records[0].decision_id

        replayed: ReplayRecord = replay_engine.replay_decision(first_decision_id)
        assert replayed is not None
        assert replayed.decision_id == first_decision_id
        assert replayed.policy_version == "v1.0.0"
        assert replayed.observable_context_snapshot.scenario_id == "scen_replay_01"
        assert len(replayed.candidate_evaluations) == len(SimulatedActionType)
        assert replayed.execution_outcome is not None
        assert replayed.execution_outcome.recovered is True
        assert replayed.aggregate_state_before == "failed"
        assert replayed.aggregate_state_after == "captured"

    @pytest.mark.anyio
    async def test_demo_script_functions_execute_cleanly(self):
        """All 5 demo signature functions must execute without unhandled exceptions."""
        await demo_case_1_abstention()
        await demo_case_2_delayed_retry_economic_selection()
        await demo_case_3_late_state_change()
        await demo_case_4_safety_block()
        demo_case_5_batch_benchmark()

    def test_north_star_benchmark_assertion(self):
        """RecoveryOS must achieve higher incremental_adjusted_net_recovery than Baseline 1 & 2 under fixed demo seed."""
        sim = Simulator()
        scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=100))
        harness = EvaluationHarness()
        policies = [
            NoActionPolicy(),
            AlwaysRetryPolicy(),
            StaticRulePolicy(),
            ProbabilityOnlyPolicy(),
            DeterministicRecoveryPolicy(),
        ]
        results = harness.evaluate_all(policies, scenarios)

        b1_incr_adj = results["baseline_1_always_retry"].metrics.incremental_adjusted_net_recovery_paise
        b2_incr_adj = results["baseline_2_static_rules"].metrics.incremental_adjusted_net_recovery_paise
        recoveryos_incr_adj = results["RECOVERYOS_DETERMINISTIC_V0"].metrics.incremental_adjusted_net_recovery_paise
        recoveryos_avoided = results["RECOVERYOS_DETERMINISTIC_V0"].metrics.actions_avoided_count

        assert recoveryos_incr_adj > b1_incr_adj
        assert recoveryos_incr_adj > b2_incr_adj
        assert recoveryos_avoided > 0
