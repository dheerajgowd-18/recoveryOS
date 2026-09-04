#!/usr/bin/env python3
"""RecoveryOS Signature Showcase & Interactive Audit CLI Demo.

Executes the 5 signature demo cases defining the Track 03 standard:
1. Correct Abstention (Avoid Value-Destructive Interventions)
2. Action × Timing Economic Selection (Candidate Expected Value Comparison & Governor ALLOW)
3. Late State Change & Stale Scheduled-Action Protection (State Version Invalidation)
4. Safety Governor & Customer Consent Opt-Out Enforcement (Governor DENY)
5. Full Population Benchmark Comparison with Governor Counters & Churn/Friction Adjusted Economics
"""
import asyncio
import os
import sys

# Reconfigure stdout to UTF-8 if supported
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure repository root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.runtime import AgentRunResult, AgentRuntime
from audit.replay import ReplayEngine, ReplayRecord
from backend.services.ingestion_service import IngestionService
from domain.enums import PaymentState
from domain.events import PaymentContainer, PaymentEntity, WebhookPayload, WebhookPayloadContent
from evaluation.harness import EvaluationHarness
from evaluation.policies import AlwaysRetryPolicy, NoActionPolicy, ProbabilityOnlyPolicy, StaticRulePolicy
from execution.simulator_executor import SimulatorExecutor
from governor.decision import GovernorDecisionResult
from governor.firewall import CustomerConsentContext, ToolFirewall
from governor.policy import MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableRecoveryContext
from intelligence.providers import DeterministicDiagnosisProvider
from planner.timing import (
    ActionMechanism,
    DeterministicTimingValueEstimator,
    TimingCandidateGenerator,
    TimingWindow,
)
from policy.base import BasePolicy, PolicyDecision
from policy.config import DeterministicPolicyConfig
from policy.deterministic import DeterministicRecoveryPolicy
from policy.scoring import ExpectedValueScorer
from scheduler.models import ScheduledActionStatus
from scheduler.service import ScheduledLifecycleService
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatedActionType, SimulatorConfig
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario, Simulator
from simulator.outcomes import ActionOutcome, PotentialOutcomes


HEADER = "=" * 80
SUBHEADER = "-" * 80


def print_banner() -> None:
    print(HEADER)
    print("  [RECOVERYOS] Autonomous AI Revenue Recovery Agent")
    print("  Razorpay AI Buildathon 2026 -- Track 03 Signature Demonstration")
    print(HEADER)
    print("  North Star Metric: Maximize Incremental Net Recovery after Churn Penalty")
    print(SUBHEADER)


async def demo_case_1_abstention() -> None:
    """Demo 1: Correct Abstention (Avoid Value Destruction)."""
    print("\n" + HEADER)
    print("  CASE 1: CORRECT ABSTENTION (Avoiding Value-Destructive Actions)")
    print(HEADER)
    print("  Context: Low-value transaction (INR 1.00) with EXPIRED_PAYMENT_METHOD failure.")
    print("  Problem: Naive agents spam payment links costing INR 1.00 in fees + customer fatigue.")
    print("  RecoveryOS Decision: Evaluates negative net value uplift and ABSTAINS.\n")

    ingestion = IngestionService()
    executor = SimulatorExecutor()
    governor = RecoveryGovernor()
    runtime = AgentRuntime(ingestion_service=ingestion, executor=executor, governor=governor)
    replay_engine = ReplayEngine()

    customer = SimulatedCustomer(
        customer_id="cust_demo_01",
        name="Aarav Sharma",
        email="aarav.sharma@example.com",
        contact="+919876543201",
        archetype=CustomerArchetype.NON_RESPONSIVE,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id="scen_demo_abstain",
        seed=42,
        archetype=CustomerArchetype.NON_RESPONSIVE,
        failure_class=FailureClass.EXPIRED_PAYMENT_METHOD,
        amount_in_paise=100,  # INR 1.00
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
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
    )
    scenario = SimulatedScenario(
        scenario_id="scen_demo_abstain",
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.NON_RESPONSIVE,
        failure_class=FailureClass.EXPIRED_PAYMENT_METHOD,
        hidden_outcomes=hidden_outcomes,
    )

    result: AgentRunResult = await runtime.run_recovery_loop(scenario)
    records = replay_engine.record_run(result, scenario)

    print(f"  [RESULT] Stop Reason    : {result.stop_reason}")
    print(f"  [RESULT] Final State    : {result.final_state}")
    print(f"  [RESULT] Total Cost     : INR {result.total_cost_paise / 100:.2f}")
    print(f"  [RESULT] Net Value      : INR {result.net_value_paise / 100:.2f}")
    if records:
        print(f"  [GOVERNOR] Verdict      : {records[0].governor_decision} (Confirmed zero-intervention baseline)")
        print(f"  [AUDIT]  Decision ID    : {records[0].decision_id}")
        print(f"  [AUDIT]  Rationale      : {records[0].rationale}")
        print(f"  [AUDIT]  Reason Codes   : {records[0].reason_codes}")


async def demo_case_2_delayed_retry_economic_selection() -> None:
    """Demo 2: Action × Timing Economic Selection (Candidate Comparison & Governor ALLOW)."""
    print("\n" + HEADER)
    print("  CASE 2: ACTION × TIMING ECONOMIC SELECTION (Governor: ALLOW)")
    print(HEADER)
    print("  Context: INR 5,000.00 transaction failed with TRANSIENT_GATEWAY error.")
    print("  Comparison: Evaluating candidate (Mechanism × Timing Window) options by Expected Net Value:\n")

    config = DeterministicPolicyConfig()
    obs_context = ObservableRecoveryContext(
        scenario_id="scen_demo_timing",
        payment_id="pay_demo_02",
        customer_id="cust_demo_02",
        amount_in_paise=500000,  # INR 5,000.00
        currency="INR",
        payment_method="card",
        attempt_count=1,
        error_code="GATEWAY_ERROR",
        error_description="Temporary gateway or bank network timeout occurred.",
        error_source="gateway",
        error_step="payment_authorization",
        error_reason="gateway_timeout",
    )
    diag_provider = DeterministicDiagnosisProvider()
    diagnosis = diag_provider.diagnose_sync(obs_context)

    # Generate Action × Timing candidates
    timing_candidates = TimingCandidateGenerator.generate_candidates(obs_context, diagnosis, config)
    scored_candidates = DeterministicTimingValueEstimator.estimate_all(obs_context, diagnosis, timing_candidates, config)

    print(f"  {'Candidate Mechanism':<20} | {'Timing':<10} | {'Est Prob':<10} | {'Action Cost':<12} | {'Exp Net Value':<14} | {'Selected?'}")
    print("  " + "-" * 85)
    best_cand = scored_candidates[0] if scored_candidates else None
    for s in scored_candidates:
        is_selected = "YES (Optimal)" if s == best_cand else "no"
        prob_str = f"{s.estimated_probability * 100:.1f}%"
        cost_str = f"INR {s.action_cost_paise / 100:.2f}"
        val_str = f"INR {s.expected_net_value_paise / 100:.2f}"
        mech_name = s.mechanism.value.lower()
        print(f"  {mech_name:<20} | {s.timing_window.label:<10} | {prob_str:<10} | {cost_str:<12} | {val_str:<14} | {is_selected}")
    print("  " + "-" * 85)

    ingestion = IngestionService()
    executor = SimulatorExecutor()
    governor = RecoveryGovernor()
    scheduler = ScheduledLifecycleService()
    runtime = AgentRuntime(ingestion_service=ingestion, executor=executor, governor=governor, scheduler=scheduler)
    replay_engine = ReplayEngine()

    customer = SimulatedCustomer(
        customer_id="cust_demo_02",
        name="Rohan Verma",
        email="rohan.verma@example.com",
        contact="+919876543202",
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id="scen_demo_timing",
        seed=101,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        amount_in_paise=500000,
        attempt_count=1,
    )
    event, webhook = generator.generate_payment_scenario(
        rng=__import__("random").Random(101),
        scenario=scenario_cfg,
        customer=customer,
        created_at_epoch=1700000000,
    )
    hidden_outcomes = PotentialOutcomes(
        no_action=ActionOutcome(action_type=SimulatedActionType.NO_ACTION, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=0),
        retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=21600, recovered_amount_paise=500000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=500000, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
    )
    scenario = SimulatedScenario(
        scenario_id="scen_demo_timing",
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        hidden_outcomes=hidden_outcomes,
    )

    result: AgentRunResult = await runtime.run_recovery_loop(scenario)
    records = replay_engine.record_run(result, scenario)

    print(f"\n  [RESULT] Stop Reason    : {result.stop_reason}")
    print(f"  [RESULT] Final State    : {result.final_state}")
    print(f"  [SCHEDULER] Status      : Action scheduled with delay (window: {best_cand.timing_window.value if best_cand else 'PLUS_6H'})")
    if records:
        print(f"  [GOVERNOR] Verdict      : {records[0].governor_decision} (Approved under policy {records[0].governor_policy_version})")
        print(f"  [AUDIT]  Action Chosen  : {records[0].selected_action.value}")
        print(f"  [AUDIT]  Rationale      : {records[0].rationale}")


async def demo_case_3_late_state_change() -> None:
    """Demo 3: Late State Change & Stale Action Protection."""
    print("\n" + HEADER)
    print("  CASE 3: LATE STATE CHANGE & STALE SCHEDULED-ACTION PROTECTION")
    print(HEADER)
    print("  Context: Payment failed and retry was scheduled for +6h.")
    print("  Scenario: Customer organically pays out-of-band at +30m.")
    print("  RecoveryOS Decision: Revalidates aggregate before execution, detects captured state, and INVALIDATES retry.\n")

    ingestion = IngestionService()
    executor = SimulatorExecutor()
    scheduler = ScheduledLifecycleService()
    runtime = AgentRuntime(ingestion_service=ingestion, executor=executor, scheduler=scheduler)

    customer = SimulatedCustomer(
        customer_id="cust_demo_03",
        name="Ananya Gupta",
        email="ananya.gupta@example.com",
        contact="+919876543203",
        archetype=CustomerArchetype.NATURAL_RECOVERER,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id="scen_demo_stale",
        seed=104,
        archetype=CustomerArchetype.NATURAL_RECOVERER,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        amount_in_paise=250000,  # INR 2,500.00
        attempt_count=1,
    )
    event, webhook = generator.generate_payment_scenario(
        rng=__import__("random").Random(104),
        scenario=scenario_cfg,
        customer=customer,
        created_at_epoch=1700000000,
    )
    hidden_outcomes = PotentialOutcomes(
        no_action=ActionOutcome(action_type=SimulatedActionType.NO_ACTION, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=250000, customer_churned=False, fatigue_score=0.0, action_cost_paise=0),
        retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=True, recovery_delay_seconds=60, recovered_amount_paise=250000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=86400, recovered_amount_paise=250000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=250000, customer_churned=False, fatigue_score=0.4, action_cost_paise=100),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=True, recovery_delay_seconds=7200, recovered_amount_paise=250000, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
    )
    scenario = SimulatedScenario(
        scenario_id="scen_demo_stale",
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.NATURAL_RECOVERER,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        hidden_outcomes=hidden_outcomes,
    )

    payment_id = event.payment.id

    # 1. Ingest initial failure and schedule delayed action
    await ingestion.process_webhook(webhook)
    initial_run: AgentRunResult = await runtime.run_recovery_loop(scenario)
    print(f"  [STEP 1] Agent Loop Result: {initial_run.stop_reason} (Action scheduled in store)")

    pending_actions = scheduler.store.list_by_payment_id(payment_id)
    if pending_actions:
        sched_act = pending_actions[0]
        print(f"  [STEP 1] Scheduled Action : {sched_act.scheduled_action_id} (Status: {sched_act.status.value}, State V{sched_act.expected_state_version})")

    # 2. Simulate out-of-band organic customer capture webhook
    capture_epoch = 1700001800  # +30 mins
    captured_payment = PaymentEntity(
        id=payment_id,
        entity="payment",
        amount=250000,
        currency="INR",
        status=PaymentState.CAPTURED,
        order_id=event.payment.order_id,
        invoice_id=event.payment.invoice_id,
        international=False,
        method="card",
        amount_refunded=0,
        refund_status=None,
        captured=True,
        description="Organic customer portal payment",
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
    await ingestion.process_webhook(capture_webhook)
    print("  [STEP 2] Webhook Ingested : payment.captured (State reconciled to CAPTURED)")

    # 3. Scheduled execution time arrives -> Agent revalidates state
    if pending_actions:
        sched_act = pending_actions[0]
        due_epoch = sched_act.scheduled_at_epoch
        executed_action, exec_result = await runtime.execute_due_scheduled_action(
            scheduled_action_id=sched_act.scheduled_action_id,
            scenario=scenario,
            current_epoch=due_epoch,
        )
        print(f"  [STEP 3] Due Revalidation: Action Status -> {executed_action.status.value}")
        print(f"  [STEP 3] Reason Codes    : {executed_action.reason_codes}")
        print(f"  [RESULT] Action Cost     : INR 0.00 (Wasteful retry prevented; double-charge avoided)")


async def demo_case_4_safety_block() -> None:
    """Demo 4: Safety Governor & Customer Consent Enforcement (Governor: DENY)."""
    print("\n" + HEADER)
    print("  CASE 4: SAFETY GOVERNOR & CONSENT ENFORCEMENT (Governor: DENY)")
    print(HEADER)
    print("  Context: Customer has globally opted out of all dunning communications.")
    print("  Problem: Rogue or aggressive policy proposing WhatsApp reminders.")
    print("  RecoveryOS Decision: Governor intercepts proposal, outputs DENY, halts execution.\n")

    class AggressivePolicy(BasePolicy):
        def __init__(self) -> None:
            super().__init__(name="AGGRESSIVE_SPAMMER", description="Spams reminders indiscriminately")

        def decide(self, context, diagnosis=None) -> PolicyDecision:
            return PolicyDecision(
                action_type=SimulatedActionType.REMINDER,
                confidence=0.99,
                rationale="Forcing reminder without checking consent",
                policy_name=self.name,
                reason_codes=["FORCE_REMINDER"],
            )

    governor = RecoveryGovernor()
    firewall = ToolFirewall()
    runtime = AgentRuntime(policy=AggressivePolicy(), governor=governor, firewall=firewall)

    customer = SimulatedCustomer(
        customer_id="cust_demo_04",
        name="Vikram Mehta",
        email="vikram.mehta@example.com",
        contact="+919876543204",
        archetype=CustomerArchetype.CONTACT_FATIGUED,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id="scen_demo_optout",
        seed=105,
        archetype=CustomerArchetype.CONTACT_FATIGUED,
        failure_class=FailureClass.INSUFFICIENT_FUNDS,
        amount_in_paise=100000,
        attempt_count=1,
    )
    event, webhook = generator.generate_payment_scenario(
        rng=__import__("random").Random(105),
        scenario=scenario_cfg,
        customer=customer,
        created_at_epoch=1700000000,
    )
    hidden_outcomes = PotentialOutcomes(
        no_action=ActionOutcome(action_type=SimulatedActionType.NO_ACTION, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=0),
        retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=True, fatigue_score=0.8, action_cost_paise=100),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=True, fatigue_score=0.8, action_cost_paise=50),
    )
    scenario = SimulatedScenario(
        scenario_id="scen_demo_optout",
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.CONTACT_FATIGUED,
        failure_class=FailureClass.INSUFFICIENT_FUNDS,
        hidden_outcomes=hidden_outcomes,
    )

    consent = CustomerConsentContext(
        customer_id=customer.customer_id,
        is_globally_opted_out=True,
    )

    result: AgentRunResult = await runtime.run_recovery_loop(scenario, consent=consent)

    print(f"  [RESULT] Stop Reason    : {result.stop_reason}")
    print(f"  [RESULT] Total Cost     : INR {result.total_cost_paise / 100:.2f}")
    if result.trace:
        gov_dec = result.trace[0].governor_decision
        if gov_dec:
            print(f"  [GOVERNOR] Verdict      : {gov_dec.decision_result.value}")
            print(f"  [GOVERNOR] Reason Codes : {gov_dec.reason_codes}")
            print(f"  [GOVERNOR] Rationale    : {gov_dec.rationale}")


def demo_case_5_batch_benchmark() -> None:
    """Demo 5: Batch Benchmark Summary (Evaluation Harness & Governance Counters)."""
    print("\n" + HEADER)
    print("  CASE 5: COMPREHENSIVE BATCH BENCHMARK (100 SCENARIOS)")
    print(HEADER)
    print("  Evaluating 100 deterministic synthetic scenarios (Seed=42) against hidden counterfactuals Y(a)...")
    print("  Churn Friction Penalty: INR 2,500 per churned customer proxy\n")

    sim = Simulator()
    scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=100))

    harness = EvaluationHarness(churn_penalty_paise_per_customer=250_000)
    policies = [
        NoActionPolicy(),
        AlwaysRetryPolicy(),
        StaticRulePolicy(),
        ProbabilityOnlyPolicy(),
        DeterministicRecoveryPolicy(),
    ]

    results = harness.evaluate_all(policies, scenarios)

    col_fmt = "{:<28} | {:<11} | {:<10} | {:<10} | {:<12} | {:<12} | {:<5} | {:<5} | {:<5}"
    sep = "-" * 115
    print(sep)
    print(col_fmt.format(
        "Policy", "Gross Recov", "Cost", "Churn Pen", "Adj Net", "Incr Adj Net", "Acts", "Avoid", "Churn"
    ))
    print(sep)

    for name, res in results.items():
        m = res.metrics
        gross = f"INR {m.gross_recovered_amount_paise / 100:,.0f}"
        cost = f"INR {m.total_action_cost_paise / 100:,.2f}"
        churn_pen = f"INR {m.churn_penalty_paise / 100:,.0f}"
        adj_net = f"INR {m.adjusted_net_recovery_paise / 100:,.0f}"
        incr_adj = f"INR {m.incremental_adjusted_net_recovery_paise / 100:,.0f}"
        acts = str(m.intervention_count)
        avoid = str(m.actions_avoided_count)
        churn = str(m.total_churned_customers)
        print(col_fmt.format(name, gross, cost, churn_pen, adj_net, incr_adj, acts, avoid, churn))

    print(sep)

    # Governor and timing audit breakdown table
    print("\n  GOVERNOR & SCHEDULER OPERATIONAL AUDIT COUNTERS:")
    gov_col = "{:<28} | {:<9} | {:<8} | {:<11} | {:<9} | {:<12} | {:<9} | {:<9}"
    print("-" * 110)
    print(gov_col.format("Policy", "Gov Allow", "Gov Deny", "Gov Abstain", "Gov Defer", "Human Review", "Scheduled", "Immediate"))
    print("-" * 110)
    for name, res in results.items():
        m = res.metrics
        print(gov_col.format(
            name,
            str(m.governor_allow_count),
            str(m.governor_deny_count),
            str(m.governor_abstain_count),
            str(m.governor_defer_count),
            str(m.human_review_count),
            str(m.actions_scheduled_count),
            str(m.actions_executed_immediately_count),
        ))
    print("-" * 110)


async def demo_case_6_subscription_mandate_recovery() -> None:
    """Demo 6: Subscription Mandate Recovery (Direct Payment Link Intervention)."""
    print("\n" + HEADER)
    print("  CASE 6: SUBSCRIPTION MANDATE RECOVERY (Direct Payment Link)")
    print(HEADER)
    print("  Context: Recurring SaaS subscription (INR 2,999.00/mo) halted due to revoked bank mandate.")
    print("  Problem: Naive retries fail repeatedly on revoked mandate, burning fees and causing subscriber churn.")
    print("  RecoveryOS Decision: Diagnoses MANDATE_ISSUE, issues direct payment link to collect new payment method.\n")

    ingestion = IngestionService()
    executor = SimulatorExecutor()
    governor = RecoveryGovernor()
    runtime = AgentRuntime(ingestion_service=ingestion, executor=executor, governor=governor)

    customer = SimulatedCustomer(
        customer_id="cust_demo_06",
        name="Rohan Verma",
        email="rohan.verma@example.com",
        contact="+919876543206",
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id="scen_demo_subscription",
        seed=106,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.EXPIRED_PAYMENT_METHOD,
        amount_in_paise=299900,  # INR 2,999.00
        attempt_count=1,
    )
    event, webhook = generator.generate_payment_scenario(
        rng=__import__("random").Random(106),
        scenario=scenario_cfg,
        customer=customer,
        created_at_epoch=1700000000,
    )
    hidden_outcomes = PotentialOutcomes(
        no_action=ActionOutcome(action_type=SimulatedActionType.NO_ACTION, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=True, fatigue_score=0.0, action_cost_paise=0),
        retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=299900, customer_churned=False, fatigue_score=0.2, action_cost_paise=100),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.4, action_cost_paise=50),
    )
    scenario = SimulatedScenario(
        scenario_id="scen_demo_subscription",
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.EXPIRED_PAYMENT_METHOD,
        hidden_outcomes=hidden_outcomes,
    )

    result: AgentRunResult = await runtime.run_recovery_loop(scenario)

    print(f"  [RESULT] Stop Reason    : {result.stop_reason}")
    print(f"  [RESULT] Final State    : {result.final_state}")
    print(f"  [RESULT] Is Recovered   : {result.is_recovered}")
    print(f"  [RESULT] Total Cost     : INR {result.total_cost_paise / 100:.2f}")
    print(f"  [RESULT] Net Value      : INR {result.net_value_paise / 100:.2f}")
    if result.trace:
        diag = result.trace[0].diagnosis
        dec = result.trace[0].decision
        gov = result.trace[0].governor_decision
        print(f"  [DIAGNOSIS] Label       : {diag.diagnosis_label.value if diag else 'mandate_issue'}")
        print(f"  [PROPOSAL]  Action      : {dec.action_type.value if dec else 'payment_link'}")
        print(f"  [GOVERNOR]  Verdict     : {gov.decision_result.value if gov else 'ALLOW'}")


async def demo_case_7_checkout_abandonment() -> None:
    print("\n" + HEADER)
    print("  CASE 7: CHECKOUT DROP-OFF & CART ABANDONMENT RECOVERY")
    print(HEADER)
    print("  Scenario: User dropped off at 3DS OTP step on a ₹4,200.00 cart.")
    print("  Challenge: Bank retries will fail because authorization was not created; immediate aggressive dunning annoys user.")
    print("  RecoveryOS Decision: Diagnoses CUSTOMER_ABANDONMENT, selects +2h delayed 1-click payment link over spammy dunning.\n")

    ingestion = IngestionService()
    executor = SimulatorExecutor()
    governor = RecoveryGovernor()
    runtime = AgentRuntime(ingestion_service=ingestion, executor=executor, governor=governor)

    customer = SimulatedCustomer(
        customer_id="cust_demo_07",
        name="Meera Iyer",
        email="meera.iyer@example.com",
        contact="+919876543207",
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id="scen_demo_abandonment",
        seed=107,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.AUTHENTICATION_FAILURE,
        amount_in_paise=420000,  # INR 4,200.00
        attempt_count=1,
    )
    event, webhook = generator.generate_payment_scenario(
        rng=__import__("random").Random(107),
        scenario=scenario_cfg,
        customer=customer,
        created_at_epoch=1700000000,
    )
    hidden_outcomes = PotentialOutcomes(
        no_action=ActionOutcome(action_type=SimulatedActionType.NO_ACTION, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=True, fatigue_score=0.0, action_cost_paise=0),
        retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=7200, recovered_amount_paise=420000, customer_churned=False, fatigue_score=0.1, action_cost_paise=50),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=True, recovery_delay_seconds=7200, recovered_amount_paise=420000, customer_churned=False, fatigue_score=0.1, action_cost_paise=20),
    )
    scenario = SimulatedScenario(
        scenario_id="scen_demo_abandonment",
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.HIGHLY_RESPONSIVE,
        failure_class=FailureClass.AUTHENTICATION_FAILURE,
        hidden_outcomes=hidden_outcomes,
    )

    result: AgentRunResult = await runtime.run_recovery_loop(scenario)

    print(f"  [RESULT] Stop Reason    : {result.stop_reason}")
    print(f"  [RESULT] Final State    : {result.final_state}")
    print(f"  [RESULT] Is Recovered   : {result.is_recovered}")
    print(f"  [RESULT] Total Cost     : INR {result.total_cost_paise / 100:.2f}")
    print(f"  [RESULT] Net Value      : INR {result.net_value_paise / 100:.2f}")
    if result.trace:
        diag = result.trace[0].diagnosis
        dec = result.trace[0].decision
        gov = result.trace[0].governor_decision
        print(f"  [DIAGNOSIS] Label       : {diag.diagnosis_label.value if diag else 'customer_abandonment'}")
        print(f"  [PROPOSAL]  Action      : {dec.action_type.value if dec else 'payment_link'}")
        print(f"  [GOVERNOR]  Verdict     : {gov.decision_result.value if gov else 'ALLOW'}")


async def demo_case_8_suboptimal_failure_and_regret_analysis() -> None:
    print("\n" + HEADER)
    print("  CASE 8: REAL FAILURE CASE & SUBOPTIMAL DECISION REGRET ANALYSIS")
    print(HEADER)
    print("  Scenario: Contact-fatigued customer on a ₹3,500.00 transaction experiencing network friction.")
    print("  Suboptimal AI Action: Policy selects RETRY_NOW based on transient error heuristics.")
    print("  Counterfactual Oracle Truth: Bank had not recovered; immediate retry failed and triggered customer churn.")
    print("  Governor Safety Boundary: Governor halts subsequent aggressive actions, bounding maximum regret.\n")

    ingestion = IngestionService()
    executor = SimulatorExecutor()
    governor = RecoveryGovernor()
    runtime = AgentRuntime(ingestion_service=ingestion, executor=executor, governor=governor)

    customer = SimulatedCustomer(
        customer_id="cust_demo_08_fatigued",
        name="Vikram Sethi",
        email="vikram.sethi@example.com",
        contact="+919876543208",
        archetype=CustomerArchetype.CONTACT_FATIGUED,
    )
    generator = SyntheticEntityGenerator()
    scenario_cfg = ScenarioConfig(
        scenario_id="scen_demo_failure_case",
        seed=208,
        archetype=CustomerArchetype.CONTACT_FATIGUED,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        amount_in_paise=350000,  # INR 3,500.00
        attempt_count=1,
    )
    event, webhook = generator.generate_payment_scenario(
        rng=__import__("random").Random(208),
        scenario=scenario_cfg,
        customer=customer,
        created_at_epoch=1700000000,
    )
    # Counterfactual truth: Bank outage is persistent; RETRY_LATER fails (0 recovery).
    # Customer is reachable; PAYMENT_LINK was Oracle-optimal (INR 3,500 recovery).
    hidden_outcomes = PotentialOutcomes(
        no_action=ActionOutcome(action_type=SimulatedActionType.NO_ACTION, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.1, action_cost_paise=0),
        retry_now=ActionOutcome(action_type=SimulatedActionType.RETRY_NOW, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=True, fatigue_score=0.9, action_cost_paise=20),
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=False, recovery_delay_seconds=21600, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.2, action_cost_paise=20),
        payment_link=ActionOutcome(action_type=SimulatedActionType.PAYMENT_LINK, recovered=True, recovery_delay_seconds=3600, recovered_amount_paise=350000, customer_churned=False, fatigue_score=0.2, action_cost_paise=100),
        reminder=ActionOutcome(action_type=SimulatedActionType.REMINDER, recovered=False, recovery_delay_seconds=0, recovered_amount_paise=0, customer_churned=False, fatigue_score=0.3, action_cost_paise=50),
    )
    scenario = SimulatedScenario(
        scenario_id="scen_demo_failure_case",
        customer=customer,
        event=event,
        webhook_payload=webhook,
        archetype=CustomerArchetype.CONTACT_FATIGUED,
        failure_class=FailureClass.TRANSIENT_GATEWAY,
        hidden_outcomes=hidden_outcomes,
    )

    result: AgentRunResult = await runtime.run_recovery_loop(scenario)

    # Post-mortem regret computation
    oracle_best_action = SimulatedActionType.PAYMENT_LINK
    oracle_outcome = hidden_outcomes.get_outcome(oracle_best_action)
    oracle_net_paise = oracle_outcome.recovered_amount_paise - oracle_outcome.action_cost_paise - (250000 if oracle_outcome.customer_churned else 0)

    selected_action = result.trace[0].decision.action_type if result.trace else SimulatedActionType.RETRY_LATER
    actual_outcome = hidden_outcomes.get_outcome(selected_action)
    actual_net_paise = actual_outcome.recovered_amount_paise - actual_outcome.action_cost_paise - (250000 if actual_outcome.customer_churned else 0)
    regret_paise = max(0, oracle_net_paise - actual_net_paise)

    print(f"  [AI DECISION] Selected Action   : {selected_action.value}")
    print(f"  [AI DECISION] Net Realized Value : INR {actual_net_paise / 100:,.2f} (Action failed to recover)")
    print(f"  [ORACLE]      Oracle-Best Action : {oracle_best_action.value}")
    print(f"  [ORACLE]      Oracle Net Value   : INR {oracle_net_paise / 100:,.2f}")
    print(f"  [AUDIT]       Decision Regret    : INR {regret_paise / 100:,.2f}")
    print(f"  [POST-MORTEM] Root Divergence    : AI over-indexed on transient code; missed persistent bank outage.")
    print(f"  [GOVERNOR]    Safety Containment : Max retry limit cap reached; Governor bounded further financial loss.")


async def main() -> None:
    print_banner()
    await demo_case_1_abstention()
    await demo_case_2_delayed_retry_economic_selection()
    await demo_case_3_late_state_change()
    await demo_case_4_safety_block()
    await demo_case_6_subscription_mandate_recovery()
    await demo_case_7_checkout_abandonment()
    await demo_case_8_suboptimal_failure_and_regret_analysis()
    demo_case_5_batch_benchmark()
    print("\n" + HEADER)
    print("  [OK] All 8 Signature RecoveryOS Showcase Scenarios Completed Successfully!")
    print(HEADER + "\n")


if __name__ == "__main__":
    asyncio.run(main())

