"""Public scenario view projection strictly sanitized of private simulator attributes."""
from intelligence.context import ObservableContextBuilder, ObservableRecoveryContext
from simulator.generator import SimulatedScenario


class PublicScenarioView(ObservableRecoveryContext):
    """Sanitized, public view of a recovery scenario safe for policy ingestion.

    Strictly excludes:
    - `failure_class` (Ground-truth root cause - must be inferred via StructuredDiagnosis)
    - `hidden_outcomes` / `potential_outcomes` (Secret counterfactuals)
    - `archetype` / `customer_archetype` (Latent behavioral ground truths)
    - Any internal simulator ground-truth states
    """

    @classmethod
    def from_simulated_scenario(cls, scenario: SimulatedScenario) -> "PublicScenarioView":
        """Extract only public domain event fields, strictly discarding secret simulation attributes."""
        ctx = ObservableContextBuilder.build_from_simulated_scenario(scenario)
        return cls(**ctx.model_dump())
