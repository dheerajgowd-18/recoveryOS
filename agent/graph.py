"""Stateful recovery orchestration graph connecting specialized agents, RAG, Governor, and Execution."""
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from agent.agents import (
    CandidateStrategyOption,
    ContextRetrievalAgent,
    DiagnosisAgent,
    OutcomeVerificationAgent,
    RecoveryStrategyAgent,
    TimingReasonerAgent,
)
from agent.risk import RiskAssessment, RiskDetector
from backend.services.ingestion_service import IngestionService
from domain.aggregates import PaymentAggregate
from domain.enums import PaymentState
from domain.events import PaymentEvent
from execution.executor import ExecutionContext, ExecutionResult, RecoveryExecutor
from execution.simulator_executor import SimulatorExecutor
from governor.decision import GovernorDecision, GovernorDecisionResult
from governor.exceptions import (
    ActionBlockedError,
    ConsentViolationError,
    DuplicateExecutionError,
    PolicyOutageError,
    SchemaValidationError,
)
from governor.firewall import CustomerConsentContext, ToolFirewall
from governor.policy import MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis
from planner.timing import ActionTimingCandidate, TimingWindow
from policy.base import PolicyDecision
from policy.config import DeterministicPolicyConfig
from scheduler.models import ScheduledAction
from scheduler.service import ScheduledLifecycleService
from simulator.config import SimulatedActionType
from simulator.generator import SimulatedScenario


class WorkflowStepTrace(BaseModel):
    """Trace entry recording a single node transition in the stateful graph."""
    model_config = ConfigDict(extra="forbid")

    step_name: str = Field(..., description="Node name in the orchestration graph")
    status: str = Field(..., description="Execution status e.g. 'SUCCESS', 'SKIPPED', 'HALTED', 'ERROR'")
    elapsed_ms: float = Field(default=0.0, ge=0.0, description="Step duration in milliseconds")
    summary: str = Field(..., description="Human-readable step summary")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Structured step artifact")


class RecoveryWorkflowState(BaseModel):
    """Explicit, strongly-typed state container flowing through the RecoveryOS graph."""
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., description="Unique scenario session identifier")
    payment_id: str = Field(..., description="Payment identifier")
    iteration: int = Field(default=1, ge=1, description="Recovery loop iteration")
    current_epoch: int = Field(..., description="Current system epoch timestamp")
    event: PaymentEvent = Field(..., description="Incoming failure event")
    aggregate: Optional[PaymentAggregate] = Field(default=None, description="Reconciled payment aggregate")
    consent: Optional[CustomerConsentContext] = Field(default=None, description="Customer communication consent")
    policy_healthy: bool = Field(default=True, description="Health status of merchant policy engine")

    # Node intermediate artifacts
    observable_context: Optional[ObservableRecoveryContext] = Field(default=None, description="Sanitized observable context")
    memory_bundle: Optional[Dict[str, Any]] = Field(default=None, description="Retrieved bounded memory bundle")
    risk_assessment: Optional[RiskAssessment] = Field(default=None, description="Risk detector verdict")
    diagnosis: Optional[StructuredDiagnosis] = Field(default=None, description="Root cause diagnosis")
    strategy_proposal: Optional[Any] = Field(default=None, description="Structured strategy reasoning proposal")
    strategy_candidates: List[CandidateStrategyOption] = Field(default_factory=list, description="Candidate actions proposed")
    timing_candidates: List[ActionTimingCandidate] = Field(default_factory=list, description="Evaluated action x timing options")
    selected_candidate: Optional[ActionTimingCandidate] = Field(default=None, description="Economically optimal candidate")
    proposal: Optional[PolicyDecision] = Field(default=None, description="Synthesized policy proposal")
    governor_decision: Optional[GovernorDecision] = Field(default=None, description="Authoritative governance verdict")
    firewall_action: Optional[SimulatedActionType] = Field(default=None, description="Validated firewall action")
    scheduled_action: Optional[ScheduledAction] = Field(default=None, description="Scheduled delayed action if deferred")
    execution_result: Optional[ExecutionResult] = Field(default=None, description="Direct execution outcome")
    verification_outcome: Optional[Dict[str, Any]] = Field(default=None, description="Verified state change summary")

    # Workflow lifecycle tracking
    is_terminal: bool = Field(default=False, description="Whether state has reached a terminal branch")
    stop_reason: Optional[str] = Field(default=None, description="Final stopping reason code")
    step_traces: List[WorkflowStepTrace] = Field(default_factory=list, description="Chronological node execution trace")


class RecoveryStateGraph:
    """Stateful Agentic Graph Orchestrator executing the complete recovery decision workflow."""

    def __init__(
        self,
        ingestion_service: Optional[IngestionService] = None,
        context_agent: Optional[ContextRetrievalAgent] = None,
        risk_detector: Optional[RiskDetector] = None,
        diagnosis_agent: Optional[DiagnosisAgent] = None,
        strategy_agent: Optional[RecoveryStrategyAgent] = None,
        timing_agent: Optional[TimingReasonerAgent] = None,
        verification_agent: Optional[OutcomeVerificationAgent] = None,
        governor: Optional[RecoveryGovernor] = None,
        scheduler: Optional[ScheduledLifecycleService] = None,
        firewall: Optional[ToolFirewall] = None,
        executor: Optional[RecoveryExecutor] = None,
    ) -> None:
        self.ingestion = ingestion_service or IngestionService()
        self.context_agent = context_agent or ContextRetrievalAgent()
        self.risk_detector = risk_detector or RiskDetector()
        self.diagnosis_agent = diagnosis_agent or DiagnosisAgent()
        self.strategy_agent = strategy_agent or RecoveryStrategyAgent()
        self.timing_agent = timing_agent or TimingReasonerAgent()
        self.verification_agent = verification_agent or OutcomeVerificationAgent()
        self.governor = governor or RecoveryGovernor()
        self.scheduler = scheduler or ScheduledLifecycleService()
        self.firewall = firewall or ToolFirewall()
        self.executor = executor or SimulatorExecutor()

    async def execute_workflow(
        self,
        initial_scenario: SimulatedScenario,
        consent: Optional[CustomerConsentContext] = None,
        policy_healthy: bool = True,
        attempt_count: int = 1,
    ) -> RecoveryWorkflowState:
        """Executes the full stateful graph for an incoming scenario event."""
        payment_id = initial_scenario.event.payment.id if initial_scenario.event.payment else "pay_unknown"
        created_at_epoch = int(initial_scenario.webhook_payload.created_at) if initial_scenario.webhook_payload else int(time.time())

        # Initialize State
        state = RecoveryWorkflowState(
            scenario_id=initial_scenario.scenario_id,
            payment_id=payment_id,
            iteration=attempt_count,
            current_epoch=created_at_epoch,
            event=initial_scenario.event,
            aggregate=None,
            consent=consent,
            policy_healthy=policy_healthy,
        )

        # -------------------------------------------------------------
        # NODE 1: Ingest & Reconcile State
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        await self.ingestion.process_webhook(initial_scenario.webhook_payload)
        state.aggregate = await self.ingestion.event_store.get_payment_aggregate(payment_id)
        current_state_val = state.aggregate.current_state.value if state.aggregate else PaymentState.FAILED.value
        state.step_traces.append(
            WorkflowStepTrace(
                step_name="NODE_1_INGESTION_RECONCILIATION",
                status="SUCCESS",
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                summary=f"Event ingested and aggregate reconciled to '{current_state_val}'",
                payload={"payment_id": payment_id, "state": current_state_val},
            )
        )

        # Terminal state early exit check
        if state.aggregate and state.aggregate.is_terminal:
            state.is_terminal = True
            state.stop_reason = "TERMINAL_STATE_REACHED"
            return state

        # -------------------------------------------------------------
        # NODE 2: Risk Assessment Boundary
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        state.risk_assessment = self.risk_detector.detect_payment_risk(state.event.payment, state.aggregate)
        state.step_traces.append(
            WorkflowStepTrace(
                step_name="NODE_2_RISK_DETECTION",
                status="PASSED" if state.risk_assessment.risk_level in ("LOW", "NEGLIGIBLE") else "FLAGGED",
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                summary=f"Payment classified as {state.risk_assessment.risk_level} risk",
                payload=state.risk_assessment.model_dump(),
            )
        )

        if not state.risk_assessment.is_at_risk:
            state.is_terminal = True
            state.stop_reason = "NO_RISK_DETECTED"
            return state

        # -------------------------------------------------------------
        # NODE 3: Context Retrieval & Bounded RAG (Agent 1)
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        obs_ctx, mem_bundle = self.context_agent.execute(
            event=state.event,
            aggregate=state.aggregate,
            consent=state.consent,
            attempt_count=state.iteration,
            scenario_id=state.scenario_id,
        )
        state.observable_context = obs_ctx
        state.memory_bundle = mem_bundle.model_dump()
        state.step_traces.append(
            WorkflowStepTrace(
                step_name="NODE_3_CONTEXT_RETRIEVAL_RAG",
                status="SUCCESS",
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                summary=f"Assembled sanitized context with {len(mem_bundle.retrieved_items)} bounded memory items",
                payload={
                    "retrieved_count": len(mem_bundle.retrieved_items),
                    "items": [item.title for item in mem_bundle.retrieved_items],
                    "retrieval_latency_ms": mem_bundle.retrieval_latency_ms,
                },
            )
        )

        # -------------------------------------------------------------
        # NODE 4: Root Cause Diagnosis (Agent 2)
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        if not state.policy_healthy:
            state.is_terminal = True
            state.stop_reason = "POLICY_OUTAGE"
            state.step_traces.append(
                WorkflowStepTrace(
                    step_name="NODE_4_DIAGNOSIS",
                    status="HALTED",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                    summary="Policy engine unhealthy; failing closed before diagnosis",
                    payload={"error": "POLICY_OUTAGE"},
                )
            )
            return state

        state.diagnosis = await self.diagnosis_agent.diagnose_async(state.observable_context, mem_bundle)
        state.step_traces.append(
            WorkflowStepTrace(
                step_name="NODE_4_DIAGNOSIS",
                status="SUCCESS",
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                summary=f"Inferred '{state.diagnosis.diagnosis_label.value}' (conf={state.diagnosis.confidence:.2f}, src={state.diagnosis.diagnosis_source})",
                payload=state.diagnosis.model_dump(),
            )
        )

        # -------------------------------------------------------------
        # NODE 5: Strategy Candidates & LLM Reasoning (Agent 3)
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        state.strategy_proposal = await self.strategy_agent.propose_strategy_async(
            context=state.observable_context,
            diagnosis=state.diagnosis,
            memory_bundle=mem_bundle,
        )
        state.strategy_candidates = self.strategy_agent.generate_strategy_candidates(
            context=state.observable_context,
            diagnosis=state.diagnosis,
            memory_bundle=mem_bundle,
        )
        state.step_traces.append(
            WorkflowStepTrace(
                step_name="NODE_5_STRATEGY_REASONING",
                status="SUCCESS",
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                summary=f"Strategy Agent ({state.strategy_proposal.strategy_source}): Proposed '{state.strategy_proposal.primary_recommendation.value}' with {len(state.strategy_candidates)} admissible candidate options",
                payload=state.strategy_proposal.model_dump(),
            )
        )

        # -------------------------------------------------------------
        # NODE 6: Timing & Economic Valuation (Agent 4)
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        state.timing_candidates = self.timing_agent.evaluate_timing_options(
            context=state.observable_context,
            diagnosis=state.diagnosis,
            strategy_candidates=state.strategy_candidates,
        )

        best_timing = state.timing_candidates[0] if state.timing_candidates else None
        state.selected_candidate = best_timing

        # Build Policy Proposal
        if best_timing and best_timing.action_type != SimulatedActionType.NO_ACTION and best_timing.expected_uplift >= 0.0 and best_timing.expected_net_value_paise >= 0:
            state.proposal = PolicyDecision(
                action_type=best_timing.action_type,
                confidence=best_timing.estimated_probability,
                rationale=f"Selected {best_timing.mechanism.value} ({best_timing.timing_window.value}) with expected net return ₹{best_timing.expected_net_value_paise / 100:.2f}.",
                policy_name="RECOVERYOS_STATEFUL_AGENT_V1",
                reason_codes=best_timing.reason_codes,
                expected_net_value_paise=best_timing.expected_net_value_paise,
                expected_incremental_value_paise=best_timing.expected_incremental_value_paise,
                timing_window=best_timing.timing_window.value,
                delay_seconds=best_timing.delay_seconds,
                diagnosis=state.diagnosis,
            )
        else:
            state.proposal = PolicyDecision(
                action_type=SimulatedActionType.NO_ACTION,
                confidence=1.0,
                rationale="Abstaining: Negative or negligible expected net incremental value.",
                policy_name="RECOVERYOS_STATEFUL_AGENT_V1",
                reason_codes=["ABSTAIN_NEGATIVE_UPLIFT" if (best_timing and best_timing.expected_uplift < 0) else "ABSTAIN_LOW_EXPECTED_VALUE"],
                expected_net_value_paise=0,
                expected_incremental_value_paise=0,
                diagnosis=state.diagnosis,
            )

        state.step_traces.append(
            WorkflowStepTrace(
                step_name="NODE_6_TIMING_AND_ECONOMICS",
                status="SUCCESS",
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                summary=f"Optimal economic choice: {state.proposal.action_type.value} ({state.proposal.timing_window or 'IMMEDIATE'})",
                payload={
                    "selected_action": state.proposal.action_type.value,
                    "timing_window": state.proposal.timing_window,
                    "expected_net_value_paise": state.proposal.expected_net_value_paise,
                    "candidates_ranked": len(state.timing_candidates),
                },
            )
        )

        # -------------------------------------------------------------
        # NODE 7: Authoritative Recovery Governor (Safety Gate)
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        state.governor_decision = self.governor.evaluate(
            context=state.observable_context,
            diagnosis=state.diagnosis,
            proposal=state.proposal,
            aggregate=state.aggregate,
            consent=state.consent,
            policy_healthy=state.policy_healthy,
        )
        state.step_traces.append(
            WorkflowStepTrace(
                step_name="NODE_7_RECOVERY_GOVERNOR",
                status=state.governor_decision.decision_result.value,
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                summary=f"Governor verdict: {state.governor_decision.decision_result.value} (Policy: {state.governor_decision.policy_version})",
                payload=state.governor_decision.model_dump(),
            )
        )

        if state.governor_decision.decision_result != GovernorDecisionResult.ALLOW:
            state.is_terminal = True
            state.stop_reason = state.governor_decision.stop_reason or "GOVERNOR_BLOCKED"
            return state

        # -------------------------------------------------------------
        # NODE 8: Scheduling vs Immediate Tool Firewall
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        is_delayed = (
            state.governor_decision.delay_seconds > 0
            or state.governor_decision.timing_window in ("PLUS_2H", "PLUS_6H", "PLUS_12H", "PLUS_24H")
            or state.proposal.action_type == SimulatedActionType.RETRY_LATER
        )

        if is_delayed:
            # Schedule future action bound to state version
            timing_win = TimingWindow(state.governor_decision.timing_window) if state.governor_decision.timing_window else TimingWindow.PLUS_6H
            scheduled_act = self.scheduler.schedule_action(
                decision=state.proposal,
                context=state.observable_context,
                aggregate=state.aggregate,
                policy=self.governor.merchant_policy,
                current_epoch=state.current_epoch,
                timing_window=timing_win,
                delay_seconds=state.governor_decision.delay_seconds if state.governor_decision.delay_seconds > 0 else timing_win.delay_seconds,
            )
            state.scheduled_action = scheduled_act
            state.is_terminal = True
            state.stop_reason = "ACTION_SCHEDULED"
            state.step_traces.append(
                WorkflowStepTrace(
                    step_name="NODE_8_SCHEDULER",
                    status="SUCCESS",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                    summary=f"Scheduled delayed action '{scheduled_act.action_type.value}' for +{scheduled_act.delay_seconds}s (State V{scheduled_act.expected_state_version})",
                    payload=scheduled_act.model_dump(),
                )
            )
            return state

        # -------------------------------------------------------------
        # NODE 9: Tool Firewall & Immediate Execution
        # -------------------------------------------------------------
        chosen_action = state.governor_decision.selected_action or state.proposal.action_type
        exec_key = f"exec_{state.payment_id}_{state.iteration}_{chosen_action.value}_{state.current_epoch}"

        try:
            validated_action = self.firewall.validate_and_gate(
                action=chosen_action,
                execution_key=exec_key,
                consent=state.consent,
                policy_healthy=state.policy_healthy,
            )
            state.firewall_action = validated_action
        except (ActionBlockedError, ConsentViolationError, SchemaValidationError, DuplicateExecutionError, PolicyOutageError) as e:
            state.is_terminal = True
            state.stop_reason = "ACTION_BLOCKED" if not isinstance(e, PolicyOutageError) else "POLICY_OUTAGE"
            state.step_traces.append(
                WorkflowStepTrace(
                    step_name="NODE_9_TOOL_FIREWALL",
                    status="BLOCKED",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                    summary=f"Tool Firewall blocked action: {str(e)}",
                    payload={"error": str(e)},
                )
            )
            return state

        # Dispatch Execution
        exec_ctx = ExecutionContext(
            scenario=initial_scenario,
            attempt_count=state.iteration,
            current_epoch=state.current_epoch,
        )
        try:
            exec_res = await self.executor.execute(validated_action, exec_ctx)
            state.execution_result = exec_res
        except Exception as e:
            state.is_terminal = True
            state.stop_reason = "EXECUTION_FAILURE"
            state.step_traces.append(
                WorkflowStepTrace(
                    step_name="NODE_9_EXECUTION",
                    status="ERROR",
                    elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                    summary=f"Executor raised exception: {str(e)}",
                    payload={"error": str(e)},
                )
            )
            return state

        # -------------------------------------------------------------
        # NODE 10: Event Reconciliation & Outcome Verification (Agent 5)
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        if exec_res.resulting_payload:
            await self.ingestion.process_webhook(exec_res.resulting_payload)

        updated_agg = await self.ingestion.event_store.get_payment_aggregate(payment_id)
        verification = self.verification_agent.verify_state_transition(
            aggregate_before=state.aggregate,
            aggregate_after=updated_agg,
            execution_success=exec_res.success,
        )
        state.aggregate = updated_agg
        state.verification_outcome = verification
        state.is_terminal = True
        state.stop_reason = "REVENUE_RECOVERED" if verification.get("is_recovered") else "CYCLE_COMPLETED"

        state.step_traces.append(
            WorkflowStepTrace(
                step_name="NODE_10_VERIFICATION_OUTCOME",
                status="SUCCESS",
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                summary=f"Reconciled final state: {verification.get('state_after')} (Recovered: {verification.get('is_recovered')})",
                payload=verification,
            )
        )

        return state
