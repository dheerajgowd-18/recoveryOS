"""Evaluation harness orchestrator executing policies against synthetic scenarios and computing ground-truth metrics."""
from typing import Dict, List
from pydantic import BaseModel, ConfigDict, Field

from evaluation.metrics import EvaluationMetrics, MetricCalculator, ScenarioEvaluationRecord
from evaluation.policies import BasePolicy
from simulator.config import SimulatedActionType
from simulator.generator import SimulatedScenario


class EvaluationResult(BaseModel):
    """Encapsulates the complete evaluation outcome of a policy against a batch of scenarios."""
    model_config = ConfigDict(extra="forbid")

    policy_name: str = Field(..., description="Name of the evaluated policy")
    metrics: EvaluationMetrics = Field(..., description="Aggregated benchmark metrics")
    records: List[ScenarioEvaluationRecord] = Field(..., description="Detailed per-scenario traces")


class EvaluationHarness:
    """Batch evaluation harness comparing policy interventions against hidden potential outcomes."""

    def evaluate_policy(self, policy: BasePolicy, scenarios: List[SimulatedScenario]) -> EvaluationResult:
        """Run a policy on a batch of scenarios and evaluate against hidden counterfactuals."""
        records: List[ScenarioEvaluationRecord] = []

        for scenario in scenarios:
            # Policy decision based purely on public domain scenario data
            decision = policy.decide(scenario)

            # Retrieve secret ground truth counterfactuals from hidden_outcomes
            chosen_outcome = scenario.hidden_outcomes.get_outcome(decision.action_type)
            natural_outcome = scenario.hidden_outcomes.get_outcome(SimulatedActionType.NO_ACTION)

            record = MetricCalculator.create_record(
                scenario_id=scenario.scenario_id,
                policy_name=policy.name,
                chosen_action=decision.action_type,
                chosen_outcome=chosen_outcome,
                natural_outcome=natural_outcome,
            )
            records.append(record)

        metrics = MetricCalculator.compute_metrics(policy_name=policy.name, records=records)

        return EvaluationResult(
            policy_name=policy.name,
            metrics=metrics,
            records=records,
        )

    def evaluate_all(
        self,
        policies: List[BasePolicy],
        scenarios: List[SimulatedScenario],
    ) -> Dict[str, EvaluationResult]:
        """Evaluate multiple policies sequentially against the exact same scenario population."""
        results: Dict[str, EvaluationResult] = {}
        for policy in policies:
            results[policy.name] = self.evaluate_policy(policy=policy, scenarios=scenarios)
        return results
