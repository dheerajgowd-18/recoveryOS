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
from intelligence.schemas import (
    DiagnosisLabel,
    StrategyCandidateProposal,
    StrategyProposal,
    StructuredDiagnosis,
)
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
    supporting_evidence: List[str] = Field(default_factory=list, description="Evidence references supporting candidate")
    risk_notes: List[str] = Field(default_factory=list, description="Constraint or fatigue risk notes")
    preferred_timing_direction: Optional[str] = Field(default=None, description="Preferred timing window hint")
    preferred_channel: Optional[str] = Field(default=None, description="Preferred delivery channel")


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
    """Agent 2: Root-Cause Diagnosis Reasoner with explicit uncertainty detection and real Groq LLM reasoning."""

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
        """Produces structured, explainable diagnosis asynchronously using Groq LLM + bounded memory."""
        return await self.provider.diagnose(context, memory_bundle)

    def diagnose_sync(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StructuredDiagnosis:
        """Produces structured, explainable diagnosis synchronously checking replay cache before live API."""
        return self.provider.diagnose_sync(context, memory_bundle)


class RecoveryStrategyAgent:
    """Agent 3: Strategic Decision Reasoner proposing candidate recovery interventions via Groq LLM without authorizing execution.

    Synthesizes:
    - Root cause diagnosis and uncertainty
    - Bounded recovery memory (Customer history, Merchant playbooks, Operational counters)
    - Merchant constraints (Max retries, contact fatigue caps, amount limits)
    - First-class strategic abstention (NO_ACTION)
    """

    def __init__(
        self,
        provider: Optional[Any] = None,
        strategy_provider: Optional[Any] = None,
        config: Optional[DeterministicPolicyConfig] = None,
    ) -> None:
        self.config = config or DeterministicPolicyConfig()
        active_provider = provider or strategy_provider
        if active_provider is None:
            from intelligence.providers.strategy_provider import (
                DeterministicStrategyProvider,
                LLMStrategyProvider,
            )
            fallback = DeterministicStrategyProvider(config=self.config)
            self.provider = LLMStrategyProvider(fallback_provider=fallback)
        else:
            self.provider = active_provider

    async def propose_strategy_async(
        self,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StrategyProposal:
        """Asynchronously produces structured strategy proposals using Groq LLM + bounded memory."""
        admissible = CandidateGenerator.generate_candidates(context, diagnosis, self.config)
        return await self.provider.propose(
            context=context,
            diagnosis=diagnosis,
            memory_bundle=memory_bundle,
            admissible_actions=admissible,
            constraints=self.config.model_dump(),
        )

    def propose_strategy(
        self,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StrategyProposal:
        """Synchronously produces structured strategy proposals checking replay cache before live API."""
        admissible = CandidateGenerator.generate_candidates(context, diagnosis, self.config)
        return self.provider.propose_sync(
            context=context,
            diagnosis=diagnosis,
            memory_bundle=memory_bundle,
            admissible_actions=admissible,
            constraints=self.config.model_dump(),
        )

    def generate_strategy_candidates_from_proposal(
        self,
        proposal: StrategyProposal,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> List[CandidateStrategyOption]:
        """Maps an already-produced StrategyProposal into deterministic CandidateStrategyOption list without re-invoking the LLM."""
        candidates: List[CandidateStrategyOption] = []
        admissible = CandidateGenerator.generate_candidates(context, diagnosis, self.config)
        admissible_set = set(admissible)

        for p in proposal.proposals:
            # Deterministic Admissibility Check: Hard constraint & physical impossibility filter
            if p.action_type not in admissible_set and p.action_type != SimulatedActionType.NO_ACTION:
                continue

            if p.action_type in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER):
                if diagnosis.diagnosis_label == DiagnosisLabel.EXPIRED_PAYMENT_METHOD:
                    continue
                if context.attempt_count >= self.config.max_retry_attempts:
                    continue

            mech = (
                ActionMechanism.NO_ACTION if p.action_type == SimulatedActionType.NO_ACTION else (
                    ActionMechanism.RETRY if p.action_type in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER) else (
                        ActionMechanism.PAYMENT_LINK if p.action_type == SimulatedActionType.PAYMENT_LINK else ActionMechanism.REMINDER
                    )
                )
            )
            candidates.append(
                CandidateStrategyOption(
                    action_type=p.action_type,
                    mechanism=mech,
                    confidence=p.confidence,  # Model-reported strategy confidence
                    rationale=p.rationale,
                    is_abstention=p.is_abstention,
                    supporting_evidence=p.supporting_evidence,
                    risk_notes=p.risk_notes,
                    preferred_timing_direction=p.preferred_timing_direction,
                    preferred_channel=p.preferred_channel,
                )
            )

        # Guarantee first-class abstention is always present
        if not any(c.action_type == SimulatedActionType.NO_ACTION for c in candidates):
            candidates.insert(
                0,
                CandidateStrategyOption(
                    action_type=SimulatedActionType.NO_ACTION,
                    mechanism=ActionMechanism.NO_ACTION,
                    confidence=1.0,
                    rationale="Zero-cost natural recovery baseline; prevents unnecessary customer fatigue and gateway fees.",
                    is_abstention=True,
                ),
            )

        # Deterministic Search-Space Preservation:
        # LLM omission must not suppress deterministically admissible actions from economic valuation.
        proposed_action_types = {c.action_type for c in candidates}
        for adm_action in admissible:
            if adm_action in proposed_action_types:
                continue
            if adm_action in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER):
                if diagnosis.diagnosis_label == DiagnosisLabel.EXPIRED_PAYMENT_METHOD:
                    continue
                if context.attempt_count >= self.config.max_retry_attempts:
                    continue

            mech = (
                ActionMechanism.NO_ACTION if adm_action == SimulatedActionType.NO_ACTION else (
                    ActionMechanism.RETRY if adm_action in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER) else (
                        ActionMechanism.PAYMENT_LINK if adm_action == SimulatedActionType.PAYMENT_LINK else ActionMechanism.REMINDER
                    )
                )
            )
            candidates.append(
                CandidateStrategyOption(
                    action_type=adm_action,
                    mechanism=mech,
                    confidence=0.50,
                    rationale=f"Deterministically admissible fallback candidate ({adm_action.value}) preserved in economic search space.",
                    is_abstention=(adm_action == SimulatedActionType.NO_ACTION),
                    supporting_evidence=["DETERMINISTIC_SEARCH_SPACE_PRESERVED"],
                    risk_notes=[],
                )
            )

        return candidates

    def generate_strategy_candidates(
        self,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> List[CandidateStrategyOption]:
        """Produces StrategyProposal and maps it into CandidateStrategyOption list."""
        proposal = self.propose_strategy(context, diagnosis, memory_bundle)
        return self.generate_strategy_candidates_from_proposal(proposal, context, diagnosis, memory_bundle)


class TimingAndEconomicOptimizationAgent:
    """Agent 4: Timing & Deterministic Economic Optimization Agent.

    Evaluates the Action × Timing candidate matrix deterministically by calculating:
    - Expected gross recovery
    - Expected natural recovery baseline
    - Expected incremental recovery
    - Direct action execution costs
    - Customer contact friction & churn penalties
    - Expected Net Recovery Value
    """

    def __init__(self, config: Optional[DeterministicPolicyConfig] = None) -> None:
        self.config = config or DeterministicPolicyConfig()

    def evaluate_timing_options(
        self,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        strategy_candidates: List[CandidateStrategyOption],
    ) -> List[ActionTimingCandidate]:
        """Computes deterministic expected net recovery values across (Mechanism × Timing Window) matrix."""
        timing_candidates = TimingCandidateGenerator.generate_candidates(
            context=context,
            diagnosis=diagnosis,
            config=self.config,
            strategy_candidates=strategy_candidates,
        )
        scored_timings = DeterministicTimingValueEstimator.estimate_all(
            context=context,
            diagnosis=diagnosis,
            candidates=timing_candidates,
            config=self.config,
            strategy_candidates=strategy_candidates,
        )
        return scored_timings


# Alias for backward compatibility
TimingReasonerAgent = TimingAndEconomicOptimizationAgent


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
