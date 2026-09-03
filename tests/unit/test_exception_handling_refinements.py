"""Tests verifying improved, granular exception handling across execution, webhook validation, and agent runtime."""
import pytest
from pydantic import ValidationError

from agent.runtime import AgentRuntime
from audit.decision_log import DecisionRecord
from audit.replay import ReplayEngine
from domain.actions import Action
from execution.executor import ExecutionContext, ExecutionResult, RecoveryExecutor
from ingestion.razorpay_webhook import (
    InvalidWebhookSignatureError,
    WebhookPayloadValidationError,
    parse_and_validate_razorpay_webhook,
)
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario
from simulator.outcomes import ActionOutcome, PotentialOutcomes


class FaultyBuggyExecutor(RecoveryExecutor):
    """Simulates a developer bug (AttributeError) rather than a network/operational error."""
    async def execute(self, action, context):
        raise AttributeError("Simulated unexpected developer bug in executor")


class NetworkTimeoutExecutor(RecoveryExecutor):
    """Simulates an expected operational network timeout."""
    async def execute(self, action, context):
        raise TimeoutError("Gateway connection timed out after 5000ms")


def create_test_scenario() -> SimulatedScenario:
    customer = SimulatedCustomer(
        customer_id="cust_test_exc",
        name="Exception Subject",
        email="subject@example.com",
        contact="+919876543999",
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id="scen_test_exc",
        seed=42,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        amount_in_paise=500000,
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
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=0, recovered_amount_paise=500000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=0, recovered_amount_paise=500000, customer_churned=False, fatigue_score=0.0, action_cost_paise=100),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=True, recovery_delay_seconds=0, recovered_amount_paise=500000, customer_churned=False, fatigue_score=0.0, action_cost_paise=50),
    )
    return SimulatedScenario(
        scenario_id="scen_test_exc",
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        hidden_outcomes=hidden_outcomes,
    )


from evaluation.policies import AlwaysRetryPolicy


@pytest.mark.anyio
async def test_operational_network_timeout_handled_gracefully():
    """Operational TimeoutError is cleanly caught and set to EXECUTION_FAILURE without crash."""
    scenario = create_test_scenario()
    runtime = AgentRuntime(policy=AlwaysRetryPolicy(), executor=NetworkTimeoutExecutor())
    result = await runtime.run_recovery_loop(scenario)

    assert result.stop_reason == "EXECUTION_FAILURE"
    assert result.is_recovered is False
    assert len(result.trace) > 0
    assert "TimeoutError" in (result.trace[0].error_message or "")


@pytest.mark.anyio
async def test_unexpected_programming_bug_raises_immediately():
    """Unexpected developer bugs (AttributeError) are not swallowed into business failures."""
    scenario = create_test_scenario()
    runtime = AgentRuntime(policy=AlwaysRetryPolicy(), executor=FaultyBuggyExecutor())

    with pytest.raises(AttributeError, match="Simulated unexpected developer bug in executor"):
        await runtime.run_recovery_loop(scenario)


def test_webhook_schema_validation_error():
    """Malformed webhook structure raises WebhookPayloadValidationError specifically."""
    raw_body = b'{"event": "payment.failed", "payload": {}}'
    secret = "wh_sec_test"
    import hashlib, hmac
    sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    with pytest.raises(WebhookPayloadValidationError, match="Invalid Razorpay webhook structure"):
        parse_and_validate_razorpay_webhook(raw_body, sig, secret)
