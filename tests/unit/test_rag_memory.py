"""Unit tests for Recovery Memory and RAG bounded context retrieval."""
import pytest

from intelligence.context import ObservableRecoveryContext
from rag.customer_memory import CustomerMemoryStore
from rag.merchant_memory import MerchantMemoryStore
from rag.retrieval import RecoveryMemoryRetriever
from rag.schemas import BoundedContextBundle, MemoryCategory, RecoveryMemoryItem


@pytest.fixture
def sample_context():
    return ObservableRecoveryContext(
        scenario_id="scen_rag_test_01",
        payment_id="pay_rag_01",
        customer_id="cust_high_responsive",
        amount_in_paise=450000,
        currency="INR",
        payment_method="card",
        attempt_count=1,
        error_code="GATEWAY_ERROR",
        error_source="gateway",
        error_reason="gateway_timeout",
    )


class TestRecoveryMemoryRAG:
    """Validates bounded retrieval, provenance generation, and isolation from hidden truth."""

    def test_bounded_context_assembly(self, sample_context):
        retriever = RecoveryMemoryRetriever()
        bundle = retriever.retrieve_bounded_context(sample_context)

        assert isinstance(bundle, BoundedContextBundle)
        assert bundle.scenario_id == sample_context.scenario_id
        assert len(bundle.retrieved_items) <= 5
        assert bundle.retrieval_latency_ms >= 0.0

        # Check required categories present
        categories = {item.category for item in bundle.retrieved_items}
        assert MemoryCategory.CUSTOMER_HISTORY in categories
        assert MemoryCategory.MERCHANT_PLAYBOOK in categories
        assert MemoryCategory.OPERATIONAL_TELEMETRY in categories

    def test_provenance_metadata_attached_to_all_items(self, sample_context):
        retriever = RecoveryMemoryRetriever()
        bundle = retriever.retrieve_bounded_context(sample_context)

        for item in bundle.retrieved_items:
            assert item.provenance.source_system is not None
            assert item.provenance.record_id is not None
            assert item.provenance.relevance_score >= 0.0
            assert len(item.provenance.retrieval_rationale) > 0

    def test_merchant_playbook_matching_logic(self):
        store = MerchantMemoryStore()
        # Gateway error matches transient gateway playbook
        gw_pb = store.match_playbook("GATEWAY_ERROR", 50000)
        assert gw_pb.rule_id == "pb_transient_gateway"

        # High value matches enterprise playbook
        high_val_pb = store.match_playbook("GATEWAY_ERROR", 15_000_000)
        assert high_val_pb.rule_id == "pb_high_value_enterprise"

    def test_customer_memory_profile_lookup(self):
        store = CustomerMemoryStore()
        prof = store.get_profile("cust_high_responsive")
        assert prof.is_vip is True
        assert prof.prior_recovery_success_rate > 0.90

        # Unknown customer returns safe fallback
        unknown = store.get_profile("cust_unseen_999")
        assert unknown.account_age_days == 60
        assert unknown.lifetime_successful_payments == 1

    def test_rag_memory_injected_into_llm_prompt(self, sample_context):
        from intelligence.providers.llm_provider import LLMDiagnosisProvider
        retriever = RecoveryMemoryRetriever()
        bundle = retriever.retrieve_bounded_context(sample_context)

        provider = LLMDiagnosisProvider()
        prompt = provider.build_user_prompt(sample_context, bundle)

        # Check prompt contains bounded memory headers and provenance info
        assert "RETRIEVED RECOVERY MEMORY" in prompt
        assert "recoveryos_event_store" in prompt
        assert "cust_high_responsive" in prompt

    def test_no_hidden_simulator_fields_leak_into_llm_prompt(self, sample_context):
        from intelligence.providers.llm_provider import LLMDiagnosisProvider
        retriever = RecoveryMemoryRetriever()
        bundle = retriever.retrieve_bounded_context(sample_context)

        provider = LLMDiagnosisProvider()
        prompt = provider.build_user_prompt(sample_context, bundle)

        forbidden_leak_strings = [
            "hidden_outcomes",
            "potential_outcomes",
            "ground_truth",
            "counterfactual",
            "LATENT_ARCHETYPE",
            "simulated_recovery_delay",
        ]
        for s in forbidden_leak_strings:
            assert s not in prompt, f"Forbidden simulator private variable '{s}' leaked into LLM prompt!"

