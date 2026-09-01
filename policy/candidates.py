"""Deterministic candidate action generator enforcing physical and policy constraints."""
from typing import List, Set

from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.config import DeterministicPolicyConfig
from simulator.config import SimulatedActionType


class CandidateGenerator:
    """Generates admissible candidate intervention actions based on observable context and structured diagnosis."""

    @staticmethod
    def generate_candidates(
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        config: DeterministicPolicyConfig,
    ) -> List[SimulatedActionType]:
        """Produce a filtered, valid list of candidate actions.

        Rules:
        - NO_ACTION is unconditionally included in all candidate sets.
        - EXPIRED_PAYMENT_METHOD: Disallows retries (physical impossibility); permits PAYMENT_LINK,
          and REMINDER only if high-value.
        - TRANSIENT_GATEWAY_FAILURE: Considers RETRY_LATER; permits RETRY_NOW only if attempt_count == 1 and config enables it.
        - INSUFFICIENT_FUNDS: Considers RETRY_LATER only if attempt_count < max_retry_attempts; allows PAYMENT_LINK/REMINDER.
        - AUTHENTICATION_FAILURE / MANDATE_ISSUE: Allows customer communication links.
        - UNKNOWN/OTHER or LOW CONFIDENCE: Considers NO_ACTION; allows PAYMENT_LINK only for high-value amounts.
        """
        candidates: Set[SimulatedActionType] = {SimulatedActionType.NO_ACTION}

        label = diagnosis.diagnosis_label
        is_high_value = context.amount_in_paise >= config.high_value_threshold_paise

        # Low confidence guard
        if diagnosis.confidence < config.confidence_threshold:
            if is_high_value and not diagnosis.abstain_recommended:
                candidates.add(SimulatedActionType.PAYMENT_LINK)
            return sorted(list(candidates), key=lambda a: a.value)

        if label == DiagnosisLabel.EXPIRED_PAYMENT_METHOD:
            # Physical constraint: retries always fail on expired instruments
            candidates.add(SimulatedActionType.PAYMENT_LINK)
            if is_high_value:
                candidates.add(SimulatedActionType.REMINDER)

        elif label == DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE:
            if context.attempt_count < config.max_retry_attempts:
                candidates.add(SimulatedActionType.RETRY_LATER)
                if context.attempt_count <= 1 and config.allow_immediate_retry:
                    candidates.add(SimulatedActionType.RETRY_NOW)
            else:
                # Retries exhausted; fall back to customer communication
                candidates.add(SimulatedActionType.PAYMENT_LINK)

        elif label == DiagnosisLabel.INSUFFICIENT_FUNDS:
            if context.attempt_count < config.max_retry_attempts:
                candidates.add(SimulatedActionType.RETRY_LATER)
            candidates.add(SimulatedActionType.PAYMENT_LINK)
            if is_high_value:
                candidates.add(SimulatedActionType.REMINDER)

        elif label in (DiagnosisLabel.AUTHENTICATION_FAILURE, DiagnosisLabel.MANDATE_ISSUE):
            candidates.add(SimulatedActionType.PAYMENT_LINK)
            if is_high_value:
                candidates.add(SimulatedActionType.REMINDER)

        else:
            # Unknown / unclassified failure mode
            if is_high_value and not diagnosis.abstain_recommended:
                candidates.add(SimulatedActionType.PAYMENT_LINK)

        return sorted(list(candidates), key=lambda a: a.value)
