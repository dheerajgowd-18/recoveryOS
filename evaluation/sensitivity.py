"""Economic sensitivity analysis across churn penalties and execution cost multipliers."""
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from evaluation.harness import EvaluationHarness, EvaluationResult
from evaluation.metrics import DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER, MetricCalculator, ScenarioEvaluationRecord
from evaluation.policies import (
    AlwaysRetryPolicy,
    BasePolicy,
    NoActionPolicy,
    ProbabilityOnlyPolicy,
    StaticRulePolicy,
)
from policy.deterministic import DeterministicRecoveryPolicy
from simulator.config import SimulatedActionType
from simulator.generator import SimulatedScenario
from simulator.outcomes import ActionOutcome

__all__ = [
    "SensitivityCellResult",
    "SensitivityAnalysisResult",
    "SensitivityAnalyzer",
]


class SensitivityCellResult(BaseModel):
    """Evaluation outcome for a single parameter cell in the sensitivity grid."""
    model_config = ConfigDict(extra="forbid")

    churn_penalty_paise: int = Field(..., description="Churn friction penalty in paise")
    churn_penalty_inr: float = Field(..., description="Churn friction penalty in INR")
    action_cost_multiplier: float = Field(..., description="Direct execution cost scaling factor")
    policy_incremental_adjusted_net_paise: Dict[str, int] = Field(
        ..., description="Incremental adjusted net recovery in paise per policy"
    )
    best_baseline_name: str = Field(..., description="Top performing baseline policy name")
    best_baseline_incremental_adjusted_net_paise: int = Field(
        ..., description="Top baseline incremental adjusted net recovery in paise"
    )
    recoveryos_incremental_adjusted_net_paise: int = Field(
        ..., description="RecoveryOS incremental adjusted net recovery in paise"
    )
    recoveryos_margin_over_best_baseline_paise: int = Field(
        ..., description="Economic advantage of RecoveryOS over top baseline in paise (RecoveryOS - Best Baseline)"
    )
    winning_policy_name: str = Field(..., description="Policy with highest incremental adjusted net recovery")
    recoveryos_wins: bool = Field(..., description="Whether RecoveryOS outperformed all baseline benchmarks")


class SensitivityAnalysisResult(BaseModel):
    """Complete multi-parameter sensitivity analysis report."""
    model_config = ConfigDict(extra="forbid")

    total_combinations: int = Field(..., ge=1, description="Total parameter cells evaluated")
    recoveryos_wins_count: int = Field(..., ge=0, description="Total parameter cells won by RecoveryOS")
    recoveryos_win_rate_pct: float = Field(..., ge=0.0, le=100.0, description="Proportion of cells won by RecoveryOS")
    grid_cells: List[SensitivityCellResult] = Field(..., description="Detailed per-cell economic evaluations")
    markdown_matrix: str = Field(..., description="Formatted markdown sensitivity table")


class SensitivityAnalyzer:
    """Evaluates economic robustness of RecoveryOS against baseline heuristics across parameter grids."""

    DEFAULT_CHURN_PENALTIES_PAISE = [100_000, 250_000, 500_000]  # ₹1,000, ₹2,500, ₹5,000
    DEFAULT_COST_MULTIPLIERS = [0.5, 1.0, 2.0]

    def __init__(
        self,
        churn_penalties_paise: Optional[List[int]] = None,
        action_cost_multipliers: Optional[List[float]] = None,
    ) -> None:
        self.churn_penalties_paise = churn_penalties_paise or self.DEFAULT_CHURN_PENALTIES_PAISE
        self.action_cost_multipliers = action_cost_multipliers or self.DEFAULT_COST_MULTIPLIERS

    def run_analysis(
        self,
        scenarios: List[SimulatedScenario],
        policies: Optional[List[BasePolicy]] = None,
    ) -> SensitivityAnalysisResult:
        """Executes sensitivity grid sweep across all churn penalty and action cost combinations."""
        if policies is None:
            policies = [
                NoActionPolicy(),
                AlwaysRetryPolicy(),
                StaticRulePolicy(),
                ProbabilityOnlyPolicy(),
                DeterministicRecoveryPolicy(),
            ]

        # First run base evaluation across all policies to collect decision traces
        harness = EvaluationHarness()
        base_results = harness.evaluate_all(policies, scenarios)

        grid_cells: List[SensitivityCellResult] = []
        recoveryos_policy_name = "RECOVERYOS_DETERMINISTIC_V0"

        for penalty in self.churn_penalties_paise:
            for cost_mult in self.action_cost_multipliers:
                cell_incr_adj: Dict[str, int] = {}

                for pol in policies:
                    res = base_results.get(pol.name)
                    if not res:
                        continue

                    # Rescore records under modified cost multiplier and churn penalty
                    adj_net_total = 0
                    for rec in res.records:
                        scaled_cost = int(round(rec.action_cost_paise * cost_mult))
                        churn_cost = penalty if rec.customer_churned else 0
                        net_val = rec.recovered_amount_paise - scaled_cost - churn_cost
                        adj_net_total += net_val

                    # For baseline 0 (no action), compute its adjusted net total under current penalty
                    base0_res = base_results.get("baseline_0_no_action")
                    base0_adj_net = 0
                    if base0_res:
                        for rec in base0_res.records:
                            scaled_cost = int(round(rec.action_cost_paise * cost_mult))
                            churn_cost = penalty if rec.customer_churned else 0
                            base0_adj_net += (rec.recovered_amount_paise - scaled_cost - churn_cost)

                    incr_adj_net = adj_net_total - base0_adj_net
                    cell_incr_adj[pol.name] = incr_adj_net

                # Find best baseline (excluding RecoveryOS)
                baseline_items = {k: v for k, v in cell_incr_adj.items() if k != recoveryos_policy_name}
                if baseline_items:
                    best_baseline_name, best_baseline_val = max(baseline_items.items(), key=lambda x: x[1])
                else:
                    best_baseline_name, best_baseline_val = "baseline_0_no_action", 0

                rec_val = cell_incr_adj.get(recoveryos_policy_name, 0)
                margin = rec_val - best_baseline_val
                winning_name, _ = max(cell_incr_adj.items(), key=lambda x: x[1])
                rec_wins = (winning_name == recoveryos_policy_name) or (rec_val >= best_baseline_val)

                cell = SensitivityCellResult(
                    churn_penalty_paise=penalty,
                    churn_penalty_inr=round(penalty / 100.0, 2),
                    action_cost_multiplier=cost_mult,
                    policy_incremental_adjusted_net_paise=cell_incr_adj,
                    best_baseline_name=best_baseline_name,
                    best_baseline_incremental_adjusted_net_paise=best_baseline_val,
                    recoveryos_incremental_adjusted_net_paise=rec_val,
                    recoveryos_margin_over_best_baseline_paise=margin,
                    winning_policy_name=winning_name,
                    recoveryos_wins=rec_wins,
                )
                grid_cells.append(cell)

        wins_count = sum(1 for c in grid_cells if c.recoveryos_wins)
        total_combos = len(grid_cells)
        win_rate = round((wins_count / total_combos) * 100.0, 2) if total_combos > 0 else 0.0

        # Generate markdown matrix table
        md_table = self._format_markdown_matrix(grid_cells)

        return SensitivityAnalysisResult(
            total_combinations=total_combos,
            recoveryos_wins_count=wins_count,
            recoveryos_win_rate_pct=win_rate,
            grid_cells=grid_cells,
            markdown_matrix=md_table,
        )

    def _format_markdown_matrix(self, cells: List[SensitivityCellResult]) -> str:
        """Formats sensitivity cells into an executive markdown matrix table."""
        lines = [
            "| Churn Penalty | Cost Mult | Top Baseline Policy | Top Baseline Incr Adj | RecoveryOS Incr Adj | RecoveryOS Margin | RecoveryOS Wins? |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for c in cells:
            pen_str = f"₹{c.churn_penalty_inr:,.0f}"
            cost_str = f"{c.action_cost_multiplier:.1f}x"
            base_str = c.best_baseline_name
            base_val_str = f"₹{c.best_baseline_incremental_adjusted_net_paise / 100.0:,.2f}"
            rec_val_str = f"₹{c.recoveryos_incremental_adjusted_net_paise / 100.0:,.2f}"
            margin_str = f"+₹{c.recoveryos_margin_over_best_baseline_paise / 100.0:,.2f}" if c.recoveryos_margin_over_best_baseline_paise >= 0 else f"-₹{abs(c.recoveryos_margin_over_best_baseline_paise) / 100.0:,.2f}"
            win_str = "✅ YES" if c.recoveryos_wins else "❌ NO"
            lines.append(f"| {pen_str} | {cost_str} | {base_str} | {base_val_str} | {rec_val_str} | {margin_str} | {win_str} |")
        return "\n".join(lines)
