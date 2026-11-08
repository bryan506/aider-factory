#!/usr/bin/env python3
"""test_e2e_aiderignore_gitignore_live.py — Zero-Mock Live E2E Tests for .aiderignore and .gitignore.

Directly challenges and verifies:
  1. Legacy multi-line .aiderignore and .gitignore (.aider_factory/ + .aider*) clean upgrade via run_bootstrap().
  2. Real 'aider' interactive `/add` succeeding on designated .aider_factory/ workspace files
     (strategy_template.md, CONVENTIONS.md, .env_plan_do.yml, temp/*, markdown/templates/*,
     sessions/*/{session.yml,feature_adr/*,templates/*}), while internal .aider_factory/ files
     (strategy_instruct_template.md, .aider.conf.yml, sample_yaml_config/env_plan_do.yml,
     sessions/*/.aider.chat.history.md) remain blocked.
  3. Static repo maps (`aider-factory --repo-map-all`) and native Aider live RepoMap (`--show-repo-map --map-tokens 2048`)
     excluding .aider_factory/ even after un-ignored .aider_factory/ files are tracked and committed in git.
  4. Live LLM edit of untracked strategy_template.md via real 'aider' with .gitignore active.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

test_file_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(test_file_dir, "../../../../.."))
src_dir = os.path.join(repo_root, "src")
pkg_dir = os.path.join(src_dir, "aider_factory")
python_dir = os.path.join(pkg_dir, "python")
cli_script = os.path.join(pkg_dir, "cli.py")

for p in (repo_root, src_dir, pkg_dir, python_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

import cli
from bootstrap import run_bootstrap
from env_utils import is_dummy_key, load_env_files
from orchestrate import AiderFactory, Task


def _get_clean_env(extra_env=None):
    env = os.environ.copy()
    for k in list(env.keys()):
        if (
            k.startswith("AI_FACTORY_")
            or k.startswith("ORACLE_")
            or k.startswith("AIDER_")
            or k.startswith("GOOGLE_")
            or k.startswith("VERTEX")
            or k in (
                "LITELLM_API_KEY",
                "LITELLM_BASE_URL",
                "GEMINI_API_KEY",
                "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY",
                "OPENROUTER_API_KEY",
                "GROQ_API_KEY",
                "DEEPSEEK_API_KEY",
                "MISTRAL_API_KEY",
            )
        ):
            env.pop(k, None)
    env["OPENAI_API_KEY"] = "sk-dummy"
    if extra_env:
        env.update(extra_env)
    return env


def _resolve_live_gemini_key() -> tuple[str, str] | None:
    load_env_files(repo_root)
    for k in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "AIDER_GEMINI_API_KEY",
    ):
        val = os.environ.get(k)
        if val and not is_dummy_key(val):
            return k, val
    return None


class TestE2EAiderignoreGitignoreLive(unittest.TestCase):
    def setUp(self):
        cli.ensure_aider_installed()
        if not shutil.which("aider"):
            self.skipTest("Real 'aider' binary not found in PATH.")
        self.tmp_dir = tempfile.mkdtemp(prefix="e2e_aiderignore_live_")
        self.project_dir = Path(self.tmp_dir)
        self.old_cwd = os.getcwd()
        os.chdir(self.project_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _init_git_repo_with_legacy_ignores(self):
        subprocess.run(["git", "init"], cwd=self.tmp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "E2E Ignore Tester"], cwd=self.tmp_dir, check=True)
        subprocess.run(["git", "config", "user.email", "ignore@aider.local"], cwd=self.tmp_dir, check=True)

        (self.project_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "tests").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "src" / "app.py").write_text(
            "def compute_value(x: int) -> int:\n    return x * 2\n",
            encoding="utf-8",
        )
        (self.project_dir / "tests" / "test_app.py").write_text(
            "from src.app import compute_value\n\ndef test_compute():\n    assert compute_value(3) == 6\n",
            encoding="utf-8",
        )

        # Realistic .gitignore with both .aider_factory/ and .aider*
        (self.project_dir / ".gitignore").write_text(
            "# Ephemeral and Local Workspace Files\n"
            ".aider_factory/\n"
            "temp/\n"
            "logs/\n\n"
            "# Local system files\n"
            ".DS_Store\n"
            ".aider*\n",
            encoding="utf-8",
        )

        # Legacy multi-line .aiderignore that previously broke upgrades
        (self.project_dir / ".aiderignore").write_text(
            "# Ignore RAG database, logs, and caches\n"
            ".aider_factory/\n"
            ".aider_factory/markdown/internal\n"
            ".aider_factory/markdown/lanceDB\n"
            ".aider_factory/bash\n"
            ".aider_factory/.aider*\n"
            ".aider_factory/.helper*\n"
            ".aider_factory/.oracle_*\n\n"
            "# Ignore temp folders\n"
            "temp/\n",
            encoding="utf-8",
        )

        subprocess.run(["git", "add", "src/app.py", "tests/test_app.py", ".gitignore"], cwd=self.tmp_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial repo with legacy ignores"], cwd=self.tmp_dir, check=True)

    def test_bootstrap_upgrades_legacy_ignores_and_real_aider_interactive_add(self):
        """1. Verify run_bootstrap() cleans legacy .aiderignore/.gitignore and real 'aider' can /add strategy_template.md."""
        self._init_git_repo_with_legacy_ignores()

        run_bootstrap(self.tmp_dir)

        aiderignore_txt = (self.project_dir / ".aiderignore").read_text(encoding="utf-8")
        gitignore_txt = (self.project_dir / ".gitignore").read_text(encoding="utf-8")

        for stale in (
            ".aider_factory/markdown/internal",
            ".aider_factory/markdown/lanceDB",
            ".aider_factory/bash",
            ".aider_factory/.aider*",
            ".aider_factory/.helper*",
            ".aider_factory/.oracle_*",
        ):
            self.assertNotIn(stale, aiderignore_txt)

        self.assertEqual(aiderignore_txt.count("# Ignore RAG database, logs, and caches"), 1)
        self.assertIn("!.aider_factory/markdown/oracle_pre_plan/strategy_template.md", aiderignore_txt)
        self.assertIn("!.aider_factory/markdown/oracle_pre_plan/strategy_template.md", gitignore_txt)
        self.assertLess(aiderignore_txt.index("temp/"), aiderignore_txt.index("!.aider_factory/temp/"))
        self.assertLess(gitignore_txt.index("temp/"), gitignore_txt.index("!.aider_factory/temp/"))
        self.assertLess(gitignore_txt.index(".aider*"), gitignore_txt.index("!.aider_factory/"))

        # Seed scratchpad and session artifacts
        seeded_files = {
            ".aider_factory/temp/scratch.py": "def scratch_fn():\n    return 42\n",
            ".aider_factory/sessions/s1/session.yml": "session: s1\n",
            ".aider_factory/sessions/s1/feature_adr/adr_001.md": "# ADR 001\n",
            ".aider_factory/sessions/s1/templates/rendered.md": "# Rendered Template\n",
            ".aider_factory/sessions/s1/temp/notes.py": "# Session temp scratch\n",
            ".aider_factory/sessions/s1/.aider.chat.history.md": "# Chat History\n",
        }
        for rel_path, content in seeded_files.items():
            abs_p = self.project_dir / rel_path
            abs_p.parent.mkdir(parents=True, exist_ok=True)
            abs_p.write_text(content, encoding="utf-8")

        allowed_rels = (
            ".aider_factory/markdown/oracle_pre_plan/strategy_template.md",
            ".aider_factory/CONVENTIONS.md",
            ".aider_factory/.env_plan_do.yml",
            ".aider_factory/temp/scratch.py",
            ".aider_factory/markdown/templates/validate.md",
            ".aider_factory/markdown/templates/agent_persona/code-reviewer.md",
            ".aider_factory/sessions/s1/session.yml",
            ".aider_factory/sessions/s1/feature_adr/adr_001.md",
            ".aider_factory/sessions/s1/templates/rendered.md",
            ".aider_factory/sessions/s1/temp/notes.py",
        )
        blocked_rels = (
            ".aider_factory/markdown/oracle_pre_plan/strategy_instruct_template.md",
            ".aider_factory/.aider.conf.yml",
            ".aider_factory/sample_yaml_config/env_plan_do.yml",
            ".aider_factory/sessions/s1/.aider.chat.history.md",
        )

        # Verify git check-ignore directly
        for allowed_rel in allowed_rels:
            chk_allowed = subprocess.run(["git", "check-ignore", "-q", allowed_rel], cwd=self.tmp_dir)
            self.assertEqual(chk_allowed.returncode, 1, f"{allowed_rel} must NOT be git-ignored")

        for blocked_rel in blocked_rels + (".aider_factory/markdown/internal/analyze_bugs.md",):
            chk_blocked = subprocess.run(["git", "check-ignore", "-q", blocked_rel], cwd=self.tmp_dir)
            self.assertEqual(chk_blocked.returncode, 0, f"{blocked_rel} MUST be git-ignored")

        # Run real 'aider' with interactive /add commands on stdin
        env = _get_clean_env({"COLUMNS": "300"})
        add_lines = [f"/add {rel}" for rel in allowed_rels + blocked_rels]
        commands = "\n".join(add_lines + ["/ls", "/exit"]) + "\n"
        proc = subprocess.run(
            [
                "aider",
                "--no-auto-commits",
                "--no-check-update",
                "--no-show-model-warnings",
                "--no-pretty",
                "--yes-always",
            ],
            cwd=self.tmp_dir,
            env=env,
            input=commands,
            capture_output=True,
            text=True,
            timeout=60,
        )
        combined = proc.stdout + proc.stderr
        combined_norm = combined.replace("\\", "/")
        combined_unwrapped = combined_norm.replace("\r", "").replace("\n", "")
        self.assertEqual(proc.returncode, 0, f"Aider interactive run failed:\n{combined}")

        for allowed_rel in allowed_rels:
            self.assertIn(
                f"Added {allowed_rel} to the chat",
                combined_norm,
                f"Expected {allowed_rel} to be added to chat:\n{combined}",
            )

        for blocked_rel in blocked_rels:
            fname = os.path.basename(blocked_rel)
            self.assertNotIn(
                f"Added {blocked_rel} to the chat",
                combined_norm,
                f"Expected {blocked_rel} to be blocked from chat:\n{combined}",
            )
            self.assertTrue(
                f"{fname} which is in gitignore" in combined_unwrapped
                or f"{fname} due to aiderignore" in combined_unwrapped
                or f"Skipping {blocked_rel}" in combined_unwrapped,
                f"Expected {blocked_rel} to be rejected by gitignore/aiderignore:\n{combined}",
            )

    def test_static_and_native_repomap_exclude_aider_factory_when_strategy_tracked(self):
        """2. Verify --repo-map-all and native Aider RepoMap exclude .aider_factory/ even when un-ignored files are git-tracked."""
        self._init_git_repo_with_legacy_ignores()
        run_bootstrap(self.tmp_dir)

        scratch_rel = ".aider_factory/temp/scratch.py"
        sess_rel = ".aider_factory/sessions/s1/session.yml"
        conv_rel = ".aider_factory/CONVENTIONS.md"
        strat_rel = ".aider_factory/markdown/oracle_pre_plan/strategy_template.md"

        (self.project_dir / scratch_rel).parent.mkdir(parents=True, exist_ok=True)
        (self.project_dir / scratch_rel).write_text(
            "def temp_scratch_helper() -> str:\n    return 'scratch'\n",
            encoding="utf-8",
        )
        (self.project_dir / sess_rel).parent.mkdir(parents=True, exist_ok=True)
        (self.project_dir / sess_rel).write_text("session: s1\n", encoding="utf-8")

        # Git add without -f must succeed because all four paths are un-ignored in .gitignore
        subprocess.run(
            ["git", "add", ".gitignore", strat_rel, conv_rel, scratch_rel, sess_rel],
            cwd=self.tmp_dir,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Track un-ignored .aider_factory artifacts"],
            cwd=self.tmp_dir,
            check=True,
        )

        env = _get_clean_env()
        proc_map = subprocess.run(
            [sys.executable, cli_script, "--repo-map-all", "--map-tokens", "2048"],
            cwd=self.tmp_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc_map.returncode, 0, f"--repo-map-all failed:\n{proc_map.stderr}")

        src_map = (self.project_dir / ".aider_factory" / "static_repo_map.md").read_text(encoding="utf-8").replace("\\", "/")
        test_map = (self.project_dir / ".aider_factory" / "static_repo_map_tests.md").read_text(encoding="utf-8").replace("\\", "/")

        self.assertIn("src/app.py", src_map)
        for forbidden in ("strategy_template.md", "CONVENTIONS.md", "scratch.py", "temp_scratch_helper", "session.yml", ".aider_factory"):
            self.assertNotIn(forbidden, src_map)

        self.assertIn("tests/test_app.py", test_map)
        for forbidden in ("strategy_template.md", "CONVENTIONS.md", "scratch.py", "temp_scratch_helper", "session.yml", ".aider_factory"):
            self.assertNotIn(forbidden, test_map)

        # Verify native Aider --show-repo-map with task-scoped .aiderignore from AiderFactory
        factory = AiderFactory(project_dir=self.tmp_dir, session_name="repomap_iso_sess")
        headless_task = Task(id="p1_job1_app", files=["src/app.py"], pair_programming=False)
        task_ignore = factory._resolve_task_aiderignore(headless_task, ask_mode=False)
        self.assertIsNotNone(task_ignore)

        proc_native = subprocess.run(
            [
                "aider",
                "--map-tokens",
                "2048",
                "--show-repo-map",
                "--no-show-model-warnings",
                "--no-check-update",
                "--aiderignore",
                str(task_ignore),
            ],
            cwd=self.tmp_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc_native.returncode, 0, proc_native.stderr)
        native_out = proc_native.stdout.replace("\\", "/")
        self.assertIn("src/app.py", native_out)
        for forbidden in ("strategy_template.md", "CONVENTIONS.md", "scratch.py", "temp_scratch_helper", "session.yml", ".aider_factory"):
            self.assertNotIn(forbidden, native_out)

    def test_live_llm_aider_edits_strategy_template_with_gitignore_active(self):
        """3. Zero-Mock Live LLM test: real 'aider' edits untracked strategy_template.md when .gitignore is active."""
        gem_creds = _resolve_live_gemini_key()
        if not gem_creds:
            self.skipTest("No live GEMINI_API_KEY detected for live LLM edit test.")

        self._init_git_repo_with_legacy_ignores()
        run_bootstrap(self.tmp_dir)

        key_name, key_val = gem_creds
        env = _get_clean_env({key_name: key_val, "GEMINI_API_KEY": key_val})

        strat_rel = ".aider_factory/markdown/oracle_pre_plan/strategy_template.md"
        strat_abs = self.project_dir / strat_rel

        proc = subprocess.run(
            [
                "aider",
                "--model",
                "gemini/gemini-2.5-flash",
                "--yes-always",
                "--no-auto-commits",
                "--no-check-update",
                "--no-show-model-warnings",
                "--no-analytics",
                "--no-pretty",
                "--exit",
                "--message",
                "In `.aider_factory/markdown/oracle_pre_plan/strategy_template.md`, replace `- [Define implementation/refactoring scope and objectives]` with `- Live E2E Verified Scope Entry`.",
                strat_rel,
            ],
            cwd=self.tmp_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
        )
        combined = (proc.stdout + proc.stderr).replace("\\", "/")
        self.assertEqual(proc.returncode, 0, f"Live Aider edit failed:\n{combined}")
        self.assertNotIn("which is in gitignore", combined)
        updated_text = strat_abs.read_text(encoding="utf-8")
        self.assertIn("Live E2E Verified Scope Entry", updated_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
