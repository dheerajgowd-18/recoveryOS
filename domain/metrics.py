"""Canonical financial metrics calculation for RecoveryOS.

Shared by both the Evaluation Lab benchmark runners and the Operations Console dashboard.
Ensures 100% mathematical consistency across all reporting surfaces.

Formulas:
- gross_recovery_paise = sum(recovered_amount_paise for recovered events)
- natural_recovery_paise = sum(recovered_amount_paise without intervention)
- incremental_recovery_paise = gross_recovery_paise - natural_recovery_paise
- total_action_cost_paise = sum(action_cost_paise for executed actions)
- net_recovery_paise = gross_recovery_paise - total_action_cost_paise
- incremental_net_recovery_paise = net_recovery_paise - natural_recovery_paise
- churn_penalty_paise = churned_customers_count * churn_penalty_per_customer_paise
- adjusted_net_recovery_paise = net_recovery_paise - churn_penalty_paise
- natural_adjusted_net_paise = natural_recovery_paise - (natural_churn_count * churn_penalty_per_customer_paise)
- incremental_adjusted_net_recovery_paise = adjusted_net_recovery_paise - natural_adjusted_net_paise
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CHURN_PENALTY_PAISE = 250_000  # ₹2,500 per churned customer


class CanonicalFinancialKPIs(BaseModel):
    """Encapsulates the standard financial KPIs computed across a cohort of recovery decisions."""
    model_config = ConfigDict(extra="forbid")

    total_cases: int = Field(default=0, ge=0, description="Total cases evaluated")
    gross_recovery_paise: int = Field(default=0, ge=0, description="Total gross recovery in paise")
    natural_recovery_paise: int = Field(default=0, ge=0, description="Total organic recovery without intervention in paise")
    incremental_recovery_paise: int = Field(default=0, description="Gross - Natural in paise")
    total_action_cost_paise: int = Field(default=0, ge=0, description="Direct execution cost in paise")
    net_recovery_paise: int = Field(default=0, description="Gross - Cost in paise")
    incremental_net_recovery_paise: int = Field(default=0, description="Net - Natural Net in paise")
    churned_customers_count: int = Field(default=0, ge=0, description="Number of churned customers")
    churn_penalty_paise: int = Field(default=0, ge=0, description="Churn count * penalty per customer in paise")
    adjusted_net_recovery_paise: int = Field(default=0, description="Net - Churn Penalty in paise")
    natural_adjusted_net_paise: int = Field(default=0, description="Natural - Natural Churn Penalty in paise")
    incremental_adjusted_net_recovery_paise: int = Field(default=0, description="North-star metric: Adjusted Net - Natural Adjusted Net in paise")
    actions_dispatched_count: int = Field(default=0, ge=0, description="Total active actions executed")
    actions_avoided_count: int = Field(default=0, ge=0, description="Total interventions safely avoided")
    human_reviews_escalated_count: int = Field(default=0, ge=0, description="Total cases escalated to human ops")
    policy_blocked_count: int = Field(default=0, ge=0, description="Total cases denied by policy governor")
    invalidation_count: int = Field(default=0, ge=0, description="Total stale actions invalidated")

    @property
    def gross_recovered_paise(self) -> int:
        return self.gross_recovery_paise

    @property
    def direct_action_costs_paise(self) -> int:
        return self.total_action_cost_paise

    @property
    def net_economic_benefit_paise(self) -> int:
        return self.incremental_adjusted_net_recovery_paise

    @property
    def incremental_recovered_revenue_paise(self) -> int:
        return self.incremental_net_recovery_paise

    @property
    def actions_executed_count(self) -> int:
        return self.actions_dispatched_count

    @property
    def human_reviews_count(self) -> int:
        return self.human_reviews_escalated_count

    @property
    def policy_blocks_count(self) -> int:
        return self.policy_blocked_count

    @property
    def invalidations_count(self) -> int:
        return self.invalidation_count

    @property
    def gross_recovery_inr(self) -> float:
        return round(self.gross_recovery_paise / 100.0, 2)

    @property
    def natural_recovery_inr(self) -> float:
        return round(self.natural_recovery_paise / 100.0, 2)

    @property
    def incremental_recovery_inr(self) -> float:
        return round(self.incremental_recovery_paise / 100.0, 2)

    @property
    def total_action_cost_inr(self) -> float:
        return round(self.total_action_cost_paise / 100.0, 2)

    @property
    def adjusted_net_recovery_inr(self) -> float:
        return round(self.adjusted_net_recovery_paise / 100.0, 2)

    @property
    def incremental_adjusted_net_recovery_inr(self) -> float:
        return round(self.incremental_adjusted_net_recovery_paise / 100.0, 2)


def compute_canonical_financial_kpis(
    records: List[Any],
    churn_penalty_per_customer_paise: int = DEFAULT_CHURN_PENALTY_PAISE,
) -> CanonicalFinancialKPIs:
    """Computes the authoritative financial KPIs from a list of records (DecisionRecord or ScenarioEvaluationRecord)."""
    if not records:
        return CanonicalFinancialKPIs()

    gross_rec = 0
    natural_rec = 0
    total_cost = 0
    churn_count = 0
    natural_churn_count = 0
    actions_executed = 0
    actions_avoided = 0
    human_reviews = 0
    policy_blocks = 0
    invalidations = 0

    for r in records:
        # Recovered amount
        rec_amt = getattr(r, "recovered_amount_paise", 0) or 0
        is_rec = getattr(r, "recovered", False)
        if is_rec and rec_amt > 0:
            gross_rec += rec_amt

        # Action & Governor
        act = getattr(r, "selected_action", None)
        act_str = act.value if hasattr(act, "value") else str(act or "")
        gov = str(getattr(r, "governor_decision", "") or "")
        stop = str(getattr(r, "stop_reason", "") or "").upper()

        # Natural recovered amount
        if hasattr(r, "natural_recovered_amount_paise"):
            nat_amt = getattr(r, "natural_recovered_amount_paise", 0) or 0
            natural_rec += nat_amt
        else:
            if is_rec and (act_str in ("NO_ACTION", "no_action") or gov == "ABSTAIN" or "ORGANIC" in stop):
                natural_rec += rec_amt

        # Action cost
        cost = getattr(r, "action_cost_paise", 0) or 0
        total_cost += cost

        # Customer churn
        churned = getattr(r, "customer_churned", False)
        if churned:
            churn_count += 1

        # Natural churn (if available)
        nat_churned = getattr(r, "natural_customer_churned", False)
        if nat_churned:
            natural_churn_count += 1

        # Operational counters
        if act_str not in ("NO_ACTION", "no_action", "") and gov == "ALLOW":
            actions_executed += 1
        if act_str in ("NO_ACTION", "no_action") or gov == "ABSTAIN":
            actions_avoided += 1
        if gov == "ESCALATE":
            human_reviews += 1
        if gov in ("DENY", "DEFER"):
            policy_blocks += 1
        if "STALE" in stop or "INVALIDAT" in stop:
            invalidations += 1

    net_rec = gross_rec - total_cost
    incr_rec = gross_rec - natural_rec
    incr_net = net_rec - natural_rec
    churn_pen = churn_count * churn_penalty_per_customer_paise
    adj_net = net_rec - churn_pen
    natural_adj_net = natural_rec - (natural_churn_count * churn_penalty_per_customer_paise)
    incr_adj_net = adj_net - natural_adj_net

    return CanonicalFinancialKPIs(
        total_cases=len(records),
        gross_recovery_paise=gross_rec,
        natural_recovery_paise=natural_rec,
        incremental_recovery_paise=incr_rec,
        total_action_cost_paise=total_cost,
        net_recovery_paise=net_rec,
        incremental_net_recovery_paise=incr_net,
        churned_customers_count=churn_count,
        churn_penalty_paise=churn_pen,
        adjusted_net_recovery_paise=adj_net,
        natural_adjusted_net_paise=natural_adj_net,
        incremental_adjusted_net_recovery_paise=incr_adj_net,
        actions_dispatched_count=actions_executed,
        actions_avoided_count=actions_avoided,
        human_reviews_escalated_count=human_reviews,
        policy_blocked_count=policy_blocks,
        invalidation_count=invalidations,
    )
