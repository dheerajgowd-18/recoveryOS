"""Bounded Recovery Memory Retrieval Engine constructing sanitized context bundles with verifiable provenance."""
import time
from typing import List, Optional

from intelligence.context import ObservableRecoveryContext
from rag.customer_memory import CustomerMemoryStore
from rag.merchant_memory import MerchantMemoryStore
from rag.schemas import BoundedContextBundle, MemoryCategory, MemoryProvenance, RecoveryMemoryItem


class RecoveryMemoryRetriever:
    """Retrieves a strictly bounded set of decision-relevant facts with provenance metadata.

    Guarantees:
    - Never leaks simulator private truth Y(a) or latent archetypes.
    - Capped retrieval size (max 5 items).
    - Structured provenance attached to every fact for audit replay.
    """

    def __init__(
        self,
        customer_store: Optional[CustomerMemoryStore] = None,
        merchant_store: Optional[MerchantMemoryStore] = None,
        max_items: int = 5,
    ) -> None:
        self.customer_store = customer_store or CustomerMemoryStore()
        self.merchant_store = merchant_store or MerchantMemoryStore()
        self.max_items = max_items

    def retrieve_bounded_context(
        self,
        context: ObservableRecoveryContext,
    ) -> BoundedContextBundle:
        """Assembles a bounded contextual memory bundle for the decision pipeline."""
        start_time = time.perf_counter()
        now_epoch = int(time.time())
        items: List[RecoveryMemoryItem] = []

        # 1. Customer History Memory Item
        cust_id = context.customer_id or "cust_default"
        cust_item = self.customer_store.retrieve_memory_item(cust_id)
        items.append(cust_item)

        # 2. Merchant Playbook Memory Item
        pb_item = self.merchant_store.retrieve_memory_item(
            error_code=context.error_code or context.error_reason,
            amount_in_paise=context.amount_in_paise,
        )
        items.append(pb_item)

        # 3. Operational Telemetry Memory Item
        op_item = RecoveryMemoryItem(
            item_id=f"mem_op_{context.payment_id or 'unknown'}",
            category=MemoryCategory.OPERATIONAL_TELEMETRY,
            title="Operational Telemetry & Current State",
            content={
                "attempt_count": context.attempt_count,
                "recent_failed_attempts": context.recent_failed_attempts,
                "contacts_in_last_24h": context.contacts_in_last_24h,
                "contacts_in_last_7d": context.contacts_in_last_7d,
                "time_since_failure_seconds": context.time_since_failure_seconds,
                "payment_method": context.payment_method,
                "subscription_status": context.subscription_status,
                "consent_opted_out": context.consent_opted_out,
            },
            provenance=MemoryProvenance(
                source_system="recoveryos_event_store",
                record_id=f"rec_agg_{context.payment_id or 'pay_none'}",
                retrieval_timestamp_epoch=now_epoch,
                relevance_score=0.99,
                retrieval_rationale="Current attempt counters and state bounds necessary for cooldown and frequency limit enforcement.",
            ),
        )
        items.append(op_item)

        # Enforce max items bound
        bounded_items = items[: self.max_items]
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return BoundedContextBundle(
            scenario_id=context.scenario_id,
            customer_id=context.customer_id,
            payment_id=context.payment_id,
            retrieved_items=bounded_items,
            customer_summary=cust_item.content,
            merchant_guidelines=pb_item.content,
            operational_context=op_item.content,
            retrieval_latency_ms=round(elapsed_ms, 2),
        )
