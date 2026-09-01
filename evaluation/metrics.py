"""Strict Pydantic v2 metrics models and calculation engine for RecoveryOS evaluations."""
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import SimulatedActionType
from simulator.outcomes import ActionOutcome

DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER = 250_000  # Rs 2,500 per churned customer proxy


class ScenarioEvaluationRecord(BaseModel):
    """Detailed evaluation trace for a single scenario under a given policy."""
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., description="Evaluated scenario identifier")
    policy_name: str = Field(..., description="Name of the evaluating policy")
    chosen_action: SimulatedActionType = Field(..., description="Action selected by the policy")
    is_intervention: bool = Field(..., description="Whether chosen action is an active intervention (not NO_ACTION)")
    is_abstention: bool = Field(default=False, description="Whether chosen action was NO_ACTION")
    is_low_confidence_abstention: bool = Field(default=False, description="Whether abstention was due to low diagnosis confidence")
    is_negative_uplift_abstention: bool = Field(default=False, description="Whether abstention was due to negative expected uplift")
    predicted_diagnosis: Optional[str] = Field(default=None, description="Inferred diagnosis label")
    diagnosis_confidence: Optional[float] = Field(default=None, description="Inferred diagnosis confidence score")
    diagnosis_source: Optional[str] = Field(default=None, description="Diagnosis provider source")
    diagnosis_correct: Optional[bool] = Field(default=None, description="Evaluator-side comparison against hidden failure class")
    recovered: bool = Field(..., description="Whether revenue was captured by the chosen action")
    recovered_amount_paise: int = Field(..., ge=0, description="Amount captured in paise under chosen action")
    action_cost_paise: int = Field(..., ge=0, description="Cost incurred to execute chosen action in paise")
    net_value_paise: int = Field(..., description="Net recovered amount (recovered amount - action cost)")
    recovery_delay_seconds: int = Field(..., ge=0, description="Time delay until recovery realization")
    customer_churned: bool = Field(..., description="Whether customer churned under chosen action")
    fatigue_score: float = Field(..., ge=0.0, le=1.0, description="Customer fatigue score under chosen action")
    natural_recovered: bool = Field(..., description="Whether revenue would naturally recover under NO_ACTION")
    natural_recovered_amount_paise: int = Field(..., ge=0, description="Amount naturally recovered under NO_ACTION")
    natural_customer_churned: bool = Field(default=False, description="Whether customer naturally churned under NO_ACTION")
    incremental_amount_paise: int = Field(..., description="Incremental recovered amount over natural recovery")


class EvaluationMetrics(BaseModel):
    """Aggregated financial, churn-adjusted, intelligence, and operational performance metrics for a policy over a batch."""
    model_config = ConfigDict(extra="forbid")

    policy_name: str = Field(..., description="Name of the evaluated policy")
    total_scenarios: int = Field(..., ge=0, description="Total number of evaluated scenarios")
    total_interventions: int = Field(..., ge=0, description="Count of active interventions (non-NO_ACTION decisions)")
    intervention_count: int = Field(..., ge=0, description="Count of active interventions")
    total_abstentions: int = Field(..., ge=0, description="Count of abstentions (NO_ACTION decisions)")
    abstention_count: int = Field(..., ge=0, description="Count of abstentions")
    actions_avoided_count: int = Field(..., ge=0, description="Count of actions avoided / abstained")
    low_confidence_abstention_count: int = Field(default=0, ge=0, description="Count of abstentions triggered by low diagnosis confidence")
    negative_uplift_abstention_count: int = Field(default=0, ge=0, description="Count of abstentions triggered by negative expected uplift")
    diagnosis_accuracy: float = Field(default=1.0, ge=0.0, le=1.0, description="Diagnosis accuracy compared to hidden true root cause")
    diagnosis_source_counts: Dict[str, int] = Field(default_factory=dict, description="Count of diagnoses by provider source")
    deterministic_fallback_count: int = Field(default=0, ge=0, description="Count of LLM fallbacks to deterministic provider")
    invalid_llm_output_count: int = Field(default=0, ge=0, description="Count of malformed or invalid LLM responses")
    intervention_rate: float = Field(..., ge=0.0, le=1.0, description="Fraction of scenarios where an intervention was triggered")
    gross_recovered_amount_paise: int = Field(..., ge=0, description="Total recovered revenue in paise under policy actions")
    natural_recovered_amount_paise: int = Field(..., ge=0, description="Baseline revenue in paise recovered without any action")
    incremental_recovered_amount_paise: int = Field(..., description="Incremental revenue gained over natural baseline (Gross - Natural)")
    total_action_cost_paise: int = Field(..., ge=0, description="Total cost of executing chosen policy interventions in paise")
    net_recovered_amount_paise: int = Field(..., description="Net recovery after subtracting execution costs (Gross - Total Cost)")
    net_recovery_after_action_cost_paise: int = Field(..., description="Net recovery after subtracting execution costs")
    total_churned_customers: int = Field(..., ge=0, description="Number of customers who churned under policy actions")
    churn_penalty_paise: int = Field(default=0, ge=0, description="Total financial penalty assigned to customer churn")
    adjusted_net_recovery_paise: int = Field(default=0, description="Net recovery after subtracting action costs and churn penalty")
    incremental_adjusted_net_recovery_paise: int = Field(default=0, description="Incremental adjusted net recovery over baseline NO_ACTION")
    recovery_rate: float = Field(..., ge=0.0, le=1.0, description="Fraction of scenarios successfully recovered by policy")
    natural_recovery_rate: float = Field(..., ge=0.0, le=1.0, description="Fraction of scenarios naturally recovered by baseline NO_ACTION")
    incremental_recovery_rate: float = Field(..., ge=-1.0, le=1.0, description="Incremental recovery rate over natural baseline")
    churn_rate: float = Field(..., ge=0.0, le=1.0, description="Fraction of customers who churned")
    average_fatigue_score: float = Field(..., ge=0.0, le=1.0, description="Mean contact fatigue score across scenarios")
    average_recovery_delay_seconds: float = Field(..., ge=0.0, description="Mean realization delay in seconds for recovered scenarios")


class MetricCalculator:
    """Computes comprehensive evaluation metrics from individual scenario records."""

    @staticmethod
    def create_record(
        scenario_id: str,
        policy_name: str,
        chosen_action: SimulatedActionType,
        chosen_outcome: ActionOutcome,
        natural_outcome: ActionOutcome,
        predicted_diagnosis: Optional[str] = None,
        diagnosis_confidence: Optional[float] = None,
        diagnosis_source: Optional[str] = None,
        diagnosis_correct: Optional[bool] = None,
        is_low_confidence_abstention: bool = False,
        is_negative_uplift_abstention: bool = False,
    ) -> ScenarioEvaluationRecord:
        """Construct a single scenario evaluation record from chosen and baseline counterfactuals."""
        is_intervention = chosen_action != SimulatedActionType.NO_ACTION
        is_abstention = not is_intervention
        recovered_amount = chosen_outcome.recovered_amount_paise if chosen_outcome.recovered else 0
        natural_recovered_amount = natural_outcome.recovered_amount_paise if natural_outcome.recovered else 0
        net_value = recovered_amount - chosen_outcome.action_cost_paise
        incremental_amount = recovered_amount - natural_recovered_amount

        return ScenarioEvaluationRecord(
            scenario_id=scenario_id,
            policy_name=policy_name,
            chosen_action=chosen_action,
            is_intervention=is_intervention,
            is_abstention=is_abstention,
            is_low_confidence_abstention=is_low_confidence_abstention,
            is_negative_uplift_abstention=is_negative_uplift_abstention,
            predicted_diagnosis=predicted_diagnosis,
            diagnosis_confidence=diagnosis_confidence,
            diagnosis_source=diagnosis_source,
            diagnosis_correct=diagnosis_correct,
            recovered=chosen_outcome.recovered,
            recovered_amount_paise=recovered_amount,
            action_cost_paise=chosen_outcome.action_cost_paise,
            net_value_paise=net_value,
            recovery_delay_seconds=chosen_outcome.recovery_delay_seconds,
            customer_churned=chosen_outcome.customer_churned,
            fatigue_score=chosen_outcome.fatigue_score,
            natural_recovered=natural_outcome.recovered,
            natural_recovered_amount_paise=natural_recovered_amount,
            natural_customer_churned=natural_outcome.customer_churned,
            incremental_amount_paise=incremental_amount,
        )

    @classmethod
    def compute_metrics(
        cls,
        policy_name: str,
        records: List[ScenarioEvaluationRecord],
        churn_penalty_paise_per_customer: int = DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER,
        deterministic_fallback_count: int = 0,
        invalid_llm_output_count: int = 0,
    ) -> EvaluationMetrics:
        """Aggregate individual scenario records into a complete EvaluationMetrics model."""
        total_scenarios = len(records)
        if total_scenarios == 0:
            return EvaluationMetrics(
                policy_name=policy_name,
                total_scenarios=0,
                total_interventions=0,
                intervention_count=0,
                total_abstentions=0,
                abstention_count=0,
                actions_avoided_count=0,
                low_confidence_abstention_count=0,
                negative_uplift_abstention_count=0,
                diagnosis_accuracy=1.0,
                diagnosis_source_counts={},
                deterministic_fallback_count=0,
                invalid_llm_output_count=0,
                intervention_rate=0.0,
                gross_recovered_amount_paise=0,
                natural_recovered_amount_paise=0,
                incremental_recovered_amount_paise=0,
                total_action_cost_paise=0,
                net_recovered_amount_paise=0,
                net_recovery_after_action_cost_paise=0,
                total_churned_customers=0,
                churn_penalty_paise=0,
                adjusted_net_recovery_paise=0,
                incremental_adjusted_net_recovery_paise=0,
                recovery_rate=0.0,
                natural_recovery_rate=0.0,
                incremental_recovery_rate=0.0,
                churn_rate=0.0,
                average_fatigue_score=0.0,
                average_recovery_delay_seconds=0.0,
            )

        total_interventions = sum(1 for r in records if r.is_intervention)
        total_abstentions = total_scenarios - total_interventions
        low_conf_abstentions = sum(1 for r in records if r.is_low_confidence_abstention)
        neg_uplift_abstentions = sum(1 for r in records if r.is_negative_uplift_abstention)

        gross_recovered = sum(r.recovered_amount_paise for r in records)
        natural_recovered = sum(r.natural_recovered_amount_paise for r in records)
        incremental_recovered = gross_recovered - natural_recovered
        total_action_cost = sum(r.action_cost_paise for r in records)
        net_recovered = gross_recovered - total_action_cost

        recovered_count = sum(1 for r in records if r.recovered)
        natural_recovered_count = sum(1 for r in records if r.natural_recovered)
        churned_count = sum(1 for r in records if r.customer_churned)
        churn_penalty = churned_count * churn_penalty_paise_per_customer
        adjusted_net_recovery = net_recovered - churn_penalty

        # Natural baseline adjusted net recovery
        natural_churned_count = sum(1 for r in records if r.natural_customer_churned)
        natural_churn_penalty = natural_churned_count * churn_penalty_paise_per_customer
        natural_adjusted_net_recovery = natural_recovered - natural_churn_penalty
        incremental_adjusted_net_recovery = adjusted_net_recovery - natural_adjusted_net_recovery

        recovery_rate = recovered_count / total_scenarios
        natural_recovery_rate = natural_recovered_count / total_scenarios
        incremental_recovery_rate = recovery_rate - natural_recovery_rate
        intervention_rate = total_interventions / total_scenarios
        churn_rate = churned_count / total_scenarios
        avg_fatigue = sum(r.fatigue_score for r in records) / total_scenarios

        recovered_delays = [r.recovery_delay_seconds for r in records if r.recovered]
        avg_delay = (sum(recovered_delays) / len(recovered_delays)) if recovered_delays else 0.0

        # Diagnosis accuracy
        records_with_eval = [r for r in records if r.diagnosis_correct is not None]
        if records_with_eval:
            diag_acc = sum(1 for r in records_with_eval if r.diagnosis_correct) / len(records_with_eval)
        else:
            diag_acc = 1.0

        source_counts: Dict[str, int] = {}
        for r in records:
            if r.diagnosis_source:
                source_counts[r.diagnosis_source] = source_counts.get(r.diagnosis_source, 0) + 1

        return EvaluationMetrics(
            policy_name=policy_name,
            total_scenarios=total_scenarios,
            total_interventions=total_interventions,
            intervention_count=total_interventions,
            total_abstentions=total_abstentions,
            abstention_count=total_abstentions,
            actions_avoided_count=total_abstentions,
            low_confidence_abstention_count=low_conf_abstentions,
            negative_uplift_abstention_count=neg_uplift_abstentions,
            diagnosis_accuracy=round(diag_acc, 4),
            diagnosis_source_counts=source_counts,
            deterministic_fallback_count=deterministic_fallback_count,
            invalid_llm_output_count=invalid_llm_output_count,
            intervention_rate=round(intervention_rate, 4),
            gross_recovered_amount_paise=gross_recovered,
            natural_recovered_amount_paise=natural_recovered,
            incremental_recovered_amount_paise=incremental_recovered,
            total_action_cost_paise=total_action_cost,
            net_recovered_amount_paise=net_recovered,
            net_recovery_after_action_cost_paise=net_recovered,
            total_churned_customers=churned_count,
            churn_penalty_paise=churn_penalty,
            adjusted_net_recovery_paise=adjusted_net_recovery,
            incremental_adjusted_net_recovery_paise=incremental_adjusted_net_recovery,
            recovery_rate=round(recovery_rate, 4),
            natural_recovery_rate=round(natural_recovery_rate, 4),
            incremental_recovery_rate=round(incremental_recovery_rate, 4),
            churn_rate=round(churn_rate, 4),
            average_fatigue_score=round(avg_fatigue, 4),
            average_recovery_delay_seconds=round(avg_delay, 2),
        )
