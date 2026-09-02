"""Specialized reasoning agents for the RecoveryOS stateful recovery graph."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from agent.risk import RiskAssessment, RiskDetector
from domain.aggregates import PaymentAggregate
from domain.enums import PaymentState
from domain.events import PaymentEvent
from governor.decision import GovernorDecision
from governor.firewall import CustomerConsentContext
from governor.policy import MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableContextBuilder, ObservableRecoveryContext
from intelligence.providers.base import BaseDiagnosisProvider
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from planner.timing import (
    ActionMechanism,
    ActionTimingCandidate,
    DeterministicTimingValueEstimator,
    TimingCandidateGenerator,
    TimingWindow,
)
from policy.base import PolicyDecision
from policy.candidates import CandidateGenerator
from policy.config import DeterministicPolicyConfig
from policy.scoring import ExpectedValueScorer, ScoredAction
from rag.retrieval import RecoveryMemoryRetriever
from rag.schemas import BoundedContextBundle
from simulator.config import SimulatedActionType


class CandidateStrategyOption(BaseModel):
    """Candidate recovery strategy proposed by Strategy Agent."""
    model_config = ConfigDict(extra="forbid")

    action_type: SimulatedActionType = Field(..., description="Proposed recovery intervention")
    mechanism: ActionMechanism = Field(..., description="Intervention mechanism category")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Agent confidence in candidate viability")
    rationale: str = Field(..., description="Strategic reasoning justifying proposal")
    is_abstention: bool = Field(default=False, description="Whether this candidate represents deliberate non-intervention")


class ContextRetrievalAgent:
    """Agent 1: Assembles bounded observable decision context and retrieves recovery memory with provenance."""

    def __init__(self, memory_retriever: Optional[RecoveryMemoryRetriever] = None) -> None:
        self.retriever = memory_retriever or RecoveryMemoryRetriever()

    def execute(
        self,
        event: PaymentEvent,
        aggregate: Optional[PaymentAggregate] = None,
        consent: Optional[CustomerConsentContext] = None,
        attempt_count: int = 1,
        scenario_id: Optional[str] = None,
    ) -> tuple[ObservableRecoveryContext, BoundedContextBundle]:
        """Constructs sanitized observable context and retrieves bounded decision-relevant memory bundle."""
        obs_context = ObservableContextBuilder.build_from_payment_event(
            event=event,
            aggregate=aggregate,
            customer_consent=consent,
            attempt_count=attempt_count,
            scenario_id=scenario_id,
        )
        memory_bundle = self.retriever.retrieve_bounded_context(obs_context)
        return obs_context, memory_bundle


class DiagnosisAgent:
    """Agent 2: Root-Cause Diagnosis Reasoner with explicit uncertainty detection and real LLM reasoning."""

    def __init__(self, provider: Optional[BaseDiagnosisProvider] = None) -> None:
        if provider is None:
            from intelligence.providers.llm_provider import LLMDiagnosisProvider
            self.provider = LLMDiagnosisProvider(fallback_provider=DeterministicDiagnosisProvider())
        else:
            self.provider = provider

    async def diagnose_async(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StructuredDiagnosis:
        """Produces structured, explainable diagnosis asynchronously using LLM + bounded memory."""
        return await self.provider.diagnose(context, memory_bundle)

    def diagnose_sync(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StructuredDiagnosis:
        """Produces structured, explainable diagnosis synchronously."""
        return self.provider.diagnose_sync(context, memory_bundle)


class RecoveryStrategyAgent:
    """Agent 3: Proposes candidate recovery interventions without authorizing execution."""

    def __init__(self, config: Optional[DeterministicPolicyConfig] = None) -> None:
        self.config = config or DeterministicPolicyConfig()

    def generate_strategy_candidates(
        self,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> List[CandidateStrategyOption]:
        """Generates admissible candidate intervention options synthesizing LLM diagnosis, RAG memory, and policy rules."""
        candidates: List[CandidateStrategyOption] = []

        # 1. First-Class Abstention Candidate (Always considered)
        candidates.append(
            CandidateStrategyOption(
                action_type=SimulatedActionType.NO_ACTION,
                mechanism=ActionMechanism.NO_ACTION,
                confidence=1.0,
                rationale="Zero-cost natural recovery baseline; prevents unnecessary customer fatigue and gateway fees.",
                is_abstention=True,
            )
        )

        # 2. Candidate generation based on failure taxonomy, LLM proposals, and constraints
        admissible_actions = CandidateGenerator.generate_candidates(context, diagnosis, self.config)

        # Merge LLM recommended actions if admissible under merchant constraints
        llm_recommended = getattr(diagnosis, "recommended_candidate_actions", [])
        for act in llm_recommended:
            if isinstance(act, SimulatedActionType) and act not in admissible_actions:
                # Validate against physical impossibility constraints
                if act in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER) and diagnosis.diagnosis_label == DiagnosisLabel.EXPIRED_PAYMENT_METHOD:
                    continue
                if act in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER) and context.attempt_count >= self.config.max_retry_attempts:
                    continue
                admissible_actions.append(act)

        # Check customer preference / historical response from memory bundle
        preferred_channel = None
        if memory_bundle and memory_bundle.customer_summary:
            preferred_channel = memory_bundle.customer_summary.get("preferred_channel")

        for act in admissible_actions:
            if act == SimulatedActionType.NO_ACTION:
                continue

            mech = ActionMechanism.RETRY if act in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER) else (
                ActionMechanism.PAYMENT_LINK if act == SimulatedActionType.PAYMENT_LINK else ActionMechanism.REMINDER
            )

            # Build explainable rationale incorporating evidence and RAG context
            evidence_str = ", ".join(diagnosis.evidence_codes[:2]) if diagnosis.evidence_codes else "observed error patterns"
            if act in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER):
                strat_rationale = (
                    f"Automated bank retry proposed for {diagnosis.diagnosis_label.value} failure "
                    f"based on evidence [{evidence_str}]."
                )
            elif act == SimulatedActionType.PAYMENT_LINK:
                strat_rationale = (
                    f"Direct customer payment link proposed to collect updated payment instrument "
                    f"for {diagnosis.diagnosis_label.value}."
                )
            else:
                channel_note = f" via {preferred_channel}" if preferred_channel else ""
                strat_rationale = (
                    f"Customer notification reminder proposed{channel_note} "
                    f"addressing {diagnosis.diagnosis_label.value}."
                )

            candidates.append(
                CandidateStrategyOption(
                    action_type=act,
                    mechanism=mech,
                    confidence=diagnosis.confidence,
                    rationale=strat_rationale,
                    is_abstention=False,
                )
            )

        return candidates


class TimingReasonerAgent:
    """Agent 4: Evaluates and compares discrete execution timing windows for recovery actions."""

    def __init__(self, config: Optional[DeterministicPolicyConfig] = None) -> None:
        self.config = config or DeterministicPolicyConfig()

    def evaluate_timing_options(
        self,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        strategy_candidates: List[CandidateStrategyOption],
    ) -> List[ActionTimingCandidate]:
        """Computes deterministic expected net recovery values across (Mechanism × Timing Window) matrix."""
        timing_candidates = TimingCandidateGenerator.generate_candidates(context, diagnosis, self.config)
        scored_timings = DeterministicTimingValueEstimator.estimate_all(
            context=context,
            diagnosis=diagnosis,
            candidates=timing_candidates,
            config=self.config,
        )
        return scored_timings


class OutcomeVerificationAgent:
    """Agent 5: Deterministic event reconciliation and outcome verification (strictly non-fabricated)."""

    @staticmethod
    def verify_state_transition(
        aggregate_before: Optional[PaymentAggregate],
        aggregate_after: Optional[PaymentAggregate],
        execution_success: bool,
    ) -> Dict[str, Any]:
        """Interprets verified outcome from domain event store state."""
        state_before = aggregate_before.current_state if aggregate_before else PaymentState.FAILED
        state_after = aggregate_after.current_state if aggregate_after else state_before

        is_captured = state_after == PaymentState.CAPTURED
        is_recovered = is_captured and (state_before != PaymentState.CAPTURED)

        return {
            "state_before": state_before.value,
            "state_after": state_after.value,
            "is_recovered": is_recovered,
            "recovered_amount_paise": aggregate_after.amount if (aggregate_after and is_captured) else 0,
            "is_terminal": aggregate_after.is_terminal if aggregate_after else False,
            "state_version": aggregate_after.version if aggregate_after else 1,
            "verification_status": "CAPTURED" if is_captured else ("FAILED" if state_after == PaymentState.FAILED else state_after.value),
        }
