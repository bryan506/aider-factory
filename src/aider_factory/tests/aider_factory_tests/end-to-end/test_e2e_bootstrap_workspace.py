"""Zero-mock E2E: run `aider-helper bootstrap` in a temp sandbox,
assert the generated .env_*.yml has populated target_files and
context_files_job, and that RAG/OCR endpoints are NOT router-stomped.

Executes the real CLI entrypoint. No mocking of subprocess or filesystem.
"""
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest


def _make_sandbox(tmp_path: Path) -> Path:
    """Create a minimal Python project with source + docs."""
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "engine.py").write_text("class Engine: pass\n")
    (tmp_path / "src" / "app" / "server.py").write_text("def serve(): pass\n")
    (tmp_path / "src" / "app" / "__init__.py").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_engine.py").write_text("def test_x(): pass\n")
    (tmp_path / "README.md").write_text("# My App\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "setup.md").write_text("Setup guide\n")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )
    return tmp_path


def _get_clean_env(extra: dict | None = None) -> dict:
    env = os.environ.copy()
    # Strip ambient session vars
    for k in list(env):
        if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_"):
            env.pop(k, None)
    if extra:
        env.update(extra)
    return env


class TestE2EBootstrapWorkspace:
    def test_bootstrap_populates_target_and_context_files(self, tmp_path):
        project = _make_sandbox(tmp_path)
        env = _get_clean_env({
            "LITELLM_BASE_URL": "http://127.0.0.1:19999/v1",  # unreachable
            "LITELLM_API_KEY": "sk-test",
        })

        proc = subprocess.run(
            ["aider-helper", "bootstrap"],
            cwd=str(project),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(f"[stdout]\n{proc.stdout}")
        print(f"[stderr]\n{proc.stderr}")
        assert proc.returncode == 0, f"bootstrap exited {proc.returncode}"

        # Find generated YAML
        yaml_files = list((project / ".aider_factory").glob(".env_*.yml"))
        assert yaml_files, "No .env_*.yml generated"
        content = yaml_files[0].read_text()

        # target_files must have exactly ONE anchor file (pipeline is 1-file-per-session)
        assert "target_files: []" not in content
        tf_section = content.split("target_files:")[1].split("extra_editable_files:")[0]
        target_entries = [l for l in tf_section.splitlines() if l.strip().startswith("- ")]
        assert len(target_entries) == 1, f"Expected 1 target, got {len(target_entries)}: {target_entries}"
        # The single entry must be a real file
        assert "engine.py" in target_entries[0]

        # Tests must NOT appear in targets
        assert "test_engine.py" not in content

        # context_files_job must include README and docs
        assert "context_files_job: []" not in content
        assert "README.md" in content
        assert "setup.md" in content

        # context_files_test must remain empty
        assert "context_files_test: []" in content

    def test_rag_ocr_endpoints_not_overwritten(self, tmp_path):
        project = _make_sandbox(tmp_path)
        router_url = "http://127.0.0.1:19999/v1"
        env = _get_clean_env({
            "LITELLM_BASE_URL": router_url,
            "LITELLM_API_KEY": "sk-test",
        })

        subprocess.run(
            ["aider-helper", "bootstrap"],
            cwd=str(project),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        yaml_files = list((project / ".aider_factory").glob(".env_*.yml"))
        content = yaml_files[0].read_text()

        # Architect SHOULD get router URL
        assert f'architect_api_base: "{router_url}"' in content

        # RAG/OCR/embed/grounding must NOT get router URL
        for key in ("rag_agent_api", "ocr_api_base", "embed_api_base",
                    "grounding_agent_api"):
            assert f'{key}: "{router_url}"' not in content, (
                f"{key} was overwritten with router URL — local auto-resolve broken"
            )

    def test_bootstrap_r_package_discovers_R_sources(self, tmp_path):
        """Zero-mock: R package with R/*.R files gets populated target_files."""
        # Build a realistic R package skeleton
        (tmp_path / "R").mkdir()
        (tmp_path / "R" / "aac_fut_b.R").write_text("aac_fut_b <- function() {}\n")
        (tmp_path / "R" / "period_subset.R").write_text("period_subset <- function() {}\n")
        (tmp_path / "tests" / "testthat").mkdir(parents=True)
        (tmp_path / "tests" / "testthat" / "test-aac.R").write_text("test_that('x', {})\n")
        (tmp_path / "DESCRIPTION").write_text("Package: rlambda\nVersion: 0.1.0\n")
        (tmp_path / "NAMESPACE").write_text("export(aac_fut_b)\n")
        (tmp_path / "README.md").write_text("# r-lambda\n")

        env = _get_clean_env({
            "LITELLM_BASE_URL": "http://127.0.0.1:19999/v1",
            "LITELLM_API_KEY": "sk-test",
        })
        proc = subprocess.run(
            ["aider-helper", "bootstrap"],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(f"[stdout]\n{proc.stdout}")
        print(f"[stderr]\n{proc.stderr}")
        assert proc.returncode == 0

        yaml_files = list((tmp_path / ".aider_factory").glob(".env_*.yml"))
        assert yaml_files, "No .env_*.yml generated"
        content = yaml_files[0].read_text()

        # Exactly ONE anchor file (first alphabetically: R/aac_fut_b.R)
        assert "target_files: []" not in content
        tf_section = content.split("target_files:")[1].split("extra_editable_files:")[0]
        target_entries = [l for l in tf_section.splitlines() if l.strip().startswith("- ")]
        assert len(target_entries) == 1, f"Expected 1 target, got {len(target_entries)}"
        assert "aac_fut_b.R" in target_entries[0]

        # Second source file must NOT be in targets (pipeline is 1-per-session)
        assert "period_subset.R" not in tf_section

        # Test files must NOT appear
        assert "test-aac.R" not in content

        # Framework must be detected as R (DESCRIPTION marker)
        assert "Rscript" in content

        # Context must include README
        assert "README.md" in content

    def test_bootstrap_no_router_still_produces_valid_yaml(self, tmp_path):
        """With no LITELLM_BASE_URL, bootstrap must still write a valid YAML
        with discovered files (endpoints stay as template placeholders)."""
        project = _make_sandbox(tmp_path)
        env = _get_clean_env()
        env.pop("LITELLM_BASE_URL", None)
        env.pop("LITELLM_API_KEY", None)
        env["GEMINI_API_KEY"] = "sk-cloud-test"

        proc = subprocess.run(
            ["aider-helper", "bootstrap"],
            cwd=str(project),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0
        yaml_files = list((project / ".aider_factory").glob(".env_*.yml"))
        assert yaml_files
        content = yaml_files[0].read_text()
        # Files still discovered even without router
        assert "engine.py" in content
        assert "README.md" in content
