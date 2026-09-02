"""Customer historical ledger and behavioral memory store (strictly observable features)."""
import time
from typing import Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from rag.schemas import MemoryCategory, MemoryProvenance, RecoveryMemoryItem


class CustomerRecoveryProfile(BaseModel):
    """Historical observable recovery profile for a customer."""
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(..., description="Customer identifier")
    account_age_days: int = Field(default=180, ge=0, description="Customer account tenure in days")
    lifetime_successful_payments: int = Field(default=5, ge=0, description="Total successful historical payments")
    prior_payment_failures: int = Field(default=1, ge=0, description="Total historical failure incidents")
    prior_recovery_success_rate: float = Field(default=0.80, ge=0.0, le=1.0, description="Historical recovery conversion rate")
    preferred_payment_method: str = Field(default="upi", description="Most frequently successful payment method")
    preferred_communication_channel: str = Field(default="whatsapp", description="Channel with highest response rate")
    average_recovery_delay_seconds: int = Field(default=7200, ge=0, description="Average time to recovery settlement")
    recent_interventions_count_24h: int = Field(default=0, ge=0, description="Interventions in the last 24 hours")
    recent_interventions_count_7d: int = Field(default=0, ge=0, description="Interventions in the last 7 days")
    is_subscription_active: bool = Field(default=True, description="Whether customer has an active recurring subscription")
    is_vip: bool = Field(default=False, description="VIP or high-LTV account flag")
    consent_opted_out: bool = Field(default=False, description="Whether customer has opted out of automated communications")


class CustomerMemoryStore:
    """In-memory store providing bounded customer history lookup with provenance."""

    def __init__(self) -> None:
        self._profiles: Dict[str, CustomerRecoveryProfile] = {}
        self._populate_bootstrap_profiles()

    def _populate_bootstrap_profiles(self) -> None:
        """Seed representative customer profiles for realistic retrieval."""
        profiles = [
            CustomerRecoveryProfile(
                customer_id="cust_high_responsive",
                account_age_days=365,
                lifetime_successful_payments=12,
                prior_payment_failures=1,
                prior_recovery_success_rate=0.92,
                preferred_payment_method="card",
                preferred_communication_channel="email",
                average_recovery_delay_seconds=3600,
                is_vip=True,
            ),
            CustomerRecoveryProfile(
                customer_id="cust_contact_fatigued",
                account_age_days=90,
                lifetime_successful_payments=2,
                prior_payment_failures=3,
                prior_recovery_success_rate=0.30,
                preferred_payment_method="upi",
                preferred_communication_channel="sms",
                recent_interventions_count_24h=2,
                recent_interventions_count_7d=4,
            ),
            CustomerRecoveryProfile(
                customer_id="cust_opted_out",
                account_age_days=200,
                lifetime_successful_payments=6,
                prior_payment_failures=1,
                prior_recovery_success_rate=0.50,
                consent_opted_out=True,
            ),
        ]
        for p in profiles:
            self._profiles[p.customer_id] = p

    def get_profile(self, customer_id: str) -> CustomerRecoveryProfile:
        """Retrieve customer recovery profile or construct conservative default."""
        if customer_id in self._profiles:
            return self._profiles[customer_id]
        # Return sensible default for new / unindexed customer
        return CustomerRecoveryProfile(
            customer_id=customer_id,
            account_age_days=60,
            lifetime_successful_payments=1,
            prior_payment_failures=0,
            prior_recovery_success_rate=0.50,
            preferred_payment_method="card",
            preferred_communication_channel="email",
            average_recovery_delay_seconds=7200,
        )

    def retrieve_memory_item(self, customer_id: str) -> RecoveryMemoryItem:
        """Retrieve bounded customer memory item with provenance metadata."""
        profile = self.get_profile(customer_id)
        now_epoch = int(time.time())

        return RecoveryMemoryItem(
            item_id=f"mem_cust_{customer_id}",
            category=MemoryCategory.CUSTOMER_HISTORY,
            title=f"Customer History Profile ({customer_id})",
            content=profile.model_dump(),
            provenance=MemoryProvenance(
                source_system="customer_ledger_v1",
                record_id=f"crm_rec_{customer_id}",
                retrieval_timestamp_epoch=now_epoch,
                relevance_score=0.95,
                retrieval_rationale="Historical recovery conversion rate and channel preference inform intervention selection and timing.",
            ),
        )
