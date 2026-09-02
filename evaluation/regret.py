"""Evaluator-side Decision Regret computation comparing policy choices to the counterfactual Oracle."""
from typing import Dict, List, Optional
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from evaluation.metrics import DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER, ScenarioEvaluationRecord
from simulator.config import SimulatedActionType
from simulator.generator import SimulatedScenario
from simulator.outcomes import ActionOutcome

__all__ = [
    "RegretSummary",
    "RegretCalculator",
]


class RegretSummary(BaseModel):
    """Statistical distribution of decision regret across an evaluated scenario population."""
    model_config = ConfigDict(extra="forbid")

    policy_name: str = Field(..., description="Name of the evaluated policy")
    total_scenarios: int = Field(..., ge=0, description="Total evaluated scenarios")
    mean_regret_paise: float = Field(..., ge=0.0, description="Mean regret in paise per scenario")
    median_regret_paise: float = Field(..., ge=0.0, description="Median regret in paise")
    p95_regret_paise: float = Field(..., ge=0.0, description="95th percentile regret in paise")
    p99_regret_paise: float = Field(..., ge=0.0, description="99th percentile regret in paise")
    max_regret_paise: int = Field(..., ge=0, description="Maximum single-scenario regret in paise")
    total_regret_paise: int = Field(..., ge=0, description="Sum of regret across all scenarios in paise")
    zero_regret_count: int = Field(..., ge=0, description="Count of decisions achieving zero regret vs Oracle")
    zero_regret_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Proportion of decisions with zero regret (identical to Oracle)"
    )
    high_regret_scenario_ids: List[str] = Field(
        default_factory=list, description="Scenario IDs with top 5% regret for failure analysis"
    )


class RegretCalculator:
    """Calculates scenario-level and aggregate regret for any policy using counterfactual potential outcomes."""

    @staticmethod
    def compute_scenario_regret(
        chosen_action: SimulatedActionType,
        scenario: SimulatedScenario,
        churn_penalty_paise: int = DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER,
    ) -> tuple[int, int, int]:
        """Calculates (regret_paise, oracle_incremental_net_paise, chosen_incremental_net_paise) for a single scenario.

        Definitions:
            adjusted_net(a) = recovered_amount(a) - action_cost(a) - churn_penalty(a)
            adjusted_net_no_action = recovered_amount(no_action) - action_cost(no_action) - churn_penalty(no_action)
            incremental_adjusted_net(a) = adjusted_net(a) - adjusted_net_no_action
            oracle_incremental_net = max_{a} incremental_adjusted_net(a)
            chosen_incremental_net = incremental_adjusted_net(chosen_action)
            regret = max(0, oracle_incremental_net - chosen_incremental_net)
        """
        all_actions = [
            SimulatedActionType.NO_ACTION,
            SimulatedActionType.RETRY_NOW,
            SimulatedActionType.RETRY_LATER,
            SimulatedActionType.PAYMENT_LINK,
            SimulatedActionType.REMINDER,
        ]

        natural_outcome: ActionOutcome = scenario.hidden_outcomes.get_outcome(SimulatedActionType.NO_ACTION)
        natural_churn_cost = churn_penalty_paise if natural_outcome.customer_churned else 0
        natural_recovered = natural_outcome.recovered_amount_paise if natural_outcome.recovered else 0
        natural_net_val = natural_recovered - natural_outcome.action_cost_paise - natural_churn_cost

        oracle_incremental_net = float("-inf")
        for action in all_actions:
            outcome: ActionOutcome = scenario.hidden_outcomes.get_outcome(action)
            churn_cost = churn_penalty_paise if outcome.customer_churned else 0
            recovered = outcome.recovered_amount_paise if outcome.recovered else 0
            net_val = recovered - outcome.action_cost_paise - churn_cost
            incr_val = net_val - natural_net_val
            if incr_val > oracle_incremental_net:
                oracle_incremental_net = incr_val

        chosen_outcome: ActionOutcome = scenario.hidden_outcomes.get_outcome(chosen_action)
        chosen_churn_cost = churn_penalty_paise if chosen_outcome.customer_churned else 0
        chosen_recovered = chosen_outcome.recovered_amount_paise if chosen_outcome.recovered else 0
        chosen_net_val = chosen_recovered - chosen_outcome.action_cost_paise - chosen_churn_cost
        chosen_incremental_net = chosen_net_val - natural_net_val

        # Regret is strictly non-negative: Oracle_Incr_Net - Chosen_Incr_Net
        regret = max(0, int(round(oracle_incremental_net - chosen_incremental_net)))
        return regret, int(round(oracle_incremental_net)), int(round(chosen_incremental_net))

    @classmethod
    def compute_regret(
        cls,
        records: List[ScenarioEvaluationRecord],
        scenarios: List[SimulatedScenario],
        churn_penalty_paise: int = DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER,
    ) -> RegretSummary:
        """Computes complete regret distribution statistics across a policy evaluation batch."""
        if not records:
            return RegretSummary(
                policy_name="unknown",
                total_scenarios=0,
                mean_regret_paise=0.0,
                median_regret_paise=0.0,
                p95_regret_paise=0.0,
                p99_regret_paise=0.0,
                max_regret_paise=0,
                total_regret_paise=0,
                zero_regret_count=0,
                zero_regret_rate=1.0,
                high_regret_scenario_ids=[],
            )

        policy_name = records[0].policy_name
        scenario_map: Dict[str, SimulatedScenario] = {s.scenario_id: s for s in scenarios}

        regrets: List[int] = []
        regret_pairs: List[tuple[str, int]] = []

        for record in records:
            scenario = scenario_map.get(record.scenario_id)
            if not scenario:
                continue
            regret, _, _ = cls.compute_scenario_regret(
                chosen_action=record.chosen_action,
                scenario=scenario,
                churn_penalty_paise=churn_penalty_paise,
            )
            regrets.append(regret)
            regret_pairs.append((record.scenario_id, regret))

        if not regrets:
            return RegretSummary(
                policy_name=policy_name,
                total_scenarios=0,
                mean_regret_paise=0.0,
                median_regret_paise=0.0,
                p95_regret_paise=0.0,
                p99_regret_paise=0.0,
                max_regret_paise=0,
                total_regret_paise=0,
                zero_regret_count=0,
                zero_regret_rate=1.0,
                high_regret_scenario_ids=[],
            )

        return cls.compute_from_regrets(
            policy_name=policy_name,
            regret_pairs=regret_pairs,
        )

    @classmethod
    def compute_from_regrets(
        cls,
        policy_name: str,
        regret_pairs: List[tuple[str, int]],
    ) -> RegretSummary:
        """Constructs a RegretSummary given a list of (scenario_id, regret_paise) pairs."""
        if not regret_pairs:
            return RegretSummary(
                policy_name=policy_name,
                total_scenarios=0,
                mean_regret_paise=0.0,
                median_regret_paise=0.0,
                p95_regret_paise=0.0,
                p99_regret_paise=0.0,
                max_regret_paise=0,
                total_regret_paise=0,
                zero_regret_count=0,
                zero_regret_rate=1.0,
                high_regret_scenario_ids=[],
            )

        regrets = [r for _, r in regret_pairs]
        arr = np.array(regrets, dtype=np.float64)
        mean_regret = float(np.mean(arr))
        median_regret = float(np.median(arr))
        p95_regret = float(np.percentile(arr, 95))
        p99_regret = float(np.percentile(arr, 99))
        max_regret = int(np.max(arr))
        total_regret = int(np.sum(arr))
        zero_regret_count = int(np.sum(arr == 0))
        zero_regret_rate = round(zero_regret_count / len(regrets), 4)

        sorted_pairs = sorted(regret_pairs, key=lambda x: x[1], reverse=True)
        top_k = max(1, int(len(regrets) * 0.05))
        high_regret_ids = [scen_id for scen_id, r in sorted_pairs[:top_k] if r > 0]

        return RegretSummary(
            policy_name=policy_name,
            total_scenarios=len(regrets),
            mean_regret_paise=round(mean_regret, 2),
            median_regret_paise=round(median_regret, 2),
            p95_regret_paise=round(p95_regret, 2),
            p99_regret_paise=round(p99_regret, 2),
            max_regret_paise=max_regret,
            total_regret_paise=total_regret,
            zero_regret_count=zero_regret_count,
            zero_regret_rate=zero_regret_rate,
            high_regret_scenario_ids=high_regret_ids,
        )
