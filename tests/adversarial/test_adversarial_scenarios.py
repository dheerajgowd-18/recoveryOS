"""Adversarial tests validating ToolFirewall validation, customer opt-out gating, policy outage fail-closed, and executor timeout fault handling."""
import pytest

from agent.runtime import AgentRunResult, AgentRuntime
from backend.services.ingestion_service import IngestionService
from domain.actions import Action
from domain.enums import ActionType, PaymentState
from execution.simulator_executor import ExecutionFaultConfig, SimulatorExecutor
from governor.exceptions import (
    ActionBlockedError,
    ConsentViolationError,
    DuplicateExecutionError,
    PolicyOutageError,
    SchemaValidationError,
)
from governor.firewall import CustomerConsentContext, ToolFirewall
from policy.base import BasePolicy, PolicyDecision
from policy.config import DeterministicPolicyConfig
from policy.deterministic import DeterministicRecoveryPolicy
from policy.public_view import PublicScenarioView
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario
from simulator.outcomes import ActionOutcome, PotentialOutcomes


def create_sample_scenario(
    scenario_id: str = "scen_adv_01",
    failure_class: FailureClass = FailureClass.TRANSIENT_GATEWAY,
    amount_in_paise: int = 50000,
) -> SimulatedScenario:
    """Helper creating a deterministic test scenario."""
    customer = SimulatedCustomer(
        customer_id=f"cust_{scenario_id}",
        name="Adversarial Subject",
        email="subject@example.com",
        contact="+919876543999",
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id=scenario_id,
        seed=42,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=failure_class,
        amount_in_paise=amount_in_paise,
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
        retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=True, recovery_delay_seconds=60, recovered_amount_paise=amount_in_paise, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=86400, recovered_amount_paise=amount_in_paise, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=amount_in_paise, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=True, recovery_delay_seconds=7200, recovered_amount_paise=amount_in_paise, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
    )
    return SimulatedScenario(
        scenario_id=scenario_id,
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=failure_class,
        hidden_outcomes=hidden_outcomes,
    )


class TestToolFirewallAdversarialValidation:
    """Validates the ToolFirewall's schema validation, consent enforcement, and duplicate execution guards."""

    def test_invalid_action_schema_rejected(self):
        """Firewall must reject malformed action dictionaries and invalid action names."""
        firewall = ToolFirewall()

        # 1. Invalid action name
        malformed_action = {"action_type": "DELETE_DATABASE", "amount": 1000}
        with pytest.raises(SchemaValidationError) as exc_info:
            firewall.validate_action_schema(malformed_action)
        assert "DELETE_DATABASE" in str(exc_info.value)

        # 2. Missing action_type key
        empty_action = {"random_key": 123}
        with pytest.raises(SchemaValidationError):
            firewall.validate_action_schema(empty_action)

        # 3. Unsupported python type
        with pytest.raises(SchemaValidationError):
            firewall.validate_action_schema(12345)  # type: ignore

    def test_valid_action_schema_accepted(self):
        """Firewall correctly parses valid domain models, enums, and structured dictionaries."""
        firewall = ToolFirewall()

        # SimulatedActionType enum
        assert firewall.validate_action_schema(SimulatedActionType.RETRY_NOW) == SimulatedActionType.RETRY_NOW

        # Domain Action model
        domain_action = Action(
            action_id="act_01",
            action_type=ActionType.RETRY_PAYMENT,
            target_id="inv_01",
        )
        assert firewall.validate_action_schema(domain_action) == SimulatedActionType.RETRY_NOW

        # Dictionary representation
        dict_action = {"action_type": "retry_later"}
        assert firewall.validate_action_schema(dict_action) == SimulatedActionType.RETRY_LATER

    def test_customer_opt_out_blocks_contact(self):
        """Firewall must block customer-facing dunning actions when opt-out is recorded."""
        firewall = ToolFirewall()

        # Global opt-out
        consent_global_optout = CustomerConsentContext(
            customer_id="cust_opt_01",
            is_globally_opted_out=True,
        )
        with pytest.raises(ConsentViolationError) as exc_info:
            firewall.check_consent(SimulatedActionType.REMINDER, consent_global_optout)
        assert "globally opted out" in str(exc_info.value)

        with pytest.raises(ConsentViolationError):
            firewall.check_consent(SimulatedActionType.PAYMENT_LINK, consent_global_optout)

        # Non-contact actions like retries remain permitted
        assert firewall.check_consent(SimulatedActionType.RETRY_NOW, consent_global_optout) is True
        assert firewall.check_consent(SimulatedActionType.RETRY_LATER, consent_global_optout) is True

        # Channel-specific opt-out (email opted out)
        consent_email_optout = CustomerConsentContext(
            customer_id="cust_opt_02",
            opted_out_channels=["email"],
        )
        with pytest.raises(ConsentViolationError):
            firewall.check_consent(SimulatedActionType.PAYMENT_LINK, consent_email_optout)

        # SMS/WhatsApp opted out
        consent_sms_optout = CustomerConsentContext(
            customer_id="cust_opt_03",
            opted_out_channels=["sms"],
        )
        with pytest.raises(ConsentViolationError):
            firewall.check_consent(SimulatedActionType.REMINDER, consent_sms_optout)

    def test_duplicate_execution_key_blocked(self):
        """Firewall must raise DuplicateExecutionError if the same execution key is submitted twice."""
        firewall = ToolFirewall()
        key = "exec_pay_123_attempt_1_retry_now"

        assert firewall.check_idempotency(key) is True

        with pytest.raises(DuplicateExecutionError) as exc_info:
            firewall.check_idempotency(key)
        assert "Duplicate blocked" in str(exc_info.value)


class MockFaultyPolicy(BasePolicy):
    """Faulty policy simulating an outage or exception."""

    def __init__(self, name: str = "FAULTY_POLICY", description: str = "Faulty Policy for Testing") -> None:
        super().__init__(name=name, description=description)

    def decide(self, scenario, diagnosis=None) -> PolicyDecision:
        raise PolicyOutageError("Policy decision service unreachable (503 Service Unavailable).")


class ForcedActionPolicy(BasePolicy):
    """Custom policy forcing a specific action type for testing."""

    def __init__(
        self,
        action_type: SimulatedActionType,
        name: str = "FORCED_ACTION_POLICY",
        description: str = "Forces a specific action",
    ) -> None:
        super().__init__(name=name, description=description)
        self._forced_action = action_type

    def decide(self, scenario, diagnosis=None) -> PolicyDecision:
        return PolicyDecision(
            action_type=self._forced_action,
            confidence=0.95,
            rationale="Forced action for adversarial test.",
            policy_name=self.name,
            reason_codes=["FORCED_ACTION_TEST"],
            diagnosis=diagnosis,
        )


@pytest.mark.anyio
class TestAgentRuntimeAdversarialFaultHandling:
    """Validates runtime resilience when facing infrastructure faults, timeouts, outages, and policy violations."""

    async def test_policy_outage_fails_closed(self):
        """If policy service is unavailable or raises PolicyOutageError, runtime must fail closed safely."""
        scenario = create_scenario = create_sample_scenario("scen_adv_outage")
        faulty_policy = MockFaultyPolicy()
        runtime = AgentRuntime(policy=faulty_policy)

        result: AgentRunResult = await runtime.run_recovery_loop(scenario)

        # Must fail closed without crashing
        assert result.is_recovered is False
        assert result.stop_reason == "POLICY_OUTAGE"
        assert result.total_cost_paise == 0
        assert len(result.trace) == 1
        assert result.trace[0].error_message is not None
        assert "Policy decision service unreachable" in result.trace[0].error_message

    async def test_policy_unhealthy_flag_fails_closed(self):
        """Passing policy_healthy=False to run_recovery_loop must fail closed immediately."""
        scenario = create_sample_scenario("scen_adv_unhealthy")
        runtime = AgentRuntime()

        result: AgentRunResult = await runtime.run_recovery_loop(scenario, policy_healthy=False)

        assert result.is_recovered is False
        assert result.stop_reason == "POLICY_OUTAGE"
        assert result.total_cost_paise == 0
        assert len(result.trace) == 1

    async def test_customer_opt_out_blocks_runtime_action(self):
        """When policy suggests a communication action for an opted-out customer, firewall blocks it and runtime halts."""
        scenario = create_sample_scenario("scen_adv_optout", failure_class=FailureClass.EXPIRED_PAYMENT_METHOD)
        # Policy forces REMINDER
        forced_policy = ForcedActionPolicy(action_type=SimulatedActionType.REMINDER)
        runtime = AgentRuntime(policy=forced_policy)

        consent = CustomerConsentContext(
            customer_id=scenario.customer.customer_id,
            is_globally_opted_out=True,
        )

        result: AgentRunResult = await runtime.run_recovery_loop(scenario, consent=consent)

        assert result.is_recovered is False
        assert result.stop_reason == "ACTION_BLOCKED"
        assert result.total_cost_paise == 0
        assert len(result.trace) == 1
        assert "globally opted out" in str(result.trace[0].error_message)

    async def test_executor_timeout_handled_gracefully(self):
        """When executor raises TimeoutError, runtime must catch it, record failure, and stop gracefully without crashing."""
        scenario = create_sample_scenario("scen_adv_timeout")
        fault_config = ExecutionFaultConfig(force_timeout=True)
        faulty_executor = SimulatorExecutor(fault_config=fault_config)
        runtime = AgentRuntime(executor=faulty_executor)

        result: AgentRunResult = await runtime.run_recovery_loop(scenario)

        # Must record failure and halt safely
        assert result.is_recovered is False
        assert result.stop_reason == "EXECUTION_FAILURE"
        assert len(result.trace) == 1
        assert "TimeoutError" in str(result.trace[0].error_message)
        assert result.final_state == PaymentState.FAILED.value

    async def test_executor_connection_error_handled_gracefully(self):
        """When executor raises ConnectionError, runtime catches it and stops safely."""
        scenario = create_sample_scenario("scen_adv_conn_err")
        fault_config = ExecutionFaultConfig(force_connection_error=True)
        faulty_executor = SimulatorExecutor(fault_config=fault_config)
        runtime = AgentRuntime(executor=faulty_executor)

        result: AgentRunResult = await runtime.run_recovery_loop(scenario)

        assert result.is_recovered is False
        assert result.stop_reason == "EXECUTION_FAILURE"
        assert len(result.trace) == 1
        assert "ConnectionError" in str(result.trace[0].error_message)
