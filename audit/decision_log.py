"""Audit models and decision log storage for deterministic decision provenance and compliance tracking."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import SimulatedActionType


class CandidateScore(BaseModel):
    """Detailed scoring evaluation for a single candidate action considered during policy decisioning."""
    model_config = ConfigDict(extra="forbid")

    action_type: SimulatedActionType = Field(..., description="Candidate action type")
    is_admissible: bool = Field(..., description="Whether action was admissible under failure physics constraints")
    rejection_reason: Optional[str] = Field(default=None, description="Reason for rejection if inadmissible")
    expected_recovery_prob: float = Field(default=0.0, ge=0.0, le=1.0, description="Estimated recovery probability prior")
    action_cost_paise: int = Field(default=0, ge=0, description="Direct cost of action in paise")
    expected_net_value_paise: int = Field(default=0, description="Estimated net monetary recovery in paise (can be negative)")
    incremental_uplift_paise: int = Field(default=0, description="Estimated incremental uplift vs no-action in paise (can be negative)")


class DecisionRecord(BaseModel):
    """Immutable audit record capturing full context, reasoning, and governance for an autonomous recovery decision."""
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(..., description="Unique deterministic decision identifier")
    scenario_id: str = Field(..., description="Scenario identifier")
    payment_id: str = Field(..., description="Razorpay payment identifier")
    iteration: int = Field(..., ge=1, description="Cycle iteration index")
    timestamp_epoch: int = Field(..., ge=0, description="Epoch timestamp of decision")
    policy_name: str = Field(..., description="Executing policy identifier")
    policy_version: str = Field(..., description="Policy version string")
    model_version: str = Field(default="deterministic-proxy-v1", description="Model / scoring engine version")
    diagnosis_label: str = Field(..., description="Inferred diagnosis classification")
    diagnosis_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score of diagnosis")
    diagnosis_source: str = Field(default="deterministic_offline", description="Diagnosis provider source")
    evidence_codes: List[str] = Field(default_factory=list, description="Observable evidence codes used in diagnosis")
    governor_decision: Optional[str] = Field(default=None, description="Governor outcome: ALLOW, DENY, DEFER, ESCALATE, ABSTAIN")
    governor_reason_codes: List[str] = Field(default_factory=list, description="Governor check reason codes")
    governor_policy_version: Optional[str] = Field(default=None, description="Merchant policy version applied by Governor")
    human_review_reason: Optional[str] = Field(default=None, description="Detailed human review trigger reason if escalated")
    failure_class: Optional[str] = Field(default=None, description="Ground truth failure class (evaluator audit only)")
    failure_code: Optional[str] = Field(default=None, description="Observed error code")
    amount_in_paise: int = Field(..., ge=0, description="Transaction amount in paise")
    aggregate_state_before: str = Field(..., description="Reconciled payment state prior to decision/execution")
    aggregate_state_after: str = Field(..., description="Reconciled payment state after execution cycle")
    aggregate_state: str = Field(..., description="Reconciled payment state at evaluation")
    risk_level: str = Field(..., description="Risk detector classification (NONE, LOW, HIGH)")
    candidate_scores: List[CandidateScore] = Field(default_factory=list, description="All evaluated candidate actions")
    selected_action: SimulatedActionType = Field(..., description="Action chosen by the policy")
    timing_window: Optional[str] = Field(default=None, description="Timing window bucket")
    delay_seconds: int = Field(default=0, ge=0, description="Scheduled delay in seconds")
    scheduled_action_id: Optional[str] = Field(default=None, description="Associated scheduled action identifier if delayed")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Decision confidence score")
    rationale: str = Field(..., description="Audit rationale for decision")
    reason_codes: List[str] = Field(default_factory=list, description="Machine-readable audit reason codes")
    execution_result_success: Optional[bool] = Field(default=None, description="Whether execution succeeded")
    recovered: Optional[bool] = Field(default=None, description="Whether revenue was captured")
    action_cost_paise: Optional[int] = Field(default=None, description="Actual action cost incurred")
    recovered_amount_paise: Optional[int] = Field(default=None, description="Actual revenue recovered")
    stop_reason: Optional[str] = Field(default=None, description="Runtime stopping reason")
    observable_context: Optional[Dict[str, Any]] = Field(default=None, description="Snapshot of observable context")


class DecisionLogStore:
    """In-memory append-only log store for decision provenance and post-mortem audit inspection."""

    def __init__(self) -> None:
        self._records: List[DecisionRecord] = []

    def save_record(self, record: DecisionRecord) -> None:
        """Persist a new immutable decision audit record."""
        self._records.append(record)

    def get_record(self, decision_id: str) -> Optional[DecisionRecord]:
        """Lookup a decision record by unique decision_id."""
        for r in self._records:
            if r.decision_id == decision_id:
                return r
        return None

    def get_records_for_scenario(self, scenario_id: str) -> List[DecisionRecord]:
        """Retrieve all decision records associated with a given scenario."""
        return [r for r in self._records if r.scenario_id == scenario_id]

    def list_records(self) -> List[DecisionRecord]:
        """Return all persisted decision records chronologically."""
        return list(self._records)

    def get_all_records(self) -> List[DecisionRecord]:
        """Alias returning all persisted decision records."""
        return self.list_records()
