#!/usr/bin/env python3
# test_e2e_factory_quickstart.py — Zero-Mock Physical Factory Initialization Matrix Test Suite.

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

script_dir = os.path.dirname(os.path.abspath(__file__))
cli_script = os.path.abspath(os.path.join(script_dir, "../../../cli.py"))
python_dir = os.path.abspath(os.path.join(script_dir, "../../../python"))

sys.path.insert(0, python_dir)
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../../..")))

import cli


def _has_unhandled_traceback(stderr: str) -> bool:
    """Return True if stderr contains a genuine unhandled traceback, ignoring runtime GC warnings."""
    lines = stderr.splitlines()
    for i, line in enumerate(lines):
        if "Traceback (most recent call last):" in line:
            prev_context = " ".join(lines[max(0, i - 3):i])
            if "Exception ignored in:" in prev_context:
                continue
            return True
    return False


def _get_clean_env(extra_env=None):
    """Construct an isolated environment dictionary scrubbing ambient session and factory variables."""
    env = os.environ.copy()
    for k in list(env.keys()):
        if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
            env.pop(k, None)
    if extra_env:
        env.update(extra_env)
    return env


def test_e2e_matrix_1_cli_aider_factory():
    """Matrix Row 1: aider-factory (any flag) calls init_user_project() at startup."""
    print("\n[Matrix Row 1] Testing aider-factory --repo-map initialization & template invariants...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        env = _get_clean_env()

        proc = subprocess.run(
            [sys.executable, cli_script, "--repo-map"],
            cwd=tmp_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"Expected rc 0, got {proc.returncode}: {proc.stderr}"

        # 1. Assert full configuration directory hierarchy
        factory_dir = tmp_path / ".aider_factory"
        assert factory_dir.is_dir(), ".aider_factory directory must be created"
        assert (factory_dir / ".env.yml").is_file(), ".env.yml must be created"
        assert (tmp_path / ".aiderignore").is_file(), ".aiderignore must be created"
        assert (factory_dir / ".aider.conf.yml").is_file(), ".aider.conf.yml must be created"
        assert (factory_dir / ".aider.model.settings.yml").is_file(), ".aider.model.settings.yml must be created"
        assert (factory_dir / "CONVENTIONS.md").is_file(), "CONVENTIONS.md must be created"

        # 2. Assert test directory provisioning (.aider_factory/tests/)
        test_dir = factory_dir / "tests"
        assert test_dir.is_dir(), ".aider_factory/tests directory must be provisioned"

        # 3. Assert bash wrappers with +x permissions
        bash_dir = factory_dir / "bash"
        for wrapper_name in ["factory", "oracle", "validate", "research", "apply"]:
            wrapper_path = bash_dir / wrapper_name
            assert wrapper_path.is_file(), f"Wrapper script {wrapper_name} must exist"
            assert bool(os.stat(wrapper_path).st_mode & stat.S_IXUSR), f"{wrapper_name} must be executable (+x)"

        # 4. Assert markdown tree and subdirectories
        markdown_dir = factory_dir / "markdown"
        assert markdown_dir.is_dir(), ".aider_factory/markdown must be created"
        for sub in ["docs", "oracle_pre_plan", "skills", "templates", "internal"]:
            sub_dir = markdown_dir / sub
            assert sub_dir.is_dir(), f"Markdown subdirectory {sub} must exist"
            assert len(list(sub_dir.glob("*.md"))) > 0, f"Markdown subdirectory {sub} must contain files"

        # 5. Assert non-destructive re-initialization (custom file & existing template modification)
        custom_file = markdown_dir / "templates" / "custom_user_template.md"
        with open(custom_file, "w", encoding="utf-8") as f:
            f.write("CUSTOM_USER_CONTENT_PRESERVE")

        # Mutate an existing bundled file to prove it is never overwritten
        existing_template = markdown_dir / "internal" / "analyze_bugs.md"
        assert existing_template.is_file(), "analyze_bugs.md must exist in internal/"
        with open(existing_template, "w", encoding="utf-8") as f:
            f.write("MUTATED_ANALYZE_BUGS_PRESERVE")

        reinit_proc = subprocess.run(
            [sys.executable, cli_script, "--repo-map"],
            cwd=tmp_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        assert reinit_proc.returncode == 0
        with open(custom_file, "r", encoding="utf-8") as f:
            assert f.read() == "CUSTOM_USER_CONTENT_PRESERVE", "Re-init must not overwrite custom markdown files"
        with open(existing_template, "r", encoding="utf-8") as f:
            assert f.read() == "MUTATED_ANALYZE_BUGS_PRESERVE", "Re-init must not overwrite modified bundled templates"

    print("  ✅ Matrix Row 1 (aider-factory) PASS")


def test_e2e_matrix_2_helper_bootstrap():
    """Matrix Row 2: aider-helper bootstrap calls init_user_project(target_dir) at wizard end."""
    print("\n[Matrix Row 2] Testing aider-helper bootstrap initialization...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        env = _get_clean_env({"GEMINI_API_KEY": "sk-dummy"})

        # Simulated stdin inputs: target files, context files (empty), framework 1 (py), mode 1 (auto), arch model (default), edit model (default), RAG (n)
        simulated_input = "scratchpad.py\n\n\n\n\n\nn\n"
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.argv=['aider-helper', 'bootstrap']; from aider_factory.cli import helper_cli; helper_cli()",
            ],
            cwd=tmp_dir,
            input=simulated_input,
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"Bootstrap failed with rc {proc.returncode}: {proc.stderr}"

        markdown_dir = tmp_path / ".aider_factory" / "markdown"
        assert markdown_dir.is_dir(), "Bootstrap must provision .aider_factory/markdown directory"
        for sub in ["docs", "oracle_pre_plan", "skills", "templates", "internal"]:
            sub_dir = markdown_dir / sub
            assert sub_dir.is_dir(), f"Bootstrap must create markdown/{sub}"
            assert len(list(sub_dir.glob("*.md"))) > 0, f"markdown/{sub} must contain template markdown files"

    print("  ✅ Matrix Row 2 (aider-helper bootstrap) PASS")


def test_e2e_matrix_3_bash_factory_workflow():
    """Matrix Row 3: .aider_factory/bash/factory runs run_workflow.py which calls init_user_project()."""
    print("\n[Matrix Row 3] Testing .aider_factory/bash/factory (run_workflow.py) auto-initialization...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        env = _get_clean_env()
        run_workflow_script = os.path.join(python_dir, "run_workflow.py")

        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import runpy; runpy.run_path(r'{run_workflow_script}', run_name='__test__')",
            ],
            cwd=tmp_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"run_workflow startup failed: {proc.stderr}"

        markdown_dir = tmp_path / ".aider_factory" / "markdown"
        assert markdown_dir.is_dir(), "run_workflow.py startup must automatically provision .aider_factory/markdown"
        for sub in ["docs", "oracle_pre_plan", "skills", "templates", "internal"]:
            sub_dir = markdown_dir / sub
            assert sub_dir.is_dir(), f"run_workflow.py must create markdown/{sub}"
            assert len(list(sub_dir.glob("*.md"))) > 0, f"markdown/{sub} must contain template files"

    print("  ✅ Matrix Row 3 (.aider_factory/bash/factory) PASS")


def test_e2e_matrix_4_helper_query_partial():
    """Matrix Row 4: aider-helper query performs partial init without calling full init_user_project()."""
    print("\n[Matrix Row 4] Testing aider-helper query partial initialization...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        env = _get_clean_env(
            {
                "AIDER_HELPER_API_BASE": "http://127.0.0.1:9999/v1",
                "OPENAI_API_KEY": "sk-dummy",
            }
        )

        # Run conversational query in a blank folder
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.argv=['aider-helper', 'query', '-a', 'What is the architect model?']; from aider_factory.cli import helper_cli; helper_cli()",
            ],
            cwd=tmp_dir,
            env=env,
            capture_output=True,
            text=True,
        )

        markdown_dir = tmp_path / ".aider_factory" / "markdown"
        assert not markdown_dir.exists(), "aider-helper query in ask mode must NOT provision markdown directory"

    print("  ✅ Matrix Row 4 (aider-helper query partial) PASS")


def test_e2e_matrix_5_standalone_utilities_no_init():
    """Matrix Row 5: Standalone utilities (oracle, validate, research, apply) do NOT create .aider_factory."""
    print("\n[Matrix Row 5] Testing standalone utilities no-init isolation...")
    utilities = ["oracle_agent.py", "validator.py", "research_agent.py", "apply_agent.py"]
    for script_name in utilities:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            env = _get_clean_env()
            target_script = os.path.join(python_dir, script_name)

            proc = subprocess.run(
                [sys.executable, target_script, "--help"],
                cwd=tmp_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            assert proc.returncode in (0, 1, 2), f"{script_name} --help failed with rc {proc.returncode}"
            assert not _has_unhandled_traceback(proc.stderr), f"{script_name} crashed: {proc.stderr}"

            factory_dir = tmp_path / ".aider_factory"
            assert not factory_dir.exists(), f"Standalone utility {script_name} must NOT create .aider_factory/"

    print("  ✅ Matrix Row 5 (standalone utilities no-init) PASS")


def test_e2e_partial_markdown_tree_backfill():
    """Edge Case: Pre-existing partial markdown directory tree is backfilled with missing subdirectories."""
    print("\n[Edge Case 1] Testing partial markdown directory tree backfilling...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        skills_dir = tmp_path / ".aider_factory" / "markdown" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        custom_skill = skills_dir / "my_custom_skill.md"
        custom_skill.write_text("# MY CUSTOM SKILL", encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, cli_script, "--repo-map"],
            cwd=tmp_dir,
            env=_get_clean_env(),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0

        # Assert all 5 subdirectories exist
        markdown_dir = tmp_path / ".aider_factory" / "markdown"
        for sub in ["docs", "oracle_pre_plan", "skills", "templates", "internal"]:
            assert (markdown_dir / sub).is_dir(), f"Missing backfilled {sub}"

        # Assert original custom file in skills was preserved
        assert custom_skill.read_text(encoding="utf-8") == "# MY CUSTOM SKILL"

    print("  ✅ Partial Markdown Backfill PASS")


def test_e2e_existing_repo_file_discovery():
    """Edge Case: Initializing on a repo with existing code files discovers target and context files without creating scratchpad.py."""
    print("\n[Edge Case 2] Testing existing repository file discovery into .env.yml...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "main.py").write_text("def run(): pass\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Documentation\n", encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, cli_script, "--repo-map"],
            cwd=tmp_dir,
            env=_get_clean_env(),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert not (tmp_path / "scratchpad.py").exists(), "Must not create scratchpad.py if source files exist"

        env_yml = (tmp_path / ".aider_factory" / ".env.yml").read_text(encoding="utf-8")
        assert 'target_files:\n        - "main.py"' in env_yml
        assert 'context_files_job:\n        - "README.md"' in env_yml

    print("  ✅ Existing File Discovery PASS")


def test_e2e_helper_flags_real_context_loading():
    """Verify that helper CLI flags (-m, -e, -t, -r) resolve documentation paths cleanly without error."""
    print("\n[Helper Flags E2E] Testing helper documentation path resolution across flags...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        env = _get_clean_env(
            {
                "AIDER_HELPER_API_BASE": "http://127.0.0.1:9999/v1",
                "OPENAI_API_KEY": "sk-dummy",
            }
        )

        # Pre-seed static repo map for -r test
        af_dir = Path(tmp_dir) / ".aider_factory"
        af_dir.mkdir(parents=True, exist_ok=True)
        (af_dir / "static_repo_map.md").write_text("src/main.py\n", encoding="utf-8")

        for flag in ["-m", "-e", "-t", "-r"]:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"import sys; sys.argv=['aider-helper', 'query', '-a', '{flag}', 'Test question']; from aider_factory.cli import helper_cli; helper_cli()",
                ],
                cwd=tmp_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            assert not _has_unhandled_traceback(proc.stderr), f"Flag {flag} caused traceback: {proc.stderr}"
            assert "FileNotFoundError" not in proc.stderr, f"Flag {flag} failed to find docs: {proc.stderr}"

        # Verify default query loads reference_schema cleanly
        default_proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.argv=['aider-helper', 'query', '-a', 'Test default']; from aider_factory.cli import helper_cli; helper_cli()",
            ],
            cwd=tmp_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        assert not _has_unhandled_traceback(default_proc.stderr), f"Default query caused traceback: {default_proc.stderr}"
        assert "FileNotFoundError" not in default_proc.stderr

    print("  ✅ Helper Flags Real Context Loading PASS")


if __name__ == "__main__":
    print("\n==================================================")
    print("Starting Zero-Mock Factory Matrix Smoke Test Suite")
    print("==================================================")
    test_e2e_matrix_1_cli_aider_factory()
    test_e2e_matrix_2_helper_bootstrap()
    test_e2e_matrix_3_bash_factory_workflow()
    test_e2e_matrix_4_helper_query_partial()
    test_e2e_matrix_5_standalone_utilities_no_init()
    test_e2e_partial_markdown_tree_backfill()
    test_e2e_existing_repo_file_discovery()
    test_e2e_helper_flags_real_context_loading()
    print("\n🎉 All Initialization Matrix & Edge-Case E2E Tests Passed Successfully!")
