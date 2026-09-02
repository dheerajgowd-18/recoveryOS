"""Ablation Study Framework isolating contributions of LLM Diagnosis and LLM Strategy."""
import json
import logging
import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from evaluation.harness import EvaluationExecutionMode, EvaluationHarness, EvaluationResult
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
    def get_cohort(strict_no_fallback: bool = False) -> List[BasePolicy]:
        from intelligence.providers.deterministic import DeterministicDiagnosisProvider
        from intelligence.providers.groq_provider import GroqLLMDiagnosisProvider

        # Variant A: Pure Deterministic Offline (Rules Diagnosis + Rules Strategy)
        det_policy = DeterministicRecoveryPolicy(
            diagnosis_provider=DeterministicDiagnosisProvider(),
        )
        det_policy.name = "A_DETERMINISTIC_DIAG_AND_STRAT"
        det_policy.description = "Ablation A: Deterministic Rule-Based Diagnosis + Deterministic Strategy Candidates"

        # Variant B: Hybrid (LLM Diagnosis + Deterministic Strategy)
        hybrid_policy = LLMDrivenRecoveryPolicy(
            diagnosis_provider=GroqLLMDiagnosisProvider(strict_no_fallback=strict_no_fallback),
        )
        hybrid_policy.name = "B_LLM_DIAG_DETERMINISTIC_STRAT"
        hybrid_policy.description = "Ablation B: Groq GPT-OSS-120B Diagnosis + Deterministic Strategy Heuristics"

        # Variant C: Full Agentic (LLM Diagnosis + LLM Strategy + Deterministic Economics + Governor)
        agentic_policy = AgenticGraphRecoveryPolicy()
        if strict_no_fallback:
            agentic_policy.diagnosis_agent.provider.strict_no_fallback = True
            agentic_policy.strategy_agent.provider.strict_no_fallback = True
        agentic_policy.name = "C_LLM_DIAG_AND_LLM_STRAT"
        agentic_policy.description = "Ablation C: Groq GPT-OSS-120B Diagnosis + Groq GPT-OSS-120B Strategy + Deterministic Economics"

        return [det_policy, hybrid_policy, agentic_policy]


class AblationResult(BaseModel):
    """Summarized results of the 3-cohort ablation study with strict provenance validity."""
    model_config = ConfigDict(extra="forbid")

    total_scenarios: int
    seeds: List[int]
    execution_mode: str
    is_valid_ablation: bool
    b_vs_a_valid: bool
    c_vs_b_valid: bool
    validity_notes: List[str] = Field(default_factory=list)
    cohort_results: Dict[str, Dict[str, Any]]
    diagnosis_contribution_uplift_paise: Optional[int]
    strategy_layer_incremental_value_paise: Optional[int]
    total_ai_layer_uplift_paise: Optional[int]


class AblationRunner:
    """Executes controlled ablation studies across synthetic scenarios with strict provenance validation."""

    def __init__(
        self,
        output_dir: str = "reports",
        mode: EvaluationExecutionMode = EvaluationExecutionMode.OFFLINE_REPLAY,
        strict_no_fallback: bool = False,
    ) -> None:
        self.output_dir = output_dir
        if strict_no_fallback or mode == EvaluationExecutionMode.STRICT_NO_FALLBACK:
            self.mode = EvaluationExecutionMode.STRICT_NO_FALLBACK
            self.strict_no_fallback = True
        else:
            self.mode = mode
            self.strict_no_fallback = False
        self.harness = EvaluationHarness(mode=self.mode)

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

        policies = AblationPolicyCohort.get_cohort(strict_no_fallback=self.strict_no_fallback)
        results: Dict[str, EvaluationResult] = {}

        for p in policies:
            res = self.harness.evaluate_policy(p, all_scenarios)
            results[p.name] = res

        metrics_a = results["A_DETERMINISTIC_DIAG_AND_STRAT"].metrics
        metrics_b = results["B_LLM_DIAG_DETERMINISTIC_STRAT"].metrics
        metrics_c = results["C_LLM_DIAG_AND_LLM_STRAT"].metrics

        summary_dict = {}
        for p_name, r in results.items():
            diag_counts = dict(r.metrics.diagnosis_source_counts)
            strat_counts = dict(r.metrics.strategy_source_counts)

            # Determine dominant diagnosis source from runtime telemetry
            if diag_counts.get("llm_structured", 0) > 0:
                diag_src = "llm_structured"
            elif diag_counts.get("cached_llm", 0) > 0:
                diag_src = "cached_llm"
            elif diag_counts.get("deterministic_fallback", 0) > 0:
                diag_src = "deterministic_fallback"
            else:
                diag_src = "deterministic_offline"

            # Determine dominant strategy source from runtime telemetry
            if strat_counts.get("llm_structured", 0) > 0:
                strat_src = "llm_structured"
            elif strat_counts.get("cached_llm", 0) > 0:
                strat_src = "cached_llm"
            elif strat_counts.get("deterministic_fallback", 0) > 0:
                strat_src = "deterministic_fallback"
            else:
                strat_src = "deterministic_offline"

            summary_dict[p_name] = {
                "gross_recovered_paise": r.metrics.gross_recovered_amount_paise,
                "action_cost_paise": r.metrics.total_action_cost_paise,
                "churn_count": r.metrics.total_churned_customers,
                "adjusted_net_paise": r.metrics.adjusted_net_recovery_paise,
                "incremental_adjusted_net_paise": r.metrics.incremental_adjusted_net_recovery_paise,
                "interventions": r.metrics.total_interventions,
                "abstentions": r.metrics.actions_avoided_count,
                "abstention_rate": round(r.metrics.abstention_count / max(1, r.metrics.total_scenarios), 3),
                "diagnosis_source": diag_src,
                "strategy_source": strat_src,
                "diagnosis_source_counts": diag_counts,
                "strategy_source_counts": strat_counts,
                "diagnosis_live_calls": r.metrics.diagnosis_live_call_count,
                "diagnosis_cache_hits": r.metrics.diagnosis_cache_hit_count,
                "diagnosis_fallbacks": r.metrics.diagnosis_fallback_count,
                "strategy_live_calls": r.metrics.strategy_live_call_count,
                "strategy_cache_hits": r.metrics.strategy_cache_hit_count,
                "strategy_fallbacks": r.metrics.strategy_fallback_count,
                "invalid_outputs": r.metrics.invalid_llm_output_count,
            }

        # Validity Assessment
        b_fallbacks = summary_dict["B_LLM_DIAG_DETERMINISTIC_STRAT"]["diagnosis_fallbacks"]
        b_src = summary_dict["B_LLM_DIAG_DETERMINISTIC_STRAT"]["diagnosis_source"]
        b_vs_a_valid = (b_fallbacks == 0) and (b_src in ("llm_structured", "cached_llm"))

        c_diag_fallbacks = summary_dict["C_LLM_DIAG_AND_LLM_STRAT"]["diagnosis_fallbacks"]
        c_strat_fallbacks = summary_dict["C_LLM_DIAG_AND_LLM_STRAT"]["strategy_fallbacks"]
        c_diag_src = summary_dict["C_LLM_DIAG_AND_LLM_STRAT"]["diagnosis_source"]
        c_strat_src = summary_dict["C_LLM_DIAG_AND_LLM_STRAT"]["strategy_source"]
        c_vs_b_valid = (
            (c_diag_fallbacks == 0)
            and (c_strat_fallbacks == 0)
            and (c_diag_src in ("llm_structured", "cached_llm"))
            and (c_strat_src in ("llm_structured", "cached_llm"))
        )

        validity_notes: List[str] = []
        if not b_vs_a_valid:
            validity_notes.append(
                f"Cohort B contains {b_fallbacks} diagnosis fallbacks (dominant source: '{b_src}'). B-A cannot be claimed as genuine LLM diagnosis uplift."
            )
        if not c_vs_b_valid:
            validity_notes.append(
                f"Cohort C contains {c_strat_fallbacks} strategy fallbacks (dominant source: '{c_strat_src}'). C-B cannot be claimed as genuine Strategy LLM uplift."
            )

        if self.strict_no_fallback and (not b_vs_a_valid or not c_vs_b_valid):
            raise RuntimeError(f"Strict ablation validation failed: {'; '.join(validity_notes)}")

        is_valid_overall = b_vs_a_valid and c_vs_b_valid

        diag_uplift = (
            metrics_b.incremental_adjusted_net_recovery_paise - metrics_a.incremental_adjusted_net_recovery_paise
            if b_vs_a_valid
            else None
        )
        strat_layer_uplift = (
            metrics_c.incremental_adjusted_net_recovery_paise - metrics_b.incremental_adjusted_net_recovery_paise
            if c_vs_b_valid
            else None
        )
        total_ai_uplift = (
            metrics_c.incremental_adjusted_net_recovery_paise - metrics_a.incremental_adjusted_net_recovery_paise
            if is_valid_overall
            else None
        )

        ablation_summary = AblationResult(
            total_scenarios=len(all_scenarios),
            seeds=active_seeds,
            execution_mode=self.mode.value,
            is_valid_ablation=is_valid_overall,
            b_vs_a_valid=b_vs_a_valid,
            c_vs_b_valid=c_vs_b_valid,
            validity_notes=validity_notes,
            cohort_results=summary_dict,
            diagnosis_contribution_uplift_paise=diag_uplift,
            strategy_layer_incremental_value_paise=strat_layer_uplift,
            total_ai_layer_uplift_paise=total_ai_uplift,
        )

        self._save_ablation_reports(ablation_summary)
        return ablation_summary

    def _save_ablation_reports(self, summary: AblationResult) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        md_path = os.path.join(self.output_dir, "ablation_summary.md")
        json_path = os.path.join(self.output_dir, "ablation_summary.json")

        # Save Machine-Readable JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary.model_dump(), f, indent=2)

        # Save Human-Readable Markdown
        lines = [
            "# RecoveryOS Ablation Study Summary",
            "",
            f"- **Cohort Size**: {summary.total_scenarios} scenarios (Seeds: {summary.seeds})",
            f"- **AI Model**: `openai/gpt-oss-120b` via Groq",
            f"- **Execution Mode**: `{summary.execution_mode}`",
            f"- **Ablation Validity**: {'VALID (Genuine LLM Provenance, Zero Fallback)' if summary.is_valid_ablation else 'INVALID / FALLBACK DETECTED'}",
            "",
        ]

        if summary.validity_notes:
            lines.extend([
                "### ⚠️ Validity Warnings",
                "",
            ])
            for note in summary.validity_notes:
                lines.append(f"- {note}")
            lines.append("")

        lines.extend([
            "## Cohort Performance Comparison",
            "",
            "| Variant | Description | Gross Recov (₹) | Costs (₹) | Churns | Adj Net (₹) | Incr Adj Net (₹) | Interventions | Abstentions |",
            "|---|---|---|---|---|---|---|---|---|",
        ])

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
            "## Variant Provenance & Provider Tracking",
            "",
            "| Variant | Diagnosis Source | Strategy Source | Live Calls (Diag/Strat) | Cache Hits (Diag/Strat) | Fallbacks (Diag/Strat) | Invalid Outputs |",
            "|---|---|---|---|---|---|---|",
        ])

        for name, data in summary.cohort_results.items():
            live_str = f"{data['diagnosis_live_calls']} / {data['strategy_live_calls']}"
            cache_str = f"{data['diagnosis_cache_hits']} / {data['strategy_cache_hits']}"
            fb_str = f"{data['diagnosis_fallbacks']} / {data['strategy_fallbacks']}"
            lines.append(
                f"| `{name}` | `{data['diagnosis_source']}` | `{data['strategy_source']}` | {live_str} | {cache_str} | {fb_str} | {data['invalid_outputs']} |"
            )

        lines.extend([
            "",
            "## AI Component Uplift Decomposition",
            "",
        ])

        if summary.b_vs_a_valid and summary.diagnosis_contribution_uplift_paise is not None:
            lines.append(f"- **LLM Diagnosis Incremental Uplift (B - A)**: ₹{summary.diagnosis_contribution_uplift_paise / 100.0:,.2f} (✅ Valid)")
        else:
            lines.append("- **LLM Diagnosis Incremental Uplift (B - A)**: *UNAVAILABLE (Cohort B contains fallback; cannot claim as LLM contribution)*")

        if summary.c_vs_b_valid and summary.strategy_layer_incremental_value_paise is not None:
            lines.append(f"- **Incremental Value of Full Agentic Strategy Layer (C - B)**: ₹{summary.strategy_layer_incremental_value_paise / 100.0:,.2f} (✅ Valid)")
        else:
            lines.append("- **Incremental Value of Full Agentic Strategy Layer (C - B)**: *UNAVAILABLE (Cohort C contains fallback; cannot claim as Strategy LLM contribution)*")

        if summary.is_valid_ablation and summary.total_ai_layer_uplift_paise is not None:
            lines.append(f"- **Total Combined AI Layer Value (C - A)**: ₹{summary.total_ai_layer_uplift_paise / 100.0:,.2f} (✅ Valid)")
        else:
            lines.append("- **Total Combined AI Layer Value (C - A)**: *UNAVAILABLE (Incomplete valid LLM data)*")

        lines.extend([
            "",
            "> **Methodological Note on Strategy Uplift**: The C − B difference estimates the incremental value of introducing the full agentic strategy layer over the diagnosis-only hybrid baseline. It is not an isolated causal estimate of the strategy model alone because downstream strategy/timing behavior differs between the cohorts.",
            "",
            "---",
            "*Generated by RecoveryOS Evaluation Lab*",
        ])

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
