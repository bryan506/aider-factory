#!/usr/bin/env python3
# test_e2e_workspace_isolation.py — Zero-Mock Multi-Workspace State & Session Isolation Test Suite.

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

script_dir = os.path.dirname(os.path.abspath(__file__))
cli_script = os.path.abspath(os.path.join(script_dir, "../../../cli.py"))
python_dir = os.path.abspath(os.path.join(script_dir, "../../../python"))

sys.path.insert(0, python_dir)
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../../..")))


def _get_clean_env(extra_env=None):
    env = os.environ.copy()
    for k in list(env.keys()):
        if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
            env.pop(k, None)
    if extra_env:
        env.update(extra_env)
    return env


class TestE2EWorkspaceIsolation(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_root.name)
        self.ws_a = self.root_path / "Workspace_Alpha"
        self.ws_b = self.root_path / "Workspace_Beta"
        self.config_dir = self.root_path / "global_config"
        self.ws_a.mkdir()
        self.ws_b.mkdir()
        self.config_dir.mkdir()

        self.env = _get_clean_env({
            "XDG_CONFIG_HOME": str(self.config_dir),
            "HOME": str(self.root_path),
            "AIDER_HELPER_API_BASE": "http://127.0.0.1:9999/v1",
            "OPENAI_API_KEY": "sk-dummy",
        })

    def tearDown(self):
        self.temp_root.cleanup()

    def test_e2e_two_workspaces_complete_isolation(self):
        """Zero-mock verification: 2 distinct workspaces initialize and maintain separate files, sessions, and configs."""
        # 1. Initialize Workspace Alpha with unique file
        (self.ws_a / "alpha_feature.py").write_text("def alpha_logic(): pass\n", encoding="utf-8")
        proc_a = subprocess.run(
            [sys.executable, cli_script, "--repo-map"],
            cwd=str(self.ws_a),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_a.returncode, 0, f"Alpha init failed: {proc_a.stderr}")

        # 2. Initialize Workspace Beta with unique file
        (self.ws_b / "beta_feature.py").write_text("def beta_logic(): pass\n", encoding="utf-8")
        proc_b = subprocess.run(
            [sys.executable, cli_script, "--repo-map"],
            cwd=str(self.ws_b),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_b.returncode, 0, f"Beta init failed: {proc_b.stderr}")

        # 3. Assert Workspace Alpha's configuration contains only Alpha's target files
        env_a = (self.ws_a / ".aider_factory" / ".env.yml").read_text(encoding="utf-8")
        self.assertIn("alpha_feature.py", env_a)
        self.assertNotIn("beta_feature.py", env_a)

        # 4. Assert Workspace Beta's configuration contains only Beta's target files
        env_b = (self.ws_b / ".aider_factory" / ".env.yml").read_text(encoding="utf-8")
        self.assertIn("beta_feature.py", env_b)
        self.assertNotIn("alpha_feature.py", env_b)

        # 5. Assert static repo maps are isolated
        repo_map_a = (self.ws_a / ".aider_factory" / "static_repo_map.md").read_text(encoding="utf-8")
        repo_map_b = (self.ws_b / ".aider_factory" / "static_repo_map.md").read_text(encoding="utf-8")
        self.assertIn("alpha_feature.py", repo_map_a)
        self.assertNotIn("beta_feature.py", repo_map_a)
        self.assertIn("beta_feature.py", repo_map_b)
        self.assertNotIn("alpha_feature.py", repo_map_b)

    def test_e2e_workspace_session_clear_isolation(self):
        """Clearing sessions in Workspace Alpha does not modify or delete sessions in Workspace Beta."""
        # Setup fake session directories in Alpha and Beta
        sess_a = self.ws_a / ".aider_factory" / "sessions" / "session_alpha_123"
        sess_b = self.ws_b / ".aider_factory" / "sessions" / "session_beta_456"
        sess_a.mkdir(parents=True, exist_ok=True)
        sess_b.mkdir(parents=True, exist_ok=True)
        (sess_a / "session.yml").write_text("name: Alpha Session\n", encoding="utf-8")
        (sess_b / "session.yml").write_text("name: Beta Session\n", encoding="utf-8")

        # Clear session in Alpha
        proc = subprocess.run(
            [sys.executable, cli_script, "--clear-session", "session_alpha_123", "--forever"],
            cwd=str(self.ws_a),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)

        # Assert Alpha session is removed, Beta session remains intact
        self.assertFalse(sess_a.exists(), "Alpha session must be deleted")
        self.assertTrue(sess_b.exists(), "Beta session must remain untouched")
        self.assertTrue((sess_b / "session.yml").exists(), "Beta session configuration must be preserved")

    def test_e2e_workspace_side_session_isolation(self):
        """Side-agent sessions (.helper_session.json, .oracle_session.json) are strictly isolated per workspace."""
        af_a = self.ws_a / ".aider_factory"
        af_b = self.ws_b / ".aider_factory"
        af_a.mkdir(parents=True, exist_ok=True)
        af_b.mkdir(parents=True, exist_ok=True)

        helper_a = af_a / ".helper_session.json"
        helper_b = af_b / ".helper_session.json"
        helper_a.write_text(json.dumps([{"role": "user", "content": "Alpha question"}]), encoding="utf-8")
        helper_b.write_text(json.dumps([{"role": "user", "content": "Beta question"}]), encoding="utf-8")

        # Clear helper session from Alpha
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.argv=['aider-helper', '--clear']; from aider_factory.cli import helper_cli; helper_cli()",
            ],
            cwd=str(self.ws_a),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)

        # Alpha helper session is removed; Beta helper session remains intact
        self.assertFalse(helper_a.exists(), "Alpha helper session must be deleted")
        self.assertTrue(helper_b.exists(), "Beta helper session must be preserved")
        self.assertIn("Beta question", helper_b.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
