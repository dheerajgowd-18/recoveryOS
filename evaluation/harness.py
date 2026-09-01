"""Evaluation harness orchestrator executing policies and governance checks against synthetic scenarios."""
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from evaluation.metrics import (
    DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER,
    EvaluationMetrics,
    MetricCalculator,
    ScenarioEvaluationRecord,
)
from evaluation.policies import BasePolicy
from governor.decision import GovernorDecisionResult
from governor.policy import MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableContextBuilder
from intelligence.providers import BaseDiagnosisProvider, DeterministicDiagnosisProvider
from intelligence.schemas import DiagnosisLabel
from simulator.config import FailureClass, SimulatedActionType
from simulator.generator import SimulatedScenario


class EvaluationResult(BaseModel):
    """Encapsulates the complete evaluation outcome of a policy against a batch of scenarios."""
    model_config = ConfigDict(extra="forbid")

    policy_name: str = Field(..., description="Name of the evaluated policy")
    metrics: EvaluationMetrics = Field(..., description="Aggregated benchmark metrics")
    records: List[ScenarioEvaluationRecord] = Field(..., description="Detailed per-scenario traces")


FAILURE_CLASS_TO_DIAGNOSIS_LABEL = {
    FailureClass.TRANSIENT_GATEWAY: DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
    FailureClass.INSUFFICIENT_FUNDS: DiagnosisLabel.INSUFFICIENT_FUNDS,
    FailureClass.EXPIRED_PAYMENT_METHOD: DiagnosisLabel.EXPIRED_PAYMENT_METHOD,
}


class EvaluationHarness:
    """Batch evaluation harness comparing policy interventions and governance verdicts against hidden potential outcomes."""

    def __init__(
        self,
        churn_penalty_paise_per_customer: int = DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER,
        diagnosis_provider: Optional[BaseDiagnosisProvider] = None,
        merchant_policy: Optional[MerchantPolicy] = None,
    ) -> None:
        self.churn_penalty_paise_per_customer = churn_penalty_paise_per_customer
        self.diagnosis_provider = diagnosis_provider or DeterministicDiagnosisProvider()
        self.merchant_policy = merchant_policy or MerchantPolicy()
        self.governor = RecoveryGovernor(merchant_policy=self.merchant_policy)

    def evaluate_policy(
        self,
        policy: BasePolicy,
        scenarios: List[SimulatedScenario],
        churn_penalty_paise_per_customer: Optional[int] = None,
    ) -> EvaluationResult:
        """Run a policy on a batch of scenarios and evaluate through Governor against hidden counterfactuals."""
        penalty = churn_penalty_paise_per_customer if churn_penalty_paise_per_customer is not None else self.churn_penalty_paise_per_customer
        records: List[ScenarioEvaluationRecord] = []

        fallback_count = 0
        invalid_output_count = 0

        for scenario in scenarios:
            # 1. Project sanitized observable context (strictly hides counterfactual outcomes and archetypes)
            context = ObservableContextBuilder.build_from_simulated_scenario(scenario)

            # 2. Produce structured diagnosis from observable context
            diagnosis = self.diagnosis_provider.diagnose_sync(context)

            # 3. Query policy proposal using ONLY the observable context and structured diagnosis
            proposal = policy.decide(context, diagnosis=diagnosis)

            # 4. Authoritative Governor Evaluation
            gov_decision = self.governor.evaluate(
                context=context,
                diagnosis=diagnosis,
                proposal=proposal,
            )

            # Effective action is permitted only if Governor ALLOWs
            if gov_decision.decision_result == GovernorDecisionResult.ALLOW and gov_decision.selected_action:
                effective_action = gov_decision.selected_action
            else:
                effective_action = SimulatedActionType.NO_ACTION

            # 5. Evaluator-side diagnosis accuracy verification (Comparing predicted label to hidden truth)
            expected_label = FAILURE_CLASS_TO_DIAGNOSIS_LABEL.get(scenario.failure_class)
            diag_to_check = proposal.diagnosis or diagnosis
            diag_correct = (diag_to_check.diagnosis_label == expected_label) if expected_label and diag_to_check else None

            # 6. Retrieve secret ground truth counterfactuals from hidden_outcomes for evaluation scoring
            chosen_outcome = scenario.hidden_outcomes.get_outcome(effective_action)
            natural_outcome = scenario.hidden_outcomes.get_outcome(SimulatedActionType.NO_ACTION)

            is_low_conf = "ABSTAIN_LOW_CONFIDENCE_DIAGNOSIS" in gov_decision.reason_codes or "ABSTAIN_LOW_CONFIDENCE_DIAGNOSIS" in proposal.reason_codes
            is_neg_uplift = "ABSTAIN_NEGATIVE_UPLIFT" in gov_decision.reason_codes or "ABSTAIN_NEGATIVE_UPLIFT" in proposal.reason_codes

            if diag_to_check and diag_to_check.diagnosis_source == "deterministic_fallback":
                fallback_count += 1

            record = MetricCalculator.create_record(
                scenario_id=scenario.scenario_id,
                policy_name=policy.name,
                chosen_action=effective_action,
                chosen_outcome=chosen_outcome,
                natural_outcome=natural_outcome,
                predicted_diagnosis=diag_to_check.diagnosis_label.value if diag_to_check else None,
                diagnosis_confidence=diag_to_check.confidence if diag_to_check else None,
                diagnosis_source=diag_to_check.diagnosis_source if diag_to_check else None,
                diagnosis_correct=diag_correct,
                is_low_confidence_abstention=is_low_conf,
                is_negative_uplift_abstention=is_neg_uplift,
                governor_decision=gov_decision.decision_result.value,
                governor_reason_codes=gov_decision.reason_codes,
            )
            records.append(record)

        metrics = MetricCalculator.compute_metrics(
            policy_name=policy.name,
            records=records,
            churn_penalty_paise_per_customer=penalty,
            deterministic_fallback_count=fallback_count,
            invalid_llm_output_count=invalid_output_count,
        )

        return EvaluationResult(
            policy_name=policy.name,
            metrics=metrics,
            records=records,
        )

    def evaluate_all(
        self,
        policies: List[BasePolicy],
        scenarios: List[SimulatedScenario],
        churn_penalty_paise_per_customer: Optional[int] = None,
    ) -> Dict[str, EvaluationResult]:
        """Evaluate multiple policies sequentially against the exact same scenario population."""
        penalty = churn_penalty_paise_per_customer if churn_penalty_paise_per_customer is not None else self.churn_penalty_paise_per_customer
        results: Dict[str, EvaluationResult] = {}
        for policy in policies:
            results[policy.name] = self.evaluate_policy(
                policy=policy,
                scenarios=scenarios,
                churn_penalty_paise_per_customer=penalty,
            )
        return results
