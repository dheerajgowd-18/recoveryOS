"""AgentRuntime orchestrating the closed-loop observe-decide-execute-observe recovery cycle."""
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from agent.risk import RiskAssessment, RiskDetector
from backend.services.ingestion_service import IngestionService
from domain.enums import PaymentState
from execution.executor import ExecutionContext, ExecutionResult, RecoveryExecutor
from execution.simulator_executor import SimulatorExecutor
from policy.base import BasePolicy, PolicyDecision
from policy.deterministic import DeterministicRecoveryPolicy
from policy.public_view import PublicScenarioView
from simulator.config import SimulatedActionType
from simulator.generator import SimulatedScenario


class AgentIterationRecord(BaseModel):
    """Step-level trace recording an individual cycle in the agent runtime loop."""
    model_config = ConfigDict(extra="forbid")

    iteration: int = Field(..., description="Cycle index (1-based)")
    risk_assessment: RiskAssessment = Field(..., description="Risk detection outcome")
    decision: PolicyDecision = Field(..., description="Action selected by policy")
    execution_result: Optional[ExecutionResult] = Field(default=None, description="Executor result if dispatched")
    aggregate_state: str = Field(..., description="Payment aggregate state after this cycle")
    timestamp_epoch: int = Field(..., description="Epoch timestamp of cycle")


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
    """Closed-loop recovery controller connecting Ingestion, Risk Detection, Policy, and Execution."""

    def __init__(
        self,
        ingestion_service: Optional[IngestionService] = None,
        policy: Optional[BasePolicy] = None,
        executor: Optional[RecoveryExecutor] = None,
        risk_detector: Optional[RiskDetector] = None,
        max_iterations: int = 5,
    ) -> None:
        self.ingestion_service = ingestion_service or IngestionService()
        self.policy = policy or DeterministicRecoveryPolicy()
        self.executor = executor or SimulatorExecutor()
        self.risk_detector = risk_detector or RiskDetector()
        self.max_iterations = max_iterations

    async def run_recovery_loop(self, initial_scenario: SimulatedScenario) -> AgentRunResult:
        """Execute the bounded, state-guarded recovery loop until resolution, abstention, or limit exhaustion."""
        current_scenario = initial_scenario
        current_event = initial_scenario.event
        current_payload = initial_scenario.webhook_payload
        payment_id = current_event.payment.id if current_event.payment else f"pay_sim_{initial_scenario.scenario_id}"

        # 1. Ingest initial failure event
        await self.ingestion_service.process_webhook(current_payload)

        trace: List[AgentIterationRecord] = []
        iteration = 0
        total_costs = 0
        recovered_amount = 0
        stop_reason = "MAX_ITERATIONS_REACHED"

        while iteration < self.max_iterations:
            iteration += 1
            current_epoch = current_payload.created_at + (iteration * 3600)

            # A. Fetch current reconciled aggregate
            aggregate = await self.ingestion_service.event_store.get_payment_aggregate(payment_id)
            current_state = aggregate.current_state if aggregate else PaymentState.FAILED

            # B. Check Terminal State Guard
            if aggregate and aggregate.is_terminal:
                is_recovered = aggregate.current_state == PaymentState.CAPTURED
                if is_recovered:
                    recovered_amount = aggregate.amount
                stop_reason = "TERMINAL_STATE_REACHED" if is_recovered else "TERMINAL_REFUNDED"
                break

            # C. Detect Risk
            risk = self.risk_detector.detect_payment_risk(current_event.payment, aggregate)
            if not risk.is_at_risk:
                stop_reason = "NO_RISK_DETECTED"
                break

            # D. Construct Sanitized Public Scenario View
            public_view = PublicScenarioView(
                scenario_id=current_scenario.scenario_id,
                failure_class=current_scenario.failure_class,
                failure_code=current_event.payment.error_code if current_event.payment else None,
                error_description=current_event.payment.error_description if current_event.payment else None,
                error_source=current_event.payment.error_source if current_event.payment else None,
                error_step=current_event.payment.error_step if current_event.payment else None,
                error_reason=current_event.payment.error_reason if current_event.payment else None,
                amount_in_paise=current_event.payment.amount if current_event.payment else 0,
                currency=current_event.payment.currency if current_event.payment else "INR",
                attempt_count=iteration,
                customer_id=current_event.payment.customer_id if current_event.payment else None,
                payment_id=payment_id,
                payment_method=current_event.payment.method if current_event.payment else "card",
            )

            # E. Policy Decision
            decision = self.policy.decide(public_view)

            # F. Abstention Check
            if decision.action_type == SimulatedActionType.NO_ACTION:
                record = AgentIterationRecord(
                    iteration=iteration,
                    risk_assessment=risk,
                    decision=decision,
                    execution_result=None,
                    aggregate_state=current_state.value,
                    timestamp_epoch=current_epoch,
                )
                trace.append(record)
                stop_reason = "POLICY_ABSTAINED"
                break

            # G. Stale Action Protection (Revalidate aggregate before execution)
            aggregate = await self.ingestion_service.event_store.get_payment_aggregate(payment_id)
            if aggregate and aggregate.is_terminal:
                record = AgentIterationRecord(
                    iteration=iteration,
                    risk_assessment=risk,
                    decision=decision,
                    execution_result=None,
                    aggregate_state=aggregate.current_state.value,
                    timestamp_epoch=current_epoch,
                )
                trace.append(record)
                stop_reason = "STALE_ACTION_PREVENTED"
                if aggregate.current_state == PaymentState.CAPTURED:
                    recovered_amount = aggregate.amount
                break

            # H. Dispatch Execution
            context = ExecutionContext(
                scenario=current_scenario,
                attempt_count=iteration,
                current_epoch=current_epoch,
            )
            exec_result = await self.executor.execute(decision.action_type, context)
            total_costs += exec_result.action_cost_paise

            # I. Ingest resulting event into event store & update aggregate
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
                decision=decision,
                execution_result=exec_result,
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
