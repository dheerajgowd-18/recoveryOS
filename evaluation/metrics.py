"""Evaluation metric calculation and benchmark reporting for RecoveryOS."""
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import SimulatedActionType
from simulator.outcomes import ActionOutcome

DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER = 250_000  # ₹2,500 per churned customer


class ScenarioEvaluationRecord(BaseModel):
    """Detailed trace of an individual scenario evaluation against potential outcomes."""
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., description="Unique scenario identifier")
    policy_name: str = Field(..., description="Name of the evaluating policy")
    chosen_action: SimulatedActionType = Field(..., description="Action selected by policy / Governor")
    is_intervention: bool = Field(..., description="Whether chosen action is an active intervention (not NO_ACTION)")
    is_abstention: bool = Field(..., description="Whether chosen action is NO_ACTION")
    recovered: bool = Field(..., description="Whether revenue was captured under chosen action")
    recovered_amount_paise: int = Field(default=0, ge=0, description="Amount recovered in paise")
    action_cost_paise: int = Field(default=0, ge=0, description="Direct cost of chosen action in paise")
    net_value_paise: int = Field(..., description="Net recovered value in paise (Recovered - Cost)")
    recovery_delay_seconds: int = Field(default=0, ge=0, description="Delay until recovery in seconds")
    customer_churned: bool = Field(..., description="Whether customer churned under chosen action")
    fatigue_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Customer contact fatigue score")
    natural_recovered: bool = Field(..., description="Whether recovery would have occurred organically without action")
    natural_recovered_amount_paise: int = Field(default=0, ge=0, description="Natural organic recovery amount in paise")
    natural_customer_churned: bool = Field(..., description="Whether customer churns under no intervention")
    incremental_amount_paise: int = Field(..., description="Causal revenue caused by intervention (Recovered - Natural)")
    predicted_diagnosis: Optional[str] = Field(default=None, description="Inferred diagnosis label")
    diagnosis_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Diagnosis confidence")
    diagnosis_source: Optional[str] = Field(default=None, description="Provider source (e.g. deterministic_offline, llm)")
    diagnosis_correct: Optional[bool] = Field(default=None, description="Whether predicted diagnosis matched hidden ground truth")
    is_low_confidence_abstention: bool = Field(default=False, description="Whether policy abstained due to low confidence")
    is_negative_uplift_abstention: bool = Field(default=False, description="Whether policy abstained due to negative uplift")
    governor_decision: Optional[str] = Field(default=None, description="Governor decision result: ALLOW, DENY, DEFER, ESCALATE, ABSTAIN")
    governor_reason_codes: List[str] = Field(default_factory=list, description="Governor check reason codes")
    is_human_review: bool = Field(default=False, description="Whether Governor escalated to human review")
    is_policy_blocked: bool = Field(default=False, description="Whether action was blocked by merchant policy")
    is_consent_blocked: bool = Field(default=False, description="Whether action was blocked due to consent opt-out")
    is_retry_limit_blocked: bool = Field(default=False, description="Whether action was blocked due to retry limit")
    is_contact_limit_blocked: bool = Field(default=False, description="Whether action was blocked due to contact limit")


class EvaluationMetrics(BaseModel):
    """Aggregated benchmark evaluation metrics comparing recovery economics across policies."""
    model_config = ConfigDict(extra="forbid")

    policy_name: str = Field(..., description="Name of the evaluated policy")
    total_scenarios: int = Field(..., ge=0, description="Total number of evaluated scenarios")
    total_interventions: int = Field(..., ge=0, description="Total active interventions executed")
    intervention_rate: float = Field(..., ge=0.0, le=1.0, description="Proportion of scenarios receiving active intervention")
    intervention_count: int = Field(default=0, ge=0, description="Count of active interventions triggered")
    abstention_count: int = Field(default=0, ge=0, description="Count of scenarios where policy abstained")
    actions_avoided_count: int = Field(default=0, ge=0, description="Count of actions safely avoided")
    gross_recovered_amount_paise: int = Field(..., ge=0, description="Total gross revenue recovered in paise")
    natural_recovered_amount_paise: int = Field(..., ge=0, description="Total organic recovery without intervention in paise")
    incremental_recovered_amount_paise: int = Field(..., description="Causal incremental revenue in paise (Gross - Natural)")
    incremental_recovery_rate: float = Field(default=0.0, description="Incremental recovery rate as fraction of total volume")
    total_action_cost_paise: int = Field(..., ge=0, description="Total direct execution and messaging costs in paise")
    net_recovered_amount_paise: int = Field(..., description="Net recovered revenue in paise (Gross - Cost)")
    incremental_net_recovery_paise: int = Field(..., description="Incremental net value in paise (Net - Natural Net)")
    total_churned_customers: int = Field(..., ge=0, description="Total customers who churned under policy actions")
    churn_rate: float = Field(..., ge=0.0, le=1.0, description="Proportion of customer cohort churned")
    churn_penalty_paise: int = Field(default=0, ge=0, description="Total economic penalty assigned for customer churn")
    adjusted_net_recovery_paise: int = Field(default=0, description="Adjusted Net Recovery (Net Recovered - Churn Penalty)")
    incremental_adjusted_net_recovery_paise: int = Field(default=0, description="North-star benchmark metric: Incremental Adjusted Net vs Baseline 0")
    recovery_rate: float = Field(..., ge=0.0, le=1.0, description="Proportion of failed payments successfully recovered")
    average_recovery_delay_seconds: float = Field(..., ge=0.0, description="Mean time to recovery in seconds")
    average_customer_fatigue: float = Field(..., ge=0.0, le=1.0, description="Mean customer contact fatigue score")
    diagnosis_accuracy: float = Field(default=0.0, ge=0.0, le=1.0, description="Proportion of diagnoses correctly identifying true failure class")
    diagnosis_source_counts: Dict[str, int] = Field(default_factory=dict, description="Counts of diagnoses by provider source")
    deterministic_fallback_count: int = Field(default=0, ge=0, description="Count of fallback invocations to offline rules")
    invalid_llm_output_count: int = Field(default=0, ge=0, description="Count of malformed LLM responses rejected")
    low_confidence_abstention_count: int = Field(default=0, ge=0, description="Count of abstentions driven by low confidence")
    negative_uplift_abstention_count: int = Field(default=0, ge=0, description="Count of abstentions driven by negative expected uplift")
    governor_allow_count: int = Field(default=0, ge=0, description="Count of actions approved by Recovery Governor")
    governor_deny_count: int = Field(default=0, ge=0, description="Count of actions denied by Recovery Governor")
    governor_abstain_count: int = Field(default=0, ge=0, description="Count of abstentions confirmed by Recovery Governor")
    governor_defer_count: int = Field(default=0, ge=0, description="Count of actions deferred by Recovery Governor")
    human_review_count: int = Field(default=0, ge=0, description="Count of cases escalated to human review")
    policy_block_count: int = Field(default=0, ge=0, description="Count of actions blocked by merchant policy")
    consent_block_count: int = Field(default=0, ge=0, description="Count of actions blocked by customer opt-out")
    retry_limit_block_count: int = Field(default=0, ge=0, description="Count of retries blocked by retry limit")
    contact_limit_block_count: int = Field(default=0, ge=0, description="Count of communications blocked by contact limit")
    low_confidence_block_count: int = Field(default=0, ge=0, description="Count of actions blocked due to low confidence")
    low_value_abstention_count: int = Field(default=0, ge=0, description="Count of abstentions due to low expected value")


class MetricCalculator:
    """Computes comprehensive individual and aggregated evaluation metrics."""

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
        governor_decision: Optional[str] = None,
        governor_reason_codes: Optional[List[str]] = None,
    ) -> ScenarioEvaluationRecord:
        """Construct a ScenarioEvaluationRecord from simulated outcomes and governance metadata."""
        is_intervention = chosen_action != SimulatedActionType.NO_ACTION
        is_abstention = chosen_action == SimulatedActionType.NO_ACTION
        recovered_amount = chosen_outcome.recovered_amount_paise if chosen_outcome.recovered else 0
        natural_amount = natural_outcome.recovered_amount_paise if natural_outcome.recovered else 0
        net_val = recovered_amount - chosen_outcome.action_cost_paise
        incr_val = recovered_amount - natural_amount

        reason_codes = governor_reason_codes or []
        is_human = governor_decision == "ESCALATE" or "HUMAN_REVIEW_REQUIRED" in reason_codes
        is_policy = "ACTION_NOT_ALLOWED_BY_POLICY" in reason_codes
        is_consent = "CUSTOMER_OPTED_OUT" in reason_codes or "CONSENT_INVALID" in reason_codes
        is_retry_limit = "RETRY_LIMIT_REACHED" in reason_codes
        is_contact_limit = "CONTACT_LIMIT_REACHED" in reason_codes

        return ScenarioEvaluationRecord(
            scenario_id=scenario_id,
            policy_name=policy_name,
            chosen_action=chosen_action,
            is_intervention=is_intervention,
            is_abstention=is_abstention,
            recovered=chosen_outcome.recovered,
            recovered_amount_paise=recovered_amount,
            action_cost_paise=chosen_outcome.action_cost_paise,
            net_value_paise=net_val,
            recovery_delay_seconds=chosen_outcome.recovery_delay_seconds,
            customer_churned=chosen_outcome.customer_churned,
            fatigue_score=chosen_outcome.fatigue_score,
            natural_recovered=natural_outcome.recovered,
            natural_recovered_amount_paise=natural_amount,
            natural_customer_churned=natural_outcome.customer_churned,
            incremental_amount_paise=incr_val,
            predicted_diagnosis=predicted_diagnosis,
            diagnosis_confidence=diagnosis_confidence,
            diagnosis_source=diagnosis_source,
            diagnosis_correct=diagnosis_correct,
            is_low_confidence_abstention=is_low_confidence_abstention,
            is_negative_uplift_abstention=is_negative_uplift_abstention,
            governor_decision=governor_decision,
            governor_reason_codes=reason_codes,
            is_human_review=is_human,
            is_policy_blocked=is_policy,
            is_consent_blocked=is_consent,
            is_retry_limit_blocked=is_retry_limit,
            is_contact_limit_blocked=is_contact_limit,
        )

    @staticmethod
    def compute_metrics(
        policy_name: str,
        records: List[ScenarioEvaluationRecord],
        churn_penalty_paise_per_customer: int = DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER,
        deterministic_fallback_count: int = 0,
        invalid_llm_output_count: int = 0,
    ) -> EvaluationMetrics:
        """Compute aggregated benchmark metrics from a series of per-scenario evaluation records."""
        total_scenarios = len(records)
        if total_scenarios == 0:
            return EvaluationMetrics(
                policy_name=policy_name,
                total_scenarios=0,
                total_interventions=0,
                intervention_rate=0.0,
                intervention_count=0,
                abstention_count=0,
                actions_avoided_count=0,
                gross_recovered_amount_paise=0,
                natural_recovered_amount_paise=0,
                incremental_recovered_amount_paise=0,
                total_action_cost_paise=0,
                net_recovered_amount_paise=0,
                incremental_net_recovery_paise=0,
                total_churned_customers=0,
                churn_rate=0.0,
                churn_penalty_paise=0,
                adjusted_net_recovery_paise=0,
                incremental_adjusted_net_recovery_paise=0,
                recovery_rate=0.0,
                average_recovery_delay_seconds=0.0,
                average_customer_fatigue=0.0,
                diagnosis_accuracy=0.0,
                diagnosis_source_counts={},
                deterministic_fallback_count=0,
                invalid_llm_output_count=0,
                low_confidence_abstention_count=0,
                negative_uplift_abstention_count=0,
                governor_allow_count=0,
                governor_deny_count=0,
                governor_abstain_count=0,
                governor_defer_count=0,
                human_review_count=0,
                policy_block_count=0,
                consent_block_count=0,
                retry_limit_block_count=0,
                contact_limit_block_count=0,
                low_confidence_block_count=0,
                low_value_abstention_count=0,
            )

        interventions = sum(1 for r in records if r.is_intervention)
        abstentions = sum(1 for r in records if r.is_abstention)
        gross_recovered = sum(r.recovered_amount_paise for r in records)
        natural_recovered = sum(r.natural_recovered_amount_paise for r in records)
        total_cost = sum(r.action_cost_paise for r in records)
        churned = sum(1 for r in records if r.customer_churned)
        total_recovered_count = sum(1 for r in records if r.recovered)
        total_delay = sum(r.recovery_delay_seconds for r in records if r.recovered)
        total_fatigue = sum(r.fatigue_score for r in records)

        net_recovered = gross_recovered - total_cost
        incremental_recovered = gross_recovered - natural_recovered
        natural_net = natural_recovered  # Natural recovery incurs 0 action cost
        incremental_net = net_recovered - natural_net

        churn_penalty = churned * churn_penalty_paise_per_customer
        adjusted_net_recovery = net_recovered - churn_penalty

        natural_churn_count = sum(1 for r in records if r.natural_customer_churned)
        natural_adjusted_net = natural_recovered - (natural_churn_count * churn_penalty_paise_per_customer)
        incremental_adjusted_net = adjusted_net_recovery - natural_adjusted_net

        # Diagnosis accuracy
        diag_evaluated = [r for r in records if r.diagnosis_correct is not None]
        accuracy = (sum(1 for r in diag_evaluated if r.diagnosis_correct) / len(diag_evaluated)) if diag_evaluated else 1.0

        # Source counts
        source_counts: Dict[str, int] = {}
        for r in records:
            if r.diagnosis_source:
                source_counts[r.diagnosis_source] = source_counts.get(r.diagnosis_source, 0) + 1

        low_conf_count = sum(1 for r in records if r.is_low_confidence_abstention)
        neg_uplift_count = sum(1 for r in records if r.is_negative_uplift_abstention)

        # Governor outcome metrics
        gov_allow = sum(1 for r in records if r.governor_decision == "ALLOW")
        gov_deny = sum(1 for r in records if r.governor_decision == "DENY")
        gov_abstain = sum(1 for r in records if r.governor_decision == "ABSTAIN")
        gov_defer = sum(1 for r in records if r.governor_decision == "DEFER")
        human_review = sum(1 for r in records if r.is_human_review)
        policy_block = sum(1 for r in records if r.is_policy_blocked)
        consent_block = sum(1 for r in records if r.is_consent_blocked)
        retry_limit_block = sum(1 for r in records if r.is_retry_limit_blocked)
        contact_limit_block = sum(1 for r in records if r.is_contact_limit_blocked)
        low_conf_block = sum(1 for r in records if "DIAGNOSIS_CONFIDENCE_TOO_LOW" in r.governor_reason_codes)
        low_val_abstain = sum(1 for r in records if "EXPECTED_VALUE_BELOW_THRESHOLD" in r.governor_reason_codes)

        return EvaluationMetrics(
            policy_name=policy_name,
            total_scenarios=total_scenarios,
            total_interventions=interventions,
            intervention_rate=round(interventions / total_scenarios, 4),
            intervention_count=interventions,
            abstention_count=abstentions,
            actions_avoided_count=abstentions,
            gross_recovered_amount_paise=gross_recovered,
            natural_recovered_amount_paise=natural_recovered,
            incremental_recovered_amount_paise=incremental_recovered,
            incremental_recovery_rate=round(incremental_recovered / gross_recovered, 4) if gross_recovered > 0 else 0.0,
            total_action_cost_paise=total_cost,
            net_recovered_amount_paise=net_recovered,
            incremental_net_recovery_paise=incremental_net,
            total_churned_customers=churned,
            churn_rate=round(churned / total_scenarios, 4),
            churn_penalty_paise=churn_penalty,
            adjusted_net_recovery_paise=adjusted_net_recovery,
            incremental_adjusted_net_recovery_paise=incremental_adjusted_net,
            recovery_rate=round(total_recovered_count / total_scenarios, 4),
            average_recovery_delay_seconds=round(total_delay / total_recovered_count, 2) if total_recovered_count > 0 else 0.0,
            average_customer_fatigue=round(total_fatigue / total_scenarios, 4),
            diagnosis_accuracy=round(accuracy, 4),
            diagnosis_source_counts=source_counts,
            deterministic_fallback_count=deterministic_fallback_count,
            invalid_llm_output_count=invalid_llm_output_count,
            low_confidence_abstention_count=low_conf_count,
            negative_uplift_abstention_count=neg_uplift_count,
            governor_allow_count=gov_allow,
            governor_deny_count=gov_deny,
            governor_abstain_count=gov_abstain,
            governor_defer_count=gov_defer,
            human_review_count=human_review,
            policy_block_count=policy_block,
            consent_block_count=consent_block,
            retry_limit_block_count=retry_limit_block,
            contact_limit_block_count=contact_limit_block,
            low_confidence_block_count=low_conf_block,
            low_value_abstention_count=low_val_abstain,
        )
