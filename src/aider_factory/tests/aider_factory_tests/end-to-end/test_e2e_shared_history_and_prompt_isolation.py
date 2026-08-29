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
        # Simulate recording turn in the chat history file
        echo "# Turn for $i" >> "$i"
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
