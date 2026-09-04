"""AgentRuntime compatibility wrapper delegating canonical orchestration to RecoveryStateGraph."""
from typing import List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from agent.agents import DiagnosisAgent, TimingAndEconomicOptimizationAgent
from agent.graph import RecoveryStateGraph, RecoveryWorkflowState
from agent.risk import RiskAssessment, RiskDetector
from backend.services.ingestion_service import IngestionService
from domain.enums import PaymentState
from execution.executor import ExecutionContext, ExecutionResult, RecoveryExecutor
from execution.simulator_executor import SimulatorExecutor
from governor.decision import GovernorDecision, GovernorDecisionResult
from governor.firewall import CustomerConsentContext, ToolFirewall
from governor.recovery_governor import RecoveryGovernor
from intelligence.providers import BaseDiagnosisProvider, DeterministicDiagnosisProvider
from intelligence.schemas import StructuredDiagnosis
from policy.base import BasePolicy, PolicyDecision
from policy.deterministic import DeterministicRecoveryPolicy
from scheduler.models import ScheduledAction
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
    """Canonical recovery controller wrapper delegating closed-loop execution to RecoveryStateGraph.

    The canonical production execution path is RecoveryStateGraph (a stateful 10-node agent pipeline).
    AgentRuntime serves as a thin lifecycle wrapper driving multi-attempt iteration and legacy result packaging.
    """

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
        self.ingestion_service = ingestion_service or IngestionService()
        self.risk_detector = risk_detector or RiskDetector()
        self.diagnosis_provider = diagnosis_provider
        self.policy = policy
        self.governor = governor or RecoveryGovernor()
        self.scheduler = scheduler or ScheduledLifecycleService()
        self.firewall = firewall or ToolFirewall()
        self.executor = executor or SimulatorExecutor()
        self.max_iterations = max_iterations

        diag_agent = DiagnosisAgent(provider=self.diagnosis_provider) if self.diagnosis_provider else None
        timing_agent = (
            TimingAndEconomicOptimizationAgent(config=getattr(self.policy, "config", None))
            if self.policy and hasattr(self.policy, "config")
            else None
        )

        self.graph = RecoveryStateGraph(
            ingestion_service=self.ingestion_service,
            risk_detector=self.risk_detector,
            diagnosis_agent=diag_agent,
            timing_agent=timing_agent,
            governor=self.governor,
            scheduler=self.scheduler,
            firewall=self.firewall,
            executor=self.executor,
            policy=self.policy,
        )
        self.state_graph = self.graph

    async def run_recovery_loop(
        self,
        initial_scenario: SimulatedScenario,
        consent: Optional[CustomerConsentContext] = None,
        policy_healthy: bool = True,
    ) -> AgentRunResult:
        """Executes the closed-loop recovery sequence by delegating step execution to RecoveryStateGraph."""
        payment_id = initial_scenario.event.payment.id if initial_scenario.event.payment else "pay_unknown"
        trace: List[AgentIterationRecord] = []
        recovered_amount = 0
        total_costs = 0
        stop_reason = "MAX_ITERATIONS_REACHED"
        current_state_val = PaymentState.FAILED.value

        for iteration in range(1, self.max_iterations + 1):
            state: RecoveryWorkflowState = await self.graph.execute_workflow(
                initial_scenario=initial_scenario,
                consent=consent,
                policy_healthy=policy_healthy,
                attempt_count=iteration,
            )

            current_state = state.aggregate.current_state if state.aggregate else PaymentState.FAILED
            current_state_val = current_state.value
            exec_cost = state.execution_result.action_cost_paise if state.execution_result else 0
            total_costs += exec_cost

            if state.aggregate and state.aggregate.current_state == PaymentState.CAPTURED:
                recovered_amount = state.aggregate.amount
            elif state.execution_result and state.execution_result.recovered:
                recovered_amount = state.execution_result.recovered_amount_paise

            # Extract aggregate state before this node cycle
            state_before = PaymentState.FAILED.value
            if state.step_traces:
                for step in state.step_traces:
                    if step.step_name == "NODE_1_INGESTION_RECONCILIATION":
                        state_before = step.payload.get("state", state_before)
                        break

            record = AgentIterationRecord(
                iteration=iteration,
                risk_assessment=state.risk_assessment or RiskAssessment(is_at_risk=True, risk_level="LOW", reason="Autonomous cycle"),
                decision=state.proposal or PolicyDecision(
                    action_type=SimulatedActionType.NO_ACTION,
                    confidence=1.0,
                    rationale="Deliberate non-intervention or fallback",
                    policy_name="GOVERNOR_BASELINE",
                ),
                diagnosis=state.diagnosis,
                governor_decision=state.governor_decision,
                execution_result=state.execution_result,
                aggregate_state_before=state_before,
                aggregate_state_after=current_state_val,
                aggregate_state=current_state_val,
                timestamp_epoch=state.current_epoch,
                error_message=state.error_message,
            )
            trace.append(record)

            if state.is_terminal and state.stop_reason != "CYCLE_COMPLETED":
                stop_reason = state.stop_reason or "TERMINAL_STATE_REACHED"
                break
            elif iteration == self.max_iterations:
                stop_reason = state.stop_reason or "MAX_ITERATIONS_REACHED"
                break

        is_rec = (current_state_val == PaymentState.CAPTURED.value) or (recovered_amount > 0)
        net_val = recovered_amount - total_costs

        return AgentRunResult(
            scenario_id=initial_scenario.scenario_id,
            payment_id=payment_id,
            total_iterations=len(trace),
            final_state=current_state_val,
            is_recovered=is_rec,
            recovered_amount_paise=recovered_amount,
            total_cost_paise=total_costs,
            net_value_paise=net_val,
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
