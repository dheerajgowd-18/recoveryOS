"""Ablation Study Framework isolating contributions of LLM Diagnosis and LLM Strategy."""
import json
import logging
import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from evaluation.harness import EvaluationHarness, EvaluationResult
from evaluation.policies import (
    AgenticGraphRecoveryPolicy,
    BasePolicy,
    DeterministicRecoveryPolicy,
    LLMDrivenRecoveryPolicy,
)
from simulator.config import SimulatorConfig
from simulator.generator import SimulatedScenario, Simulator

logger = logging.getLogger("recoveryos.evaluation.ablation")


class AblationPolicyCohort:
    """Creates the 3 canonical ablation variants."""

    @staticmethod
    def get_cohort() -> List[BasePolicy]:
        from agent.agents import DiagnosisAgent, RecoveryStrategyAgent
        from intelligence.providers.deterministic import DeterministicDiagnosisProvider
        from intelligence.providers.llm_provider import LLMDiagnosisProvider
        from intelligence.providers.strategy_provider import (
            DeterministicStrategyProvider,
            LLMStrategyProvider,
        )

        # Variant A: Pure Deterministic Offline (Rules Diagnosis + Rules Strategy)
        det_policy = DeterministicRecoveryPolicy()
        det_policy.name = "A_DETERMINISTIC_DIAG_AND_STRAT"
        det_policy.description = "Ablation A: Deterministic Rule-Based Diagnosis + Deterministic Strategy Candidates"

        # Variant B: Hybrid (LLM Diagnosis + Deterministic Strategy)
        hybrid_policy = LLMDrivenRecoveryPolicy()
        hybrid_policy.name = "B_LLM_DIAG_DETERMINISTIC_STRAT"
        hybrid_policy.description = "Ablation B: Groq GPT-OSS-120B Diagnosis + Deterministic Strategy Heuristics"

        # Variant C: Full Agentic (LLM Diagnosis + LLM Strategy + Deterministic Economics + Governor)
        agentic_policy = AgenticGraphRecoveryPolicy()
        agentic_policy.name = "C_LLM_DIAG_AND_LLM_STRAT"
        agentic_policy.description = "Ablation C: Groq GPT-OSS-120B Diagnosis + Groq GPT-OSS-120B Strategy + Deterministic Economics"

        return [det_policy, hybrid_policy, agentic_policy]


class AblationResult(BaseModel):
    """Summarized results of the 3-cohort ablation study."""
    model_config = ConfigDict(extra="forbid")

    total_scenarios: int
    seeds: List[int]
    cohort_results: Dict[str, Dict[str, Any]]
    diagnosis_contribution_uplift_paise: int
    strategy_layer_incremental_value_paise: int
    total_ai_layer_uplift_paise: int


class AblationRunner:
    """Executes controlled ablation studies across synthetic scenarios."""

    def __init__(self, output_dir: str = "reports") -> None:
        self.output_dir = output_dir
        self.harness = EvaluationHarness()

    def run_ablation(
        self,
        seeds: Optional[List[int]] = None,
        scenarios_per_seed: int = 50,
    ) -> AblationResult:
        active_seeds = seeds or [42, 43]
        sim = Simulator()
        all_scenarios: List[SimulatedScenario] = []

        for seed in active_seeds:
            batch = sim.generate_batch(SimulatorConfig(seed=seed, num_scenarios=scenarios_per_seed))
            all_scenarios.extend(batch)

        policies = AblationPolicyCohort.get_cohort()
        results: Dict[str, EvaluationResult] = {}

        for p in policies:
            res = self.harness.evaluate_policy(p, all_scenarios)
            results[p.name] = res

        metrics_a = results["A_DETERMINISTIC_DIAG_AND_STRAT"].metrics
        metrics_b = results["B_LLM_DIAG_DETERMINISTIC_STRAT"].metrics
        metrics_c = results["C_LLM_DIAG_AND_LLM_STRAT"].metrics

        diag_uplift = metrics_b.incremental_adjusted_net_recovery_paise - metrics_a.incremental_adjusted_net_recovery_paise
        strat_layer_uplift = metrics_c.incremental_adjusted_net_recovery_paise - metrics_b.incremental_adjusted_net_recovery_paise
        total_ai_uplift = metrics_c.incremental_adjusted_net_recovery_paise - metrics_a.incremental_adjusted_net_recovery_paise

        summary_dict = {
            p_name: {
                "gross_recovered_paise": r.metrics.gross_recovered_amount_paise,
                "action_cost_paise": r.metrics.total_action_cost_paise,
                "churn_count": r.metrics.total_churned_customers,
                "adjusted_net_paise": r.metrics.adjusted_net_recovery_paise,
                "incremental_adjusted_net_paise": r.metrics.incremental_adjusted_net_recovery_paise,
                "interventions": r.metrics.total_interventions,
                "abstentions": r.metrics.actions_avoided_count,
                "abstention_rate": round(r.metrics.abstention_count / max(1, r.metrics.total_scenarios), 3),
            }
            for p_name, r in results.items()
        }

        ablation_summary = AblationResult(
            total_scenarios=len(all_scenarios),
            seeds=active_seeds,
            cohort_results=summary_dict,
            diagnosis_contribution_uplift_paise=diag_uplift,
            strategy_layer_incremental_value_paise=strat_layer_uplift,
            total_ai_layer_uplift_paise=total_ai_uplift,
        )

        self._save_ablation_reports(ablation_summary)
        return ablation_summary

    def _save_ablation_reports(self, summary: AblationResult) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        report_path = os.path.join(self.output_dir, "ablation_summary.md")

        lines = [
            "# RecoveryOS Ablation Study Summary",
            "",
            f"- **Cohort Size**: {summary.total_scenarios} scenarios (Seeds: {summary.seeds})",
            f"- **AI Model**: `openai/gpt-oss-120b` via Groq",
            f"- **Evaluation Date**: Controlled Simulation Replay",
            "",
            "## Cohort Performance Comparison",
            "",
            "| Variant | Description | Gross Recov (₹) | Costs (₹) | Churns | Adj Net (₹) | Incr Adj Net (₹) | Interventions | Abstentions |",
            "|---|---|---|---|---|---|---|---|---|",
        ]

        for name, data in summary.cohort_results.items():
            gross_inr = data["gross_recovered_paise"] / 100.0
            cost_inr = data["action_cost_paise"] / 100.0
            adj_net_inr = data["adjusted_net_paise"] / 100.0
            incr_inr = data["incremental_adjusted_net_paise"] / 100.0
            lines.append(
                f"| `{name}` | Variant | ₹{gross_inr:,.2f} | ₹{cost_inr:,.2f} | {data['churn_count']} | ₹{adj_net_inr:,.2f} | ₹{incr_inr:,.2f} | {data['interventions']} | {data['abstentions']} ({data['abstention_rate']:.1%}) |"
            )

        lines.extend([
            "",
            "## AI Component Uplift Decomposition",
            "",
            f"- **LLM Diagnosis Incremental Uplift (B - A)**: ₹{summary.diagnosis_contribution_uplift_paise / 100.0:,.2f}",
            f"- **Incremental Value of Full Agentic Strategy Layer (C - B)**: ₹{summary.strategy_layer_incremental_value_paise / 100.0:,.2f}",
            f"- **Total Combined AI Layer Value (C - A)**: ₹{summary.total_ai_layer_uplift_paise / 100.0:,.2f}",
            "",
            "> **Methodological Note on Strategy Uplift**: The C − B difference estimates the incremental value of introducing the full agentic strategy layer over the diagnosis-only hybrid baseline. It is not an isolated causal estimate of the strategy model alone because downstream strategy/timing behavior differs between the cohorts.",
            "",
            "---",
            "*Generated by RecoveryOS Evaluation Lab*",
        ])

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
