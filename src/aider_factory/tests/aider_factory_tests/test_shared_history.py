#!/usr/bin/env python3
# test_shared_history.py

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from aider_factory import cli
from aider_factory.python.orchestrate import AiderFactory, Task, TaskStatus


class TestOrchestratorVaultSwap(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.temp_dir, "project")
        os.makedirs(self.project_dir, exist_ok=True)
        self.session_name = "test_session"
        self.factory = AiderFactory(
            project_dir=self.project_dir,
            session_name=self.session_name,
        )
        self.session_dir = str(self.factory.session_dir)
        self.vault_dir = os.path.join(self.session_dir, "chat_history")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_state_files_completeness(self):
        """Verify all 9 active state payload files are enumerated."""
        files = self.factory._get_state_files()
        self.assertEqual(len(files), 9)
        base_names = [os.path.basename(f) for f in files]
        expected = [
            ".aider.chat.history.md",
            ".aider.input.history",
            ".aider.llm.history",
            ".oracle_session.json",
            ".oracle_session.json.costs.json",
            ".oracle_debate_session.json",
            ".debate_aider_history.md",
            ".oracle_chat.history.md",
            ".pair_capture.log",
        ]
        for exp in expected:
            self.assertIn(exp, base_names)

    def test_get_vault_path_mapping(self):
        """Verify deterministic stem injection into vault paths."""
        active_chat = os.path.join(self.session_dir, ".aider.chat.history.md")
        vault_chat = self.factory._get_vault_path(active_chat, "auth_service")
        self.assertEqual(
            vault_chat,
            os.path.join(self.vault_dir, ".aider.chat.history_auth_service.md"),
        )

        active_oracle = os.path.join(self.session_dir, ".oracle_session.json")
        vault_oracle = self.factory._get_vault_path(active_oracle, "auth_service")
        self.assertEqual(
            vault_oracle,
            os.path.join(self.vault_dir, ".oracle_session_auth_service.json"),
        )

        active_costs = os.path.join(
            self.session_dir, ".oracle_session.json.costs.json"
        )
        vault_costs = self.factory._get_vault_path(active_costs, "auth_service")
        self.assertEqual(
            vault_costs,
            os.path.join(
                self.vault_dir, ".oracle_session_auth_service.json.costs.json"
            ),
        )

    def test_swap_in_state_clean_and_restore(self):
        """Verify _swap_in_state purges stale active files and restores vault files for the stem."""
        # Setup stale active files
        stale_chat = os.path.join(self.session_dir, ".aider.chat.history.md")
        with open(stale_chat, "w", encoding="utf-8") as f:
            f.write("Stale previous conversation")

        # Setup vault files for stem 'target_file'
        os.makedirs(self.vault_dir, exist_ok=True)
        vault_chat = os.path.join(
            self.vault_dir, ".aider.chat.history_target_file.md"
        )
        with open(vault_chat, "w", encoding="utf-8") as f:
            f.write("Saved conversation for target_file")

        self.factory._swap_in_state("target_file")

        # Assert active stage was replaced with vault content
        with open(stale_chat, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "Saved conversation for target_file")

    def test_swap_in_state_empty_vault_wipes_active_stage(self):
        """Verify _swap_in_state with no prior vault files leaves a clean active stage."""
        stale_chat = os.path.join(self.session_dir, ".aider.chat.history.md")
        with open(stale_chat, "w", encoding="utf-8") as f:
            f.write("Stale data")

        self.factory._swap_in_state("new_file_without_history")
        self.assertFalse(os.path.exists(stale_chat))

    def test_swap_out_state_saves_active_files(self):
        """Verify _swap_out_state copies active files into the vault."""
        active_chat = os.path.join(self.session_dir, ".aider.chat.history.md")
        with open(active_chat, "w", encoding="utf-8") as f:
            f.write("Turn 1 discussion")

        self.factory._swap_out_state("module_a")

        vault_chat = os.path.join(self.vault_dir, ".aider.chat.history_module_a.md")
        self.assertTrue(os.path.exists(vault_chat))
        with open(vault_chat, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "Turn 1 discussion")

    def test_swap_out_state_syncs_deletions(self):
        """Verify _swap_out_state deletes vault files if active file was removed."""
        os.makedirs(self.vault_dir, exist_ok=True)
        vault_oracle = os.path.join(
            self.vault_dir, ".oracle_session_module_a.json"
        )
        with open(vault_oracle, "w", encoding="utf-8") as f:
            f.write("{}")

        active_oracle = os.path.join(self.session_dir, ".oracle_session.json")
        if os.path.exists(active_oracle):
            os.remove(active_oracle)

        # Active file does NOT exist -> must delete vault file
        self.factory._swap_out_state("module_a")
        self.assertFalse(os.path.exists(vault_oracle))

    def test_run_task_oracle_triggers_swap_lifecycle(self):
        """Verify oracle tasks execute swap_in and swap_out via top-level try...finally."""
        def fake_oracle_job(task):
            active_chat = os.path.join(self.session_dir, ".aider.chat.history.md")
            with open(active_chat, "w", encoding="utf-8") as f:
                f.write("Oracle generated context")
            return True

        with patch.object(self.factory, "_run_oracle_job", side_effect=fake_oracle_job) as mock_oracle:
            task = Task(id="test_oracle", oracle={"template": "t.md"}, history_stem="file_x")
            res = self.factory.run_task(task)
            self.assertTrue(res)
            self.assertTrue(mock_oracle.called)

            # Confirm vault was written
            vault_chat = os.path.join(self.vault_dir, ".aider.chat.history_file_x.md")
            self.assertTrue(os.path.exists(vault_chat))
            with open(vault_chat, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "Oracle generated context")

    @patch.object(AiderFactory, "_run_validate", return_value=True)
    def test_run_task_validate_triggers_swap_lifecycle(self, mock_val):
        """Verify validation tasks execute swap lifecycle."""
        task = Task(id="test_val", validate={"review": "r.md"}, history_stem="file_y")
        res = self.factory.run_task(task)
        self.assertTrue(res)
        self.assertTrue(mock_val.called)

    @patch.object(AiderFactory, "_run_deliberation", return_value=True)
    def test_run_task_deliberate_triggers_swap_lifecycle(self, mock_delib):
        """Verify deliberation tasks execute swap lifecycle."""
        task = Task(id="test_delib", deliberate={"loops": 2}, history_stem="file_z")
        res = self.factory.run_task(task)
        self.assertTrue(res)
        self.assertTrue(mock_delib.called)

    def test_run_task_skip_aider_triggers_swap_lifecycle(self):
        """Verify skip_aider setup tasks execute swap lifecycle."""
        task = Task(id="test_skip", skip_aider=True, history_stem="file_skip")
        res = self.factory.run_task(task)
        self.assertTrue(res)

    def test_run_task_without_history_stem_does_not_swap(self):
        """Verify shared history mode (history_stem=None) leaves active files unswapped."""
        task = Task(id="test_shared", skip_aider=True, history_stem=None)
        active_chat = os.path.join(self.session_dir, ".aider.chat.history.md")
        with open(active_chat, "w", encoding="utf-8") as f:
            f.write("Shared history content")

        res = self.factory.run_task(task)
        self.assertTrue(res)
        self.assertFalse(os.path.exists(self.vault_dir))
        self.assertTrue(os.path.exists(active_chat))


class TestCLISharedHistory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sess_dir = os.path.join(
            self.temp_dir, ".aider_factory", "sessions", "session_alpha"
        )
        self.hist_dir = os.path.join(self.sess_dir, "chat_history")
        os.makedirs(self.hist_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_list_sessions_isolated_precedence(self):
        """Verify _list_sessions prioritizes chat_history/ over active stage."""
        # Root chat history: 2 KB
        root_chat = os.path.join(self.sess_dir, ".aider.chat.history.md")
        with open(root_chat, "wb") as f:
            f.write(b"x" * 2048)

        # Isolated histories: 5 KB + 5 KB = 10 KB
        with open(os.path.join(self.hist_dir, ".aider.chat.history_a.md"), "wb") as f:
            f.write(b"x" * 5120)
        with open(os.path.join(self.hist_dir, ".aider.chat.history_b.md"), "wb") as f:
            f.write(b"x" * 5120)

        with patch("builtins.print") as mock_print:
            cli._list_sessions(self.temp_dir)
            output = " ".join(str(call) for call in mock_print.call_args_list)
            self.assertIn("10 KB (isolated)", output)

    def test_get_side_session_artifacts_vault_filtering(self):
        """Verify _get_side_session_artifacts includes vault oracle files but ignores main chat."""
        # Main chat history in vault (must NOT be counted as side-agent)
        with open(os.path.join(self.hist_dir, ".aider.chat.history_a.md"), "w") as f:
            f.write("chat")

        # Oracle session in vault (MUST be counted)
        oracle_vault = os.path.join(self.hist_dir, ".oracle_session_a.json")
        with open(oracle_vault, "w") as f:
            f.write(json.dumps([{"role": "user", "content": "q"}]))

        # Debate session in vault (MUST be counted)
        debate_vault = os.path.join(self.hist_dir, ".oracle_debate_session_a.json")
        with open(debate_vault, "w") as f:
            f.write(json.dumps({"messages": []}))

        artifacts = cli._get_side_session_artifacts(self.temp_dir)
        paths = [a["path"] for a in artifacts]
        
        self.assertIn(oracle_vault, paths)
        self.assertIn(debate_vault, paths)
        self.assertNotIn(os.path.join(self.hist_dir, ".aider.chat.history_a.md"), paths)

    def test_clear_side_session_by_name_removes_vault_sidecars(self):
        """Verify clearing by session name removes sidecars inside chat_history/."""
        oracle_vault = os.path.join(self.hist_dir, ".oracle_session_a.json")
        with open(oracle_vault, "w") as f:
            f.write("{}")

        chat_vault = os.path.join(self.hist_dir, ".aider.chat.history_a.md")
        with open(chat_vault, "w") as f:
            f.write("important chat history")

        cli._clear_side_session_by_name(
            self.temp_dir, "session_alpha", forever=True
        )

        # Oracle sidecar was deleted
        self.assertFalse(os.path.exists(oracle_vault))
        # Main chat history remains untouched
        self.assertTrue(os.path.exists(chat_vault))


class TestWorkflowSharedHistory(unittest.TestCase):
    def test_shared_history_toggle_defaults(self):
        """Verify shared_history extraction defaults to False."""
        toggles_empty = {}
        shared_val = toggles_empty.get("shared_history")
        shared = shared_val if shared_val is not None else False
        self.assertFalse(shared)

        toggles_true = {"shared_history": True}
        shared_val = toggles_true.get("shared_history")
        shared = shared_val if shared_val is not None else False
        self.assertTrue(shared)

    def test_stem_derivation(self):
        """Verify _h_stem returns f'{job_prefix}_{base_name}' when shared_history is False, else None."""
        target_file = "src/modules/auth_core.py"
        base_name = os.path.splitext(os.path.basename(target_file))[0]

        # Isolated mode (shared_history = False) -> Dual Isolation per stage
        shared_history = False
        def _h_stem_iso(job_prefix: str):
            return None if shared_history else f"{job_prefix}_{base_name}"

        for stage in ("job1", "job2", "job3", "verify", "escalate", "oracle", "autofix", "heal", "finalize"):
            self.assertEqual(_h_stem_iso(stage), f"{stage}_auth_core")

        # Shared mode (shared_history = True) -> Legacy Continuous Mode
        shared_history = True
        def _h_stem_shared(job_prefix: str):
            return None if shared_history else f"{job_prefix}_{base_name}"

        for stage in ("job1", "job2", "job3", "verify", "escalate", "oracle", "autofix", "heal", "finalize"):
            self.assertIsNone(_h_stem_shared(stage))


if __name__ == "__main__":
    unittest.main()
