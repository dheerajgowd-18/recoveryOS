"""Data contracts for bounded Recovery Memory and RAG retrieval provenance."""
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class MemoryCategory(str, Enum):
    """Categorical classification of decision-relevant memory elements."""
    CUSTOMER_HISTORY = "customer_history"
    MERCHANT_PLAYBOOK = "merchant_playbook"
    OPERATIONAL_TELEMETRY = "operational_telemetry"
    POLICY_RULESET = "policy_ruleset"


class MemoryProvenance(BaseModel):
    """Immutable provenance tracking for each retrieved memory fact."""
    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(..., description="Origin system e.g. 'crm_ledger', 'merchant_playbook_store', 'event_store'")
    record_id: str = Field(..., description="Unique record or document identifier in source system")
    retrieval_timestamp_epoch: int = Field(..., description="Epoch timestamp when retrieval occurred")
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="Semantic or rule-based relevance confidence [0.0, 1.0]")
    retrieval_rationale: str = Field(..., description="Explanation of why this memory item is decision-relevant")


class RecoveryMemoryItem(BaseModel):
    """A discrete, bounded memory item with structured payload and provenance."""
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., description="Unique memory item ID")
    category: MemoryCategory = Field(..., description="Memory classification category")
    title: str = Field(..., description="Concise human-readable description")
    content: Dict[str, Any] = Field(..., description="Structured bounded factual context payload")
    provenance: MemoryProvenance = Field(..., description="Origin provenance and relevance justification")


class BoundedContextBundle(BaseModel):
    """Bounded contextual bundle assembled for specialized agents and LLM inference.

    Strict Architectural Invariants:
    - Guaranteed bounded size (max items capped).
    - Strictly excludes simulator hidden ground truth Y(a) or latent archetypes.
    - Every included memory item contains verifiable provenance metadata for UI audit replay.
    """
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., description="Scenario identifier")
    customer_id: Optional[str] = Field(default=None, description="Customer identifier")
    payment_id: Optional[str] = Field(default=None, description="Payment transaction ID")
    retrieved_items: List[RecoveryMemoryItem] = Field(default_factory=list, description="Bounded collection of retrieved items")
    customer_summary: Optional[Dict[str, Any]] = Field(default=None, description="Structured customer profile summary")
    merchant_guidelines: Optional[Dict[str, Any]] = Field(default=None, description="Applicable merchant recovery playbooks")
    operational_context: Optional[Dict[str, Any]] = Field(default=None, description="Recent operational health context")
    retrieval_latency_ms: float = Field(default=0.0, ge=0.0, description="Total retrieval elapsed time in ms")
