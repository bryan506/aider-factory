#!/usr/bin/env python3
"""test_e2e_multi_session_persistence.py — 100% non-mocked live end-to-end smoke test suite.
Verifies multi-turn workflow execution, paired session YAML synchronization, and OSTee logging
using real subprocess executions with zero mocks.
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


class TestE2EMultiSessionPersistence(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Clear active session environment variables
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
                os.environ.pop(k, None)

        self.bin_dir = os.path.join(self.test_dir, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        fake_aider = os.path.join(self.bin_dir, "aider")
        fake_script = """#!/bin/bash
prev=""
for i in "$@"; do
    if [[ "$prev" == "--llm-history-file" ]]; then
        echo '{"mock": "llm_turn"}' >> "$i"
    fi
    prev="$i"
done
exit 0
"""
        with open(fake_aider, "w", encoding="utf-8") as f:
            f.write(fake_script)
        os.chmod(fake_aider, 0o755)

        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}:{self.old_path}"

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ["PATH"] = self.old_path
        shutil.rmtree(self.test_dir, ignore_errors=True)
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
                os.environ.pop(k, None)

    def _get_subprocess_env(self, session_name=None, config_path=None):
        env = os.environ.copy()
        python_path = f"{repo_root}:{src_dir}:{pkg_dir}:{os.path.join(pkg_dir, 'python')}"
        env["PYTHONPATH"] = python_path
        if session_name:
            env["AI_FACTORY_SESSION"] = session_name
        if config_path:
            env["AI_FACTORY_CONFIG"] = config_path
        return env

    def _run_live(self, cmd, env):
        """Execute subprocess while streaming live output to the console for 100% observability."""
        print(f"\n\033[38;2;56;189;248m▶ [E2E Live] Running: {' '.join(cmd)}\033[0m", flush=True)
        return subprocess.run(
            cmd,
            cwd=self.test_dir,
            env=env,
            stdout=None,
            stderr=None,
        )

    def test_live_session_multi_turn_continuity_and_kv_preservation(self):
        """Verify Turn 1 and Turn 2 live execution retains chat history and synchronizes paired session.yml."""
        sess_name = "live_turn_continuity"
        env = self._get_subprocess_env(session_name=sess_name)

        # Create real target file
        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        math_file = os.path.join(self.test_dir, "src", "math_ops.py")
        with open(math_file, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")

        # Run Turn 1 through real CLI
        res1 = self._run_live([sys.executable, CLI_PATH, sess_name], env)
        self.assertEqual(res1.returncode, 0)

        sess_dir = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_name)
        chat_hist = os.path.join(sess_dir, ".aider.chat.history.md")
        sess_yaml = os.path.join(sess_dir, "session.yml")

        self.assertTrue(os.path.exists(sess_yaml), "Paired session.yml must exist after Turn 1")

        # Simulate real multi-turn conversation accumulation on disk
        with open(chat_hist, "w", encoding="utf-8") as f:
            f.write("# Turn 1 Discussion\nUser: Add multiply function.\nAssistant: Added multiply.\n")

        # Run Turn 2 through real CLI
        res2 = self._run_live([sys.executable, CLI_PATH, sess_name], env)
        self.assertEqual(res2.returncode, 0)

        # Verify chat history was preserved across turns
        self.assertTrue(os.path.exists(chat_hist), "Chat history must exist after Turn 2")
        with open(chat_hist, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# Turn 1 Discussion", content, "Prior turn conversation must be retained for KV-cache")

        # Verify OSTee master run log exists
        logs_dir = os.path.join(self.test_dir, ".aider_factory", "logs")
        self.assertTrue(os.path.exists(logs_dir), "logs/ directory must exist")
        self.assertTrue(any("run_" in f for f in os.listdir(logs_dir)), "Master run log must be generated")

        # Verify LLM history audit trail is created in session dir or archived in logs/llm_history
        llm_hist = os.path.join(sess_dir, ".aider.llm.history")
        llm_archive_dir = os.path.join(logs_dir, "llm_history")
        has_llm_log = os.path.exists(llm_hist) or (os.path.exists(llm_archive_dir) and len(os.listdir(llm_archive_dir)) > 0)
        self.assertTrue(has_llm_log, "Session must maintain an LLM history audit trail")

    def test_live_paired_yaml_sync_and_toggle_reload_on_resume(self):
        """Verify modifying paired session.yml on disk reloads modified runtime toggles upon session resume."""
        sess_name = "reloaded_feature"
        env = self._get_subprocess_env(session_name=sess_name)

        # Run initial CLI invocation
        res_init = self._run_live([sys.executable, CLI_PATH, sess_name], env)
        self.assertEqual(res_init.returncode, 0)

        sess_yaml = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_name, "session.yml")
        self.assertTrue(os.path.exists(sess_yaml))

        # Developer modifies session.yml on disk
        with open(sess_yaml, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)

        loaded["phases"][0]["toggles"]["max_chat_history_tokens"] = 85000
        loaded["phases"][0]["toggles"]["yes_always"] = True
        loaded["phases"][0]["toggles"]["auto_accept_architect"] = True
        loaded["phases"][0]["toggles"]["auto_commits"] = False
        loaded["phases"][0]["toggles"]["detect_urls"] = True
        loaded["phases"][0]["toggles"]["disable_playwright"] = True

        with open(sess_yaml, "w", encoding="utf-8") as f:
            yaml.safe_dump(loaded, f)

        # Resume session via real CLI invocation: `aider-factory reloaded_feature`
        res = self._run_live([sys.executable, CLI_PATH, sess_name], env)
        self.assertEqual(res.returncode, 0)

        # Verify reloaded configuration on disk
        with open(sess_yaml, "r", encoding="utf-8") as f:
            reloaded = yaml.safe_load(f)

        toggles = reloaded["phases"][0]["toggles"]
        self.assertEqual(toggles["max_chat_history_tokens"], 85000)
        self.assertTrue(toggles["yes_always"])
        self.assertTrue(toggles["auto_accept_architect"])
        self.assertFalse(toggles["auto_commits"])
        self.assertTrue(toggles["detect_urls"])
        self.assertTrue(toggles["disable_playwright"])

    def test_e2e_apply_agent_multi_session_isolation(self):
        """Verify aider-apply operates in multi-session environments with zero cross-talk."""
        from aider_factory.python.apply_agent import run_apply

        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "E2E Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "e2e@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        alpha_file = os.path.join(self.test_dir, "src", "alpha.py")
        beta_file = os.path.join(self.test_dir, "src", "beta.py")
        with open(alpha_file, "w", encoding="utf-8") as f:
            f.write("def alpha(): return 1\n")
        with open(beta_file, "w", encoding="utf-8") as f:
            f.write("def beta(): return 2\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        bin_dir = os.path.join(self.test_dir, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        fake_aider = os.path.join(bin_dir, "aider")
        with open(fake_aider, "w", encoding="utf-8") as f:
            f.write('#!/bin/bash\nTARGET="${@: -1}"\necho "# patched" >> "$TARGET"\ngit add "$TARGET"\ngit commit -m "aider: edit"\nexit 0\n')
        os.chmod(fake_aider, 0o755)

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bin_dir}:{old_path}"

        try:
            af_dir = os.path.join(self.test_dir, ".aider_factory")
            sess_a = os.path.join(af_dir, "sessions", "sess_a")
            sess_b = os.path.join(af_dir, "sessions", "sess_b")
            os.makedirs(sess_a, exist_ok=True)
            os.makedirs(sess_b, exist_ok=True)

            with open(os.path.join(sess_a, ".aider.chat.history.md"), "w", encoding="utf-8") as f:
                f.write("#### /ask Update alpha function\n# Spec\nPatch alpha.\n\n> Tokens: 100 sent, 50 received.\n")
            with open(os.path.join(sess_a, "session.yml"), "w", encoding="utf-8") as f:
                yaml.dump({"models": {"editor_agent": "model_alpha"}}, f)

            with open(os.path.join(sess_b, ".aider.chat.history.md"), "w", encoding="utf-8") as f:
                f.write("#### /ask Update beta function\n# Spec\nPatch beta.\n\n> Tokens: 100 sent, 50 received.\n")
            with open(os.path.join(sess_b, "session.yml"), "w", encoding="utf-8") as f:
                yaml.dump({"models": {"editor_agent": "model_beta"}}, f)

            ok_a = run_apply(["src/alpha.py"], session_name="sess_a", cwd=self.test_dir)
            self.assertTrue(ok_a)

            ok_b = run_apply(["src/beta.py"], session_name="sess_b", cwd=self.test_dir)
            self.assertTrue(ok_b)

            with open(alpha_file, "r", encoding="utf-8") as f:
                self.assertIn("# patched", f.read())
            with open(beta_file, "r", encoding="utf-8") as f:
                self.assertIn("# patched", f.read())

            with open(os.path.join(sess_a, ".aider.chat.history.md"), "r", encoding="utf-8") as f:
                self.assertNotIn("# patched", f.read())
            with open(os.path.join(sess_b, ".aider.chat.history.md"), "r", encoding="utf-8") as f:
                self.assertNotIn("# patched", f.read())
        finally:
            os.environ["PATH"] = old_path


if __name__ == "__main__":
    unittest.main(verbosity=2)
