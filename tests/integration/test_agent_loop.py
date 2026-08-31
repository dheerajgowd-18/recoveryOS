"""Integration tests for the closed-loop RecoveryOS Agent Runtime and Simulator Executor."""
from datetime import datetime, timezone
import pytest

from agent.runtime import AgentRunResult, AgentRuntime
from backend.services.ingestion_service import IngestionService
from domain.enums import PaymentState
from domain.events import (
    PaymentContainer,
    PaymentEntity,
    WebhookPayload,
    WebhookPayloadContent,
)
from execution.simulator_executor import SimulatorExecutor
from policy.config import DeterministicPolicyConfig
from policy.deterministic import DeterministicRecoveryPolicy
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType, SimulatorConfig
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario, Simulator
from simulator.outcomes import ActionOutcome, PotentialOutcomes


@pytest.fixture
def synthetic_generator():
    return SyntheticEntityGenerator()


@pytest.mark.anyio
class TestAgentRuntimeClosedLoop:
    """Validates the autonomous closed-loop agent observe-decide-execute-observe lifecycle."""

    async def test_full_recovery_loop_success(self):
        """Inject failed payment -> Agent decides RETRY_LATER -> Simulator captures payment -> Agent terminates."""
        ingestion = IngestionService()
        executor = SimulatorExecutor()
        runtime = AgentRuntime(ingestion_service=ingestion, executor=executor)

        # Build a scenario where RETRY_LATER succeeds (recovered=True)
        customer = SimulatedCustomer(
            customer_id="cust_loop_01",
            name="Rohan Verma",
            email="rohan.verma@example.com",
            contact="+919876543210",
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        )
        generator = SyntheticEntityGenerator()
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_loop_01",
            seed=101,
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            amount_in_paise=50000,
            attempt_count=1,
        )
        event, webhook = generator.generate_payment_scenario(
            rng=__import__("random").Random(101),
            scenario=scenario_cfg,
            customer=customer,
            created_at_epoch=1700000000,
        )
        # Outcome with RETRY_LATER capturing payment
        hidden_outcomes = PotentialOutcomes(
            no_action=ActionOutcome(
                action_type=SimulatedActionType.NO_ACTION,
                recovered=False,
                recovery_delay_seconds=0,
                recovered_amount_paise=0,
                customer_churned=False,
                fatigue_score=0.0,
                action_cost_paise=0,
            ),
            retry_now=ActionOutcome(
                action_type=SimulatedActionType.RETRY_NOW,
                recovered=False,
                recovery_delay_seconds=0,
                recovered_amount_paise=0,
                customer_churned=False,
                fatigue_score=0.0,
                action_cost_paise=20,
            ),
            retry_later=ActionOutcome(
                action_type=SimulatedActionType.RETRY_LATER,
                recovered=True,
                recovery_delay_seconds=86400,
                recovered_amount_paise=50000,
                customer_churned=False,
                fatigue_score=0.0,
                action_cost_paise=20,
            ),
            payment_link=ActionOutcome(
                action_type=SimulatedActionType.PAYMENT_LINK,
                recovered=True,
                recovery_delay_seconds=3600,
                recovered_amount_paise=50000,
                customer_churned=False,
                fatigue_score=0.4,
                action_cost_paise=100,
            ),
            reminder=ActionOutcome(
                action_type=SimulatedActionType.REMINDER,
                recovered=False,
                recovery_delay_seconds=0,
                recovered_amount_paise=0,
                customer_churned=False,
                fatigue_score=0.4,
                action_cost_paise=50,
            ),
        )
        scenario = SimulatedScenario(
            scenario_id="scen_loop_01",
            customer=customer,
            event=event,
            webhook_payload=webhook,
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            hidden_outcomes=hidden_outcomes,
        )

        result: AgentRunResult = await runtime.run_recovery_loop(scenario)

        assert result.is_recovered is True
        assert result.final_state == PaymentState.CAPTURED.value
        assert result.recovered_amount_paise == 50000
        assert result.total_cost_paise == 20
        assert result.net_value_paise == 49980
        assert result.stop_reason == "REVENUE_RECOVERED"
        assert len(result.trace) == 1
        assert result.trace[0].decision.action_type == SimulatedActionType.RETRY_LATER

    async def test_abstention_loop_for_low_value_scenario(self):
        """Inject low-value failure -> Agent decides NO_ACTION -> Agent halts without executing."""
        ingestion = IngestionService()
        executor = SimulatorExecutor()
        policy = DeterministicRecoveryPolicy(config=DeterministicPolicyConfig(min_expected_net_value_paise=5000))
        runtime = AgentRuntime(ingestion_service=ingestion, policy=policy, executor=executor)

        customer = SimulatedCustomer(
            customer_id="cust_loop_02",
            name="Priya Patel",
            email="priya.patel@example.com",
            contact="+919876543211",
            archetype=CustomerArchetype.NON_RESPONSIVE,
        )
        generator = SyntheticEntityGenerator()
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_loop_02",
            seed=102,
            archetype=CustomerArchetype.NON_RESPONSIVE,
            failure_class=FailureClass.EXPIRED_PAYMENT_METHOD,
            amount_in_paise=100,  # ₹1.00 low value
            attempt_count=1,
        )
        event, webhook = generator.generate_payment_scenario(
            rng=__import__("random").Random(102),
            scenario=scenario_cfg,
            customer=customer,
            created_at_epoch=1700000000,
        )
        hidden_outcomes = PotentialOutcomes(
            no_action=ActionOutcome(
                action_type=SimulatedActionType.NO_ACTION,
                recovered=False,
                recovery_delay_seconds=0,
                recovered_amount_paise=0,
                customer_churned=False,
                fatigue_score=0.0,
                action_cost_paise=0,
            ),
            retry_now=ActionOutcome(
                action_type=SimulatedActionType.RETRY_NOW,
                recovered=False,
                recovery_delay_seconds=0,
                recovered_amount_paise=0,
                customer_churned=False,
                fatigue_score=0.0,
                action_cost_paise=20,
            ),
            retry_later=ActionOutcome(
                action_type=SimulatedActionType.RETRY_LATER,
                recovered=False,
                recovery_delay_seconds=0,
                recovered_amount_paise=0,
                customer_churned=False,
                fatigue_score=0.0,
                action_cost_paise=20,
            ),
            payment_link=ActionOutcome(
                action_type=SimulatedActionType.PAYMENT_LINK,
                recovered=False,
                recovery_delay_seconds=0,
                recovered_amount_paise=0,
                customer_churned=False,
                fatigue_score=0.4,
                action_cost_paise=100,
            ),
            reminder=ActionOutcome(
                action_type=SimulatedActionType.REMINDER,
                recovered=False,
                recovery_delay_seconds=0,
                recovered_amount_paise=0,
                customer_churned=False,
                fatigue_score=0.4,
                action_cost_paise=50,
            ),
        )
        scenario = SimulatedScenario(
            scenario_id="scen_loop_02",
            customer=customer,
            event=event,
            webhook_payload=webhook,
            archetype=CustomerArchetype.NON_RESPONSIVE,
            failure_class=FailureClass.EXPIRED_PAYMENT_METHOD,
            hidden_outcomes=hidden_outcomes,
        )

        result: AgentRunResult = await runtime.run_recovery_loop(scenario)

        assert result.is_recovered is False
        assert result.total_cost_paise == 0
        assert result.stop_reason == "POLICY_ABSTAINED"
        assert len(result.trace) == 1
        assert result.trace[0].decision.action_type == SimulatedActionType.NO_ACTION
        assert result.trace[0].execution_result is None

    async def test_retry_exhaustion_loop(self):
        """Inject payment.failed -> retries fail -> reaches max retry limit -> abstains and stops."""
        ingestion = IngestionService()
        executor = SimulatorExecutor()
        policy = DeterministicRecoveryPolicy(config=DeterministicPolicyConfig(max_retry_attempts=2))
        runtime = AgentRuntime(
            ingestion_service=ingestion,
            policy=policy,
            executor=executor,
            max_iterations=5,
        )

        customer = SimulatedCustomer(
            customer_id="cust_loop_03",
            name="Vikram Mehta",
            email="vikram.mehta@example.com",
            contact="+919876543212",
            archetype=CustomerArchetype.NON_RESPONSIVE,
        )
        generator = SyntheticEntityGenerator()
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_loop_03",
            seed=103,
            archetype=CustomerArchetype.NON_RESPONSIVE,
            failure_class=FailureClass.INSUFFICIENT_FUNDS,
            amount_in_paise=49900,
            attempt_count=1,
        )
        event, webhook = generator.generate_payment_scenario(
            rng=__import__("random").Random(103),
            scenario=scenario_cfg,
            customer=customer,
            created_at_epoch=1700000000,
        )
        # All actions fail in this scenario
        hidden_outcomes = PotentialOutcomes(
            no_action=ActionOutcome(action_type=SimulatedActionType.NO_ACTION, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=0),
            retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
            reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
        )
        scenario = SimulatedScenario(
            scenario_id="scen_loop_03",
            customer=customer,
            event=event,
            webhook_payload=webhook,
            archetype=CustomerArchetype.NON_RESPONSIVE,
            failure_class=FailureClass.INSUFFICIENT_FUNDS,
            hidden_outcomes=hidden_outcomes,
        )

        result: AgentRunResult = await runtime.run_recovery_loop(scenario)

        # The loop runs attempts until max_retry_attempts is reached and halts
        assert result.is_recovered is False
        assert result.total_iterations >= 2
        assert result.total_cost_paise > 0
        assert result.stop_reason in ("POLICY_ABSTAINED", "MAX_ITERATIONS_REACHED")

    async def test_stale_action_protection(self):
        """Inject payment.failed -> simulate natural recovery by ingesting payment.captured out-of-band -> agent cancels execution."""
        ingestion = IngestionService()
        executor = SimulatorExecutor()
        runtime = AgentRuntime(ingestion_service=ingestion, executor=executor)

        customer = SimulatedCustomer(
            customer_id="cust_loop_04",
            name="Ananya Gupta",
            email="ananya.gupta@example.com",
            contact="+919876543213",
            archetype=CustomerArchetype.NATURAL_RECOVERER,
        )
        generator = SyntheticEntityGenerator()
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_loop_04",
            seed=104,
            archetype=CustomerArchetype.NATURAL_RECOVERER,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            amount_in_paise=50000,
            attempt_count=1,
        )
        event, webhook = generator.generate_payment_scenario(
            rng=__import__("random").Random(104),
            scenario=scenario_cfg,
            customer=customer,
            created_at_epoch=1700000000,
        )
        hidden_outcomes = PotentialOutcomes(
            no_action=ActionOutcome(action_type=SimulatedActionType.NO_ACTION, recovered=True, recovery_delay_seconds=86400, recovered_amount_paise=50000, customer_churned=False, fatigue_score=0.0, action_cost_paise=0),
            retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=True, recovery_delay_seconds=60, recovered_amount_paise=50000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=86400, recovered_amount_paise=50000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=50000, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
            reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=True, recovery_delay_seconds=7200, recovered_amount_paise=50000, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
        )
        scenario = SimulatedScenario(
            scenario_id="scen_loop_04",
            customer=customer,
            event=event,
            webhook_payload=webhook,
            archetype=CustomerArchetype.NATURAL_RECOVERER,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            hidden_outcomes=hidden_outcomes,
        )

        payment_id = event.payment.id

        # First, ingest the initial payment.failed event
        await ingestion.process_webhook(webhook)

        # Now simulate an external out-of-band capture webhook (natural organic customer payment)
        capture_epoch = 1700001800
        captured_payment = PaymentEntity(
            id=payment_id,
            entity="payment",
            amount=50000,
            currency="INR",
            status=PaymentState.CAPTURED,
            order_id=event.payment.order_id,
            invoice_id=event.payment.invoice_id,
            international=False,
            method="card",
            amount_refunded=0,
            refund_status=None,
            captured=True,
            description="Organic Customer Payment Succeeded",
            created_at=capture_epoch,
        )
        capture_webhook = WebhookPayload(
            entity="event",
            account_id=event.account_id,
            event="payment.captured",
            contains=["payment"],
            payload=WebhookPayloadContent(payment=PaymentContainer(entity=captured_payment)),
            created_at=capture_epoch,
        )
        # Ingest out-of-band capture
        await ingestion.process_webhook(capture_webhook)

        # Now run agent runtime on the scenario
        result: AgentRunResult = await runtime.run_recovery_loop(scenario)

        # The runtime must detect terminal state or stale action, canceling any new retry
        assert result.is_recovered is True
        assert result.final_state == PaymentState.CAPTURED.value
        assert result.total_cost_paise == 0
        assert result.stop_reason in ("TERMINAL_STATE_REACHED", "STALE_ACTION_PREVENTED")
