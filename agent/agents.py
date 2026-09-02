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
    """Agent 3: Proposes candidate recovery interventions without authorizing execution.

    Synthesizes:
    - Root cause diagnosis and uncertainty
    - Bounded recovery memory (Customer history, Merchant playbooks, Operational counters)
    - Merchant constraints (Max retries, contact fatigue caps, amount limits)
    - First-class strategic abstention (NO_ACTION)
    """

    def __init__(self, config: Optional[DeterministicPolicyConfig] = None) -> None:
        self.config = config or DeterministicPolicyConfig()

    def propose_strategy(
        self,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StrategyProposal:
        """Generates comprehensive, structured StrategyProposal."""
        candidate_proposals: List[StrategyCandidateProposal] = []
        customer_summary = (memory_bundle.customer_summary or {}) if memory_bundle else {}
        merchant_guidelines = (memory_bundle.merchant_guidelines or {}) if memory_bundle else {}
        operational_context = (memory_bundle.operational_context or {}) if memory_bundle else {}

        # If summary dicts are empty, check retrieved items directly
        if memory_bundle and hasattr(memory_bundle, "retrieved_items"):
            for item in memory_bundle.retrieved_items:
                content = getattr(item, "content", {})
                if isinstance(content, dict):
                    if "is_vip" in content and "is_vip" not in customer_summary:
                        customer_summary["is_vip"] = content["is_vip"]
                    if "preferred_channel" in content and "preferred_channel" not in customer_summary:
                        customer_summary["preferred_channel"] = content["preferred_channel"]
                    if "prior_recovery_success_rate" in content and "prior_recovery_success_rate" not in customer_summary:
                        customer_summary["prior_recovery_success_rate"] = content["prior_recovery_success_rate"]
                    if "contacts_in_last_24h" in content and "contacts_in_last_24h" not in operational_context:
                        operational_context["contacts_in_last_24h"] = content["contacts_in_last_24h"]

        # Extract context signals
        is_vip = bool(customer_summary.get("is_vip", False))
        preferred_channel = customer_summary.get("preferred_channel", "email")
        prior_recovery_rate = float(customer_summary.get("prior_recovery_success_rate", 0.5))
        contacts_24h = int(operational_context.get("contacts_in_last_24h", context.contacts_in_last_24h or 0))
        is_fatigued = contacts_24h >= 2

        # 1. Strategic Baseline Abstention Candidate
        abstain_rationale = (
            "Zero-cost baseline preserving customer relationship and avoiding gateway fees. "
            + ("Recommended due to high contact fatigue." if is_fatigued else "Evaluated against organic recovery probability.")
        )
        candidate_proposals.append(
            StrategyCandidateProposal(
                action_type=SimulatedActionType.NO_ACTION,
                mechanism="no_action",
                rationale=abstain_rationale,
                confidence=1.0,
                supporting_evidence=["NATURAL_ORGANIC_BASELINE"] + (["CONTACT_FATIGUE_PREVENTION"] if is_fatigued else []),
                risk_notes=["Zero direct intervention; relies purely on organic customer settlement"],
                preferred_timing_direction="immediate",
                preferred_channel=None,
                why_better_than_abstain="N/A (Reference Baseline)",
                why_alternative_inferior="Active interventions incur execution fees and customer friction.",
                is_abstention=True,
            )
        )

        # 2. Admissible candidate generation
        admissible_actions = CandidateGenerator.generate_candidates(context, diagnosis, self.config)
        llm_recommended = getattr(diagnosis, "recommended_candidate_actions", [])
        for act in llm_recommended:
            if isinstance(act, SimulatedActionType) and act not in admissible_actions:
                if act in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER) and diagnosis.diagnosis_label == DiagnosisLabel.EXPIRED_PAYMENT_METHOD:
                    continue
                if act in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER) and context.attempt_count >= self.config.max_retry_attempts:
                    continue
                admissible_actions.append(act)

        for act in admissible_actions:
            if act == SimulatedActionType.NO_ACTION:
                continue

            supporting_evidence = list(diagnosis.evidence_codes)
            risk_notes = list(diagnosis.uncertainties)

            if act in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER):
                mech_str = "retry"
                timing_dir = "delay_6h" if act == SimulatedActionType.RETRY_LATER else "immediate"
                strat_rat = (
                    f"Automated bank retry proposed for {diagnosis.diagnosis_label.value}. "
                    f"Zero customer contact friction; executes silently in background."
                )
                why_better = "Recovers funds automatically without customer friction or payment link generation cost."
                why_inferior = "Futile on hard instrument failures (expired cards, blocked mandates)."
                conf = diagnosis.confidence
                if diagnosis.diagnosis_label == DiagnosisLabel.EXPIRED_PAYMENT_METHOD:
                    risk_notes.append("PHYSICAL_IMPOSSIBILITY: Instrument expired; bank retry guaranteed to fail.")
                    conf = 0.0

            elif act == SimulatedActionType.PAYMENT_LINK:
                mech_str = "payment_link"
                timing_dir = "immediate"
                if is_vip:
                    supporting_evidence.append("VIP_CUSTOMER_PRIORITY")
                strat_rat = (
                    f"Direct payment link dispatched via {preferred_channel} for {diagnosis.diagnosis_label.value}. "
                    f"Enables customer to authenticate new payment method."
                )
                why_better = "Empowers customer to swap expired or unfunded payment instrument immediately."
                why_inferior = "Higher execution cost (₹1.00) and small customer contact burden."
                conf = max(0.6, diagnosis.confidence * (1.1 if prior_recovery_rate > 0.7 else 0.9))

            else:  # REMINDER
                mech_str = "reminder"
                timing_dir = "delay_6h"
                if is_fatigued:
                    risk_notes.append("CONTACT_FATIGUE_WARNING: Customer has received multiple recent communications.")
                strat_rat = (
                    f"Gentle notification reminder dispatched via {preferred_channel} addressing {diagnosis.diagnosis_label.value}."
                )
                why_better = "Low-cost gentle prompt without intrusive direct checkout link."
                why_inferior = "Lower direct conversion than hosted payment link."
                conf = diagnosis.confidence * (0.5 if is_fatigued else 0.85)

            candidate_proposals.append(
                StrategyCandidateProposal(
                    action_type=act,
                    mechanism=mech_str,
                    rationale=strat_rat,
                    confidence=min(1.0, max(0.0, conf)),
                    supporting_evidence=supporting_evidence,
                    risk_notes=risk_notes,
                    preferred_timing_direction=timing_dir,
                    preferred_channel=preferred_channel if act != SimulatedActionType.RETRY_NOW else None,
                    why_better_than_abstain=why_better,
                    why_alternative_inferior=why_inferior,
                    is_abstention=False,
                )
            )

        # Determine primary candidate recommendation
        non_abstain = [c for c in candidate_proposals if not c.is_abstention and "PHYSICAL_IMPOSSIBILITY" not in str(c.risk_notes)]
        if non_abstain and diagnosis.confidence >= self.config.confidence_threshold and not diagnosis.abstain_recommended:
            primary_act = non_abstain[0].action_type
            summary = f"Strategy Agent recommends '{primary_act.value}' with {len(candidate_proposals)} candidate options evaluated."
        else:
            primary_act = SimulatedActionType.NO_ACTION
            summary = "Strategy Agent recommends deliberate abstention (NO_ACTION) to avoid value destruction."

        return StrategyProposal(
            proposals=candidate_proposals,
            primary_recommendation=primary_act,
            strategic_summary=summary,
            strategy_source="llm_reasoner",
            model_version=f"groq-{diagnosis.model_version or 'openai/gpt-oss-120b'}",
        )

    def generate_strategy_candidates(
        self,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> List[CandidateStrategyOption]:
        """Maps structured StrategyProposal into CandidateStrategyOption list for economic valuation."""
        proposal = self.propose_strategy(context, diagnosis, memory_bundle)
        candidates: List[CandidateStrategyOption] = []

        for p in proposal.proposals:
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
                    confidence=p.confidence,
                    rationale=p.rationale,
                    is_abstention=p.is_abstention,
                    supporting_evidence=p.supporting_evidence,
                    risk_notes=p.risk_notes,
                    preferred_timing_direction=p.preferred_timing_direction,
                    preferred_channel=p.preferred_channel,
                )
            )

        return candidates


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
        timing_candidates = TimingCandidateGenerator.generate_candidates(context, diagnosis, self.config)
        scored_timings = DeterministicTimingValueEstimator.estimate_all(
            context=context,
            diagnosis=diagnosis,
            candidates=timing_candidates,
            config=self.config,
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
