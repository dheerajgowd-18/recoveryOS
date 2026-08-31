"""Unit and statistical validation tests for the RecoveryOS Synthetic Simulator."""
import asyncio
from typing import Dict, List
import pytest

from backend.services.ingestion_service import IngestionService
from ingestion.idempotency import InMemoryIdempotencyTracker
from ingestion.reconciler import StateReconciler
from ingestion.store import InMemoryEventStore
from simulator.config import CustomerArchetype, FailureClass, SimulatedActionType, SimulatorConfig
from simulator.generator import Simulator


class TestSimulatorDeterminism:
    """Validate pseudo-random generator determinism and reproducibility."""

    def test_reproducible_generation_same_seed(self) -> None:
        """Running the simulator twice with the same seed yields identical outputs."""
        config1 = SimulatorConfig(seed=12345, num_scenarios=25)
        config2 = SimulatorConfig(seed=12345, num_scenarios=25)

        sim1 = Simulator()
        sim2 = Simulator()

        batch1 = sim1.generate_batch(config1)
        batch2 = sim2.generate_batch(config2)

        assert len(batch1) == len(batch2) == 25

        for s1, s2 in zip(batch1, batch2):
            assert s1.scenario_id == s2.scenario_id
            assert s1.customer.customer_id == s2.customer.customer_id
            assert s1.customer.email == s2.customer.email
            assert s1.archetype == s2.archetype
            assert s1.failure_class == s2.failure_class
            assert s1.event.payment.amount == s2.event.payment.amount
            assert s1.event.payment.id == s2.event.payment.id

            # Verify hidden counterfactual outcomes are strictly identical
            for action in SimulatedActionType:
                o1 = s1.hidden_outcomes.get_outcome(action)
                o2 = s2.hidden_outcomes.get_outcome(action)
                assert o1.recovered == o2.recovered
                assert o1.recovered_amount_paise == o2.recovered_amount_paise
                assert o1.recovery_delay_seconds == o2.recovery_delay_seconds
                assert o1.customer_churned == o2.customer_churned
                assert o1.fatigue_score == o2.fatigue_score

    def test_different_seeds_yield_divergent_outputs(self) -> None:
        """Different seeds produce distinct scenarios."""
        sim = Simulator()
        batch_a = sim.generate_batch(SimulatorConfig(seed=111, num_scenarios=10))
        batch_b = sim.generate_batch(SimulatorConfig(seed=222, num_scenarios=10))

        # At least one customer email or scenario detail must diverge
        emails_a = [s.customer.email for s in batch_a]
        emails_b = [s.customer.email for s in batch_b]
        assert emails_a != emails_b


class TestSimulatorArchetypesAndOutcomes:
    """Validate behavioral dynamics and counterfactual distribution properties."""

    def test_hidden_outcome_completeness(self) -> None:
        """Every generated scenario must possess outcomes for all 5 required actions."""
        sim = Simulator()
        scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=20))

        required_actions = {
            SimulatedActionType.NO_ACTION,
            SimulatedActionType.RETRY_NOW,
            SimulatedActionType.RETRY_LATER,
            SimulatedActionType.PAYMENT_LINK,
            SimulatedActionType.REMINDER,
        }

        for s in scenarios:
            for action in required_actions:
                outcome = s.hidden_outcomes.get_outcome(action)
                assert outcome.action_type == action
                assert isinstance(outcome.recovered, bool)
                assert isinstance(outcome.customer_churned, bool)
                assert outcome.action_cost_paise >= 0
                assert 0.0 <= outcome.fatigue_score <= 1.0

    def test_natural_recoverer_vs_non_responsive_distribution(self) -> None:
        """Statistical test: NATURAL_RECOVERER no_action rate >> NON_RESPONSIVE."""
        sim = Simulator()

        # Generate 1,000 cases of NATURAL_RECOVERER
        natural_cfg = SimulatorConfig(
            seed=999,
            num_scenarios=1000,
            archetype_distribution={CustomerArchetype.NATURAL_RECOVERER: 1.0},
        )
        natural_batch = sim.generate_batch(natural_cfg)

        # Generate 1,000 cases of NON_RESPONSIVE
        non_resp_cfg = SimulatorConfig(
            seed=999,
            num_scenarios=1000,
            archetype_distribution={CustomerArchetype.NON_RESPONSIVE: 1.0},
        )
        non_resp_batch = sim.generate_batch(non_resp_cfg)

        natural_no_action_recoveries = sum(
            1 for s in natural_batch if s.hidden_outcomes.no_action.recovered
        )
        non_resp_no_action_recoveries = sum(
            1 for s in non_resp_batch if s.hidden_outcomes.no_action.recovered
        )

        natural_rate = natural_no_action_recoveries / 1000.0
        non_resp_rate = non_resp_no_action_recoveries / 1000.0

        # Natural recoverers should have high recovery rate (> 0.20), non-responsive should be low (< 0.10)
        assert natural_rate > non_resp_rate
        assert natural_rate >= 0.20
        assert non_resp_rate <= 0.10

    def test_expired_payment_method_hard_failure(self) -> None:
        """Expired payment method must strictly produce 0% recovery for retry_now and retry_later."""
        sim = Simulator()
        cfg = SimulatorConfig(
            seed=777,
            num_scenarios=100,
            failure_class_distribution={FailureClass.EXPIRED_PAYMENT_METHOD: 1.0},
        )
        batch = sim.generate_batch(cfg)

        for s in batch:
            assert s.failure_class == FailureClass.EXPIRED_PAYMENT_METHOD
            assert s.hidden_outcomes.retry_now.recovered is False
            assert s.hidden_outcomes.retry_now.recovered_amount_paise == 0
            assert s.hidden_outcomes.retry_later.recovered is False
            assert s.hidden_outcomes.retry_later.recovered_amount_paise == 0


class TestSimulatorIngestionIntegration:
    """Verify synthetic entities integrate seamlessly into the Phase 2 ingestion engine."""

    def test_feed_synthetic_webhook_to_ingestion_service(self) -> None:
        """Simulated WebhookPayloads must be completely valid and accepted by IngestionService."""
        async def _run() -> None:
            sim = Simulator()
            scenarios = sim.generate_batch(SimulatorConfig(seed=333, num_scenarios=5))

            event_store = InMemoryEventStore()
            idempotency_tracker = InMemoryIdempotencyTracker()
            reconciler = StateReconciler()
            service = IngestionService(
                event_store=event_store,
                idempotency_tracker=idempotency_tracker,
                reconciler=reconciler,
            )

            for scenario in scenarios:
                result = await service.process_webhook(scenario.webhook_payload)
                assert result.status == "ok"
                assert result.is_duplicate is False
                assert result.reconciled_state == "failed"
                assert result.entity_id == scenario.event.payment.id

                # Verify aggregate exists in event store
                agg = await event_store.get_payment_aggregate(scenario.event.payment.id)
                assert agg is not None
                assert agg.payment_id == scenario.event.payment.id
                assert agg.amount == scenario.event.payment.amount
                assert agg.current_state.value == "failed"

        asyncio.run(_run())
