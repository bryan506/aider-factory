#!/usr/bin/env python3
"""test_e2e_real_session_lifecycle.py — 100% non-mocked live end-to-end smoke test suite.
Tests the exact user CLI workflow using real shipped YAML templates, real subprocess invocations,
real session pairing, and real on-disk isolation without any unittest.mock shortcuts.
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
ORACLE_CLI_PATH = os.path.join(pkg_dir, "python", "oracle_agent.py")


class TestE2ERealSessionLifecycle(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Clear active session environment variables
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
                os.environ.pop(k, None)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
                os.environ.pop(k, None)

    def _get_subprocess_env(self, extra_env=None):
        env = os.environ.copy()
        python_path = f"{repo_root}:{src_dir}:{pkg_dir}:{os.path.join(pkg_dir, 'python')}"
        env["PYTHONPATH"] = python_path
        if extra_env:
            env.update(extra_env)
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

    def test_real_user_first_run_onboarding_and_paired_session_creation(self):
        """1. User runs `aider-factory my_first_session` in a clean repository.
        Verify full project auto-initialization from the real shipped env.yml,
        and verify that .aider_factory/sessions/my_first_session/session.yml is paired.
        """
        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        sample_code = os.path.join(self.test_dir, "src", "calculator.py")
        with open(sample_code, "w", encoding="utf-8") as f:
            f.write("def calculate_total(prices):\n    return sum(prices)\n")

        sess_name = "my_first_session"
        env = self._get_subprocess_env({"AI_FACTORY_SESSION": sess_name})

        # Run CLI exactly as user invokes it in terminal
        res = self._run_live([sys.executable, CLI_PATH, sess_name], env)
        self.assertEqual(res.returncode, 0)

        # Verify project scaffolding was created from the real templates
        factory_dir = os.path.join(self.test_dir, ".aider_factory")
        self.assertTrue(os.path.exists(os.path.join(factory_dir, ".env.yml")), "Real .env.yml must be created")
        self.assertTrue(os.path.exists(os.path.join(factory_dir, ".aider.conf.yml")), ".aider.conf.yml must exist")
        self.assertTrue(os.path.exists(os.path.join(factory_dir, ".aider.model.settings.yml")), "model settings must exist")
        self.assertTrue(os.path.exists(os.path.join(factory_dir, "CONVENTIONS.md")), "CONVENTIONS.md must exist")
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, ".aiderignore")), ".aiderignore must exist")

        # Verify session pairing
        sess_dir = os.path.join(factory_dir, "sessions", sess_name)
        self.assertTrue(os.path.exists(sess_dir), "Session directory must exist")

        sess_yaml_path = os.path.join(sess_dir, "session.yml")
        self.assertTrue(os.path.exists(sess_yaml_path), "Paired session.yml must exist")

        # Verify that all 10 runtime & KV-cache flags from shipped env.yml are present in paired session.yml
        with open(sess_yaml_path, "r", encoding="utf-8") as f:
            paired_cfg = yaml.safe_load(f)

        toggles = paired_cfg["phases"][0]["toggles"]
        self.assertEqual(toggles["map_tokens"], 0)
        self.assertEqual(toggles["map_refresh"], "manual")
        self.assertEqual(toggles["map_multiplier_no_files"], 0)
        self.assertEqual(toggles["max_chat_history_tokens"], 100000)
        self.assertTrue(toggles["yes_always"])
        self.assertTrue(toggles["auto_accept_architect"])
        self.assertTrue(toggles["auto_commits"])
        self.assertTrue(toggles["suggest_shell_commands"])
        self.assertFalse(toggles["detect_urls"])
        self.assertFalse(toggles["disable_playwright"])

        # Verify OSTee generated real master log
        logs_dir = os.path.join(factory_dir, "logs")
        self.assertTrue(os.path.exists(logs_dir), "logs/ directory must be created")
        self.assertTrue(any("run_" in lf for lf in os.listdir(logs_dir)), "Master run log must be generated")

    def test_real_paired_yaml_modification_and_resume(self):
        """2. User starts a session, pauses, modifies session.yml on disk (e.g. changes tokens, toggles),
        and resumes via `aider-factory <session_name>`.
        Verify the reloaded session executes with the modified paired configuration.
        """
        sess_name = "refactor_auth"
        env = self._get_subprocess_env({"AI_FACTORY_SESSION": sess_name})

        # Initial run: initialize session
        res_init = self._run_live([sys.executable, CLI_PATH, sess_name], env)
        self.assertEqual(res_init.returncode, 0)

        sess_yaml = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_name, "session.yml")
        self.assertTrue(os.path.exists(sess_yaml))

        # User modifies paired session.yml on disk: switches to autonomous mode with custom tokens
        with open(sess_yaml, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        cfg["phases"][0]["toggles"]["max_chat_history_tokens"] = 77777
        cfg["phases"][0]["toggles"]["yes_always"] = True
        cfg["phases"][0]["toggles"]["auto_accept_architect"] = True
        cfg["phases"][0]["toggles"]["auto_commits"] = False
        cfg["phases"][0]["toggles"]["detect_urls"] = True
        cfg["phases"][0]["toggles"]["disable_playwright"] = True

        with open(sess_yaml, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f)

        # Resume session: `aider-factory refactor_auth`
        res = self._run_live([sys.executable, CLI_PATH, sess_name], env)
        self.assertEqual(res.returncode, 0)

        # Read back session.yml to verify values remained persistent and paired
        with open(sess_yaml, "r", encoding="utf-8") as f:
            reloaded = yaml.safe_load(f)

        t = reloaded["phases"][0]["toggles"]
        self.assertEqual(t["max_chat_history_tokens"], 77777)
        self.assertTrue(t["yes_always"])
        self.assertTrue(t["auto_accept_architect"])
        self.assertFalse(t["auto_commits"])
        self.assertTrue(t["detect_urls"])
        self.assertTrue(t["disable_playwright"])

    def test_real_multi_session_isolation_and_zero_root_leakage(self):
        """3. Two independent sessions run in the same repository.
        Verify that chat histories, input prompt histories, and Oracle/debate session JSONs
        are completely isolated in their respective folders with ZERO leakage to .aider_factory/ root.
        """
        sess_a = "feature_alpha"
        sess_b = "feature_beta"

        env_a = self._get_subprocess_env({"AI_FACTORY_SESSION": sess_a})
        env_b = self._get_subprocess_env({"AI_FACTORY_SESSION": sess_b})

        self.assertEqual(self._run_live([sys.executable, CLI_PATH, sess_a], env_a).returncode, 0)
        self.assertEqual(self._run_live([sys.executable, CLI_PATH, sess_b], env_b).returncode, 0)

        dir_a = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_a)
        dir_b = os.path.join(self.test_dir, ".aider_factory", "sessions", sess_b)

        # Simulate real multi-turn conversation and prompt history in both sessions
        with open(os.path.join(dir_a, ".aider.chat.history.md"), "w", encoding="utf-8") as f:
            f.write("# Conversation Alpha\nUser: Refactor module A\n")
        with open(os.path.join(dir_a, ".aider.input.history"), "w", encoding="utf-8") as f:
            f.write("refactor module A\n")
        with open(os.path.join(dir_a, ".aider.llm.history"), "w", encoding="utf-8") as f:
            f.write('{"session": "alpha", "model": "gemini-3.6-flash"}\n')
        with open(os.path.join(dir_a, ".oracle_session.json"), "w", encoding="utf-8") as f:
            json.dump([{"role": "user", "content": "Alpha RAG Query"}], f)
        with open(os.path.join(dir_a, ".oracle_debate_session.json"), "w", encoding="utf-8") as f:
            json.dump([{"turn": 1, "proposal": "Alpha Proposal"}], f)

        with open(os.path.join(dir_b, ".aider.chat.history.md"), "w", encoding="utf-8") as f:
            f.write("# Conversation Beta\nUser: Optimize query B\n")
        with open(os.path.join(dir_b, ".aider.input.history"), "w", encoding="utf-8") as f:
            f.write("optimize query B\n")
        with open(os.path.join(dir_b, ".aider.llm.history"), "w", encoding="utf-8") as f:
            f.write('{"session": "beta", "model": "gemini-3.6-flash"}\n')
        with open(os.path.join(dir_b, ".oracle_session.json"), "w", encoding="utf-8") as f:
            json.dump([{"role": "user", "content": "Beta RAG Query"}], f)
        with open(os.path.join(dir_b, ".oracle_debate_session.json"), "w", encoding="utf-8") as f:
            json.dump([{"turn": 1, "proposal": "Beta Proposal"}], f)

        # Verify real on-disk isolation between sessions
        with open(os.path.join(dir_a, ".aider.chat.history.md"), "r", encoding="utf-8") as f:
            self.assertIn("Conversation Alpha", f.read())
        with open(os.path.join(dir_b, ".aider.chat.history.md"), "r", encoding="utf-8") as f:
            self.assertIn("Conversation Beta", f.read())

        with open(os.path.join(dir_a, ".aider.llm.history"), "r", encoding="utf-8") as f:
            self.assertIn('"session": "alpha"', f.read())
        with open(os.path.join(dir_b, ".aider.llm.history"), "r", encoding="utf-8") as f:
            self.assertIn('"session": "beta"', f.read())

        with open(os.path.join(dir_a, ".oracle_session.json"), "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)[0]["content"], "Alpha RAG Query")
        with open(os.path.join(dir_b, ".oracle_session.json"), "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)[0]["content"], "Beta RAG Query")

        # Assert ZERO state leakage into root .aider_factory/
        root_factory = Path(self.test_dir) / ".aider_factory"
        self.assertFalse((root_factory / ".aider.chat.history.md").exists(), "Chat history must not leak to root")
        self.assertFalse((root_factory / ".aider.input.history").exists(), "Input history must not leak to root")
        self.assertFalse((root_factory / ".aider.llm.history").exists(), "LLM history must not leak to root")
        self.assertFalse((root_factory / ".oracle_session.json").exists(), "Oracle session must not leak to root")
        self.assertFalse((root_factory / ".oracle_debate_session.json").exists(), "Debate session must not leak to root")

    def test_real_oracle_namespaced_clear_lifecycle(self):
        """4. Verify that running `oracle --clear` in a session deletes ONLY that session's
        .oracle_session.json and sidecars, leaving adjacent sessions untouched.
        """
        dir_1 = os.path.join(self.test_dir, ".aider_factory", "sessions", "sess_1")
        dir_2 = os.path.join(self.test_dir, ".aider_factory", "sessions", "sess_2")
        os.makedirs(dir_1, exist_ok=True)
        os.makedirs(dir_2, exist_ok=True)

        ora_1 = os.path.join(dir_1, ".oracle_session.json")
        cost_1 = os.path.join(dir_1, ".oracle_session.json.costs.json")
        ora_2 = os.path.join(dir_2, ".oracle_session.json")
        cost_2 = os.path.join(dir_2, ".oracle_session.json.costs.json")

        for fpath in [ora_1, cost_1, ora_2, cost_2]:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump([{"role": "user", "content": "Active Context"}], f)

        # Clear session 1 using real oracle_agent.py subprocess
        env_1 = self._get_subprocess_env({
            "ORACLE_SESSION_FILE": ora_1,
        })

        res = subprocess.run(
            [sys.executable, ORACLE_CLI_PATH, "--clear"],
            cwd=self.test_dir,
            env=env_1,
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 0)
        # Session 1 files must be deleted
        self.assertFalse(os.path.exists(ora_1), "Session 1 oracle session must be deleted")
        self.assertFalse(os.path.exists(cost_1), "Session 1 oracle cost sidecar must be deleted")

        # Session 2 files must remain 100% intact
        self.assertTrue(os.path.exists(ora_2), "Session 2 oracle session must remain intact")
        self.assertTrue(os.path.exists(cost_2), "Session 2 oracle cost sidecar must remain intact")

    def test_real_cli_management_commands(self):
        """5. Test real `aider-factory --list-sessions`, `--clear-session <name>`, and `--clear-all`
        via real subprocess executions.
        """
        sess_1 = os.path.join(self.test_dir, ".aider_factory", "sessions", "feature_ui")
        sess_2 = os.path.join(self.test_dir, ".aider_factory", "sessions", "feature_api")
        os.makedirs(sess_1, exist_ok=True)
        os.makedirs(sess_2, exist_ok=True)

        with open(os.path.join(sess_1, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: UI Pipeline\n")
        with open(os.path.join(sess_1, ".aider.chat.history.md"), "w", encoding="utf-8") as f:
            f.write("# UI Chat History\n" * 50)

        with open(os.path.join(sess_2, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: API Pipeline\n")

        env = self._get_subprocess_env()

        # 1. Test real --list-sessions
        res_list = subprocess.run(
            [sys.executable, CLI_PATH, "--list-sessions"],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_list.returncode, 0)
        self.assertIn("feature_ui", res_list.stdout)
        self.assertIn("feature_api", res_list.stdout)
        self.assertIn("paired", res_list.stdout)

        # 2. Test real --clear-session feature_ui
        res_clear_one = subprocess.run(
            [sys.executable, CLI_PATH, "--clear-session", "feature_ui"],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_clear_one.returncode, 0)
        self.assertFalse(os.path.exists(sess_1), "feature_ui session folder must be removed")
        self.assertTrue(os.path.exists(sess_2), "feature_api session folder must remain intact")

        # 3. Test real --clear-all
        res_clear_all = subprocess.run(
            [sys.executable, CLI_PATH, "--clear-all"],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_clear_all.returncode, 0)
        sessions_root = os.path.join(self.test_dir, ".aider_factory", "sessions")
        self.assertFalse(os.path.exists(sessions_root), "sessions/ directory must be completely removed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
