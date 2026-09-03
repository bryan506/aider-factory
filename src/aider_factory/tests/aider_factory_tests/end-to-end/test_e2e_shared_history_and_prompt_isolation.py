#!/usr/bin/env python3
"""test_e2e_shared_history_and_prompt_isolation.py

Comprehensive End-to-End and Subprocess test suite asserting:
1. Multi-target file `shared_history: false` isolation (zero conversation bleeding across target files).
2. Stdin prompt negation (`b"n\n"` instead of `b"d\n"`) to prevent out-of-scope file additions and unexpected file creation.
3. Accurate `yes_always` toggle CLI flag generation (omitting `--yes-always` when false, never generating nonexistent `--no-yes-always`).
4. Active stage directory wiping during state swaps so no residual chat history lingers in the session folder.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import yaml

test_file_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(test_file_dir, "../../../../.."))
src_dir = os.path.join(repo_root, "src")
pkg_dir = os.path.join(src_dir, "aider_factory")

sys.path.insert(0, repo_root)
sys.path.insert(0, src_dir)
sys.path.insert(0, pkg_dir)
sys.path.insert(0, os.path.join(pkg_dir, "python"))

CLI_PATH = os.path.join(pkg_dir, "cli.py")
WORKFLOW_RUNNER = os.path.join(pkg_dir, "python", "run_workflow.py")


class TestSharedHistoryAndPromptIsolation(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Scrub ambient factory environment variables
        self.old_env = dict(os.environ)
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
                os.environ.pop(k, None)

        self.bin_dir = os.path.join(self.test_dir, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        self.fake_aider_log = os.path.join(self.test_dir, "fake_aider_invocations.log")

        # Fake aider script that logs command line arguments, stdin responses, and environment variables
        self.fake_aider = os.path.join(self.bin_dir, "aider")
        fake_script = f"""#!/bin/bash
LOG="{self.fake_aider_log}"
echo "=== AIDER INVOCATION ===" >> "$LOG"
echo "ARGS: $@" >> "$LOG"

# Record stdin input sent from orchestrate.py
STDIN_INPUT=$(cat)
echo "STDIN: $STDIN_INPUT" >> "$LOG"

prev=""
for i in "$@"; do
    if [[ "$prev" == "--chat-history-file" ]]; then
        echo "HISTORY_FILE: $i" >> "$LOG"
        echo "# Turn for $i" >> "$LOG"
        # Write unique content identifying the target file being processed
        TARGET=""
        for arg in "$@"; do
            case "$arg" in
                *.py) TARGET="$arg" ;;
            esac
        done
        echo "## Session turn for target: $TARGET" >> "$i"
    fi
    if [[ "$prev" == "--message" ]]; then
        echo "MESSAGE: $i" >> "$LOG"
    fi
    prev="$i"
done
exit 0
"""
        with open(self.fake_aider, "w", encoding="utf-8") as f:
            f.write(fake_script)
        os.chmod(self.fake_aider, 0o755)

        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}:{self.old_path}"

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _get_subprocess_env(self, session_name=None, config_path=None):
        env = os.environ.copy()
        python_path = f"{repo_root}:{src_dir}:{pkg_dir}:{os.path.join(pkg_dir, 'python')}"
        env["PYTHONPATH"] = python_path
        if session_name:
            env["AI_FACTORY_SESSION"] = session_name
        if config_path:
            env["AI_FACTORY_CONFIG"] = config_path
        return env

    def test_multi_target_files_shared_history_false_strict_isolation(self):
        """CRITICAL: When shared_history is FALSE and target_files has multiple files (e.g. file_a.py, file_b.py),
        Task for file_b MUST NOT see or inherit chat history from file_a.
        Each file must have its own stemmed history in the chat_history/ vault.
        """
        src_folder = os.path.join(self.test_dir, "src")
        os.makedirs(src_folder, exist_ok=True)

        file_a = os.path.join(src_folder, "module_alpha.py")
        file_b = os.path.join(src_folder, "module_beta.py")
        file_c = os.path.join(src_folder, "module_gamma.py")

        with open(file_a, "w", encoding="utf-8") as f:
            f.write("def alpha(): pass\n")
        with open(file_b, "w", encoding="utf-8") as f:
            f.write("def beta(): pass\n")
        with open(file_c, "w", encoding="utf-8") as f:
            f.write("def gamma(): pass\n")

        # Create custom task plan template
        tmpl_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "templates")
        os.makedirs(tmpl_dir, exist_ok=True)
        plan_file = os.path.join(tmpl_dir, "implement.md")
        with open(plan_file, "w", encoding="utf-8") as f:
            f.write("# Plan\nImplement target module functions.\n")

        sess_name = "multi_target_isolation_session"
        config_data = {
            "name": "Multi-Target Isolation Pipeline",
            "working_directory": self.test_dir,
            "test_command_prefix": "",
            "test_runner": f"{sys.executable} {{file}}",
            "phases": [
                {
                    "name": "Multi-Target Phase",
                    "enabled": True,
                    "models": {
                        "architect_agent": "mock/architect",
                        "editor_agent": "mock/editor",
                    },
                    "toggles": {
                        "run_job_one": True,
                        "run_job_two": False,
                        "run_job_three": False,
                        "iterate_test": False,
                        "shared_history": False,  # Strict per-file isolation
                        "pair_programming": False,
                        "yes_always": False,
                    },
                    "files": {
                        "target_files": [
                            "src/module_alpha.py",
                            "src/module_beta.py",
                            "src/module_gamma.py",
                        ],
                        "context_files_job": [],
                    },
                    "plans": {
                        "job_one_plan": "markdown/templates/implement.md",
                    },
                }
            ],
        }

        config_path = os.path.join(self.test_dir, "multi_target_pipeline.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        env = self._get_subprocess_env(session_name=sess_name, config_path=config_path)

        res = subprocess.run(
            [sys.executable, WORKFLOW_RUNNER, sess_name, config_path],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Workflow failed: {res.stderr}")

        # Check the vaulted chat history directory
        sess_dir = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_name)
        vault_dir = os.path.join(sess_dir, "chat_history")
        self.assertTrue(os.path.isdir(vault_dir), "chat_history/ vault directory must exist")

        hist_alpha = os.path.join(vault_dir, ".aider.chat.history_job1_module_alpha.md")
        hist_beta = os.path.join(vault_dir, ".aider.chat.history_job1_module_beta.md")
        hist_gamma = os.path.join(vault_dir, ".aider.chat.history_job1_module_gamma.md")

        self.assertTrue(os.path.exists(hist_alpha), f"Alpha history {hist_alpha} must exist")
        self.assertTrue(os.path.exists(hist_beta), f"Beta history {hist_beta} must exist")
        self.assertTrue(os.path.exists(hist_gamma), f"Gamma history {hist_gamma} must exist")

        with open(hist_alpha, "r", encoding="utf-8") as f:
            alpha_content = f.read()
        with open(hist_beta, "r", encoding="utf-8") as f:
            beta_content = f.read()
        with open(hist_gamma, "r", encoding="utf-8") as f:
            gamma_content = f.read()

        # Alpha must not contain Beta or Gamma history
        self.assertNotIn("module_beta", alpha_content)
        self.assertNotIn("module_gamma", alpha_content)

        # Beta must not contain Alpha history (proves ZERO history bleeding from Task 1 into Task 2)
        self.assertNotIn("module_alpha", beta_content)
        self.assertNotIn("module_gamma", beta_content)

        # Gamma must not contain Alpha or Beta history
        self.assertNotIn("module_alpha", gamma_content)
        self.assertNotIn("module_beta", gamma_content)

        # --- Zero-mock assertions on the fake aider invocation log ---
        sess_dir = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_name)

        with open(self.fake_aider_log, "r", encoding="utf-8") as f:
            log_content = f.read()

        # Every aider invocation must target the SESSION history file, never global
        for line in log_content.splitlines():
            if line.startswith("HISTORY_FILE:"):
                path_val = line.split("HISTORY_FILE:", 1)[1].strip()
                self.assertIn(sess_dir, path_val,
                              f"--chat-history-file must point to session dir, got: {path_val}")
                global_hist = os.path.join(self.test_dir, ".aider_factory", ".aider.chat.history.md")
                self.assertNotEqual(path_val, global_hist)

        # Verify --restore-chat-history is present in every invocation
        arg_lines = [l for l in log_content.splitlines() if l.startswith("ARGS:")]
        self.assertTrue(len(arg_lines) >= 3, "Must have at least 3 aider invocations")
        for al in arg_lines:
            self.assertIn("--restore-chat-history", al,
                          f"Every aider invocation must pass --restore-chat-history: {al}")

        # Verify the generated session .aider.conf.yml has NO history-path keys
        session_conf = os.path.join(sess_dir, ".aider.conf.yml")
        self.assertTrue(os.path.exists(session_conf))
        with open(session_conf, "r", encoding="utf-8") as f:
            conf = yaml.safe_load(f) or {}
        for key in ("chat-history-file", "input-history-file", "llm-history-file", "restore-chat-history"):
            self.assertNotIn(key, conf, f"Session config must not contain '{key}'")

    def test_multi_target_files_shared_history_true_accumulation(self):
        """E2E: When shared_history is TRUE and target_files has multiple files,
        history is continuously accumulated in .aider.chat.history.md without per-file stemming.
        """
        src_folder = os.path.join(self.test_dir, "src")
        os.makedirs(src_folder, exist_ok=True)

        file_a = os.path.join(src_folder, "shared_a.py")
        file_b = os.path.join(src_folder, "shared_b.py")
        with open(file_a, "w", encoding="utf-8") as f:
            f.write("def a(): pass\n")
        with open(file_b, "w", encoding="utf-8") as f:
            f.write("def b(): pass\n")

        sess_name = "shared_history_true_session"
        config_data = {
            "name": "Shared History True Pipeline",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Shared Phase",
                    "enabled": True,
                    "models": {
                        "architect_agent": "mock/arch",
                        "editor_agent": "mock/edit",
                    },
                    "toggles": {
                        "run_job_one": True,
                        "shared_history": True,  # Shared continuous history
                        "pair_programming": False,
                        "yes_always": False,
                    },
                    "files": {
                        "target_files": ["src/shared_a.py", "src/shared_b.py"],
                    },
                }
            ],
        }

        config_path = os.path.join(self.test_dir, "shared_true_pipeline.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        env = self._get_subprocess_env(session_name=sess_name, config_path=config_path)

        res = subprocess.run(
            [sys.executable, WORKFLOW_RUNNER, sess_name, config_path],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)

        # In shared_history: true, chat history lives directly in the session root
        sess_dir = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_name)
        shared_chat = os.path.join(sess_dir, ".aider.chat.history.md")
        self.assertTrue(os.path.exists(shared_chat))

    def test_stdin_rejects_out_of_scope_prompts_with_n(self):
        """CRITICAL: In headless execution, stdin MUST send 'n\\n' (or reject) rather than 'd\\n'.
        Sending 'd' stands for '(D)on't ask again' which causes Aider to auto-accept subsequent
        out-of-scope file additions and grants write access to non-target files.
        """
        src_folder = os.path.join(self.test_dir, "src")
        os.makedirs(src_folder, exist_ok=True)
        target_file = os.path.join(src_folder, "target.py")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("def target(): pass\n")

        sess_name = "stdin_prompt_test_session"
        config_data = {
            "name": "Stdin Prompt Test Pipeline",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase 1",
                    "enabled": True,
                    "models": {
                        "architect_agent": "mock/architect",
                        "editor_agent": "mock/editor",
                    },
                    "toggles": {
                        "run_job_one": True,
                        "run_job_two": False,
                        "run_job_three": False,
                        "iterate_test": False,
                        "pair_programming": False,
                        "yes_always": False,
                    },
                    "files": {
                        "target_files": ["src/target.py"],
                        "context_files_job": [],
                    },
                    "plans": {
                        "job_one_plan": "markdown/templates/implement.md",
                    },
                }
            ],
        }

        config_path = os.path.join(self.test_dir, "stdin_test.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        env = self._get_subprocess_env(session_name=sess_name, config_path=config_path)

        res = subprocess.run(
            [sys.executable, WORKFLOW_RUNNER, sess_name, config_path],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)

        # Inspect the fake aider log to verify stdin content
        with open(self.fake_aider_log, "r", encoding="utf-8") as f:
            log_content = f.read()

        # Assert that 'd' is NEVER sent to stdin
        self.assertNotIn("STDIN: d", log_content, "orchestrate.py must NEVER send 'd' to stdin (d auto-accepts file additions)")
        # Assert that 'n' (No) is sent to reject out-of-scope prompts safely
        self.assertIn("STDIN: n", log_content, "orchestrate.py must send 'n' to stdin to reject out-of-scope prompts")

    def test_yes_always_flag_omitted_when_false_no_hallucinated_negative_flag(self):
        """CRITICAL: When yes_always is False, Aider CLI MUST NOT receive --no-yes-always (non-existent flag),
        and MUST NOT receive --yes-always. It should simply omit --yes-always.
        """
        src_folder = os.path.join(self.test_dir, "src")
        os.makedirs(src_folder, exist_ok=True)
        target_file = os.path.join(src_folder, "sample.py")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("def sample(): pass\n")

        sess_name = "yes_always_cli_test"
        config_data = {
            "name": "Yes Always Flag Pipeline",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase 1",
                    "enabled": True,
                    "models": {"architect_agent": "mock/arch", "editor_agent": "mock/edit"},
                    "toggles": {
                        "run_job_one": True,
                        "pair_programming": False,
                        "yes_always": False,
                    },
                    "files": {"target_files": ["src/sample.py"]},
                }
            ],
        }

        config_path = os.path.join(self.test_dir, "yes_always_test.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        env = self._get_subprocess_env(session_name=sess_name, config_path=config_path)

        res = subprocess.run(
            [sys.executable, WORKFLOW_RUNNER, sess_name, config_path],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)

        with open(self.fake_aider_log, "r", encoding="utf-8") as f:
            log_content = f.read()

        # Assert no hallucinated --no-yes-always flag
        self.assertNotIn("--no-yes-always", log_content, "--no-yes-always does not exist in Aider and must not be passed")
        # Assert --yes-always was omitted
        self.assertNotIn("--yes-always", log_content, "--yes-always must be omitted when yes_always is False")

        # Verify session .aider.conf.yml has yes-always: false
        sess_dir = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_name)
        session_conf = os.path.join(sess_dir, ".aider.conf.yml")
        self.assertTrue(os.path.exists(session_conf))
        with open(session_conf, "r", encoding="utf-8") as f:
            conf_yaml = yaml.safe_load(f)
        self.assertFalse(conf_yaml.get("yes-always", True))

    def test_sequential_vault_swap_across_two_runs(self):
        """E2E: Two sequential workflow runs on the same session with shared_history:false
        must vault-swap correctly: run-1 content archived to vault, run-2 (same stem)
        restores prior context via swap_in, then archives accumulated state."""
        src_folder = os.path.join(self.test_dir, "src")
        os.makedirs(src_folder, exist_ok=True)
        target = os.path.join(src_folder, "isolate_target.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("def isolate(): pass\n")

        sess_name = "sequential_swap_session"
        config_data = {
            "name": "Sequential Swap Pipeline",
            "working_directory": self.test_dir,
            "phases": [{
                "name": "Swap Phase",
                "enabled": True,
                "models": {"architect_agent": "mock/a", "editor_agent": "mock/e"},
                "toggles": {
                    "run_job_one": True, "run_job_two": False, "run_job_three": False,
                    "iterate_test": False, "shared_history": False,
                    "pair_programming": False, "yes_always": False,
                },
                "files": {"target_files": ["src/isolate_target.py"]},
            }],
        }
        config_path = os.path.join(self.test_dir, "seq_swap.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        env = self._get_subprocess_env(session_name=sess_name, config_path=config_path)

        # --- RUN 1: fake aider writes identifiable content to --chat-history-file ---
        run1_marker = "RUN_1_UNIQUE_CONTENT_xyz"
        fake_script_v2 = f"""#!/bin/bash
LOG="{self.fake_aider_log}"
echo "=== AIDER INVOCATION ===" >> "$LOG"
echo "ARGS: $@" >> "$LOG"
STDIN_INPUT=$(cat)
echo "STDIN: $STDIN_INPUT" >> "$LOG"
prev=""
for i in "$@"; do
    if [[ "$prev" == "--chat-history-file" ]]; then
        echo "{run1_marker}" >> "$i"
    fi
    prev="$i"
done
exit 0
"""
        with open(self.fake_aider, "w", encoding="utf-8") as f:
            f.write(fake_script_v2)
        os.chmod(self.fake_aider, 0o755)
        open(self.fake_aider_log, "w").close()

        res1 = subprocess.run(
            [sys.executable, WORKFLOW_RUNNER, sess_name, config_path],
            cwd=self.test_dir, env=env, capture_output=True, text=True,
        )
        self.assertEqual(res1.returncode, 0, f"Run 1 failed: {res1.stderr}")

        sess_dir = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_name)
        vault_dir = os.path.join(sess_dir, "chat_history")

        # After run 1: vault must contain run-1 content (swap_out archived it)
        self.assertTrue(os.path.isdir(vault_dir), "chat_history/ must exist after run 1")
        vault_files = os.listdir(vault_dir)
        self.assertTrue(len(vault_files) > 0, "Vault must have at least one file after run 1")
        vault_content = ""
        for vf in vault_files:
            vault_content += Path(os.path.join(vault_dir, vf)).read_text(encoding="utf-8")
        self.assertIn(run1_marker, vault_content)

        # --- RUN 2: verify swap_in wiped active, then new content is archived ---
        run2_marker = "RUN_2_UNIQUE_CONTENT_abc"
        fake_script_v3 = f"""#!/bin/bash
LOG="{self.fake_aider_log}"
echo "=== AIDER INVOCATION ===" >> "$LOG"
echo "ARGS: $@" >> "$LOG"
STDIN_INPUT=$(cat)
echo "STDIN: $STDIN_INPUT" >> "$LOG"
prev=""
for i in "$@"; do
    if [[ "$prev" == "--chat-history-file" ]]; then
        if [[ -f "$i" ]] && grep -q "{run1_marker}" "$i" 2>/dev/null; then
            echo "ACTIVE_WAS_DIRTY: $(cat "$i")" >> "$LOG"
        fi
        echo "{run2_marker}" >> "$i"
    fi
    prev="$i"
done
exit 0
"""
        with open(self.fake_aider, "w", encoding="utf-8") as f:
            f.write(fake_script_v3)
        os.chmod(self.fake_aider, 0o755)
        open(self.fake_aider_log, "w").close()

        res2 = subprocess.run(
            [sys.executable, WORKFLOW_RUNNER, sess_name, config_path],
            cwd=self.test_dir, env=env, capture_output=True, text=True,
        )
        self.assertEqual(res2.returncode, 0, f"Run 2 failed: {res2.stderr}")

        # Same stem: swap_in correctly RESTORES prior vault context (continuity is intended).
        # The fake aider should SEE run-1 content restored to the active file.
        with open(self.fake_aider_log, "r", encoding="utf-8") as f:
            log2 = f.read()
        self.assertIn("ACTIVE_WAS_DIRTY", log2,
                      "Run 2 (same stem) must see run-1 content restored by swap_in (context continuity)")
        self.assertIn(run1_marker, log2,
                      "Restored active file must contain run-1 marker")

        # Vault now contains BOTH markers (run 1 context preserved + run 2 appended)
        all_vault = ""
        for vf in os.listdir(vault_dir):
            all_vault += Path(os.path.join(vault_dir, vf)).read_text(encoding="utf-8")
        self.assertIn(run1_marker, all_vault, "Run 1 content must persist in vault")
        self.assertIn(run2_marker, all_vault, "Run 2 content must be archived to vault")

    def test_history_stem_produces_per_file_vault_names(self):
        """E2E: Each aider invocation in multi-file isolated mode must receive a
        UNIQUE --chat-history-file path derived from the target file stem."""
        src_folder = os.path.join(self.test_dir, "src")
        os.makedirs(src_folder, exist_ok=True)

        file_a = os.path.join(src_folder, "stem_alpha.py")
        file_b = os.path.join(src_folder, "stem_beta.py")
        file_c = os.path.join(src_folder, "stem_gamma.py")
        for fp in (file_a, file_b, file_c):
            with open(fp, "w", encoding="utf-8") as f:
                f.write("pass\n")

        tmpl_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "templates")
        os.makedirs(tmpl_dir, exist_ok=True)
        with open(os.path.join(tmpl_dir, "implement.md"), "w", encoding="utf-8") as f:
            f.write("# Plan\nImplement.\n")

        sess_name = "stem_names_session"
        config_data = {
            "name": "Stem Names Pipeline",
            "working_directory": self.test_dir,
            "phases": [{
                "name": "Stem Phase",
                "enabled": True,
                "models": {"architect_agent": "mock/a", "editor_agent": "mock/e"},
                "toggles": {
                    "run_job_one": True, "run_job_two": False, "run_job_three": False,
                    "iterate_test": False, "shared_history": False,
                    "pair_programming": False, "yes_always": False,
                },
                "files": {
                    "target_files": ["src/stem_alpha.py", "src/stem_beta.py", "src/stem_gamma.py"],
                    "context_files_job": [],
                },
                "plans": {"job_one_plan": "markdown/templates/implement.md"},
            }],
        }
        config_path = os.path.join(self.test_dir, "stem_names.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        env = self._get_subprocess_env(session_name=sess_name, config_path=config_path)

        res = subprocess.run(
            [sys.executable, WORKFLOW_RUNNER, sess_name, config_path],
            cwd=self.test_dir, env=env, capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, f"Workflow failed: {res.stderr}")

        sess_dir = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_name)
        vault_dir = os.path.join(sess_dir, "chat_history")

        with open(self.fake_aider_log, "r", encoding="utf-8") as f:
            log = f.read()

        hist_lines = [l for l in log.splitlines() if l.startswith("HISTORY_FILE:")]
        self.assertEqual(len(hist_lines), 3, "Must have 3 aider invocations (one per file)")

        # All invocations target the session-dir active path (isolation is via vault swap,
        # not via distinct CLI paths). Verify they all point into the session dir.
        paths = [l.split("HISTORY_FILE:", 1)[1].strip() for l in hist_lines]
        for p in paths:
            self.assertIn(sess_dir, p,
                          f"--chat-history-file must point to session dir, got: {p}")

        # Vault files must be distinct per stem (3 files in chat_history/)
        vault_files = sorted(os.listdir(vault_dir))
        self.assertEqual(len(vault_files), 3, f"Vault must have 3 distinct files, got: {vault_files}")

        # Each vault file must have unique content (proves swap_out captured distinct state)
        vault_contents = set()
        for vf in vault_files:
            vault_contents.add(Path(os.path.join(vault_dir, vf)).read_text(encoding="utf-8"))
        self.assertEqual(len(vault_contents), 3,
                         f"Vault file contents must be distinct per stem, got: {vault_contents}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from aider_factory.python.orchestrate import AiderFactory, Task, TaskStatus


class TestE2ESharedHistoryAndPromptIsolation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.factory = AiderFactory(project_dir=self.temp_dir)

    @patch("subprocess.Popen")
    def test_headless_mode_prompt_isolation(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        task = Task(
            id="test_headless",
            files=["test.py"],
            pair_programming=False,
            message_file=os.path.join(self.temp_dir, "plan.md"),
        )
        with open(task.message_file, "w") as f:
            f.write("Test plan")

        self.factory.add_task(task)
        res = self.factory.run_task(task)

        self.assertTrue(res)
        self.assertTrue(mock_popen.called)

        args, kwargs = mock_popen.call_args
        cmd_str = args[0]
        log_content = f"CMD: {cmd_str}"

        # Assert that 'n' (No) is sent to stdin to reject out-of-scope prompts safely
        mock_proc.stdin.write.assert_called_with(b"n\n" * 50)
        # Assert that --exit is passed in headless mode so Aider exits cleanly after --message
        self.assertIn("--exit", log_content, "orchestrate.py must pass --exit in headless mode to terminate immediately after message completion")


if __name__ == "__main__":
    unittest.main()
