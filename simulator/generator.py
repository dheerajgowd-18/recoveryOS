"""Main orchestrator for generating reproducible synthetic revenue-recovery evaluation environments."""
import random
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from domain.events import PaymentEvent, WebhookPayload
from simulator.config import CustomerArchetype, FailureClass, ScenarioConfig, SimulatorConfig
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.outcomes import PotentialOutcomeEngine, PotentialOutcomes


class SimulatedScenario(BaseModel):
    """Encapsulates a generated scenario with distinct public events and secret counterfactual ground truths."""
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., description="Unique scenario identifier")
    customer: SimulatedCustomer = Field(..., description="Simulated customer profile")
    event: PaymentEvent = Field(..., description="Public domain event ready for agent ingestion")
    webhook_payload: WebhookPayload = Field(..., description="Public raw Razorpay webhook payload")
    archetype: CustomerArchetype = Field(..., description="Ground-truth behavioral profile")
    failure_class: FailureClass = Field(..., description="Ground-truth root failure cause")
    hidden_outcomes: PotentialOutcomes = Field(
        ..., description="Secret counterfactual potential outcome vector Y(a) hidden from the agent"
    )


class Simulator:
    """Deterministic, seeded synthetic environment generator."""

    def __init__(self, config: Optional[SimulatorConfig] = None) -> None:
        self.config = config or SimulatorConfig()
        self.entity_generator = SyntheticEntityGenerator()
        self.outcome_engine = PotentialOutcomeEngine()

    def generate_batch(self, config: Optional[SimulatorConfig] = None) -> List[SimulatedScenario]:
        """Generate a reproducible batch of simulated recovery scenarios.

        Guarantees:
        1. Fully deterministic: Same seed + same config produces bit-identical outputs.
        2. Isolated random state: Local `random.Random(seed)` prevents global PRNG side-effects.
        3. Strict boundary separation: Hidden potential outcomes are isolated for offline scoring.
        """
        cfg = config or self.config
        rng = random.Random(cfg.seed)

        archetypes = list(cfg.archetype_distribution.keys())
        archetype_weights = [cfg.archetype_distribution[a] for a in archetypes]

        failures = list(cfg.failure_class_distribution.keys())
        failure_weights = [cfg.failure_class_distribution[f] for f in failures]

        scenarios: List[SimulatedScenario] = []
        base_epoch = 1700000000

        for idx in range(1, cfg.num_scenarios + 1):
            scenario_id = f"scen_{idx:05d}"

            # Sample archetype and failure class according to weights
            archetype = rng.choices(archetypes, weights=archetype_weights, k=1)[0]
            failure_class = rng.choices(failures, weights=failure_weights, k=1)[0]

            # Sample amount
            amount_paise = rng.randint(cfg.amount_min_paise, cfg.amount_max_paise)
            # Round amount to nearest rupee paise (multiples of 100)
            amount_paise = (amount_paise // 100) * 100

            scenario_cfg = ScenarioConfig(
                scenario_id=scenario_id,
                seed=cfg.seed + idx,
                archetype=archetype,
                failure_class=failure_class,
                amount_in_paise=amount_paise,
                attempt_count=1,
                currency=cfg.currency,
                merchant_account_id=cfg.merchant_account_id,
            )

            # Generate synthetic customer
            customer_id = f"cust_sim_{idx:05d}"
            customer = self.entity_generator.generate_customer(rng, customer_id, archetype)

            # Generate public domain event & webhook payload
            epoch_time = base_epoch + (idx * 3600)
            payment_event, webhook_payload = self.entity_generator.generate_payment_scenario(
                rng=rng,
                scenario=scenario_cfg,
                customer=customer,
                created_at_epoch=epoch_time,
            )

            # Compute secret potential outcomes
            hidden_outcomes = self.outcome_engine.compute_outcomes(rng, scenario_cfg)

            scenarios.append(
                SimulatedScenario(
                    scenario_id=scenario_id,
                    customer=customer,
                    event=payment_event,
                    webhook_payload=webhook_payload,
                    archetype=archetype,
                    failure_class=failure_class,
                    hidden_outcomes=hidden_outcomes,
                )
            )

        return scenarios
