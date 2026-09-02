"""Timing abstraction, candidate action-timing generator, and deterministic timing value estimator."""
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, ConfigDict, Field

from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.config import DeterministicPolicyConfig
from simulator.config import SimulatedActionType


class TimingWindow(str, Enum):
    """Discrete recovery timing execution windows."""
    IMMEDIATE = "IMMEDIATE"   # 0 hours / immediate dispatch
    PLUS_2H = "PLUS_2H"       # 2 hours delay
    PLUS_6H = "PLUS_6H"       # 6 hours delay
    PLUS_12H = "PLUS_12H"     # 12 hours delay
    PLUS_24H = "PLUS_24H"     # 24 hours delay

    @property
    def delay_seconds(self) -> int:
        """Offset in seconds corresponding to the timing window."""
        offsets: Dict[TimingWindow, int] = {
            TimingWindow.IMMEDIATE: 0,
            TimingWindow.PLUS_2H: 7_200,
            TimingWindow.PLUS_6H: 21_600,
            TimingWindow.PLUS_12H: 43_200,
            TimingWindow.PLUS_24H: 86_400,
        }
        return offsets[self]

    @property
    def label(self) -> str:
        """Human-readable display string."""
        labels: Dict[TimingWindow, str] = {
            TimingWindow.IMMEDIATE: "immediate",
            TimingWindow.PLUS_2H: "in 2h",
            TimingWindow.PLUS_6H: "in 6h",
            TimingWindow.PLUS_12H: "in 12h",
            TimingWindow.PLUS_24H: "in 24h",
        }
        return labels[self]


class ActionMechanism(str, Enum):
    """Core intervention mechanism independent of execution timing."""
    NO_ACTION = "NO_ACTION"
    RETRY = "RETRY"
    PAYMENT_LINK = "PAYMENT_LINK"
    REMINDER = "REMINDER"
    HUMAN_REVIEW = "HUMAN_REVIEW"


def map_mechanism_and_timing_to_simulated_action(
    mechanism: ActionMechanism,
    timing: TimingWindow,
) -> SimulatedActionType:
    """Map an (ActionMechanism, TimingWindow) pair to legacy SimulatedActionType."""
    if mechanism == ActionMechanism.NO_ACTION:
        return SimulatedActionType.NO_ACTION
    if mechanism == ActionMechanism.RETRY:
        if timing == TimingWindow.IMMEDIATE:
            return SimulatedActionType.RETRY_NOW
        return SimulatedActionType.RETRY_LATER
    if mechanism == ActionMechanism.PAYMENT_LINK:
        return SimulatedActionType.PAYMENT_LINK
    if mechanism == ActionMechanism.REMINDER:
        return SimulatedActionType.REMINDER
    return SimulatedActionType.NO_ACTION


class ActionTimingCandidate(BaseModel):
    """Encapsulates an evaluated Action Mechanism × Timing Window option."""
    model_config = ConfigDict(extra="forbid")

    mechanism: ActionMechanism = Field(..., description="Recovery intervention mechanism")
    timing_window: TimingWindow = Field(..., description="Discrete scheduled execution window")
    action_type: SimulatedActionType = Field(..., description="Mapped legacy simulated action type")
    delay_seconds: int = Field(..., ge=0, description="Execution delay in seconds")
    estimated_probability: float = Field(..., ge=0.0, le=1.0, description="Estimated recovery probability at this window")
    natural_probability: float = Field(..., ge=0.0, le=1.0, description="Estimated baseline natural recovery probability")
    expected_uplift: float = Field(..., ge=-1.0, le=1.0, description="Incremental uplift over natural recovery (can be negative)")
    expected_incremental_value_paise: int = Field(..., description="Expected incremental revenue in paise")
    action_cost_paise: int = Field(..., ge=0, description="Direct execution cost in paise")
    expected_net_value_paise: int = Field(..., description="Expected net recovery value (Incremental - Cost)")
    reason_codes: List[str] = Field(default_factory=list, description="Timing and scoring audit tags")


class TimingCandidateGenerator:
    """Generates admissible (ActionMechanism, TimingWindow) pairs under failure physics and policy."""

    @staticmethod
    def generate_candidates(
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        config: DeterministicPolicyConfig,
        strategy_candidates: Optional[List[Any]] = None,
    ) -> List[Tuple[ActionMechanism, TimingWindow]]:
        """Produce eligible (mechanism, timing) pairs constrained by observable context, failure physics, and strategy candidates."""
        candidates: Set[Tuple[ActionMechanism, TimingWindow]] = {
            (ActionMechanism.NO_ACTION, TimingWindow.IMMEDIATE)
        }

        label = diagnosis.diagnosis_label
        is_high_value = context.amount_in_paise >= config.high_value_threshold_paise

        # Low confidence guard
        if diagnosis.confidence < config.confidence_threshold:
            if is_high_value and not diagnosis.abstain_recommended:
                candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.IMMEDIATE))
                candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_2H))
        elif label == DiagnosisLabel.EXPIRED_PAYMENT_METHOD:
            # Physical constraint: Instrument expired; retries are forbidden
            candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.IMMEDIATE))
            candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_2H))
            candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_6H))
            if is_high_value:
                candidates.add((ActionMechanism.REMINDER, TimingWindow.PLUS_6H))
                candidates.add((ActionMechanism.REMINDER, TimingWindow.PLUS_12H))
                candidates.add((ActionMechanism.REMINDER, TimingWindow.PLUS_24H))

        elif label == DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE:
            if context.attempt_count < config.max_retry_attempts:
                if context.attempt_count <= 1 and config.allow_immediate_retry:
                    candidates.add((ActionMechanism.RETRY, TimingWindow.IMMEDIATE))
                    candidates.add((ActionMechanism.RETRY, TimingWindow.PLUS_2H))
                    candidates.add((ActionMechanism.RETRY, TimingWindow.PLUS_6H))
                else:
                    candidates.add((ActionMechanism.RETRY, TimingWindow.PLUS_6H))
                    candidates.add((ActionMechanism.RETRY, TimingWindow.PLUS_12H))
                    candidates.add((ActionMechanism.RETRY, TimingWindow.PLUS_24H))
            else:
                # Retries exhausted -> fallback to direct customer payment link
                candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.IMMEDIATE))
                candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_2H))
                candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_6H))

        elif label == DiagnosisLabel.INSUFFICIENT_FUNDS:
            if context.attempt_count < config.max_retry_attempts:
                candidates.add((ActionMechanism.RETRY, TimingWindow.PLUS_6H))
                candidates.add((ActionMechanism.RETRY, TimingWindow.PLUS_12H))
                candidates.add((ActionMechanism.RETRY, TimingWindow.PLUS_24H))
            candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.IMMEDIATE))
            candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_2H))
            candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_6H))
            if is_high_value:
                candidates.add((ActionMechanism.REMINDER, TimingWindow.PLUS_6H))
                candidates.add((ActionMechanism.REMINDER, TimingWindow.PLUS_12H))
                candidates.add((ActionMechanism.REMINDER, TimingWindow.PLUS_24H))

        elif label in (DiagnosisLabel.AUTHENTICATION_FAILURE, DiagnosisLabel.MANDATE_ISSUE):
            candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.IMMEDIATE))
            candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_2H))
            candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_6H))
            if is_high_value:
                candidates.add((ActionMechanism.REMINDER, TimingWindow.PLUS_6H))
                candidates.add((ActionMechanism.REMINDER, TimingWindow.PLUS_12H))
                candidates.add((ActionMechanism.REMINDER, TimingWindow.PLUS_24H))

        else:
            # Unknown / unclassified failure mode
            if is_high_value and not diagnosis.abstain_recommended:
                candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.IMMEDIATE))
                candidates.add((ActionMechanism.PAYMENT_LINK, TimingWindow.PLUS_2H))

        if strategy_candidates is not None:
            allowed_mechs = {
                getattr(c, "mechanism", None) or ActionMechanism.NO_ACTION
                for c in strategy_candidates
            } | {ActionMechanism.NO_ACTION}
            candidates = {c for c in candidates if c[0] in allowed_mechs}

        return sorted(list(candidates), key=lambda c: (c[0].value, c[1].delay_seconds))


class DeterministicTimingValueEstimator:
    """Estimates expected recovery probability, uplift, and net value for Action × Timing options."""

    # Deterministic timing probability adjustments based on failure mechanics
    TIMING_CURVES: Dict[DiagnosisLabel, Dict[ActionMechanism, Dict[TimingWindow, float]]] = {
        DiagnosisLabel.TRANSIENT_GATEWAY_FAILURE: {
            ActionMechanism.RETRY: {
                TimingWindow.IMMEDIATE: 0.20,  # Ongoing outage risk
                TimingWindow.PLUS_2H: 0.85,    # Outage resolving
                TimingWindow.PLUS_6H: 0.90,    # Fully recovered gateway
                TimingWindow.PLUS_12H: 0.88,
                TimingWindow.PLUS_24H: 0.80,
            },
            ActionMechanism.PAYMENT_LINK: {
                TimingWindow.IMMEDIATE: 0.70,
                TimingWindow.PLUS_2H: 0.65,
                TimingWindow.PLUS_6H: 0.50,
                TimingWindow.PLUS_12H: 0.40,
                TimingWindow.PLUS_24H: 0.30,
            },
            ActionMechanism.REMINDER: {
                TimingWindow.IMMEDIATE: 0.30,
                TimingWindow.PLUS_2H: 0.35,
                TimingWindow.PLUS_6H: 0.40,
                TimingWindow.PLUS_12H: 0.35,
                TimingWindow.PLUS_24H: 0.30,
            },
        },
        DiagnosisLabel.INSUFFICIENT_FUNDS: {
            ActionMechanism.RETRY: {
                TimingWindow.IMMEDIATE: 0.10,  # Immediate re-debit almost always fails
                TimingWindow.PLUS_2H: 0.25,
                TimingWindow.PLUS_6H: 0.45,
                TimingWindow.PLUS_12H: 0.55,
                TimingWindow.PLUS_24H: 0.65,   # Higher success next day / fund top-up
            },
            ActionMechanism.PAYMENT_LINK: {
                TimingWindow.IMMEDIATE: 0.75,
                TimingWindow.PLUS_2H: 0.70,
                TimingWindow.PLUS_6H: 0.60,
                TimingWindow.PLUS_12H: 0.50,
                TimingWindow.PLUS_24H: 0.40,
            },
            ActionMechanism.REMINDER: {
                TimingWindow.IMMEDIATE: 0.30,
                TimingWindow.PLUS_2H: 0.35,
                TimingWindow.PLUS_6H: 0.45,
                TimingWindow.PLUS_12H: 0.40,
                TimingWindow.PLUS_24H: 0.35,
            },
        },
        DiagnosisLabel.EXPIRED_PAYMENT_METHOD: {
            ActionMechanism.PAYMENT_LINK: {
                TimingWindow.IMMEDIATE: 0.70,
                TimingWindow.PLUS_2H: 0.65,
                TimingWindow.PLUS_6H: 0.55,
                TimingWindow.PLUS_12H: 0.45,
                TimingWindow.PLUS_24H: 0.35,
            },
            ActionMechanism.REMINDER: {
                TimingWindow.IMMEDIATE: 0.25,
                TimingWindow.PLUS_2H: 0.30,
                TimingWindow.PLUS_6H: 0.40,
                TimingWindow.PLUS_12H: 0.35,
                TimingWindow.PLUS_24H: 0.30,
            },
        },
        DiagnosisLabel.AUTHENTICATION_FAILURE: {
            ActionMechanism.PAYMENT_LINK: {
                TimingWindow.IMMEDIATE: 0.75,
                TimingWindow.PLUS_2H: 0.68,
                TimingWindow.PLUS_6H: 0.55,
                TimingWindow.PLUS_12H: 0.45,
                TimingWindow.PLUS_24H: 0.35,
            },
            ActionMechanism.REMINDER: {
                TimingWindow.IMMEDIATE: 0.30,
                TimingWindow.PLUS_2H: 0.35,
                TimingWindow.PLUS_6H: 0.40,
                TimingWindow.PLUS_12H: 0.35,
                TimingWindow.PLUS_24H: 0.30,
            },
        },
        DiagnosisLabel.MANDATE_ISSUE: {
            ActionMechanism.PAYMENT_LINK: {
                TimingWindow.IMMEDIATE: 0.70,
                TimingWindow.PLUS_2H: 0.65,
                TimingWindow.PLUS_6H: 0.55,
                TimingWindow.PLUS_12H: 0.45,
                TimingWindow.PLUS_24H: 0.35,
            },
            ActionMechanism.REMINDER: {
                TimingWindow.IMMEDIATE: 0.30,
                TimingWindow.PLUS_2H: 0.35,
                TimingWindow.PLUS_6H: 0.40,
                TimingWindow.PLUS_12H: 0.35,
                TimingWindow.PLUS_24H: 0.30,
            },
        },
        DiagnosisLabel.UNKNOWN_FAILURE: {
            ActionMechanism.PAYMENT_LINK: {
                TimingWindow.IMMEDIATE: 0.30,
                TimingWindow.PLUS_2H: 0.25,
                TimingWindow.PLUS_6H: 0.20,
                TimingWindow.PLUS_12H: 0.15,
                TimingWindow.PLUS_24H: 0.10,
            },
            ActionMechanism.REMINDER: {
                TimingWindow.IMMEDIATE: 0.15,
                TimingWindow.PLUS_2H: 0.15,
                TimingWindow.PLUS_6H: 0.15,
                TimingWindow.PLUS_12H: 0.10,
                TimingWindow.PLUS_24H: 0.10,
            },
        },
    }

    MECHANISM_COST_MAP: Dict[ActionMechanism, SimulatedActionType] = {
        ActionMechanism.NO_ACTION: SimulatedActionType.NO_ACTION,
        ActionMechanism.RETRY: SimulatedActionType.RETRY_NOW,
        ActionMechanism.PAYMENT_LINK: SimulatedActionType.PAYMENT_LINK,
        ActionMechanism.REMINDER: SimulatedActionType.REMINDER,
        ActionMechanism.HUMAN_REVIEW: SimulatedActionType.NO_ACTION,
    }

    @classmethod
    def estimate_candidate(
        cls,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        mechanism: ActionMechanism,
        timing: TimingWindow,
        config: DeterministicPolicyConfig,
    ) -> ActionTimingCandidate:
        """Deterministically calculate expected net value and incremental uplift for a candidate."""
        sim_action = map_mechanism_and_timing_to_simulated_action(mechanism, timing)
        cost_action_key = cls.MECHANISM_COST_MAP.get(mechanism, SimulatedActionType.NO_ACTION)
        cost = config.action_costs_paise.get(cost_action_key, 0)

        # Baseline natural recovery prior
        priors = config.estimated_action_priors.get(diagnosis.diagnosis_label, config.default_priors)
        p_natural = priors.get(SimulatedActionType.NO_ACTION, 0.0)

        if mechanism == ActionMechanism.NO_ACTION:
            return ActionTimingCandidate(
                mechanism=mechanism,
                timing_window=timing,
                action_type=sim_action,
                delay_seconds=0,
                estimated_probability=round(p_natural, 4),
                natural_probability=round(p_natural, 4),
                expected_uplift=0.0,
                expected_incremental_value_paise=0,
                action_cost_paise=0,
                expected_net_value_paise=0,
                reason_codes=["NATURAL_RECOVERY_BASELINE"],
            )

        # Estimate probability from deterministic timing curves or default priors
        diag_curves = cls.TIMING_CURVES.get(diagnosis.diagnosis_label, {})
        mech_curves = diag_curves.get(mechanism, {})
        p_action = mech_curves.get(timing)

        if p_action is None:
            # Fallback to action prior from config
            p_action = priors.get(sim_action, 0.0)

        # Apply confidence weighting: lower diagnosis confidence pulls towards baseline
        weighted_p_action = round((p_action * diagnosis.confidence) + (p_natural * (1.0 - diagnosis.confidence)), 4)
        uplift = round(weighted_p_action - p_natural, 4)
        incremental_value = int(context.amount_in_paise * uplift)
        net_value = incremental_value - cost

        reason_codes = [
            f"MECH_{mechanism.value}",
            f"TIMING_{timing.value}",
            f"PROB_{int(weighted_p_action * 100)}PCT",
            f"UPLIFT_{int(uplift * 100)}PCT",
            f"COST_{cost}PAISE",
        ]

        if uplift < 0:
            reason_codes.append("NEGATIVE_INCREMENTAL_UPLIFT")
        if net_value < 0:
            reason_codes.append("NEGATIVE_EXPECTED_NET_VALUE")

        return ActionTimingCandidate(
            mechanism=mechanism,
            timing_window=timing,
            action_type=sim_action,
            delay_seconds=timing.delay_seconds,
            estimated_probability=weighted_p_action,
            natural_probability=round(p_natural, 4),
            expected_uplift=uplift,
            expected_incremental_value_paise=incremental_value,
            action_cost_paise=cost,
            expected_net_value_paise=net_value,
            reason_codes=reason_codes,
        )

    @classmethod
    def estimate_all(
        cls,
        context: ObservableRecoveryContext,
        diagnosis: StructuredDiagnosis,
        candidates: List[Tuple[ActionMechanism, TimingWindow]],
        config: DeterministicPolicyConfig,
    ) -> List[ActionTimingCandidate]:
        """Estimate, rank, and sort all candidates descending by expected net recovery value."""
        scored = [
            cls.estimate_candidate(context, diagnosis, mech, timing, config)
            for mech, timing in candidates
        ]
        return sorted(scored, key=lambda s: s.expected_net_value_paise, reverse=True)
