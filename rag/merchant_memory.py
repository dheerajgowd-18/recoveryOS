"""Merchant playbooks, communication templates, and operational recovery policy knowledge."""
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from rag.schemas import MemoryCategory, MemoryProvenance, RecoveryMemoryItem


class PlaybookRule(BaseModel):
    """Specific recovery playbook rule matching error conditions."""
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(..., description="Unique playbook rule ID")
    error_signature: str = Field(..., description="Target error category or code pattern")
    recommended_playbook: str = Field(..., description="Approved recovery strategy name")
    approved_channels: List[str] = Field(default_factory=list, description="Approved outreach channels")
    cooldown_hours: int = Field(default=4, ge=0, description="Mandatory minimum spacing between contacts")
    max_discount_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Maximum authorized incentive discount")
    escalation_triggers: List[str] = Field(default_factory=list, description="Conditions requiring human operator review")


class MerchantMemoryStore:
    """Store of merchant approved recovery playbooks, communication templates, and operational rules."""

    def __init__(self) -> None:
        self._playbooks: List[PlaybookRule] = []
        self._populate_standard_playbooks()

    def _populate_standard_playbooks(self) -> None:
        """Populate standard fintech recovery playbooks."""
        self._playbooks = [
            PlaybookRule(
                rule_id="pb_transient_gateway",
                error_signature="GATEWAY_ERROR",
                recommended_playbook="silent_delayed_retry_2h_6h",
                approved_channels=[],
                cooldown_hours=2,
                max_discount_pct=0.0,
                escalation_triggers=["GATEWAY_OUTAGE_PERSISTENT_GT_12H"],
            ),
            PlaybookRule(
                rule_id="pb_insufficient_funds",
                error_signature="INSUFFICIENT_FUNDS",
                recommended_playbook="delayed_retry_6h_or_payment_link",
                approved_channels=["whatsapp", "email"],
                cooldown_hours=6,
                max_discount_pct=0.0,
                escalation_triggers=["ATTEMPTS_GE_3", "AMOUNT_GT_50000_INR"],
            ),
            PlaybookRule(
                rule_id="pb_expired_instrument",
                error_signature="EXPIRED_PAYMENT_METHOD",
                recommended_playbook="immediate_payment_method_update_link",
                approved_channels=["email", "sms"],
                cooldown_hours=12,
                max_discount_pct=5.0,
                escalation_triggers=["VIP_ACCOUNT_CANCELLATION_RISK"],
            ),
            PlaybookRule(
                rule_id="pb_high_value_enterprise",
                error_signature="HIGH_VALUE_THRESHOLD",
                recommended_playbook="manual_account_executive_outreach",
                approved_channels=["email", "phone"],
                cooldown_hours=0,
                max_discount_pct=10.0,
                escalation_triggers=["AMOUNT_GT_100000_INR", "DIAGNOSIS_CONFIDENCE_LT_80"],
            ),
        ]

    def match_playbook(self, error_code: Optional[str], amount_in_paise: int) -> PlaybookRule:
        """Find the best-matching merchant playbook rule."""
        code = (error_code or "").upper()
        if amount_in_paise >= 10_000_000:  # >= ₹100,000
            return next(p for p in self._playbooks if p.rule_id == "pb_high_value_enterprise")
        for pb in self._playbooks:
            if pb.error_signature in code or code in pb.error_signature:
                return pb
        # Default fallback playbook
        return self._playbooks[1]

    def retrieve_memory_item(self, error_code: Optional[str], amount_in_paise: int) -> RecoveryMemoryItem:
        """Retrieve bounded merchant playbook memory item with provenance metadata."""
        playbook = self.match_playbook(error_code, amount_in_paise)
        now_epoch = int(time.time())

        return RecoveryMemoryItem(
            item_id=f"mem_pb_{playbook.rule_id}",
            category=MemoryCategory.MERCHANT_PLAYBOOK,
            title=f"Merchant Recovery Playbook: {playbook.recommended_playbook}",
            content=playbook.model_dump(),
            provenance=MemoryProvenance(
                source_system="merchant_playbook_engine_v2",
                record_id=playbook.rule_id,
                retrieval_timestamp_epoch=now_epoch,
                relevance_score=0.90,
                retrieval_rationale="Approved merchant intervention protocols, communication channels, and escalation bounds.",
            ),
        )
