"""Replay engine for reconstructing exact historical decision traces, candidate evaluations, governance verdicts, and execution states."""
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from agent.risk import RiskAssessment
from agent.runtime import AgentRunResult
from audit.decision_log import CandidateScore, DecisionLogStore, DecisionRecord
from execution.executor import ExecutionResult
from governor.decision import GovernorDecision, GovernorDecisionResult
from governor.policy import MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableContextBuilder, ObservableRecoveryContext
from intelligence.providers import DeterministicDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.base import PolicyDecision
from policy.candidates import CandidateGenerator
from policy.config import DeterministicPolicyConfig
from policy.scoring import ExpectedValueScorer
from simulator.config import SimulatedActionType
from simulator.generator import SimulatedScenario


class ReplayRecord(BaseModel):
    """Full-fidelity reconstruction of a specific historical autonomous decision cycle."""
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(..., description="Decision identifier")
    scenario_id: str = Field(..., description="Scenario identifier")
    payment_id: str = Field(..., description="Payment identifier")
    iteration: int = Field(..., ge=1, description="Cycle iteration")
    policy_name: str = Field(..., description="Policy identifier used during execution")
    policy_version: str = Field(..., description="Policy code release version")
    model_version: str = Field(..., description="Model / scoring engine release version")
    observable_context_snapshot: ObservableRecoveryContext = Field(..., description="Sanitized observable input supplied to policy")
    diagnosis: StructuredDiagnosis = Field(..., description="Structured diagnosis produced by intelligence layer")
    governor_decision: Optional[GovernorDecision] = Field(default=None, description="Authoritative Governor evaluation verdict")
    aggregate_state_before: str = Field(..., description="Aggregate state before execution")
    risk_assessment: RiskAssessment = Field(..., description="Risk detection outcome")
    candidate_evaluations: List[CandidateScore] = Field(default_factory=list, description="Candidate action scores")
    decision: PolicyDecision = Field(..., description="Chosen policy decision and rationale")
    execution_outcome: Optional[ExecutionResult] = Field(default=None, description="Executor result if dispatched")
    aggregate_state_after: str = Field(..., description="Aggregate state after execution")
    stop_reason: str = Field(..., description="Runtime stopping status")
    replay_timestamp_epoch: int = Field(..., description="Replay generation timestamp")


class ReplayEngine:
    """Reconstructs historical agent decision cycles with bit-level fidelity and auditability."""

    def __init__(
        self,
        decision_log: Optional[DecisionLogStore] = None,
        config: Optional[DeterministicPolicyConfig] = None,
        merchant_policy: Optional[MerchantPolicy] = None,
    ) -> None:
        self.decision_log = decision_log or DecisionLogStore()
        self.config = config or DeterministicPolicyConfig()
        self.merchant_policy = merchant_policy or MerchantPolicy()
        self.diagnosis_provider = DeterministicDiagnosisProvider()
        self.governor = RecoveryGovernor(merchant_policy=self.merchant_policy)

    def record_run(
        self,
        run_result: AgentRunResult,
        scenario: SimulatedScenario,
        policy_version: str = "v1.0.0",
        model_version: str = "deterministic-proxy-v1",
    ) -> List[DecisionRecord]:
        """Convert runtime execution trace into immutable DecisionRecord entries and save to log store."""
        created_records: List[DecisionRecord] = []

        for idx, item in enumerate(run_result.trace):
            iteration = item.iteration
            decision_id = f"dec_{run_result.scenario_id}_it{iteration}_{item.decision.action_type.value}"

            # 1. Reconstruct sanitized ObservableRecoveryContext
            obs_context = ObservableRecoveryContext(
                scenario_id=run_result.scenario_id,
                payment_id=run_result.payment_id,
                customer_id=scenario.customer.customer_id if scenario.customer else None,
                amount_in_paise=scenario.event.payment.amount if scenario.event.payment else 0,
                currency=scenario.event.payment.currency if scenario.event.payment else "INR",
                payment_method=scenario.event.payment.method if scenario.event.payment else "card",
                attempt_count=iteration,
                error_code=scenario.event.payment.error_code if scenario.event.payment else None,
                error_description=scenario.event.payment.error_description if scenario.event.payment else None,
                error_source=scenario.event.payment.error_source if scenario.event.payment else None,
                error_step=scenario.event.payment.error_step if scenario.event.payment else None,
                error_reason=scenario.event.payment.error_reason if scenario.event.payment else None,
                time_since_failure_seconds=0,
                recent_failed_attempts=iteration,
                prior_successful_payments=1,
                prior_retry_success=True,
                prior_payment_link_success=None,
                average_recovery_time_seconds=7200,
                contacts_in_last_24h=0,
                contacts_in_last_7d=0,
                time_since_last_contact_seconds=None,
                time_since_last_successful_payment_seconds=None,
                subscription_id=scenario.event.subscription.id if scenario.event.subscription else None,
                subscription_status=scenario.event.subscription.status if scenario.event.subscription else None,
                subscription_age_days=90,
                consent_opted_out=False,
            )

            # 2. Get Structured Diagnosis
            diagnosis = (
                item.diagnosis
                or item.decision.diagnosis
                or self.diagnosis_provider.diagnose_sync(obs_context)
            )

            # 3. Get Governor Decision
            gov_decision = item.governor_decision or self.governor.evaluate(
                context=obs_context,
                diagnosis=diagnosis,
                proposal=item.decision,
            )

            admissible_actions = CandidateGenerator.generate_candidates(obs_context, diagnosis, self.config)
            candidate_scores: List[CandidateScore] = []

            priors = self.config.estimated_action_priors.get(
                diagnosis.diagnosis_label, self.config.default_priors
            )

            for action_type in SimulatedActionType:
                is_admissible = action_type in admissible_actions
                rejection_reason = None if is_admissible else "Inadmissible under failure physics or attempt limit"
                prob = priors.get(action_type, 0.0)
                cost = self.config.action_costs_paise.get(action_type, 0)
                scored = ExpectedValueScorer.score_candidate(obs_context, diagnosis, action_type, self.config)

                candidate_scores.append(
                    CandidateScore(
                        action_type=action_type,
                        is_admissible=is_admissible,
                        rejection_reason=rejection_reason,
                        expected_recovery_prob=prob,
                        action_cost_paise=cost,
                        expected_net_value_paise=scored.expected_net_value_paise,
                        incremental_uplift_paise=scored.expected_incremental_value_paise,
                    )
                )

            exec_success = item.execution_result.success if item.execution_result else None
            recovered = item.execution_result.recovered if item.execution_result else None
            action_cost = item.execution_result.action_cost_paise if item.execution_result else None
            recovered_amount = item.execution_result.recovered_amount_paise if item.execution_result else None

            record = DecisionRecord(
                decision_id=decision_id,
                scenario_id=run_result.scenario_id,
                payment_id=run_result.payment_id,
                iteration=iteration,
                timestamp_epoch=item.timestamp_epoch,
                policy_name=item.decision.policy_name,
                policy_version=policy_version,
                model_version=model_version,
                diagnosis_label=diagnosis.diagnosis_label.value,
                diagnosis_confidence=diagnosis.confidence,
                diagnosis_source=diagnosis.diagnosis_source,
                evidence_codes=diagnosis.evidence_codes,
                governor_decision=gov_decision.decision_result.value if gov_decision else None,
                governor_reason_codes=gov_decision.reason_codes if gov_decision else [],
                governor_policy_version=gov_decision.policy_version if gov_decision else self.merchant_policy.policy_version,
                human_review_reason=gov_decision.human_review_reason if gov_decision else None,
                failure_class=scenario.failure_class.value if scenario.failure_class else None,
                failure_code=scenario.event.payment.error_code if scenario.event.payment else None,
                amount_in_paise=scenario.event.payment.amount if scenario.event.payment else 0,
                aggregate_state_before=item.aggregate_state_before,
                aggregate_state_after=item.aggregate_state_after,
                aggregate_state=item.aggregate_state,
                risk_level=item.risk_assessment.risk_level,
                candidate_scores=candidate_scores,
                selected_action=item.decision.action_type,
                timing_window=item.decision.timing_window or (gov_decision.timing_window if gov_decision else None),
                delay_seconds=item.decision.delay_seconds if item.decision.delay_seconds is not None else (gov_decision.delay_seconds if gov_decision else 0),
                scheduled_action_id=None,
                confidence=item.decision.confidence,
                diagnostic_confidence=diagnosis.confidence,
                economic_confidence=getattr(item.decision, "economic_confidence", item.decision.confidence),
                execution_state_validity=getattr(item.decision, "execution_state_validity", 1.0),
                record_origin="ACTUAL_RUNTIME_EXECUTION",
                rationale=item.decision.rationale,
                reason_codes=item.decision.reason_codes,
                execution_result_success=exec_success,
                recovered=recovered,
                action_cost_paise=action_cost,
                recovered_amount_paise=recovered_amount,
                stop_reason=run_result.stop_reason if idx == len(run_result.trace) - 1 else None,
                observable_context=obs_context.model_dump(),
            )

            self.decision_log.save_record(record)
            created_records.append(record)

        return created_records

    def replay_decision(
        self,
        decision_id: str,
        scenario: Optional[SimulatedScenario] = None,
    ) -> Optional[ReplayRecord]:
        """Reconstruct the exact decision trace, governance verdict, and scoring breakdown for a specific decision_id."""
        record = self.decision_log.get_record(decision_id)
        if not record:
            return None

        # Reconstruct ObservableRecoveryContext
        obs_context = (
            ObservableRecoveryContext(**record.observable_context)
            if record.observable_context
            else ObservableRecoveryContext(
                scenario_id=record.scenario_id,
                payment_id=record.payment_id,
                amount_in_paise=record.amount_in_paise,
                currency="INR",
                attempt_count=record.iteration,
                error_code=record.failure_code,
            )
        )

        try:
            diag_label = DiagnosisLabel(record.diagnosis_label)
        except (ValueError, KeyError, TypeError):
            diag_label = DiagnosisLabel.UNKNOWN_FAILURE

        diagnosis = StructuredDiagnosis(
            diagnosis_label=diag_label,
            confidence=record.diagnosis_confidence,
            evidence_codes=record.evidence_codes,
            uncertainties=[],
            recommended_candidate_actions=[record.selected_action],
            recommended_timing_hint=None,
            human_review_required=record.human_review_reason is not None,
            abstain_recommended=False,
            rationale=record.rationale,
            diagnosis_source=record.diagnosis_source,
            model_version=record.model_version,
        )

        selected_score = next(
            (score for score in record.candidate_scores if score.action_type == record.selected_action),
            None,
        )

        decision = PolicyDecision(
            action_type=record.selected_action,
            confidence=record.confidence,
            rationale=record.rationale,
            policy_name=record.policy_name,
            reason_codes=record.reason_codes,
            expected_net_value_paise=selected_score.expected_net_value_paise if selected_score else None,
            expected_incremental_value_paise=selected_score.incremental_uplift_paise if selected_score else None,
            diagnosis=diagnosis,
        )

        gov_decision: Optional[GovernorDecision] = None
        if record.governor_decision:
            try:
                gov_res = GovernorDecisionResult(record.governor_decision)
            except (ValueError, KeyError, TypeError):
                gov_res = GovernorDecisionResult.ALLOW

            gov_decision = GovernorDecision(
                decision_result=gov_res,
                selected_action=record.selected_action if gov_res == GovernorDecisionResult.ALLOW else None,
                timing_hint=None,
                reason_codes=record.governor_reason_codes,
                policy_version=record.governor_policy_version or "v1.0.0",
                diagnosis_confidence=record.diagnosis_confidence,
                expected_incremental_value_paise=selected_score.incremental_uplift_paise if selected_score else 0,
                expected_net_value_paise=selected_score.expected_net_value_paise if selected_score else 0,
                human_review_reason=record.human_review_reason,
                stop_reason=record.stop_reason,
                rationale=record.rationale,
            )

        risk = RiskAssessment(
            is_at_risk=record.risk_level in ("HIGH", "CRITICAL"),
            risk_level=record.risk_level,
            reason=f"Recorded risk level: {record.risk_level}",
        )

        exec_outcome: Optional[ExecutionResult] = None
        if record.execution_result_success is not None:
            exec_outcome = ExecutionResult(
                success=record.execution_result_success,
                action_type=record.selected_action,
                resulting_event=None,
                resulting_payload=None,
                recovered=record.recovered or False,
                recovered_amount_paise=record.recovered_amount_paise or 0,
                action_cost_paise=record.action_cost_paise or 0,
                execution_timestamp_epoch=record.timestamp_epoch,
                message=f"Replayed execution of {record.selected_action.value}",
            )

        return ReplayRecord(
            decision_id=record.decision_id,
            scenario_id=record.scenario_id,
            payment_id=record.payment_id,
            iteration=record.iteration,
            policy_name=record.policy_name,
            policy_version=record.policy_version,
            model_version=record.model_version,
            observable_context_snapshot=obs_context,
            diagnosis=diagnosis,
            governor_decision=gov_decision,
            aggregate_state_before=record.aggregate_state_before,
            risk_assessment=risk,
            candidate_evaluations=record.candidate_scores,
            decision=decision,
            execution_outcome=exec_outcome,
            aggregate_state_after=record.aggregate_state_after,
            stop_reason=record.stop_reason or "CYCLE_COMPLETED",
            replay_timestamp_epoch=int(datetime.now(timezone.utc).timestamp()),
        )
