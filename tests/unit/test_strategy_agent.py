"""Unit tests for RecoveryStrategyAgent structured reasoning, context differentiation, and safety constraints."""
import pytest

from agent.agents import CandidateStrategyOption, RecoveryStrategyAgent
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import DiagnosisLabel, StrategyProposal, StructuredDiagnosis
from planner.timing import ActionMechanism
from rag.schemas import BoundedContextBundle, MemoryCategory, MemoryProvenance, RecoveryMemoryItem
from simulator.config import SimulatedActionType


@pytest.fixture
def base_context() -> ObservableRecoveryContext:
    return ObservableRecoveryContext(
        scenario_id="scen_strategy_01",
        payment_id="pay_strat_01",
        customer_id="cust_strat_01",
        amount_in_paise=250000,  # ₹2,500
        currency="INR",
        payment_method="card",
        attempt_count=1,
        error_code="INSUFFICIENT_FUNDS",
        error_reason="insufficient_funds",
    )


@pytest.fixture
def base_diagnosis() -> StructuredDiagnosis:
    return StructuredDiagnosis(
        diagnosis_label=DiagnosisLabel.INSUFFICIENT_FUNDS,
        confidence=0.85,
        evidence_codes=["OBS_INSUFFICIENT_FUNDS"],
        uncertainties=[],
        recommended_candidate_actions=[SimulatedActionType.RETRY_LATER, SimulatedActionType.PAYMENT_LINK],
        recommended_timing_hint="delay_6h",
        human_review_required=False,
        abstain_recommended=False,
        rationale="Account funds depleted at payroll cycle; retry in +6h or send payment link.",
        diagnosis_source="llm_structured",
        model_version="groq-openai/gpt-oss-120b",
    )


class TestRecoveryStrategyAgent:
    """Validates structured candidate proposals, context differentiation, and safety bounds."""

    def test_strategy_agent_produces_structured_strategy_proposal(self, base_context, base_diagnosis):
        agent = RecoveryStrategyAgent()
        proposal = agent.propose_strategy(base_context, base_diagnosis)

        assert isinstance(proposal, StrategyProposal)
        assert len(proposal.proposals) >= 2
        assert proposal.primary_recommendation in (SimulatedActionType.RETRY_LATER, SimulatedActionType.PAYMENT_LINK, SimulatedActionType.NO_ACTION)
        assert len(proposal.strategic_summary) > 0

        # Check fields of candidates
        for cand in proposal.proposals:
            assert cand.action_type is not None
            assert len(cand.mechanism) > 0
            assert len(cand.rationale) > 0
            assert 0.0 <= cand.confidence <= 1.0
            assert len(cand.why_better_than_abstain) > 0
            assert len(cand.why_alternative_inferior) > 0

    def test_strategy_agent_always_includes_first_class_abstention(self, base_context, base_diagnosis):
        agent = RecoveryStrategyAgent()
        proposal = agent.propose_strategy(base_context, base_diagnosis)

        abstain_cands = [c for c in proposal.proposals if c.is_abstention]
        assert len(abstain_cands) == 1
        assert abstain_cands[0].action_type == SimulatedActionType.NO_ACTION
        assert abstain_cands[0].confidence == 1.0

    def test_context_differentiation_contact_fatigue_prompts_risk_warning(self, base_context, base_diagnosis):
        """When customer has high contact count in 24h, strategy agent flags fatigue and deprioritizes intrusive reminders."""
        memory_item = RecoveryMemoryItem(
            item_id="mem_fatigue_01",
            category=MemoryCategory.OPERATIONAL_TELEMETRY,
            title="Operational Activity",
            content={"contacts_in_last_24h": 3, "recent_failed_attempts": 2},
            provenance=MemoryProvenance(
                source_system="notification_service",
                record_id="notif_99",
                relevance_score=1.0,
                retrieval_rationale="Recent notifications",
                retrieval_timestamp_epoch=1700000000,
            ),
        )
        bundle = BoundedContextBundle(
            scenario_id=base_context.scenario_id,
            retrieved_items=[memory_item],
            retrieval_latency_ms=0.8,
        )

        agent = RecoveryStrategyAgent()
        proposal = agent.propose_strategy(base_context, base_diagnosis, memory_bundle=bundle)

        reminder_cands = [c for c in proposal.proposals if c.mechanism == "reminder"]
        if reminder_cands:
            assert any("CONTACT_FATIGUE" in str(c.risk_notes) for c in reminder_cands)

    def test_context_differentiation_vip_customer_attaches_priority_evidence(self, base_context, base_diagnosis):
        """When customer is VIP with WhatsApp preference, strategy candidate reflects channel and priority."""
        memory_item = RecoveryMemoryItem(
            item_id="mem_vip_01",
            category=MemoryCategory.CUSTOMER_HISTORY,
            title="Customer Profile",
            content={"is_vip": True, "preferred_channel": "whatsapp", "prior_recovery_success_rate": 0.95},
            provenance=MemoryProvenance(
                source_system="crm",
                record_id="cust_vip_1",
                relevance_score=1.0,
                retrieval_rationale="Customer account profile",
                retrieval_timestamp_epoch=1700000000,
            ),
        )
        bundle = BoundedContextBundle(
            scenario_id=base_context.scenario_id,
            retrieved_items=[memory_item],
            retrieval_latency_ms=0.5,
        )

        agent = RecoveryStrategyAgent()
        proposal = agent.propose_strategy(base_context, base_diagnosis, memory_bundle=bundle)

        link_cands = [c for c in proposal.proposals if c.mechanism == "payment_link"]
        assert len(link_cands) > 0
        assert link_cands[0].preferred_channel == "whatsapp"
        assert "VIP_CUSTOMER_PRIORITY" in link_cands[0].supporting_evidence

    def test_physical_impossibility_prevents_retry_on_expired_card(self):
        """Physical constraint: Bank retry is physically impossible for expired card."""
        ctx = ObservableRecoveryContext(
            scenario_id="scen_expired_01",
            amount_in_paise=100000,
            attempt_count=1,
            error_code="BAD_REQUEST_ERROR",
            error_reason="card_expired",
        )
        diag = StructuredDiagnosis(
            diagnosis_label=DiagnosisLabel.EXPIRED_PAYMENT_METHOD,
            confidence=0.95,
            evidence_codes=["OBS_CARD_EXPIRED"],
            uncertainties=[],
            recommended_candidate_actions=[SimulatedActionType.RETRY_NOW, SimulatedActionType.PAYMENT_LINK],
            rationale="Card expired",
            diagnosis_source="llm_structured",
        )

        agent = RecoveryStrategyAgent()
        candidates = agent.generate_strategy_candidates(ctx, diag)
        action_types = [c.action_type for c in candidates]

        # Retry now and retry later MUST be filtered out as physically impossible
        assert SimulatedActionType.RETRY_NOW not in action_types
        assert SimulatedActionType.RETRY_LATER not in action_types
        assert SimulatedActionType.PAYMENT_LINK in action_types
        assert SimulatedActionType.NO_ACTION in action_types
