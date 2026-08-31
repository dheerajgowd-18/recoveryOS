"""Packaging and release surface sanity tests for RecoveryOS."""
import os
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestPackagingSanity:
    """Validates presence and integrity of developer command surface and environment templates."""

    def test_makefile_exists_and_contains_standard_targets(self):
        """Makefile must exist and declare install, test, and demo targets."""
        makefile_path = os.path.join(ROOT_DIR, "Makefile")
        assert os.path.exists(makefile_path), "Makefile does not exist in root directory"

        with open(makefile_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "install:" in content, "Makefile missing install target"
        assert "test:" in content, "Makefile missing test target"
        assert "demo:" in content, "Makefile missing demo target"
        assert "pip install" in content, "Makefile install target must reference pip install"
        assert "python -m pytest" in content, "Makefile test target must reference pytest"
        assert "python scripts/demo.py" in content, "Makefile demo target must reference scripts/demo.py"

    def test_env_example_contains_safe_placeholders_only(self):
        """.env.example must exist and contain safe placeholder values with no production keys."""
        env_example_path = os.path.join(ROOT_DIR, ".env.example")
        assert os.path.exists(env_example_path), ".env.example does not exist in root directory"

        with open(env_example_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "RAZORPAY_KEY_ID=" in content
        assert "RAZORPAY_WEBHOOK_SECRET=" in content

        # Security assertion: No real secret prefixes or live credentials
        assert "rzp_live_" not in content, "Production key prefix found in .env.example"
        assert "your_" in content, "Placeholders must be prefixed with your_"

    def test_gitignore_excludes_env_and_local_handoff_artifacts(self):
        """.gitignore must explicitly ignore .env and all local handoff summary/review files."""
        gitignore_path = os.path.join(ROOT_DIR, ".gitignore")
        assert os.path.exists(gitignore_path), ".gitignore does not exist in root directory"

        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert ".env" in content
        assert "CONTEXT_SUMMARY_*.md" in content or "CONTEXT_SUMMARY_PHASE_*.md" in content
        assert "REVIEW_ARTIFACT_*.md" in content or "REVIEW_ARTIFACT_PHASE_*.md" in content
