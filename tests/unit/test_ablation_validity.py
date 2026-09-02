"""Unit tests verifying A/B/C ablation study validity rules and report generation."""
import json
import os
import tempfile
from unittest.mock import MagicMock
import pytest

from evaluation.ablation import AblationPolicyCohort, AblationResult, AblationRunner
from evaluation.harness import EvaluationExecutionMode
from evaluation.policies import (
    AgenticGraphRecoveryPolicy,
    DeterministicRecoveryPolicy,
    LLMDrivenRecoveryPolicy,
)
from intelligence.context import ObservableRecoveryContext
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.providers.llm_provider import LLMDiagnosisProvider
from intelligence.providers.strategy_provider import LLMStrategyProvider
from intelligence.replay_cache import LLMReplayCache
from simulator.config import SimulatorConfig
from simulator.generator import Simulator


class TestAblationValidityRules:
    """Verifies that ablation studies distinguish genuine LLM contributions from unintended fallbacks."""

    def test_offline_replay_fallback_marks_ablation_invalid_for_llm_claims(self):
        """When running in OFFLINE_REPLAY with empty replay cache, B and C fall back, and uplift claims are marked invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = AblationRunner(output_dir=tmpdir, mode=EvaluationExecutionMode.OFFLINE_REPLAY)
            res = runner.run_ablation(seeds=[42], scenarios_per_seed=2)

            assert isinstance(res, AblationResult)
            assert res.is_valid_ablation is False
            assert res.b_vs_a_valid is False
            assert res.c_vs_b_valid is False
            assert res.diagnosis_contribution_uplift_paise is None
            assert res.strategy_layer_incremental_value_paise is None
            assert len(res.validity_notes) > 0

            # Verify JSON artifact was saved
            json_path = os.path.join(tmpdir, "ablation_summary.json")
            assert os.path.exists(json_path)
            with open(json_path, "r", encoding="utf-8") as f:
                saved_json = json.load(f)
            assert saved_json["is_valid_ablation"] is False

    def test_strict_mode_ablation_raises_when_fallback_occurs(self):
        """In STRICT_NO_FALLBACK mode, fallback MUST raise RuntimeError rather than producing an invalid report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = AblationRunner(output_dir=tmpdir, mode=EvaluationExecutionMode.STRICT_NO_FALLBACK, strict_no_fallback=True)
            with pytest.raises(RuntimeError):
                runner.run_ablation(seeds=[42], scenarios_per_seed=2)

    def test_mocked_valid_llm_ablation_is_valid(self, monkeypatch):
        """When genuine LLM/mock responses are returned with zero fallback, ablation is marked valid with computed uplifts."""
        diag_client = MagicMock()
        diag_client.chat.completions.create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content=json.dumps({
                            "diagnosis_label": "transient_gateway_failure",
                            "confidence": 0.90,
                            "evidence_codes": ["OBS_GATEWAY_TIMEOUT"],
                            "uncertainties": [],
                            "recommended_candidate_actions": ["retry_later", "retry_now"],
                            "recommended_timing_hint": "delay_2h",
                            "human_review_required": False,
                            "abstain_recommended": False,
                            "rationale": "Transient gateway failure diagnosed.",
                        })
                    )
                )
            ]
        )

        strat_client = MagicMock()
        strat_client.chat.completions.create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content=json.dumps({
                            "primary_recommendation": "no_action",
                            "strategic_summary": "Evaluated candidate options.",
                            "proposals": [
                                {
                                    "action_type": "no_action",
                                    "mechanism": "no_action",
                                    "rationale": "Natural baseline",
                                    "confidence": 1.0,
                                    "supporting_evidence": [],
                                    "risk_notes": [],
                                    "why_better_than_abstain": "Baseline",
                                    "why_alternative_inferior": "Fees",
                                    "is_abstention": True,
                                },
                                {
                                    "action_type": "payment_link",
                                    "mechanism": "payment_link",
                                    "rationale": "Payment link intervention",
                                    "confidence": 0.85,
                                    "supporting_evidence": [],
                                    "risk_notes": [],
                                    "why_better_than_abstain": "Direct recovery",
                                    "why_alternative_inferior": "Cost",
                                    "is_abstention": False,
                                },
                            ],
                        })
                    )
                )
            ]
        )

        def mock_get_cohort(strict_no_fallback: bool = False):
            det_p = DeterministicRecoveryPolicy()
            det_p.name = "A_DETERMINISTIC_DIAG_AND_STRAT"

            llm_p = LLMDrivenRecoveryPolicy(
                diagnosis_provider=LLMDiagnosisProvider(api_key="mock_key", client=diag_client, replay_cache=LLMReplayCache())
            )
            llm_p.name = "B_LLM_DIAG_DETERMINISTIC_STRAT"

            agentic_p = AgenticGraphRecoveryPolicy()
            agentic_p.diagnosis_agent.provider = LLMDiagnosisProvider(api_key="mock_key", client=diag_client, replay_cache=LLMReplayCache())
            agentic_p.strategy_agent.provider = LLMStrategyProvider(api_key="mock_key", client=strat_client, replay_cache=LLMReplayCache())
            agentic_p.name = "C_LLM_DIAG_AND_LLM_STRAT"

            return [det_p, llm_p, agentic_p]

        monkeypatch.setattr(AblationPolicyCohort, "get_cohort", mock_get_cohort)

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = AblationRunner(output_dir=tmpdir, mode=EvaluationExecutionMode.LIVE_LLM)
            res = runner.run_ablation(seeds=[42], scenarios_per_seed=2)

            assert res.is_valid_ablation is True
            assert res.b_vs_a_valid is True
            assert res.c_vs_b_valid is True
            assert res.diagnosis_contribution_uplift_paise is not None
            assert res.strategy_layer_incremental_value_paise is not None
            assert res.total_ai_layer_uplift_paise is not None

            # Verify markdown report contains valid markers
            md_path = os.path.join(tmpdir, "ablation_summary.md")
            assert os.path.exists(md_path)
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "VALID" in content
            assert "Live Calls" in content
