"""Replay engine for reconstructing exact historical decision traces, candidate evaluations, and execution states."""
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from agent.risk import RiskAssessment
from agent.runtime import AgentRunResult
from audit.decision_log import CandidateScore, DecisionLogStore, DecisionRecord
from execution.executor import ExecutionResult
from policy.base import PolicyDecision
from policy.candidates import CandidateGenerator
from policy.config import DeterministicPolicyConfig
from policy.public_view import PublicScenarioView
from policy.scoring import ExpectedValueScorer
from simulator.config import FailureClass, SimulatedActionType
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
    public_view_snapshot: PublicScenarioView = Field(..., description="Sanitized public input supplied to policy")
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
    ) -> None:
        self.decision_log = decision_log or DecisionLogStore()
        self.config = config or DeterministicPolicyConfig()

    def record_run(
        self,
        run_result: AgentRunResult,
        scenario: SimulatedScenario,
        policy_version: str = "v0.8.0",
        model_version: str = "deterministic-proxy-v1",
    ) -> List[DecisionRecord]:
        """Convert runtime execution trace into immutable DecisionRecord entries and save to log store."""
        created_records: List[DecisionRecord] = []

        for idx, item in enumerate(run_result.trace):
            iteration = item.iteration
            decision_id = f"dec_{run_result.scenario_id}_it{iteration}_{item.decision.action_type.value}"

            # Evaluate candidate scores for complete provenance
            public_view = PublicScenarioView(
                scenario_id=run_result.scenario_id,
                failure_class=scenario.failure_class,
                failure_code=scenario.event.payment.error_code if scenario.event.payment else None,
                error_description=scenario.event.payment.error_description if scenario.event.payment else None,
                error_source=scenario.event.payment.error_source if scenario.event.payment else None,
                error_step=scenario.event.payment.error_step if scenario.event.payment else None,
                error_reason=scenario.event.payment.error_reason if scenario.event.payment else None,
                amount_in_paise=scenario.event.payment.amount if scenario.event.payment else 0,
                currency=scenario.event.payment.currency if scenario.event.payment else "INR",
                attempt_count=iteration,
                customer_id=scenario.customer.customer_id,
                payment_id=run_result.payment_id,
                payment_method=scenario.event.payment.method if scenario.event.payment else "card",
            )

            admissible_actions = CandidateGenerator.generate_candidates(public_view, self.config)
            candidate_scores: List[CandidateScore] = []

            priors = self.config.estimated_action_priors.get(
                public_view.failure_class, self.config.default_priors
            )

            for action_type in SimulatedActionType:
                is_admissible = action_type in admissible_actions
                rejection_reason = None if is_admissible else "Inadmissible under failure physics or attempt limit"
                prob = priors.get(action_type, 0.0)
                cost = self.config.action_costs_paise.get(action_type, 0)
                scored = ExpectedValueScorer.score_candidate(public_view, action_type, self.config)

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
                failure_class=scenario.failure_class.value,
                failure_code=scenario.event.payment.error_code if scenario.event.payment else None,
                amount_in_paise=scenario.event.payment.amount if scenario.event.payment else 0,
                aggregate_state_before=item.aggregate_state_before,
                aggregate_state_after=item.aggregate_state_after,
                aggregate_state=item.aggregate_state,
                risk_level=item.risk_assessment.risk_level,
                candidate_scores=candidate_scores,
                selected_action=item.decision.action_type,
                confidence=item.decision.confidence,
                rationale=item.decision.rationale,
                reason_codes=item.decision.reason_codes,
                execution_result_success=exec_success,
                recovered=recovered,
                action_cost_paise=action_cost,
                recovered_amount_paise=recovered_amount,
                stop_reason=run_result.stop_reason if idx == len(run_result.trace) - 1 else None,
            )

            self.decision_log.save_record(record)
            created_records.append(record)

        return created_records

    def replay_decision(
        self,
        decision_id: str,
        scenario: Optional[SimulatedScenario] = None,
    ) -> Optional[ReplayRecord]:
        """Reconstruct the exact decision trace and scoring breakdown for a specific decision_id."""
        record = self.decision_log.get_record(decision_id)
        if not record:
            return None

        # Reconstruct PublicScenarioView
        try:
            fc = FailureClass(record.failure_class.lower())
        except Exception:
            fc = FailureClass.TRANSIENT_GATEWAY

        public_view = PublicScenarioView(
            scenario_id=record.scenario_id,
            failure_class=fc,
            failure_code=record.failure_code,
            error_description=None,
            error_source=None,
            error_step=None,
            error_reason=None,
            amount_in_paise=record.amount_in_paise,
            currency="INR",
            attempt_count=record.iteration,
            customer_id=None,
            payment_id=record.payment_id,
            payment_method="card",
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
            public_view_snapshot=public_view,
            aggregate_state_before=record.aggregate_state_before,
            risk_assessment=risk,
            candidate_evaluations=record.candidate_scores,
            decision=decision,
            execution_outcome=exec_outcome,
            aggregate_state_after=record.aggregate_state_after,
            stop_reason=record.stop_reason or "CYCLE_COMPLETED",
            replay_timestamp_epoch=int(datetime.now(timezone.utc).timestamp()),
        )
