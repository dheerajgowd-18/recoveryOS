"""Lightweight consistency and integrity tests for RecoveryOS project documentation."""
import os
import pytest

DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

REQUIRED_DOC_FILES = [
    "README.md",
    "ARCHITECTURE.md",
    "EVALUATION.md",
    "ASSUMPTIONS.md",
    "LIMITATIONS.md",
    "THREAT_MODEL.md",
    "DEMO.md",
    "PITCH.md",
]


class TestDocumentationConsistency:
    """Validates presence and required content invariants across all submission markdown documents."""

    @pytest.mark.parametrize("filename", REQUIRED_DOC_FILES)
    def test_required_documentation_files_exist(self, filename: str):
        """Every core submission documentation file must exist on disk and be non-empty."""
        filepath = os.path.join(DOCS_DIR, filename)
        assert os.path.exists(filepath), f"Missing required documentation file: {filename}"
        assert os.path.getsize(filepath) > 100, f"Documentation file {filename} is empty or incomplete"

    def test_readme_contains_core_submission_headings_and_commands(self):
        """README.md must feature the project name, North Star metric, and demo invocation command."""
        readme_path = os.path.join(DOCS_DIR, "README.md")
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "RecoveryOS" in content
        assert "Incremental Adjusted Net Recovery" in content
        assert "python scripts/demo.py" in content
        assert "python -m pytest -v" in content

    def test_evaluation_doc_contains_synthetic_disclosure(self):
        """EVALUATION.md must include honest disclosure regarding synthetic simulation."""
        eval_path = os.path.join(DOCS_DIR, "EVALUATION.md")
        with open(eval_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "Synthetic" in content or "synthetic" in content
        assert "Potential Outcome" in content or "potential outcome" in content
        assert "Incremental Adjusted Net" in content

    def test_threat_model_covers_core_threat_categories(self):
        """THREAT_MODEL.md must document stale state, duplicate webhooks, opt-out, and policy outages."""
        threat_path = os.path.join(DOCS_DIR, "THREAT_MODEL.md")
        with open(threat_path, "r", encoding="utf-8") as f:
            content = f.read().lower()

        assert "stale" in content
        assert "duplicate" in content
        assert "opt-out" in content
        assert "policy" in content

    def test_pitch_script_covers_signature_demo_cases(self):
        """PITCH.md must contain the 5-minute timed script structure and key Q&A topics."""
        pitch_path = os.path.join(DOCS_DIR, "PITCH.md")
        with open(pitch_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "The Hook" in content or "0:00" in content
        assert "The Real Problem" in content or "0:15" in content
        assert "Tool Firewall" in content or "ToolFirewall" in content
        assert "Why abstain?" in content or "Why isn't payment probability enough?" in content
