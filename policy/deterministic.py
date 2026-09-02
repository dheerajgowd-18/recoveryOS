"""Deterministic RecoveryOS Policy v1 with structured diagnosis, candidate generation, and negative uplift abstention."""
from typing import Optional

from intelligence.context import ObservableRecoveryContext
from intelligence.providers import BaseDiagnosisProvider, DeterministicDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.base import BasePolicy, PolicyDecision
from policy.candidates import CandidateGenerator
from policy.config import DeterministicPolicyConfig
from policy.scoring import ExpectedValueScorer
from simulator.config import SimulatedActionType


class DeterministicRecoveryPolicy(BasePolicy):
    """Deterministic, transparent, cost-aware RecoveryOS policy (v1).

    Operates strictly on sanitized ObservableRecoveryContext and StructuredDiagnosis.
    Enforces candidate filtering, expected net value scoring with negative uplift semantics,
    and fail-safe low-confidence abstention guards.
    """

    def __init__(
        self,
        config: Optional[DeterministicPolicyConfig] = None,
        diagnosis_provider: Optional[BaseDiagnosisProvider] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        self.config = config or DeterministicPolicyConfig()
        self.diagnosis_provider = diagnosis_provider or DeterministicDiagnosisProvider()
        super().__init__(
            name=name or "RECOVERYOS_DETERMINISTIC_V0",
            description=description or "Deterministic cost-aware RecoveryOS policy optimizing expected incremental recovery value.",
        )

    def decide(
        self,
        context: ObservableRecoveryContext,
        diagnosis: Optional[StructuredDiagnosis] = None,
    ) -> PolicyDecision:
        """Evaluate observable context and structured diagnosis to produce a bounded recovery decision."""
        # 1. Obtain Structured Diagnosis
        diag = diagnosis or self.diagnosis_provider.diagnose_sync(context)

        # 2. Low-Confidence / Unknown Diagnosis Safe Gate
        if (
            diag.confidence < self.config.confidence_threshold
            or diag.abstain_recommended
            or diag.diagnosis_label == DiagnosisLabel.UNKNOWN_FAILURE
        ):
            reason_codes = []
            if diag.confidence < self.config.confidence_threshold:
                reason_codes.append("ABSTAIN_LOW_CONFIDENCE_DIAGNOSIS")
            if diag.diagnosis_label == DiagnosisLabel.UNKNOWN_FAILURE:
                reason_codes.append("ABSTAIN_UNKNOWN_DIAGNOSIS")
            if diag.human_review_required:
                reason_codes.append("HUMAN_REVIEW_REQUIRED")
            if not reason_codes:
                reason_codes.append("ABSTAIN_LOW_EXPECTED_VALUE")

            return PolicyDecision(
                action_type=SimulatedActionType.NO_ACTION,
                confidence=diag.confidence,
                rationale=(
                    f"Abstaining safely: Diagnosis '{diag.diagnosis_label.value}' has low confidence ({diag.confidence:.2f}) "
                    f"or recommends abstention. Reason: {diag.rationale}"
                ),
                policy_name=self.name,
                reason_codes=reason_codes,
                expected_net_value_paise=0,
                expected_incremental_value_paise=0,
                diagnosis=diag,
            )

        # 3. Candidate Action Generation
        candidates = CandidateGenerator.generate_candidates(context, diag, self.config)

        # 4. Transparent Expected Value Scoring (with negative uplift support)
        scored_candidates = ExpectedValueScorer.score_all(context, diag, candidates, self.config)

        # 5. Filter candidates by operational and physical constraints
        admissible_scored = []
        for scored in scored_candidates:
            # Enforce max retry attempts constraint
            if (
                scored.action_type in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER)
                and context.attempt_count >= self.config.max_retry_attempts
            ):
                continue

            # Enforce physical block on retrying expired payment methods
            if (
                scored.action_type in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER)
                and diag.diagnosis_label == DiagnosisLabel.EXPIRED_PAYMENT_METHOD
            ):
                continue

            admissible_scored.append(scored)

        # 6. Best Candidate Selection & Abstention Evaluation
        best_candidate = admissible_scored[0] if admissible_scored else None

        if (
            best_candidate is None
            or best_candidate.action_type == SimulatedActionType.NO_ACTION
            or best_candidate.expected_net_value_paise < self.config.min_expected_net_value_paise
            or best_candidate.expected_uplift < 0.0
        ):
            # Explicit Abstention
            reason_codes = []
            if best_candidate and best_candidate.expected_uplift < 0.0:
                reason_codes.append("ABSTAIN_NEGATIVE_UPLIFT")
            else:
                reason_codes.append("ABSTAIN_LOW_EXPECTED_VALUE")

            if context.attempt_count >= self.config.max_retry_attempts:
                reason_codes.append("ABSTAIN_ATTEMPT_LIMIT_EXCEEDED")

            return PolicyDecision(
                action_type=SimulatedActionType.NO_ACTION,
                confidence=1.0,
                rationale="Abstaining: Expected incremental recovery value does not justify intervention cost or risk.",
                policy_name=self.name,
                reason_codes=reason_codes,
                expected_net_value_paise=0,
                expected_incremental_value_paise=0,
                diagnosis=diag,
            )

        # 7. Optimal Active Intervention Selection
        timing_window = "IMMEDIATE"
        delay_seconds = 0
        if best_candidate.action_type == SimulatedActionType.RETRY_LATER:
            timing_window = "PLUS_6H"
            delay_seconds = 21600
        elif best_candidate.action_type == SimulatedActionType.REMINDER:
            timing_window = "PLUS_6H"
            delay_seconds = 21600

        reason_codes = [
            "OPTIMAL_EXPECTED_NET_VALUE",
            f"DIAGNOSIS_{diag.diagnosis_label.name}",
            f"SOURCE_{diag.diagnosis_source.upper()}",
            f"TIMING_{timing_window}",
        ] + best_candidate.reason_codes

        rationale = (
            f"Diagnosed {diag.diagnosis_label.value} (conf={diag.confidence:.2f}, src={diag.diagnosis_source}). "
            f"Selected {best_candidate.action_type.value} ({timing_window}) yielding expected net value ₹{best_candidate.expected_net_value_paise / 100:.2f} "
            f"(uplift {best_candidate.expected_uplift * 100:.1f}% over natural baseline)."
        )

        return PolicyDecision(
            action_type=best_candidate.action_type,
            confidence=best_candidate.estimated_probability,
            rationale=rationale,
            policy_name=self.name,
            reason_codes=reason_codes,
            expected_net_value_paise=best_candidate.expected_net_value_paise,
            expected_incremental_value_paise=best_candidate.expected_incremental_value_paise,
            timing_window=timing_window,
            delay_seconds=delay_seconds,
            diagnosis=diag,
        )


class LLMDrivenRecoveryPolicy(DeterministicRecoveryPolicy):
    """LLM-driven RecoveryOS policy pairing Groq structured diagnosis with deterministic economic scoring."""

    def __init__(
        self,
        config: Optional[DeterministicPolicyConfig] = None,
        diagnosis_provider: Optional[BaseDiagnosisProvider] = None,
    ) -> None:
        from intelligence.providers.groq_provider import GroqLLMDiagnosisProvider

        provider = diagnosis_provider or GroqLLMDiagnosisProvider()
        super().__init__(
            config=config,
            diagnosis_provider=provider,
            name="RECOVERYOS_LLM_DRIVEN",
            description="LLM-driven RecoveryOS policy pairing Groq open-weights inference with deterministic governance.",
        )
