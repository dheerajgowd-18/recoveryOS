"""AgentRuntime orchestrating the closed-loop observe-diagnose-propose-govern-schedule-execute recovery cycle."""
from typing import List, Optional, Tuple
import httpx
from pydantic import BaseModel, ConfigDict, Field

from agent.risk import RiskAssessment, RiskDetector
from backend.services.ingestion_service import IngestionService
from domain.enums import PaymentState
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
from intelligence.context import ObservableContextBuilder, ObservableRecoveryContext
from intelligence.providers import BaseDiagnosisProvider, DeterministicDiagnosisProvider
from intelligence.schemas import StructuredDiagnosis
from planner.timing import TimingWindow
from policy.base import BasePolicy, PolicyDecision
from policy.deterministic import DeterministicRecoveryPolicy
from scheduler.models import ScheduledAction, ScheduledActionStatus
from scheduler.service import ScheduledLifecycleService
from simulator.config import SimulatedActionType
from simulator.generator import SimulatedScenario


class AgentIterationRecord(BaseModel):
    """Step-level trace recording an individual cycle in the agent runtime loop."""
    model_config = ConfigDict(extra="forbid")

    iteration: int = Field(..., description="Cycle index (1-based)")
    risk_assessment: RiskAssessment = Field(..., description="Risk detection outcome")
    decision: PolicyDecision = Field(..., description="Action proposed by policy")
    diagnosis: Optional[StructuredDiagnosis] = Field(default=None, description="Structured diagnosis produced")
    governor_decision: Optional[GovernorDecision] = Field(default=None, description="Authoritative governance verdict")
    execution_result: Optional[ExecutionResult] = Field(default=None, description="Executor result if dispatched")
    aggregate_state_before: str = Field(..., description="Payment aggregate state before this cycle")
    aggregate_state_after: str = Field(..., description="Payment aggregate state after this cycle")
    aggregate_state: str = Field(..., description="Payment aggregate state after this cycle")
    timestamp_epoch: int = Field(..., description="Epoch timestamp of cycle")
    error_message: Optional[str] = Field(default=None, description="Any caught error or exception message")


class AgentRunResult(BaseModel):
    """Overall summary and execution trace of an agent recovery lifecycle."""
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., description="Scenario evaluated")
    payment_id: str = Field(..., description="Payment entity identifier")
    total_iterations: int = Field(..., ge=0, description="Total execution cycles executed")
    final_state: str = Field(..., description="Final reconciled payment aggregate state")
    is_recovered: bool = Field(..., description="Whether revenue was successfully recovered")
    recovered_amount_paise: int = Field(default=0, ge=0, description="Amount recovered in paise")
    total_cost_paise: int = Field(default=0, ge=0, description="Total action costs incurred in paise")
    net_value_paise: int = Field(..., description="Net recovered value in paise (Recovered - Cost)")
    stop_reason: str = Field(..., description="Reason the closed-loop agent halted")
    trace: List[AgentIterationRecord] = Field(default_factory=list, description="Step-by-step audit history")


class AgentRuntime:
    """Closed-loop recovery controller connecting Ingestion, Intelligence, Policy, Governor, Scheduler, Firewall, and Execution."""

    def __init__(
        self,
        ingestion_service: Optional[IngestionService] = None,
        risk_detector: Optional[RiskDetector] = None,
        diagnosis_provider: Optional[BaseDiagnosisProvider] = None,
        policy: Optional[BasePolicy] = None,
        governor: Optional[RecoveryGovernor] = None,
        scheduler: Optional[ScheduledLifecycleService] = None,
        firewall: Optional[ToolFirewall] = None,
        executor: Optional[RecoveryExecutor] = None,
        max_iterations: int = 5,
    ) -> None:
        from intelligence.providers.llm_provider import LLMDiagnosisProvider
        from rag.retrieval import RecoveryMemoryRetriever

        self.ingestion_service = ingestion_service or IngestionService()
        self.risk_detector = risk_detector or RiskDetector()
        self.diagnosis_provider = diagnosis_provider or LLMDiagnosisProvider(fallback_provider=DeterministicDiagnosisProvider())
        self.policy = policy or DeterministicRecoveryPolicy(diagnosis_provider=self.diagnosis_provider)
        self.governor = governor or RecoveryGovernor()
        self.scheduler = scheduler or ScheduledLifecycleService()
        self.firewall = firewall or ToolFirewall()
        self.executor = executor or SimulatorExecutor()
        self.retriever = RecoveryMemoryRetriever()
        self.max_iterations = max_iterations

    async def run_recovery_loop(
        self,
        initial_scenario: SimulatedScenario,
        consent: Optional[CustomerConsentContext] = None,
        policy_healthy: bool = True,
    ) -> AgentRunResult:
        """Execute the closed-loop recovery sequence for an incoming payment failure event."""
        # 1. Ingest initial failure event into the system
        await self.ingestion_service.process_webhook(initial_scenario.webhook_payload)

        payment_id = initial_scenario.event.payment.id if initial_scenario.event.payment else "pay_unknown"
        trace: List[AgentIterationRecord] = []
        recovered_amount = 0
        total_costs = 0
        stop_reason = "MAX_ITERATIONS_REACHED"

        current_event = initial_scenario.event
        current_payload = initial_scenario.webhook_payload

        for iteration in range(1, self.max_iterations + 1):
            current_epoch = int(current_payload.created_at) + ((iteration - 1) * 3600)

            # A. State Reconstruction (Observe)
            aggregate = await self.ingestion_service.event_store.get_payment_aggregate(payment_id)
            current_state = aggregate.current_state if aggregate else PaymentState.FAILED

            # B. Terminal State Early Exit Check
            if aggregate and aggregate.is_terminal:
                if aggregate.current_state == PaymentState.CAPTURED:
                    recovered_amount = aggregate.amount
                    stop_reason = "TERMINAL_STATE_REACHED"
                else:
                    stop_reason = "TERMINAL_STATE_REACHED"
                break

            # C. Risk Assessment
            risk = self.risk_detector.detect_payment_risk(current_event.payment, aggregate)
            if not risk.is_at_risk:
                stop_reason = "NO_RISK_DETECTED"
                break

            # D. Observable Context Construction & Bounded RAG Memory Retrieval
            obs_context = ObservableContextBuilder.build_from_payment_event(
                event=current_event,
                aggregate=aggregate,
                customer_consent=consent,
                attempt_count=iteration,
                scenario_id=initial_scenario.scenario_id,
            )
            memory_bundle = self.retriever.retrieve_bounded_context(obs_context)

            # E. Intelligence Diagnosis & Policy Proposal
            try:
                if not policy_healthy:
                    raise PolicyOutageError("Policy decision engine is flagged unhealthy. Failing closed.")

                diagnosis = await self.diagnosis_provider.diagnose(obs_context, memory_bundle)
                proposal = self.policy.decide(obs_context, diagnosis=diagnosis)
            except PolicyOutageError as e:
                # Policy Outage Fail-Closed: Pass through Governor to record governance decision
                gov_decision = self.governor.evaluate(
                    context=obs_context,
                    diagnosis=None,
                    proposal=None,
                    aggregate=aggregate,
                    consent=consent,
                    policy_healthy=False,
                )
                fallback_decision = PolicyDecision(
                    action_type=SimulatedActionType.NO_ACTION,
                    confidence=1.0,
                    rationale="Policy engine unavailable. Failing closed.",
                    policy_name="GOVERNOR_FAIL_CLOSED",
                    reason_codes=["POLICY_OUTAGE_FAIL_CLOSED"],
                )
                record = AgentIterationRecord(
                    iteration=iteration,
                    risk_assessment=risk,
                    decision=fallback_decision,
                    diagnosis=None,
                    governor_decision=gov_decision,
                    execution_result=None,
                    aggregate_state_before=current_state.value,
                    aggregate_state_after=current_state.value,
                    aggregate_state=current_state.value,
                    timestamp_epoch=current_epoch,
                    error_message=str(e),
                )
                trace.append(record)
                stop_reason = gov_decision.stop_reason or "POLICY_OUTAGE"
                break

            # F. Recovery Governor Evaluation (Authority Check with Timing Validation)
            gov_decision = self.governor.evaluate(
                context=obs_context,
                diagnosis=diagnosis,
                proposal=proposal,
                aggregate=aggregate,
                consent=consent,
                policy_healthy=policy_healthy,
            )

            if gov_decision.decision_result != GovernorDecisionResult.ALLOW:
                record = AgentIterationRecord(
                    iteration=iteration,
                    risk_assessment=risk,
                    decision=proposal,
                    diagnosis=diagnosis,
                    governor_decision=gov_decision,
                    execution_result=None,
                    aggregate_state_before=current_state.value,
                    aggregate_state_after=current_state.value,
                    aggregate_state=current_state.value,
                    timestamp_epoch=current_epoch,
                    error_message=gov_decision.human_review_reason if gov_decision.decision_result == GovernorDecisionResult.ESCALATE else (gov_decision.rationale if gov_decision.decision_result == GovernorDecisionResult.DENY else None),
                )
                trace.append(record)
                stop_reason = gov_decision.stop_reason or "GOVERNOR_BLOCKED"
                break

            # G. Timing Selection: Delayed Action Scheduling vs Immediate Execution
            is_delayed = (
                gov_decision.delay_seconds > 0
                or gov_decision.timing_window in ("PLUS_2H", "PLUS_6H", "PLUS_12H", "PLUS_24H")
                or proposal.action_type == SimulatedActionType.RETRY_LATER
            )

            if is_delayed:
                # Schedule future action bound to current state version and exit cycle
                try:
                    timing_win = TimingWindow(gov_decision.timing_window) if gov_decision.timing_window else TimingWindow.PLUS_6H
                except (ValueError, KeyError, TypeError):
                    timing_win = TimingWindow.PLUS_6H

                scheduled_action = self.scheduler.schedule_action(
                    decision=proposal,
                    context=obs_context,
                    aggregate=aggregate,
                    policy=self.governor.merchant_policy,
                    current_epoch=current_epoch,
                    timing_window=timing_win,
                    delay_seconds=gov_decision.delay_seconds if gov_decision.delay_seconds > 0 else timing_win.delay_seconds,
                )

                record = AgentIterationRecord(
                    iteration=iteration,
                    risk_assessment=risk,
                    decision=proposal,
                    diagnosis=diagnosis,
                    governor_decision=gov_decision,
                    execution_result=None,
                    aggregate_state_before=current_state.value,
                    aggregate_state_after=current_state.value,
                    aggregate_state=current_state.value,
                    timestamp_epoch=current_epoch,
                )
                trace.append(record)
                stop_reason = "ACTION_SCHEDULED"
                break

            # H. Immediate Action: Stale Action Protection (Revalidate aggregate before execution)
            aggregate = await self.ingestion_service.event_store.get_payment_aggregate(payment_id)
            if aggregate and aggregate.is_terminal:
                record = AgentIterationRecord(
                    iteration=iteration,
                    risk_assessment=risk,
                    decision=proposal,
                    diagnosis=diagnosis,
                    governor_decision=gov_decision,
                    execution_result=None,
                    aggregate_state_before=current_state.value,
                    aggregate_state_after=aggregate.current_state.value,
                    aggregate_state=aggregate.current_state.value,
                    timestamp_epoch=current_epoch,
                )
                trace.append(record)
                stop_reason = "STALE_ACTION_PREVENTED"
                if aggregate.current_state == PaymentState.CAPTURED:
                    recovered_amount = aggregate.amount
                break

            # I. Tool Firewall Validation Gate (Independent Pre-Execution Verification)
            chosen_action = gov_decision.selected_action or proposal.action_type
            execution_key = f"exec_{payment_id}_{iteration}_{chosen_action.value}_{current_epoch}"
            try:
                validated_action = self.firewall.validate_and_gate(
                    action=chosen_action,
                    execution_key=execution_key,
                    consent=consent,
                    policy_healthy=policy_healthy,
                )
            except (ActionBlockedError, ConsentViolationError, SchemaValidationError, DuplicateExecutionError, PolicyOutageError) as e:
                record = AgentIterationRecord(
                    iteration=iteration,
                    risk_assessment=risk,
                    decision=proposal,
                    diagnosis=diagnosis,
                    governor_decision=gov_decision,
                    execution_result=None,
                    aggregate_state_before=current_state.value,
                    aggregate_state_after=current_state.value,
                    aggregate_state=current_state.value,
                    timestamp_epoch=current_epoch,
                    error_message=str(e),
                )
                trace.append(record)
                if isinstance(e, ConsentViolationError):
                    stop_reason = "ACTION_BLOCKED"
                elif isinstance(e, PolicyOutageError):
                    stop_reason = "POLICY_OUTAGE"
                else:
                    stop_reason = "ACTION_BLOCKED"
                break

            # J. Dispatch Execution with Fault Tolerance Handling
            current_scenario = SimulatedScenario(
                scenario_id=initial_scenario.scenario_id,
                customer=initial_scenario.customer,
                event=current_event,
                webhook_payload=current_payload,
                archetype=initial_scenario.archetype,
                failure_class=initial_scenario.failure_class,
                hidden_outcomes=initial_scenario.hidden_outcomes,
            )
            exec_ctx = ExecutionContext(
                scenario=current_scenario,
                attempt_count=iteration,
                current_epoch=current_epoch,
            )
            try:
                exec_result = await self.executor.execute(validated_action, exec_ctx)
            except (TimeoutError, ConnectionError, PolicyOutageError, RuntimeError, httpx.RequestError, httpx.HTTPError) as e:
                record = AgentIterationRecord(
                    iteration=iteration,
                    risk_assessment=risk,
                    decision=proposal,
                    diagnosis=diagnosis,
                    governor_decision=gov_decision,
                    execution_result=None,
                    aggregate_state_before=current_state.value,
                    aggregate_state_after=current_state.value,
                    aggregate_state=current_state.value,
                    timestamp_epoch=current_epoch,
                    error_message=f"{type(e).__name__}: {str(e)}",
                )
                trace.append(record)
                if isinstance(e, PolicyOutageError):
                    stop_reason = "POLICY_OUTAGE"
                else:
                    stop_reason = "EXECUTION_FAILURE"
                break

            total_costs += exec_result.action_cost_paise

            # K. Ingest resulting event into event store & update aggregate
            if exec_result.resulting_payload:
                await self.ingestion_service.process_webhook(exec_result.resulting_payload)
                current_payload = exec_result.resulting_payload
                if exec_result.resulting_event:
                    current_event = exec_result.resulting_event

            updated_agg = await self.ingestion_service.event_store.get_payment_aggregate(payment_id)
            new_state = updated_agg.current_state.value if updated_agg else current_state.value

            record = AgentIterationRecord(
                iteration=iteration,
                risk_assessment=risk,
                decision=proposal,
                diagnosis=diagnosis,
                governor_decision=gov_decision,
                execution_result=exec_result,
                aggregate_state_before=current_state.value,
                aggregate_state_after=new_state,
                aggregate_state=new_state,
                timestamp_epoch=current_epoch,
            )
            trace.append(record)

            if exec_result.recovered:
                recovered_amount = exec_result.recovered_amount_paise
                stop_reason = "REVENUE_RECOVERED"
                break

        # Final aggregate inspection
        final_agg = await self.ingestion_service.event_store.get_payment_aggregate(payment_id)
        final_state_str = final_agg.current_state.value if final_agg else PaymentState.FAILED.value
        is_recovered = final_state_str == PaymentState.CAPTURED.value

        return AgentRunResult(
            scenario_id=initial_scenario.scenario_id,
            payment_id=payment_id,
            total_iterations=len(trace),
            final_state=final_state_str,
            is_recovered=is_recovered,
            recovered_amount_paise=recovered_amount,
            total_cost_paise=total_costs,
            net_value_paise=recovered_amount - total_costs,
            stop_reason=stop_reason,
            trace=trace,
        )

    async def execute_due_scheduled_action(
        self,
        scheduled_action_id: str,
        scenario: SimulatedScenario,
        current_epoch: int,
        consent: Optional[CustomerConsentContext] = None,
    ) -> Tuple[ScheduledAction, Optional[ExecutionResult]]:
        """Revalidate state, pass through tool firewall, and execute a due scheduled action."""
        action = self.scheduler.store.get(scheduled_action_id)
        if not action:
            raise ValueError(f"Scheduled action '{scheduled_action_id}' not found.")

        payment_id = action.payment_id
        aggregate = await self.ingestion_service.event_store.get_payment_aggregate(payment_id)

        # 1. Revalidation check
        is_valid, invalidation_reason, codes = self.scheduler.revalidate_and_check_executable(
            scheduled_action=action,
            current_aggregate=aggregate,
            consent=consent,
            current_epoch=current_epoch,
            policy=self.governor.merchant_policy,
        )

        if not is_valid:
            if "TIMING_EXPIRED_BEFORE_EXECUTION" in codes or "ACTION_EXPIRED" in codes:
                expired_action = self.scheduler.expire_action(scheduled_action_id, reason=invalidation_reason or "Expired")
                return (expired_action, None)
            invalidated_action = self.scheduler.invalidate_action(
                scheduled_action_id,
                reason=invalidation_reason or "Invalidated",
                reason_codes=codes,
            )
            return (invalidated_action, None)

        # 2. Tool Firewall Gate
        execution_key = action.idempotency_key
        validated_action = self.firewall.validate_and_gate(
            action=action.action_type,
            execution_key=execution_key,
            consent=consent,
        )

        # 3. Execution dispatch
        exec_ctx = ExecutionContext(
            scenario=scenario,
            attempt_count=2,
            current_epoch=current_epoch,
        )
        exec_result = await self.executor.execute(validated_action, exec_ctx)

        # 4. Ingest outcome
        if exec_result.resulting_payload:
            await self.ingestion_service.process_webhook(exec_result.resulting_payload)

        # 5. Mark executed
        executed_action = self.scheduler.mark_executed(scheduled_action_id, execution_key=execution_key)
        return (executed_action, exec_result)
