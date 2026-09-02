"""Baseline policy implementations for RecoveryOS evaluation."""
from typing import Dict, Optional

from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis
from policy.base import BasePolicy, PolicyDecision
from simulator.config import SimulatedActionType

from policy.deterministic import DeterministicRecoveryPolicy, LLMDrivenRecoveryPolicy

__all__ = [
    "BasePolicy",
    "PolicyDecision",
    "NoActionPolicy",
    "AlwaysRetryPolicy",
    "StaticRulePolicy",
    "ProbabilityOnlyPolicy",
    "DeterministicRecoveryPolicy",
    "LLMDrivenRecoveryPolicy",
    "AgenticGraphRecoveryPolicy",
]


class NoActionPolicy(BasePolicy):
    """Baseline 0: Always abstain from intervening, relying purely on organic natural recovery."""

    def __init__(self) -> None:
        super().__init__(
            name="baseline_0_no_action",
            description="Abstain from all interventions; capture natural recovery baseline.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            action_type=SimulatedActionType.NO_ACTION,
            confidence=1.0,
            rationale="Baseline 0: Organic recovery control (no intervention).",
            policy_name=self.name,
            reason_codes=["BASELINE_0_ABSTAIN"],
            expected_net_value_paise=0,
            expected_incremental_value_paise=0,
            diagnosis=diagnosis,
        )


class AlwaysRetryPolicy(BasePolicy):
    """Baseline 1: Always retry invoice payment immediately whenever a failure occurs."""

    def __init__(self) -> None:
        super().__init__(
            name="baseline_1_always_retry",
            description="Unconditionally retry failed transactions immediately.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            action_type=SimulatedActionType.RETRY_NOW,
            confidence=1.0,
            rationale="Baseline 1: Immediate retry heuristic without root-cause differentiation.",
            policy_name=self.name,
            reason_codes=["BASELINE_1_UNCONDITIONAL_RETRY"],
            diagnosis=diagnosis,
        )


class StaticRulePolicy(BasePolicy):
    """Baseline 2: Rule-based heuristic branching on observable error codes and source steps."""

    def __init__(self) -> None:
        super().__init__(
            name="baseline_2_static_rules",
            description="Rule-based heuristic mapping observable error codes to targeted actions.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        error_code = context.error_code or context.failure_code or ""
        error_source = context.error_source or ""
        error_desc = (context.error_description or "").lower()

        # Hard failure on expired / bad payment method: naive rule engine dispatches link on BAD_REQUEST_ERROR
        if error_code == "BAD_REQUEST_ERROR" or "expired" in error_desc:
            return PolicyDecision(
                action_type=SimulatedActionType.PAYMENT_LINK,
                confidence=0.90,
                rationale="Static Rule: Expired payment method requires customer payment link to update credentials.",
                policy_name=self.name,
                reason_codes=["RULE_EXPIRED_PAYMENT_METHOD"],
                diagnosis=diagnosis,
            )

        # Gateway network error: immediate retry is optimal
        if error_code == "GATEWAY_ERROR" or error_source == "gateway":
            return PolicyDecision(
                action_type=SimulatedActionType.RETRY_NOW,
                confidence=0.85,
                rationale="Static Rule: Transient gateway error diagnosed; executing immediate retry.",
                policy_name=self.name,
                reason_codes=["RULE_TRANSIENT_GATEWAY"],
                diagnosis=diagnosis,
            )

        # Insufficient funds: delayed retry gives time for account replenishment
        if error_code == "INSUFFICIENT_FUNDS" or context.error_reason == "insufficient_funds":
            return PolicyDecision(
                action_type=SimulatedActionType.RETRY_LATER,
                confidence=0.75,
                rationale="Static Rule: Insufficient funds diagnosed; scheduling delayed retry.",
                policy_name=self.name,
                reason_codes=["RULE_INSUFFICIENT_FUNDS"],
                diagnosis=diagnosis,
            )

        # Default fallback
        return PolicyDecision(
            action_type=SimulatedActionType.PAYMENT_LINK,
            confidence=0.60,
            rationale="Static Rule: Default fallback to payment link dispatch.",
            policy_name=self.name,
            reason_codes=["RULE_DEFAULT_FALLBACK"],
            diagnosis=diagnosis,
        )


class ProbabilityOnlyPolicy(BasePolicy):
    """Baseline 3: Selects action with highest raw estimated recovery probability, ignoring costs and churn."""

    ESTIMATED_PRIORS: Dict[str, Dict[SimulatedActionType, float]] = {
        "BAD_REQUEST_ERROR": {
            SimulatedActionType.NO_ACTION: 0.05,
            SimulatedActionType.RETRY_NOW: 0.00,
            SimulatedActionType.RETRY_LATER: 0.00,
            SimulatedActionType.PAYMENT_LINK: 0.75,
            SimulatedActionType.REMINDER: 0.50,
        },
        "GATEWAY_ERROR": {
            SimulatedActionType.NO_ACTION: 0.30,
            SimulatedActionType.RETRY_NOW: 0.85,
            SimulatedActionType.RETRY_LATER: 0.75,
            SimulatedActionType.PAYMENT_LINK: 0.60,
            SimulatedActionType.REMINDER: 0.50,
        },
        "INSUFFICIENT_FUNDS": {
            SimulatedActionType.NO_ACTION: 0.20,
            SimulatedActionType.RETRY_NOW: 0.20,
            SimulatedActionType.RETRY_LATER: 0.70,
            SimulatedActionType.PAYMENT_LINK: 0.65,
            SimulatedActionType.REMINDER: 0.60,
        },
    }

    DEFAULT_PRIORS: Dict[SimulatedActionType, float] = {
        SimulatedActionType.NO_ACTION: 0.15,
        SimulatedActionType.RETRY_NOW: 0.40,
        SimulatedActionType.RETRY_LATER: 0.55,
        SimulatedActionType.PAYMENT_LINK: 0.65,
        SimulatedActionType.REMINDER: 0.50,
    }

    def __init__(self) -> None:
        super().__init__(
            name="baseline_3_probability_only",
            description="Greedy probability maximizer picking argmax P(recovery|action) without cost or uplift consideration.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        error_code = context.error_code or context.failure_code or ""
        priors = self.ESTIMATED_PRIORS.get(error_code, self.DEFAULT_PRIORS)

        # Pick action with maximum estimated raw recovery probability
        best_action = max(priors.items(), key=lambda item: item[1])[0]
        max_prob = priors[best_action]

        return PolicyDecision(
            action_type=best_action,
            confidence=round(max_prob, 2),
            rationale=f"Baseline 3: Greedy probability selection maximizing raw recovery P={max_prob:.2f} (ignoring costs/churn).",
            policy_name=self.name,
            reason_codes=["BASELINE_3_GREEDY_MAX_PROB"],
            diagnosis=diagnosis,
        )


class AgenticGraphRecoveryPolicy(BasePolicy):
    """Full RecoveryOS Agentic Graph Policy running specialized multi-agent reasoning with RAG memory."""

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        from agent.agents import (
            ContextRetrievalAgent,
            DiagnosisAgent,
            RecoveryStrategyAgent,
            TimingReasonerAgent,
        )
        self.context_agent = ContextRetrievalAgent()
        self.diagnosis_agent = DiagnosisAgent()
        self.strategy_agent = RecoveryStrategyAgent()
        self.timing_agent = TimingReasonerAgent()
        super().__init__(
            name=name or "RECOVERYOS_AGENTIC_V1",
            description=description or "Agentic RecoveryOS executing Context Retrieval, LLM Diagnosis, Strategy Reasoning, and Economic Timing Optimization.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        # 1. Retrieve bounded context memory bundle
        mem_bundle = self.context_agent.retriever.retrieve_bounded_context(context)

        # 2. LLM / Offline Root-Cause Diagnosis
        diag = diagnosis or self.diagnosis_agent.diagnose_sync(context, mem_bundle)

        # 3. Strategy Reasoning & Candidate Generation
        strategy_proposal = self.strategy_agent.propose_strategy(
            context=context,
            diagnosis=diag,
            memory_bundle=mem_bundle,
        )
        strategy_candidates = self.strategy_agent.generate_strategy_candidates_from_proposal(
            proposal=strategy_proposal,
            context=context,
            diagnosis=diag,
            memory_bundle=mem_bundle,
        )

        # 4. Action x Timing Economic Evaluation
        timing_candidates = self.timing_agent.evaluate_timing_options(
            context=context,
            diagnosis=diag,
            strategy_candidates=strategy_candidates,
        )

        best_timing = timing_candidates[0] if timing_candidates else None
        strat_src = strategy_proposal.strategy_source

        if best_timing and best_timing.action_type != SimulatedActionType.NO_ACTION and best_timing.expected_uplift >= 0.0 and best_timing.expected_net_value_paise >= 0:
            return PolicyDecision(
                action_type=best_timing.action_type,
                confidence=best_timing.estimated_probability,
                rationale=f"Full Agent Graph selected {best_timing.mechanism.value} ({best_timing.timing_window.value}) with expected net return ₹{best_timing.expected_net_value_paise / 100:.2f}.",
                policy_name=self.name,
                reason_codes=best_timing.reason_codes,
                expected_net_value_paise=best_timing.expected_net_value_paise,
                expected_incremental_value_paise=best_timing.expected_incremental_value_paise,
                timing_window=best_timing.timing_window.value,
                delay_seconds=best_timing.delay_seconds,
                diagnosis=diag,
                strategy_source=strat_src,
                strategy_proposal=strategy_proposal,
            )
        else:
            return PolicyDecision(
                action_type=SimulatedActionType.NO_ACTION,
                confidence=1.0,
                rationale="Full Agent Graph abstained: Negative or negligible expected net incremental value.",
                policy_name=self.name,
                reason_codes=["ABSTAIN_NEGATIVE_UPLIFT" if (best_timing and best_timing.expected_uplift < 0) else "ABSTAIN_LOW_EXPECTED_VALUE"],
                expected_net_value_paise=0,
                expected_incremental_value_paise=0,
                diagnosis=diag,
                strategy_source=strat_src,
                strategy_proposal=strategy_proposal,
            )

