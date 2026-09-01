"""Structured diagnosis data contracts and taxonomy definitions for RecoveryOS."""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import SimulatedActionType


class DiagnosisLabel(str, Enum):
    """Canonical root-cause diagnosis taxonomy inferred strictly from observable context."""
    TRANSIENT_GATEWAY_FAILURE = "transient_gateway_failure"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    EXPIRED_PAYMENT_METHOD = "expired_payment_method"
    AUTHENTICATION_FAILURE = "authentication_failure"
    MANDATE_ISSUE = "mandate_issue"
    CUSTOMER_ABANDONMENT = "customer_abandonment"
    SUBSCRIPTION_PAYMENT_FAILURE = "subscription_payment_failure"
    OVERDUE_INVOICE = "overdue_invoice"
    UNKNOWN_FAILURE = "unknown_failure"


class StructuredDiagnosis(BaseModel):
    """Schema-validated, explainable diagnosis produced by an intelligence provider.

    Contains machine-readable evidence, confidence calibration, action recommendations,
    and fallback provenance.
    """
    model_config = ConfigDict(extra="forbid")

    diagnosis_label: DiagnosisLabel = Field(..., description="Root cause diagnosis category")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Calibrated confidence score [0.0, 1.0]")
    evidence_codes: List[str] = Field(default_factory=list, description="Observable evidence codes justifying diagnosis")
    uncertainties: List[str] = Field(default_factory=list, description="Identified risk factors or ambiguities")
    recommended_candidate_actions: List[SimulatedActionType] = Field(
        default_factory=list, description="Candidate recovery actions recommended by diagnosis"
    )
    recommended_timing_hint: Optional[str] = Field(
        default=None, description="Suggested execution timing hint (e.g. 'immediate', 'delay_2h', 'delay_6h')"
    )
    human_review_required: bool = Field(default=False, description="Flag requesting merchant operator review")
    abstain_recommended: bool = Field(default=False, description="Flag indicating intervention is likely value-destructive")
    rationale: str = Field(..., min_length=1, description="Audit rationale explaining the diagnostic inference")
    diagnosis_source: str = Field(
        default="deterministic_offline",
        description="Provenance source of diagnosis ('deterministic_offline', 'llm_structured', 'deterministic_fallback')",
    )
    model_version: Optional[str] = Field(default="v1.0", description="Diagnosis model or provider version")
