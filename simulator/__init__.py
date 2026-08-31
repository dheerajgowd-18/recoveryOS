"""Synthetic revenue-recovery evaluation environment (Simulator v1)."""
from simulator.archetypes import (
    ARCHETYPE_PROFILES,
    FAILURE_CLASS_BEHAVIORS,
    ArchetypeBehavior,
    FailureClassBehavior,
)
from simulator.config import (
    CustomerArchetype,
    FailureClass,
    ScenarioConfig,
    SimulatedActionType,
    SimulatorConfig,
)
from simulator.entities import SimulatedCustomer, SyntheticEntityGenerator
from simulator.generator import SimulatedScenario, Simulator
from simulator.outcomes import ActionOutcome, PotentialOutcomeEngine, PotentialOutcomes

__all__ = [
    "Simulator",
    "SimulatedScenario",
    "SimulatorConfig",
    "ScenarioConfig",
    "CustomerArchetype",
    "FailureClass",
    "SimulatedActionType",
    "SimulatedCustomer",
    "SyntheticEntityGenerator",
    "ActionOutcome",
    "PotentialOutcomes",
    "PotentialOutcomeEngine",
    "ARCHETYPE_PROFILES",
    "FAILURE_CLASS_BEHAVIORS",
    "ArchetypeBehavior",
    "FailureClassBehavior",
]
