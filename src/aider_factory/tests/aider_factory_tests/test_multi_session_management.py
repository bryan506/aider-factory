#!/usr/bin/env python3
"""test_multi_session_management.py — Unit and integration tests for aider-factory
named multi-session management and paired configuration synchronization.
"""

import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, pkg_dir)
sys.path.insert(0, os.path.join(pkg_dir, "aider_factory"))
sys.path.insert(0, os.path.join(pkg_dir, "aider_factory", "python"))

import cli
import orchestrate
from orchestrate import AiderFactory, Task


class TestCLISessionParsing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        for k in ["AI_FACTORY_SESSION", "AI_FACTORY_CONFIG"]:
            os.environ.pop(k, None)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        for k in ["AI_FACTORY_SESSION", "AI_FACTORY_CONFIG"]:
            os.environ.pop(k, None)

    @patch("runpy.run_path")
    @patch("cli.init_user_project")
    @patch("cli.ensure_aider_installed")
    def test_cli_positional_session_only(self, mock_inst, mock_init, mock_run):
        with patch.object(sys, "argv", ["aider-factory", "refactor_ohlcv"]):
            cli.main()
        self.assertEqual(os.environ.get("AI_FACTORY_SESSION"), "refactor_ohlcv")
        self.assertIsNone(os.environ.get("AI_FACTORY_CONFIG"))

    @patch("runpy.run_path")
    @patch("cli.init_user_project")
    @patch("cli.ensure_aider_installed")
    def test_cli_config_and_session_args(self, mock_inst, mock_init, mock_run):
        with open("custom.yml", "w", encoding="utf-8") as f:
            f.write("name: test\n")
        with patch.object(sys, "argv", ["aider-factory", "custom.yml", "my_session"]):
            cli.main()
        self.assertEqual(os.environ.get("AI_FACTORY_SESSION"), "my_session")
        self.assertEqual(os.environ.get("AI_FACTORY_CONFIG"), "custom.yml")

    @patch("runpy.run_path")
    @patch("cli.init_user_project")
    @patch("cli.ensure_aider_installed")
    def test_cli_session_flag(self, mock_inst, mock_init, mock_run):
        with patch.object(sys, "argv", ["aider-factory", "--session", "flag_session"]):
            cli.main()
        self.assertEqual(os.environ.get("AI_FACTORY_SESSION"), "flag_session")

    @patch("runpy.run_path")
    @patch("cli.init_user_project")
    @patch("cli.ensure_aider_installed")
    def test_cli_session_short_flag(self, mock_inst, mock_init, mock_run):
        with patch.object(sys, "argv", ["aider-factory", "-s", "short_session"]):
            cli.main()
        self.assertEqual(os.environ.get("AI_FACTORY_SESSION"), "short_session")


class TestCLISessionManagement(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_session_listing_empty(self):
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            cli._list_sessions(self.temp_dir)
        output = captured.getvalue()
        self.assertIn("No active sessions found.", output)

    def test_session_listing_and_clearing(self):
        sess_dir_a = os.path.join(self.temp_dir, ".aider_factory", "sessions", "session_a")
        sess_dir_b = os.path.join(self.temp_dir, ".aider_factory", "sessions", "session_b")
        os.makedirs(sess_dir_a, exist_ok=True)
        os.makedirs(sess_dir_b, exist_ok=True)

        with open(os.path.join(sess_dir_a, ".aider.chat.history.md"), "w", encoding="utf-8") as f:
            f.write("# History\n" * 100)
        with open(os.path.join(sess_dir_a, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: test_a\n")

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            cli._list_sessions(self.temp_dir)
        output = captured.getvalue()
        self.assertIn("session_a", output)
        self.assertIn("session_b", output)
        self.assertIn("paired", output)

        # Clear session_a
        cli._clear_session(self.temp_dir, "session_a")
        self.assertFalse(os.path.exists(sess_dir_a))
        self.assertTrue(os.path.exists(sess_dir_b))

        # Clear all
        cli._clear_all_sessions(self.temp_dir)
        sess_root = os.path.join(self.temp_dir, ".aider_factory", "sessions")
        self.assertFalse(os.path.exists(sess_root))


class TestOrchestratorSessionRouting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_factory_initialization_defaults(self):
        factory = AiderFactory(self.temp_dir)
        self.assertEqual(factory.session_name, "default")
        expected_dir = Path(self.temp_dir) / ".aider_factory" / "sessions" / "default"
        self.assertEqual(factory.session_dir, expected_dir)
        self.assertTrue(factory.session_dir.exists())

    def test_factory_initialization_custom_session(self):
        factory = AiderFactory(self.temp_dir, session_name="feature_auth")
        self.assertEqual(factory.session_name, "feature_auth")
        expected_dir = Path(self.temp_dir) / ".aider_factory" / "sessions" / "feature_auth"
        self.assertEqual(factory.session_dir, expected_dir)
        self.assertTrue(factory.session_dir.exists())

    @patch("subprocess.Popen")
    def test_run_task_history_flags_and_session_routing(self, mock_popen):
        factory = AiderFactory(self.temp_dir, session_name="test_routing")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        task = Task(id="test_task", files=["src/app.py"], model="test-arch", editor_model="test-edit")
        success = factory.run_task(task)

        self.assertTrue(success)
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        chat_hist = os.path.join(str(factory.session_dir), ".aider.chat.history.md")
        input_hist = os.path.join(str(factory.session_dir), ".aider.input.history")
        llm_hist = os.path.join(str(factory.session_dir), ".aider.llm.history")

        self.assertIn("--restore-chat-history", cmd)
        self.assertIn(chat_hist, cmd)
        self.assertIn(input_hist, cmd)
        self.assertIn(llm_hist, cmd)

    @patch("subprocess.Popen")
    def test_run_task_archives_llm_history(self, mock_popen):
        """Verify that .aider.llm.history is archived to logs/llm_history/ upon task completion."""
        factory = AiderFactory(self.temp_dir, session_name="test_llm_archive")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        # Simulate Aider writing raw LLM history to session directory
        llm_hist = os.path.join(str(factory.session_dir), ".aider.llm.history")
        with open(llm_hist, "w", encoding="utf-8") as f:
            f.write('{"model": "gemini/gemini-3.6-flash", "tokens": 150}\n')

        task = Task(id="test_archive_task", files=["src/app.py"], model="test-arch", editor_model="test-edit")
        success = factory.run_task(task)
        self.assertTrue(success)

        # Verify archive directory was created and contains the archived log
        llm_hist_dir = os.path.join(self.temp_dir, ".aider_factory", "logs", "llm_history")
        self.assertTrue(os.path.exists(llm_hist_dir))
        archived_files = os.listdir(llm_hist_dir)
        self.assertEqual(len(archived_files), 1)
        self.assertTrue(archived_files[0].endswith("_test_archive_task.llm.log"))
        with open(os.path.join(llm_hist_dir, archived_files[0]), "r", encoding="utf-8") as f:
            self.assertIn("gemini-3.6-flash", f.read())

    @patch("subprocess.Popen")
    def test_aider_ask_turn_history_flags(self, mock_popen):
        factory = AiderFactory(self.temp_dir, session_name="test_ask")
        mock_proc = MagicMock()
        mock_proc.stdout.read.side_effect = ["P", "R", "O", "P", "O", "S", "A", "L", ":", " ", "o", "k", ""]
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        task = Task(id="ask_task", model="test-arch", editor_model="test-edit")
        out = factory._aider_ask_turn(task, "Test query", [])

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[1]["cmd"] if "cmd" in mock_popen.call_args[1] else mock_popen.call_args[0][0]
        chat_hist = os.path.join(str(factory.session_dir), ".aider.chat.history.md")
        input_hist = os.path.join(str(factory.session_dir), ".aider.input.history")
        llm_hist = os.path.join(str(factory.session_dir), ".aider.llm.history")

        self.assertIn("--restore-chat-history", cmd)
        self.assertIn(chat_hist, cmd)
        self.assertIn(input_hist, cmd)
        self.assertIn(llm_hist, cmd)

    @patch("subprocess.Popen")
    def test_task_runtime_flags_cli_generation(self, mock_popen):
        """Verify Task runtime & KV-cache flags are correctly formatted as CLI arguments."""
        factory = AiderFactory(self.temp_dir, session_name="test_flags")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        # Test Case 1: Pair mode with negative overrides
        task_pair = Task(
            id="task_pair",
            files=["src/app.py"],
            map_tokens=0,
            map_refresh="manual",
            map_multiplier_no_files=0,
            max_chat_history_tokens=90000,
            yes_always=False,
            auto_accept_architect=False,
            auto_commits=True,
            suggest_shell_commands=True,
            detect_urls=False,
            disable_playwright=False,
        )
        factory.run_task(task_pair)
        cmd_pair = mock_popen.call_args[0][0]

        self.assertIn("--map-tokens", cmd_pair)
        self.assertIn("0", cmd_pair)
        self.assertIn("--map-refresh", cmd_pair)
        self.assertIn("manual", cmd_pair)
        self.assertIn("--map-multiplier-no-files", cmd_pair)
        self.assertIn("0", cmd_pair)
        self.assertIn("--max-chat-history-tokens", cmd_pair)
        self.assertIn("90000", cmd_pair)
        self.assertIn("--no-auto-accept-architect", cmd_pair)
        self.assertIn("--auto-commits", cmd_pair)
        self.assertIn("--suggest-shell-commands", cmd_pair)
        self.assertIn("--no-detect-urls", cmd_pair)
        self.assertNotIn("--yes-always", cmd_pair)
        self.assertNotIn("--disable-playwright", cmd_pair)

        mock_popen.reset_mock()

        # Test Case 2: Autonomous mode overrides
        task_auto = Task(
            id="task_auto",
            files=["src/app.py"],
            yes_always=True,
            auto_accept_architect=True,
            auto_commits=False,
            suggest_shell_commands=False,
            detect_urls=True,
            disable_playwright=True,
        )
        factory.run_task(task_auto)
        cmd_auto = mock_popen.call_args[0][0]

        self.assertIn("--yes-always", cmd_auto)
        self.assertIn("--auto-accept-architect", cmd_auto)
        self.assertIn("--no-auto-commits", cmd_auto)
        self.assertIn("--no-suggest-shell-commands", cmd_auto)
        self.assertIn("--detect-urls", cmd_auto)
        self.assertIn("--disable-playwright", cmd_auto)


if __name__ == "__main__":
    unittest.main()
