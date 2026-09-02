"""Evaluator-side Oracle Benchmark for calculating theoretical upper-bound recovery performance."""
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from evaluation.harness import EvaluationHarness, EvaluationResult
from evaluation.metrics import (
    DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER,
    EvaluationMetrics,
    MetricCalculator,
    ScenarioEvaluationRecord,
)
from evaluation.policies import BasePolicy, PolicyDecision
from intelligence.context import ObservableContextBuilder, ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis
from simulator.config import SimulatedActionType
from simulator.generator import SimulatedScenario
from simulator.outcomes import ActionOutcome, PotentialOutcomes

__all__ = [
    "OraclePolicy",
    "OracleComparisonResult",
    "evaluate_oracle",
]


class OracleComparisonResult(BaseModel):
    """Detailed comparison between RecoveryOS and the theoretical Oracle benchmark."""
    model_config = ConfigDict(extra="forbid")

    oracle_gross_recovery_paise: int = Field(..., description="Oracle gross recovered revenue in paise")
    oracle_action_cost_paise: int = Field(..., description="Oracle action costs in paise")
    oracle_churn_penalty_paise: int = Field(..., description="Oracle churn penalty incurred in paise")
    oracle_adjusted_net_recovery_paise: int = Field(..., description="Oracle adjusted net recovery in paise")
    oracle_incremental_adjusted_net_recovery_paise: int = Field(
        ..., description="Oracle incremental adjusted net recovery over natural baseline in paise"
    )
    recoveryos_adjusted_net_recovery_paise: int = Field(..., description="RecoveryOS adjusted net recovery in paise")
    recoveryos_incremental_adjusted_net_recovery_paise: int = Field(
        ..., description="RecoveryOS incremental adjusted net recovery in paise"
    )
    recoveryos_vs_oracle_gap_paise: int = Field(
        ..., description="Incremental economic gap between Oracle and RecoveryOS in paise (Oracle Incr Net - RecoveryOS Incr Net)"
    )
    recoveryos_oracle_efficiency_pct: float = Field(
        ..., description="RecoveryOS incremental adjusted net recovery as a percentage of Oracle potential"
    )
    oracle_intervention_count: int = Field(default=0, ge=0, description="Total interventions chosen by Oracle")
    oracle_actions_avoided_count: int = Field(default=0, ge=0, description="Total abstentions chosen by Oracle")
    oracle_churn_count: int = Field(default=0, ge=0, description="Total churned customers under Oracle")


class OraclePolicy(BasePolicy):
    """Diagnostic ceiling policy that possesses perfect hindsight of hidden counterfactual outcomes Y(a).

    IMPORTANT: The Oracle is NOT a deployable baseline. It represents the mathematical ceiling
    for observable decisioning by selecting the action that maximizes incremental adjusted net recovery:
        a* = argmax_a [ incremental_adjusted_net(a) ]
        where incremental_adjusted_net(a) = adjusted_net(a) - adjusted_net(no_action)
    """

    def __init__(self, churn_penalty_paise: int = DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER) -> None:
        super().__init__(
            name="oracle_counterfactual_ceiling",
            description="Evaluator-side oracle benchmark selecting the optimal action with perfect counterfactual foresight.",
        )
        self.churn_penalty_paise = churn_penalty_paise
        self._current_hidden_outcomes: Optional[PotentialOutcomes] = None

    def set_scenario_hindsight(self, hidden_outcomes: PotentialOutcomes) -> None:
        """Bind secret potential outcomes for evaluator-side hindsight query."""
        self._current_hidden_outcomes = hidden_outcomes

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        """Select action maximizing counterfactual incremental net value over no_action."""
        if not self._current_hidden_outcomes:
            # Fallback if outcomes not explicitly bound
            return PolicyDecision(
                action_type=SimulatedActionType.NO_ACTION,
                confidence=1.0,
                rationale="Oracle fallback: no hindsight provided.",
                policy_name=self.name,
                reason_codes=["ORACLE_NO_HINDSIGHT"],
                diagnosis=diagnosis,
            )

        candidate_actions = [
            SimulatedActionType.NO_ACTION,
            SimulatedActionType.RETRY_NOW,
            SimulatedActionType.RETRY_LATER,
            SimulatedActionType.PAYMENT_LINK,
            SimulatedActionType.REMINDER,
        ]

        natural_outcome = self._current_hidden_outcomes.get_outcome(SimulatedActionType.NO_ACTION)
        natural_churn_cost = self.churn_penalty_paise if natural_outcome.customer_churned else 0
        natural_recovered = natural_outcome.recovered_amount_paise if natural_outcome.recovered else 0
        natural_net_val = natural_recovered - natural_outcome.action_cost_paise - natural_churn_cost

        best_action = SimulatedActionType.NO_ACTION
        best_incr_net_value = float("-inf")
        best_net_value = float("-inf")

        for action in candidate_actions:
            outcome: ActionOutcome = self._current_hidden_outcomes.get_outcome(action)
            churn_cost = self.churn_penalty_paise if outcome.customer_churned else 0
            recovered = outcome.recovered_amount_paise if outcome.recovered else 0
            net_val = recovered - outcome.action_cost_paise - churn_cost
            incr_net_val = net_val - natural_net_val

            # Deterministic tie-breaking favoring lower-friction actions (NO_ACTION first)
            if incr_net_val > best_incr_net_value:
                best_incr_net_value = incr_net_val
                best_net_value = net_val
                best_action = action

        return PolicyDecision(
            action_type=best_action,
            confidence=1.0,
            rationale=f"Oracle hindsight selected optimal action '{best_action.value}' with incremental net value {best_incr_net_value} paise.",
            policy_name=self.name,
            reason_codes=["ORACLE_OPTIMAL_HINDSIGHT"],
            expected_net_value_paise=int(best_net_value),
            expected_incremental_value_paise=int(best_incr_net_value),
            diagnosis=diagnosis,
        )


def evaluate_oracle(
    scenarios: List[SimulatedScenario],
    churn_penalty_paise: int = DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER,
    recoveryos_result: Optional[EvaluationResult] = None,
) -> tuple[EvaluationResult, OracleComparisonResult]:
    """Evaluates the Oracle ceiling policy on a scenario batch and computes the efficiency gap."""
    oracle_policy = OraclePolicy(churn_penalty_paise=churn_penalty_paise)
    records: List[ScenarioEvaluationRecord] = []

    for scenario in scenarios:
        oracle_policy.set_scenario_hindsight(scenario.hidden_outcomes)
        context = ObservableContextBuilder.build_from_simulated_scenario(scenario)
        decision = oracle_policy.decide(context)
        chosen_action = decision.action_type
        chosen_outcome = scenario.hidden_outcomes.get_outcome(chosen_action)
        natural_outcome = scenario.hidden_outcomes.get_outcome(SimulatedActionType.NO_ACTION)

        is_sched = chosen_action in (SimulatedActionType.RETRY_LATER, SimulatedActionType.REMINDER)
        is_immed = chosen_action in (SimulatedActionType.RETRY_NOW, SimulatedActionType.PAYMENT_LINK)

        record = MetricCalculator.create_record(
            scenario_id=scenario.scenario_id,
            policy_name=oracle_policy.name,
            chosen_action=chosen_action,
            chosen_outcome=chosen_outcome,
            natural_outcome=natural_outcome,
            timing_window="IMMEDIATE" if is_immed else ("PLUS_6H" if is_sched else None),
            delay_seconds=0 if is_immed else (21600 if is_sched else 0),
            is_scheduled=is_sched,
            is_immediate=is_immed,
            predicted_diagnosis="oracle_hindsight",
            diagnosis_confidence=1.0,
            diagnosis_source="oracle_hindsight",
            diagnosis_correct=True,
            governor_decision="ALLOW",
            governor_reason_codes=["ORACLE_ALLOW"],
        )
        records.append(record)

    oracle_metrics = MetricCalculator.compute_metrics(
        policy_name=oracle_policy.name,
        records=records,
        churn_penalty_paise_per_customer=churn_penalty_paise,
    )
    oracle_result = EvaluationResult(
        policy_name=oracle_policy.name,
        metrics=oracle_metrics,
        records=records,
    )

    # Compute comparison against RecoveryOS on incremental adjusted net recovery
    rec_adj_net = recoveryos_result.metrics.adjusted_net_recovery_paise if recoveryos_result else 0
    rec_incr_adj = recoveryos_result.metrics.incremental_adjusted_net_recovery_paise if recoveryos_result else 0
    oracle_incr_adj = oracle_metrics.incremental_adjusted_net_recovery_paise
    gap = max(0, oracle_incr_adj - rec_incr_adj)

    if oracle_incr_adj > 0:
        efficiency = round(
            (rec_incr_adj / oracle_incr_adj) * 100.0, 2
        )
    else:
        efficiency = 100.0 if rec_incr_adj >= 0 else 0.0

    comparison = OracleComparisonResult(
        oracle_gross_recovery_paise=oracle_metrics.gross_recovered_amount_paise,
        oracle_action_cost_paise=oracle_metrics.total_action_cost_paise,
        oracle_churn_penalty_paise=oracle_metrics.churn_penalty_paise,
        oracle_adjusted_net_recovery_paise=oracle_metrics.adjusted_net_recovery_paise,
        oracle_incremental_adjusted_net_recovery_paise=oracle_incr_adj,
        recoveryos_adjusted_net_recovery_paise=rec_adj_net,
        recoveryos_incremental_adjusted_net_recovery_paise=rec_incr_adj,
        recoveryos_vs_oracle_gap_paise=gap,
        recoveryos_oracle_efficiency_pct=efficiency,
        oracle_intervention_count=oracle_metrics.intervention_count,
        oracle_actions_avoided_count=oracle_metrics.actions_avoided_count,
        oracle_churn_count=oracle_metrics.total_churned_customers,
    )

    return oracle_result, comparison
