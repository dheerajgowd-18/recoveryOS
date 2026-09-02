"""True End-to-End Architectural Integrity Test for RecoveryOS.

Proves the fundamental system principle:
"The model proposes. Deterministic systems constrain. Economics selects. The Governor authorizes. The Firewall executes."
"""
import pytest

from agent.agents import (
    CandidateStrategyOption,
    DiagnosisAgent,
    RecoveryStrategyAgent,
    TimingAndEconomicOptimizationAgent,
)
from governor.decision import GovernorDecisionResult
from governor.policy import MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import (
    DiagnosisLabel,
    StrategyCandidateProposal,
    StrategyProposal,
    StructuredDiagnosis,
)
from planner.timing import ActionMechanism, TimingWindow
from policy.base import PolicyDecision
from simulator.config import SimulatedActionType


class TestAgenticIntegrityE2E:
    """Validates the complete 7-stage pipeline integrity with mocked LLM proposals under different economic regimes."""

    def test_e2e_scenario_1_economics_overrides_llm_preference_to_abstain(self):
        """Scenario 1: Model strongly proposes payment_link, but economics determines negative net value on low-value transaction.

        Flow:
        ObservableContext (₹1.00) -> Diagnosis -> StrategyProposal (payment_link) ->
        Admissibility -> Economics (Selects NO_ACTION) -> Governor (Confirms ABSTAIN)
        """
        # 1. Observable Context
        ctx = ObservableRecoveryContext(
            scenario_id="e2e_scen_low_val",
            amount_in_paise=10,  # ₹0.10 transaction (fees exceed transaction value)
            attempt_count=1,
            error_code="INSUFFICIENT_FUNDS",
            error_reason="insufficient_funds",
        )

        # 2. Structured Diagnosis (Root cause inferred)
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.INSUFFICIENT_FUNDS,
            confidence=0.88,
            evidence_codes=["OBS_INSUFFICIENT_FUNDS"],
            uncertainties=[],
            recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK],
            rationale="Temporary insufficient funds; customer needs payment link.",
            diagnosis_source="llm_structured",
        )

        # 3. Strategy Proposal (Model proposes payment_link as primary recommendation)
        strategy_proposal = StrategyProposal(
            proposals=[
                StrategyCandidateProposal(
                    action_type=SimulatedActionType.PAYMENT_LINK,
                    mechanism="payment_link",
                    rationale="Direct hosted payment link",
                    confidence=0.95,
                    is_abstention=False,
                    why_better_than_abstain="Direct recovery",
                    why_alternative_inferior="None",
                ),
                StrategyCandidateProposal(
                    action_type=SimulatedActionType.NO_ACTION,
                    mechanism="no_action",
                    rationale="Zero cost baseline",
                    confidence=1.0,
                    is_abstention=True,
                    why_better_than_abstain="N/A",
                    why_alternative_inferior="Fees",
                ),
            ],
            primary_recommendation=SimulatedActionType.PAYMENT_LINK,
            strategic_summary="LLM recommends payment link",
            strategy_source="llm_structured",
            model_version="groq-openai/gpt-oss-120b",
        )

        # 4. Hard Deterministic Admissibility Check
        strategy_agent = RecoveryStrategyAgent()
        admissible_candidates = strategy_agent.generate_strategy_candidates_from_proposal(
            proposal=strategy_proposal,
            context=ctx,
            diagnosis=diag,
        )

        # 5. Timing & Deterministic Economic Optimization
        timing_agent = TimingAndEconomicOptimizationAgent()
        evaluated_options = timing_agent.evaluate_timing_options(
            context=ctx,
            diagnosis=diag,
            strategy_candidates=admissible_candidates,
        )

        best_option = evaluated_options[0]
        # Economic selection: Fee of ₹1.00 on ₹1.00 transaction gives non-positive net value. NO_ACTION wins.
        assert best_option.action_type == SimulatedActionType.NO_ACTION

        # 6. Recovery Governor Authorization
        proposal = PolicyDecision(
            action_type=best_option.action_type,
            confidence=diag.confidence,
            rationale="Deterministic economic evaluation selected zero-cost abstention.",
            policy_name="RECOVERYOS_AGENTIC_V1",
            reason_codes=best_option.reason_codes,
            timing_window=best_option.timing_window.value,
            delay_seconds=best_option.delay_seconds,
            diagnosis=diag,
        )
        governor = RecoveryGovernor(merchant_policy=MerchantPolicy())
        gov_verdict = governor.evaluate(context=ctx, diagnosis=diag, proposal=proposal)

        # Governor confirms safe abstention
        assert gov_verdict.decision_result == GovernorDecisionResult.ABSTAIN
        assert gov_verdict.selected_action == SimulatedActionType.NO_ACTION

    def test_e2e_scenario_2_economics_approves_profitable_llm_candidate(self):
        """Scenario 2: Model proposes payment_link, and economics validates positive net recovery value on high-value transaction.

        Flow:
        ObservableContext (₹3,500.00) -> Diagnosis -> StrategyProposal (payment_link) ->
        Admissibility -> Economics (Selects PAYMENT_LINK) -> Governor (ALLOW)
        """
        # 1. Observable Context
        ctx = ObservableRecoveryContext(
            scenario_id="e2e_scen_high_val",
            amount_in_paise=350000,  # ₹3,500.00 transaction
            attempt_count=1,
            error_code="AUTHENTICATION_FAILED",
            error_reason="authentication_failure",
        )

        # 2. Structured Diagnosis
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.AUTHENTICATION_FAILURE,
            confidence=0.92,
            evidence_codes=["OBS_AUTH_FAILED"],
            uncertainties=[],
            recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK],
            rationale="3DS authentication drop-off; send fresh payment link via WhatsApp.",
            diagnosis_source="llm_structured",
        )

        # 3. Strategy Proposal
        strategy_proposal = StrategyProposal(
            proposals=[
                StrategyCandidateProposal(
                    action_type=SimulatedActionType.PAYMENT_LINK,
                    mechanism="payment_link",
                    rationale="Customer needs out-of-band payment link to re-authenticate",
                    confidence=0.88,
                    is_abstention=False,
                    why_better_than_abstain="High recovery on ₹3,500 ticket",
                    why_alternative_inferior="Silent retry will fail 3DS",
                ),
                StrategyCandidateProposal(
                    action_type=SimulatedActionType.NO_ACTION,
                    mechanism="no_action",
                    rationale="Zero cost baseline",
                    confidence=1.0,
                    is_abstention=True,
                    why_better_than_abstain="N/A",
                    why_alternative_inferior="Abandonment",
                ),
            ],
            primary_recommendation=SimulatedActionType.PAYMENT_LINK,
            strategic_summary="LLM recommends payment link",
            strategy_source="llm_structured",
            model_version="groq-openai/gpt-oss-120b",
        )

        # 4. Hard Deterministic Admissibility Check
        strategy_agent = RecoveryStrategyAgent()
        admissible_candidates = strategy_agent.generate_strategy_candidates_from_proposal(
            proposal=strategy_proposal,
            context=ctx,
            diagnosis=diag,
        )

        # 5. Timing & Deterministic Economic Optimization
        timing_agent = TimingAndEconomicOptimizationAgent()
        evaluated_options = timing_agent.evaluate_timing_options(
            context=ctx,
            diagnosis=diag,
            strategy_candidates=admissible_candidates,
        )

        best_option = evaluated_options[0]
        # Economic selection: ₹3,500 * uplift far exceeds ₹1.00 cost. PAYMENT_LINK wins.
        assert best_option.action_type == SimulatedActionType.PAYMENT_LINK
        assert best_option.expected_net_value_paise > 0

        # 6. Recovery Governor Authorization
        proposal = PolicyDecision(
            action_type=best_option.action_type,
            confidence=diag.confidence,
            rationale="Economically validated payment link recovery.",
            policy_name="RECOVERYOS_AGENTIC_V1",
            reason_codes=best_option.reason_codes,
            timing_window=best_option.timing_window.value,
            delay_seconds=best_option.delay_seconds,
            diagnosis=diag,
        )
        governor = RecoveryGovernor(merchant_policy=MerchantPolicy())
        gov_verdict = governor.evaluate(context=ctx, diagnosis=diag, proposal=proposal)

        # Governor authorizes profitable action
        assert gov_verdict.decision_result == GovernorDecisionResult.ALLOW
        assert gov_verdict.selected_action == SimulatedActionType.PAYMENT_LINK

    def test_e2e_scenario_3_model_omission_preserves_optimal_deterministic_candidate(self):
        """Scenario 3: Model omits a better admissible candidate (e.g. proposes only PAYMENT_LINK and NO_ACTION on insufficient funds).

        Flow:
        ObservableContext (₹2,500.00 INSUFFICIENT_FUNDS) -> Diagnosis ->
        StrategyProposal (omits RETRY_LATER) -> Admissibility (preserves RETRY_LATER) ->
        Economics (Evaluates all safe candidates, finds RETRY_LATER at +6h is economically optimal) ->
        Governor (ALLOWs RETRY_LATER).
        """
        # 1. Observable Context
        ctx = ObservableRecoveryContext(
            scenario_id="e2e_scen_transient_gateway",
            amount_in_paise=250000,  # ₹2,500.00 transaction
            attempt_count=1,
            error_code="GATEWAY_TIMEOUT",
            error_reason="gateway_error",
        )

        # 2. Structured Diagnosis
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE,
            confidence=0.88,
            evidence_codes=["OBS_GATEWAY_OUTAGE"],
            uncertainties=[],
            recommended_candidate_actions=[SimulatedActionType.PAYMENT_LINK, SimulatedActionType.RETRY_LATER],
            rationale="Transient gateway glitch; delayed retry is optimal.",
            diagnosis_source="llm_structured",
        )

        # 3. Strategy Proposal that mistakenly omits RETRY_LATER
        strategy_proposal = StrategyProposal(
            proposals=[
                StrategyCandidateProposal(
                    action_type=SimulatedActionType.PAYMENT_LINK,
                    mechanism="payment_link",
                    rationale="Customer link",
                    confidence=0.75,
                    is_abstention=False,
                    why_better_than_abstain="Direct recovery",
                    why_alternative_inferior="None",
                ),
                StrategyCandidateProposal(
                    action_type=SimulatedActionType.NO_ACTION,
                    mechanism="no_action",
                    rationale="Zero cost baseline",
                    confidence=1.0,
                    is_abstention=True,
                    why_better_than_abstain="N/A",
                    why_alternative_inferior="Fees",
                ),
            ],
            primary_recommendation=SimulatedActionType.PAYMENT_LINK,
            strategic_summary="LLM only proposes payment link",
            strategy_source="llm_structured",
            model_version="groq-openai/gpt-oss-120b",
        )

        # 4. Hard Deterministic Admissibility Check - preserves complete safe search space
        strategy_agent = RecoveryStrategyAgent()
        admissible_candidates = strategy_agent.generate_strategy_candidates_from_proposal(
            proposal=strategy_proposal,
            context=ctx,
            diagnosis=diag,
        )
        candidate_actions = [c.action_type for c in admissible_candidates]
        assert SimulatedActionType.RETRY_LATER in candidate_actions

        # 5. Timing & Deterministic Economic Optimization
        timing_agent = TimingAndEconomicOptimizationAgent()
        evaluated_options = timing_agent.evaluate_timing_options(
            context=ctx,
            diagnosis=diag,
            strategy_candidates=admissible_candidates,
        )

        best_option = evaluated_options[0]
        # RETRY_LATER at +6h gives highest net return (high recovery probability with low ₹0.20 retry fee and 0 contact fatigue)
        assert best_option.action_type == SimulatedActionType.RETRY_LATER
        assert best_option.timing_window == TimingWindow.PLUS_6H

        # 6. Recovery Governor Authorization
        proposal = PolicyDecision(
            action_type=best_option.action_type,
            confidence=diag.confidence,
            rationale="Delayed batch retry economically outperforms link dispatch.",
            policy_name="RECOVERYOS_AGENTIC_V1",
            reason_codes=best_option.reason_codes,
            timing_window=best_option.timing_window.value,
            delay_seconds=best_option.delay_seconds,
            diagnosis=diag,
        )
        governor = RecoveryGovernor(merchant_policy=MerchantPolicy())
        gov_verdict = governor.evaluate(context=ctx, diagnosis=diag, proposal=proposal)

        assert gov_verdict.decision_result == GovernorDecisionResult.ALLOW
        assert gov_verdict.selected_action == SimulatedActionType.RETRY_LATER
