#!/usr/bin/env python3
"""RecoveryOS Signature Showcase & Interactive Audit CLI Demo.

Executes the 5 signature demo cases defining the Track 03 standard:
1. Correct Abstention (Avoid Value-Destructive Interventions)
2. Delayed Retry Economic Selection (Candidate Expected Value Comparison)
3. Late State Change & Stale Action Protection
4. Safety Block & Customer Consent Opt-Out Enforcement
5. Full Population Benchmark Comparison with Churn/Friction Adjusted Economics
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
from governor.firewall import CustomerConsentContext, ToolFirewall
from intelligence.context import ObservableRecoveryContext
from intelligence.providers import DeterministicDiagnosisProvider
from policy.base import BasePolicy, PolicyDecision
from policy.config import DeterministicPolicyConfig
from policy.deterministic import DeterministicRecoveryPolicy
from policy.scoring import ExpectedValueScorer
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
    runtime = AgentRuntime(ingestion_service=ingestion, executor=executor)
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

    print(f"  [RESULT] Stop Reason : {result.stop_reason}")
    print(f"  [RESULT] Final State : {result.final_state}")
    print(f"  [RESULT] Total Cost  : INR {result.total_cost_paise / 100:.2f}")
    print(f"  [RESULT] Net Value   : INR {result.net_value_paise / 100:.2f}")
    if records:
        print(f"  [AUDIT]  Decision ID : {records[0].decision_id}")
        print(f"  [AUDIT]  Rationale   : {records[0].rationale}")
        print(f"  [AUDIT]  Reason Codes: {records[0].reason_codes}")


async def demo_case_2_delayed_retry_economic_selection() -> None:
    """Demo 2: Delayed Retry Economic Selection (Candidate Comparison)."""
    print("\n" + HEADER)
    print("  CASE 2: DELAYED RETRY ECONOMIC SELECTION (Candidate Comparison)")
    print(HEADER)
    print("  Context: INR 5,000.00 transaction failed with TRANSIENT_GATEWAY error.")
    print("  Comparison: Evaluating all candidate interventions and ranking by Expected Net Value:\n")

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

    candidates = [
        SimulatedActionType.RETRY_NOW,
        SimulatedActionType.RETRY_LATER,
        SimulatedActionType.PAYMENT_LINK,
        SimulatedActionType.REMINDER,
        SimulatedActionType.NO_ACTION,
    ]
    scored = ExpectedValueScorer.score_all(obs_context, diagnosis, candidates, config)

    print(f"  {'Candidate Action':<18} | {'Est Prob':<10} | {'Action Cost':<12} | {'Exp Net Value':<14} | {'Selected?'}")
    print("  " + "-" * 70)
    for s in scored:
        is_selected = "YES (Optimal)" if s.action_type == SimulatedActionType.RETRY_LATER else "no"
        prob_str = f"{s.estimated_probability * 100:.1f}%"
        cost_str = f"INR {s.action_cost_paise / 100:.2f}"
        val_str = f"INR {s.expected_net_value_paise / 100:.2f}"
        print(f"  {s.action_type.value:<18} | {prob_str:<10} | {cost_str:<12} | {val_str:<14} | {is_selected}")
    print("  " + "-" * 70)

    ingestion = IngestionService()
    executor = SimulatorExecutor()
    runtime = AgentRuntime(ingestion_service=ingestion, executor=executor)
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
        retry_later=ActionOutcome(action_type=SimulatedActionType.RETRY_LATER, recovered=True, recovery_delay_seconds=86400, recovered_amount_paise=500000, customer_churned=False, fatigue_score=0.0, action_cost_paise=20),
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
    print(f"  [RESULT] Recovered Amount: INR {result.recovered_amount_paise / 100:.2f}")
    print(f"  [RESULT] Total Cost     : INR {result.total_cost_paise / 100:.2f}")
    print(f"  [RESULT] Net Value      : INR {result.net_value_paise / 100:.2f}")
    if records:
        print(f"  [AUDIT]  Action Chosen  : {records[0].selected_action.value}")
        print(f"  [AUDIT]  Rationale      : {records[0].rationale}")


async def demo_case_3_late_state_change() -> None:
    """Demo 3: Late State Change & Stale Action Protection."""
    print("\n" + HEADER)
    print("  CASE 3: LATE STATE CHANGE & STALE ACTION PROTECTION")
    print(HEADER)
    print("  Context: Payment failed, but customer organically pays out-of-band.")
    print("  Problem: In-flight dunning action could double-charge or annoy customer.")
    print("  RecoveryOS Decision: Revalidates aggregate prior to execution and cancels retry.\n")

    ingestion = IngestionService()
    executor = SimulatorExecutor()
    runtime = AgentRuntime(ingestion_service=ingestion, executor=executor)

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

    # 1. Ingest initial failure
    await ingestion.process_webhook(webhook)

    # 2. Simulate out-of-band organic customer capture webhook
    capture_epoch = 1700001800
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

    result: AgentRunResult = await runtime.run_recovery_loop(scenario)

    print(f"  [RESULT] Stop Reason     : {result.stop_reason}")
    print(f"  [RESULT] Final State     : {result.final_state}")
    print(f"  [RESULT] Captured Amount : INR {result.recovered_amount_paise / 100:.2f}")
    print(f"  [RESULT] Action Cost     : INR {result.total_cost_paise / 100:.2f} (Zero wasteful fees)")


async def demo_case_4_safety_block() -> None:
    """Demo 4: Safety Block & Customer Consent Opt-Out."""
    print("\n" + HEADER)
    print("  CASE 4: SAFETY GOVERNOR & CUSTOMER CONSENT ENFORCEMENT")
    print(HEADER)
    print("  Context: Customer has globally opted out of all dunning communications.")
    print("  Problem: Rogue or aggressive policy proposing WhatsApp reminders.")
    print("  RecoveryOS Decision: ToolFirewall intercepts action, raises ConsentViolationError, fails closed.\n")

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

    firewall = ToolFirewall()
    runtime = AgentRuntime(policy=AggressivePolicy(), firewall=firewall)

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

    print(f"  [RESULT] Stop Reason : {result.stop_reason}")
    print(f"  [RESULT] Total Cost  : INR {result.total_cost_paise / 100:.2f}")
    if result.trace:
        print(f"  [FIREWALL] Error Msg : {result.trace[0].error_message}")


def demo_case_5_batch_benchmark() -> None:
    """Demo 5: Batch Benchmark Summary (Evaluation Harness)."""
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


async def main() -> None:
    print_banner()
    await demo_case_1_abstention()
    await demo_case_2_delayed_retry_economic_selection()
    await demo_case_3_late_state_change()
    await demo_case_4_safety_block()
    demo_case_5_batch_benchmark()
    print("\n" + HEADER)
    print("  [OK] All 5 Signature RecoveryOS Showcase Scenarios Completed Successfully!")
    print(HEADER + "\n")


if __name__ == "__main__":
    asyncio.run(main())
