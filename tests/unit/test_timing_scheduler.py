"""Unit test suite for Action × Timing decision model and lightweight scheduler lifecycle."""
import pytest

from agent.runtime import AgentRunResult, AgentRuntime
from domain.aggregates import PaymentAggregate
from domain.enums import PaymentState
from evaluation.harness import EvaluationHarness
from policy.deterministic import DeterministicRecoveryPolicy
from execution.simulator_executor import SimulatorExecutor
from governor.decision import GovernorDecisionResult
from governor.firewall import CustomerConsentContext, ToolFirewall
from governor.policy import AutomationMode, MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableRecoveryContext
from intelligence.providers import DeterministicDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from planner.timing import (
    ActionMechanism,
    DeterministicTimingValueEstimator,
    TimingCandidateGenerator,
    TimingWindow,
)
from policy.base import PolicyDecision
from policy.config import DeterministicPolicyConfig
from scheduler.models import ScheduledActionStatus
from scheduler.service import ScheduledLifecycleService
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType, SimulatorConfig
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario, Simulator
from simulator.outcomes import ActionOutcome, PotentialOutcomes


@pytest.fixture
def policy_config() -> DeterministicPolicyConfig:
    return DeterministicPolicyConfig()


@pytest.fixture
def merchant_policy() -> MerchantPolicy:
    return MerchantPolicy(
        policy_version="v1.0.0",
        automation_mode=AutomationMode.AUTONOMOUS,
        max_retries=3,
        max_contacts_24h=2,
        max_contacts_7d=4,
        max_automatic_action_amount_paise=10_000_000,
        human_review_amount_threshold_paise=2_000_000,
        recovery_window_hours=72,
        cooldown_seconds=3600,
        allow_delayed_execution=True,
    )


@pytest.fixture
def base_context() -> ObservableRecoveryContext:
    return ObservableRecoveryContext(
        scenario_id="scen_timing_test_01",
        payment_id="pay_timing_test_01",
        customer_id="cust_timing_01",
        amount_in_paise=500_000,  # ₹5,000.00
        currency="INR",
        payment_method="card",
        attempt_count=1,
        error_code="GATEWAY_ERROR",
        error_description="Bank gateway timeout",
        error_source="gateway",
        error_step="payment_authorization",
        error_reason="gateway_timeout",
        time_since_failure_seconds=300,
    )


class TestTimingCandidateGeneration:
    """Validates admissible Action × Timing combinations under failure physics."""

    def test_timing_candidates_generated_only_for_eligible_mechanisms(self, base_context, policy_config):
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.EXPIRED_PAYMENT_METHOD,
            confidence=0.95,
            evidence_codes=["CARD_EXPIRED"],
            uncertainties=[],
            recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK],
            rationale="Card expired",
            diagnosis_source="deterministic_offline",
            model_version="v1",
        )

        candidates = TimingCandidateGenerator.generate_candidates(base_context, diag, policy_config)
        mechanisms = {mech for mech, _ in candidates}

        # Expired payment instruments must NOT generate any RETRY candidates regardless of timing
        assert ActionMechanism.RETRY not in mechanisms
        assert ActionMechanism.PAYMENT_LINK in mechanisms
        assert ActionMechanism.NO_ACTION in mechanisms

    def test_transient_gateway_generates_retry_timing_windows(self, base_context):
        cfg = DeterministicPolicyConfig(allow_immediate_retry=True)
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.90,
            evidence_codes=["GATEWAY_TIMEOUT"],
            uncertainties=[],
            recommended_candidate_actions=[SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER],
            rationale="Temporary network timeout",
            diagnosis_source="deterministic_offline",
            model_version="v1",
        )

        candidates = TimingCandidateGenerator.generate_candidates(base_context, diag, cfg)
        retry_timings = {timing for mech, timing in candidates if mech == ActionMechanism.RETRY}

        # Attempt count 1 with allow_immediate_retry generates immediate, 2h, and 6h retries
        assert TimingWindow.IMMEDIATE in retry_timings
        assert TimingWindow.PLUS_2H in retry_timings
        assert TimingWindow.PLUS_6H in retry_timings


class TestDeterministicTimingEstimator:
    """Validates deterministic mathematical expected-value scoring across timing options."""

    def test_timing_estimator_deterministic(self, base_context, policy_config):
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.90,
            evidence_codes=["GATEWAY_TIMEOUT"],
            uncertainties=[],
            recommended_candidate_actions=[SimulatedActionType.RETRY_LATER],
            rationale="Gateway timeout",
            diagnosis_source="deterministic_offline",
            model_version="v1",
        )

        score_1 = DeterministicTimingValueEstimator.estimate_candidate(
            base_context, diag, ActionMechanism.RETRY, TimingWindow.PLUS_6H, policy_config
        )
        score_2 = DeterministicTimingValueEstimator.estimate_candidate(
            base_context, diag, ActionMechanism.RETRY, TimingWindow.PLUS_6H, policy_config
        )

        assert score_1.expected_net_value_paise == score_2.expected_net_value_paise
        assert score_1.estimated_probability == score_2.estimated_probability
        assert score_1.expected_uplift == score_2.expected_uplift

    def test_timing_estimator_produces_negative_expected_value(self, policy_config):
        low_val_ctx = ObservableRecoveryContext(
            scenario_id="scen_low_val",
            payment_id="pay_low_val",
            amount_in_paise=100,  # ₹1.00
            currency="INR",
            attempt_count=1,
        )
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.EXPIRED_PAYMENT_METHOD,
            confidence=0.90,
            evidence_codes=["EXPIRED_CARD"],
            uncertainties=[],
            recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK],
            rationale="Expired card",
            diagnosis_source="deterministic_offline",
            model_version="v1",
        )

        # Payment link costs 100 paise; on a 100 paise payment with ~60% probability, net value is negative
        score = DeterministicTimingValueEstimator.estimate_candidate(
            low_val_ctx, diag, ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_6H, policy_config
        )
        assert score.expected_net_value_paise < 0
        assert "NEGATIVE_EXPECTED_NET_VALUE" in score.reason_codes


class TestGovernorTimingValidation:
    """Validates Recovery Governor enforcement of timing policies, windows, and cooldowns."""

    def test_governor_rejects_timing_outside_recovery_window(self, merchant_policy):
        ctx = ObservableRecoveryContext(
            scenario_id="scen_window_expiry",
            payment_id="pay_window_expiry",
            amount_in_paise=500_000,
            currency="INR",
            time_since_failure_seconds=250_000,  # ~69.4 hours
            attempt_count=1,
        )
        proposal = PolicyDecision(
            action_type=SimulatedActionType.RETRY_LATER,
            confidence=0.90,
            rationale="Retry in 24h",
            policy_name="TEST_POLICY",
            timing_window="PLUS_24H",
            delay_seconds=86_400,  # 69.4h + 24h = 93.4h > 72h window
        )

        governor = RecoveryGovernor(merchant_policy=merchant_policy)
        decision = governor.evaluate(context=ctx, diagnosis=None, proposal=proposal)

        assert decision.decision_result == GovernorDecisionResult.DENY
        assert "TIMING_OUTSIDE_RECOVERY_WINDOW" in decision.reason_codes
        assert "RECOVERY_WINDOW_EXPIRED" in decision.reason_codes

    def test_governor_rejects_timing_during_cooldown(self, merchant_policy):
        ctx = ObservableRecoveryContext(
            scenario_id="scen_cooldown",
            payment_id="pay_cooldown",
            amount_in_paise=500_000,
            currency="INR",
            time_since_last_contact_seconds=600,  # 10 mins ago (cooldown is 3600s = 60 mins)
            attempt_count=1,
        )
        proposal = PolicyDecision(
            action_type=SimulatedActionType.PAYMENT_LINK,
            confidence=0.90,
            rationale="Immediate payment link",
            policy_name="TEST_POLICY",
            timing_window="IMMEDIATE",
            delay_seconds=0,
        )

        governor = RecoveryGovernor(merchant_policy=merchant_policy)
        decision = governor.evaluate(context=ctx, diagnosis=None, proposal=proposal)

        assert decision.decision_result == GovernorDecisionResult.DEFER
        assert "COOLDOWN_ACTIVE" in decision.reason_codes

    def test_governor_rejects_delayed_contact_when_contact_limit_exceeded(self, merchant_policy):
        ctx = ObservableRecoveryContext(
            scenario_id="scen_contact_limit",
            payment_id="pay_contact_limit",
            amount_in_paise=500_000,
            currency="INR",
            contacts_in_last_24h=2,  # Limit is 2
            attempt_count=1,
        )
        proposal = PolicyDecision(
            action_type=SimulatedActionType.PAYMENT_LINK,
            confidence=0.90,
            rationale="Delayed payment link in 6h",
            policy_name="TEST_POLICY",
            timing_window="PLUS_6H",
            delay_seconds=21_600,
        )

        governor = RecoveryGovernor(merchant_policy=merchant_policy)
        decision = governor.evaluate(context=ctx, diagnosis=None, proposal=proposal)

        assert decision.decision_result == GovernorDecisionResult.DENY
        assert "TIMING_VIOLATES_CONTACT_LIMIT" in decision.reason_codes
        assert "CONTACT_LIMIT_REACHED" in decision.reason_codes

    def test_governor_allows_valid_delayed_retry(self, base_context, merchant_policy):
        proposal = PolicyDecision(
            action_type=SimulatedActionType.RETRY_LATER,
            confidence=0.90,
            rationale="Retry in 6h",
            policy_name="TEST_POLICY",
            timing_window="PLUS_6H",
            delay_seconds=21_600,
            expected_net_value_paise=400_000,
            expected_incremental_value_paise=400_020,
        )

        governor = RecoveryGovernor(merchant_policy=merchant_policy)
        decision = governor.evaluate(context=base_context, diagnosis=None, proposal=proposal)

        assert decision.decision_result == GovernorDecisionResult.ALLOW
        assert decision.timing_window == "PLUS_6H"
        assert decision.delay_seconds == 21_600


class TestScheduledLifecycleAndStaleState:
    """Validates scheduler persistence, state version binding, and pre-execution invalidation."""

    @pytest.mark.anyio
    async def test_immediate_allowed_action_executes_without_scheduling(self):
        generator = SyntheticEntityGenerator()
        customer = SimulatedCustomer(
            customer_id="cust_immed",
            name="Immed User",
            email="immed@example.com",
            contact="+919876543210",
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        )
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_immed",
            seed=42,
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            amount_in_paise=500_000,
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
            retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=True, recovery_delay_seconds=60, recovered_amount_paise=500_000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=21600, recovered_amount_paise=500_000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=500_000, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
            reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
        )
        scenario = SimulatedScenario(
            scenario_id="scen_immed",
            customer=customer,
            event=event,
            webhook_payload=webhook,
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            hidden_outcomes=hidden_outcomes,
        )

        class ImmediatePolicy(DeterministicRecoveryPolicy):
            def decide(self, context, diagnosis=None):
                return PolicyDecision(
                    action_type=SimulatedActionType.RETRY_NOW,
                    confidence=0.95,
                    rationale="Immediate retry",
                    policy_name=self.name,
                    timing_window="IMMEDIATE",
                    delay_seconds=0,
                    expected_net_value_paise=450_000,
                    expected_incremental_value_paise=450_020,
                )

        runtime = AgentRuntime(policy=ImmediatePolicy())
        result: AgentRunResult = await runtime.run_recovery_loop(scenario)

        assert result.stop_reason == "REVENUE_RECOVERED"
        assert result.is_recovered is True
        assert len(runtime.scheduler.store.list_all()) == 0

    @pytest.mark.anyio
    async def test_delayed_allowed_action_creates_pending_scheduled_action(self):
        generator = SyntheticEntityGenerator()
        customer = SimulatedCustomer(
            customer_id="cust_delay",
            name="Delay User",
            email="delay@example.com",
            contact="+919876543211",
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        )
        scenario_cfg = ScenarioConfig(
            scenario_id="scen_delay",
            seed=42,
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            amount_in_paise=500_000,
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
            retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=21600, recovered_amount_paise=500_000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
            payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=500_000, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
            reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
        )
        scenario = SimulatedScenario(
            scenario_id="scen_delay",
            customer=customer,
            event=event,
            webhook_payload=webhook,
            archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
            failure_class=FailureClass.TRANSIENT_GATEWAY,
            hidden_outcomes=hidden_outcomes,
        )

        runtime = AgentRuntime()
        result: AgentRunResult = await runtime.run_recovery_loop(scenario)

        assert result.stop_reason == "ACTION_SCHEDULED"
        scheduled = runtime.scheduler.store.list_all()
        assert len(scheduled) == 1
        assert scheduled[0].status == ScheduledActionStatus.PENDING
        assert scheduled[0].timing_window == TimingWindow.PLUS_6H
        assert scheduled[0].expected_state_version == 1

    def test_scheduled_action_invalidated_if_payment_captured_before_execution(self, merchant_policy):
        service = ScheduledLifecycleService()
        action = service.schedule_action(
            decision=PolicyDecision(
                action_type=SimulatedActionType.RETRY_LATER,
                confidence=0.90,
                rationale="Retry in 6h",
                policy_name="TEST_POLICY",
                timing_window="PLUS_6H",
                delay_seconds=21600,
            ),
            context=ObservableRecoveryContext(
                scenario_id="scen_reval",
                payment_id="pay_reval_01",
                amount_in_paise=250_000,
                currency="INR",
            ),
            aggregate=PaymentAggregate(
                payment_id="pay_reval_01",
                amount=250_000,
                currency="INR",
                current_state=PaymentState.FAILED,
                version=1,
            ),
            policy=merchant_policy,
            current_epoch=1700000000,
            timing_window=TimingWindow.PLUS_6H,
        )

        # Payment is now captured organically
        captured_agg = PaymentAggregate(
            payment_id="pay_reval_01",
            amount=250_000,
            currency="INR",
            current_state=PaymentState.CAPTURED,
            version=2,
        )

        is_valid, reason, codes = service.revalidate_and_check_executable(
            scheduled_action=action,
            current_aggregate=captured_agg,
            current_epoch=1700021600,
            policy=merchant_policy,
        )

        assert is_valid is False
        assert "REVENUE_ALREADY_RECOVERED" in codes
        assert "STALE_OR_INVALID_SCHEDULED_ACTION" in codes

    def test_scheduled_action_expires_if_beyond_recovery_window(self, merchant_policy):
        service = ScheduledLifecycleService()
        action = service.schedule_action(
            decision=PolicyDecision(
                action_type=SimulatedActionType.RETRY_LATER,
                confidence=0.90,
                rationale="Retry in 6h",
                policy_name="TEST_POLICY",
                timing_window="PLUS_6H",
                delay_seconds=21600,
            ),
            context=ObservableRecoveryContext(
                scenario_id="scen_reval_exp",
                payment_id="pay_reval_exp",
                amount_in_paise=250_000,
                currency="INR",
            ),
            aggregate=PaymentAggregate(
                payment_id="pay_reval_exp",
                amount=250_000,
                currency="INR",
                current_state=PaymentState.FAILED,
                version=1,
            ),
            policy=merchant_policy,
            current_epoch=1700000000,
            timing_window=TimingWindow.PLUS_6H,
        )

        # Attempting execution 100 hours later (> 72h expiry)
        due_epoch = 1700000000 + (100 * 3600)
        is_valid, reason, codes = service.revalidate_and_check_executable(
            scheduled_action=action,
            current_aggregate=PaymentAggregate(
                payment_id="pay_reval_exp",
                amount=250_000,
                currency="INR",
                current_state=PaymentState.FAILED,
                version=1,
            ),
            current_epoch=due_epoch,
            policy=merchant_policy,
        )

        assert is_valid is False
        assert "TIMING_EXPIRED_BEFORE_EXECUTION" in codes

    def test_duplicate_scheduled_action_idempotency_key_blocked(self, merchant_policy):
        service = ScheduledLifecycleService()
        ctx = ObservableRecoveryContext(
            scenario_id="scen_dup_key",
            payment_id="pay_dup_key",
            amount_in_paise=250_000,
            currency="INR",
        )
        decision = PolicyDecision(
            action_type=SimulatedActionType.RETRY_LATER,
            confidence=0.90,
            rationale="Retry in 6h",
            policy_name="TEST_POLICY",
            timing_window="PLUS_6H",
            delay_seconds=21600,
        )

        # First scheduling succeeds
        service.schedule_action(
            decision=decision,
            context=ctx,
            aggregate=None,
            policy=merchant_policy,
            current_epoch=1700000000,
            timing_window=TimingWindow.PLUS_6H,
            delay_seconds=21600,
        )

        # Duplicate active schedule is blocked
        with pytest.raises(Exception) as excinfo:
            service.schedule_action(
                decision=decision,
                context=ctx,
                aggregate=None,
                policy=merchant_policy,
                current_epoch=1700000000,
                timing_window=TimingWindow.PLUS_6H,
                delay_seconds=21600,
            )
        assert "Duplicate scheduled action" in str(excinfo.value)

    def test_scheduled_action_revalidation_checks_state_version(self, merchant_policy):
        service = ScheduledLifecycleService()
        action = service.schedule_action(
            decision=PolicyDecision(
                action_type=SimulatedActionType.RETRY_LATER,
                confidence=0.90,
                rationale="Retry in 6h",
                policy_name="TEST_POLICY",
                timing_window="PLUS_6H",
                delay_seconds=21600,
            ),
            context=ObservableRecoveryContext(
                scenario_id="scen_ver",
                payment_id="pay_ver_01",
                amount_in_paise=250_000,
                currency="INR",
            ),
            aggregate=PaymentAggregate(
                payment_id="pay_ver_01",
                amount=250_000,
                currency="INR",
                current_state=PaymentState.FAILED,
                version=1,
            ),
            policy=merchant_policy,
            current_epoch=1700000000,
            timing_window=TimingWindow.PLUS_6H,
        )

        # Aggregate version mutated to v3
        mutated_agg = PaymentAggregate(
            payment_id="pay_ver_01",
            amount=250_000,
            currency="INR",
            current_state=PaymentState.FAILED,
            version=3,
        )

        is_valid, reason, codes = service.revalidate_and_check_executable(
            scheduled_action=action,
            current_aggregate=mutated_agg,
            current_epoch=1700021600,
            policy=merchant_policy,
        )

        assert is_valid is False
        assert "STATE_VERSION_MISMATCH" in codes


class TestBenchmarkEvaluationCounters:
    """Validates that evaluation metrics include Governor and timing counters."""

    def test_benchmark_report_includes_governor_counters_and_timing_metrics(self):
        sim = Simulator()
        scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=10))

        harness = EvaluationHarness()
        policy = DeterministicRecoveryPolicy()
        result = harness.evaluate_policy(policy, scenarios)

        m = result.metrics
        assert hasattr(m, "governor_allow_count")
        assert hasattr(m, "governor_deny_count")
        assert hasattr(m, "governor_abstain_count")
        assert hasattr(m, "governor_defer_count")
        assert hasattr(m, "human_review_count")
        assert hasattr(m, "actions_scheduled_count")
        assert hasattr(m, "actions_executed_immediately_count")

        # Invariants
        assert m.governor_allow_count + m.governor_deny_count + m.governor_abstain_count + m.governor_defer_count + m.human_review_count >= m.total_scenarios
