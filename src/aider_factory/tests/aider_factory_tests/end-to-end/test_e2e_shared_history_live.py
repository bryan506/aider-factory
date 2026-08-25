#!/usr/bin/env python3
# test_e2e_shared_history_live.py

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import yaml

cur_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.abspath(os.path.join(cur_dir, "../../../python"))
if python_dir not in sys.path:
    sys.path.insert(0, python_dir)
src_dir = os.path.abspath(os.path.join(cur_dir, "../../../.."))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from aider_factory.python.orchestrate import AiderFactory, Task


class TestE2ESharedHistoryLive(unittest.TestCase):
    """Zero-Mock Live End-to-End Test Suite for Shared History & Session State Isolation."""

    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.ws_dir = os.path.join(self.temp_root, "workspace")
        self.af_dir = os.path.join(self.ws_dir, ".aider_factory")
        self.sessions_dir = os.path.join(self.af_dir, "sessions")

        os.makedirs(self.sessions_dir, exist_ok=True)

        # Resolve paths to real entrypoints
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        self.cli_script = os.path.abspath(os.path.join(cur_dir, "../../../cli.py"))
        self.workflow_script = os.path.abspath(
            os.path.join(cur_dir, "../../../python/run_workflow.py")
        )
        src_dir = os.path.abspath(os.path.join(cur_dir, "../../../.."))

        # Set up a clean subprocess environment
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = src_dir
        for k in list(self.env.keys()):
            if (
                k.startswith("AI_FACTORY_")
                or k.startswith("ORACLE_")
                or k.startswith("AIDER_")
            ):
                self.env.pop(k, None)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _run_cmd(self, cmd: list[str], cwd: str = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=cwd or self.ws_dir,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_e2e_cli_listing_and_status_telemetry(self):
        """Live test: verify CLI session listing and status report isolated vault size."""
        # 1. Setup Session Isolated (Alpha)
        alpha_dir = os.path.join(self.sessions_dir, "alpha")
        alpha_vault = os.path.join(alpha_dir, "chat_history")
        os.makedirs(alpha_vault, exist_ok=True)
        with open(os.path.join(alpha_dir, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: alpha\n")
        # 2 x 4KB files in vault = 8KB
        with open(
            os.path.join(alpha_vault, ".aider.chat.history_mod1.md"), "wb"
        ) as f:
            f.write(b"a" * 4096)
        with open(
            os.path.join(alpha_vault, ".aider.chat.history_mod2.md"), "wb"
        ) as f:
            f.write(b"b" * 4096)

        # 2. Setup Session Shared (Beta)
        beta_dir = os.path.join(self.sessions_dir, "beta")
        os.makedirs(beta_dir, exist_ok=True)
        with open(os.path.join(beta_dir, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: beta\n")
        with open(
            os.path.join(beta_dir, ".aider.chat.history.md"), "wb"
        ) as f:
            f.write(b"c" * 3072)

        # 3. Run real 'aider-factory --list-sessions'
        proc = self._run_cmd([sys.executable, self.cli_script, "--list-sessions"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("alpha", proc.stdout)
        self.assertIn("8 KB (isolated)", proc.stdout)
        self.assertIn("beta", proc.stdout)
        self.assertIn("3 KB", proc.stdout)

        # 4. Run real 'aider-factory --status'
        proc_status = self._run_cmd([sys.executable, self.cli_script, "--status"])
        self.assertEqual(proc_status.returncode, 0)
        self.assertIn("8 KB (isolated)", proc_status.stdout)
        self.assertIn("3 KB", proc_status.stdout)

    def test_e2e_cli_side_session_clearing_preserves_main_chat(self):
        """Live test: verify side-session clearing purges vault oracle files but NEVER chat history."""
        sess_dir = os.path.join(self.sessions_dir, "proj_session")
        vault_dir = os.path.join(sess_dir, "chat_history")
        os.makedirs(vault_dir, exist_ok=True)

        chat_hist = os.path.join(vault_dir, ".aider.chat.history_core.md")
        oracle_hist = os.path.join(vault_dir, ".oracle_session_core.json")
        debate_hist = os.path.join(vault_dir, ".oracle_debate_session_core.json")

        with open(chat_hist, "w", encoding="utf-8") as f:
            f.write("# Conversational memory")
        with open(oracle_hist, "w", encoding="utf-8") as f:
            f.write(json.dumps([{"role": "assistant", "content": "chunk"}]))
        with open(debate_hist, "w", encoding="utf-8") as f:
            f.write(json.dumps({"messages": []}))

        # Run clear-side-session targeting this session
        proc = self._run_cmd(
            [
                sys.executable,
                self.cli_script,
                "--clear-side-session",
                "proj_session",
                "--forever",
            ]
        )
        self.assertEqual(proc.returncode, 0)

        # Assert Oracle and Debate files are deleted from disk
        self.assertFalse(os.path.exists(oracle_hist))
        self.assertFalse(os.path.exists(debate_hist))
        # Assert Main Chat History is strictly preserved
        self.assertTrue(os.path.exists(chat_hist))

    def test_e2e_workflow_isolated_execution(self):
        """Live test: execute real multi-file workflow in isolated mode (shared_history: false)."""
        # Create target files
        f1 = os.path.join(self.ws_dir, "auth.py")
        f2 = os.path.join(self.ws_dir, "billing.py")
        with open(f1, "w", encoding="utf-8") as f:
            f.write("# auth module\n")
        with open(f2, "w", encoding="utf-8") as f:
            f.write("# billing module\n")

        # Create conventions file
        with open(
            os.path.join(self.ws_dir, "CONVENTIONS.md"), "w", encoding="utf-8"
        ) as f:
            f.write("# Conventions\n")

        config_data = {
            "name": "E2E Isolated Pipeline",
            "working_directory": self.ws_dir,
            "phases": [
                {
                    "name": "Phase Isolated",
                    "enabled": True,
                    "models": {
                        "architect_agent": "gemini/gemini-3.7-flash",
                        "editor_agent": "gemini/gemini-3.6-flash",
                    },
                    "toggles": {
                        "shared_history": False,
                        "pair_programming": False,
                        "run_job_one": False,
                        "run_job_two": False,
                        "run_job_three": False,
                        "iterate_test": False,
                    },
                    "rag": {"run_ocr_rag": True, "collection_name": "lib_docs"},
                    "files": {
                        "target_files": ["auth.py", "billing.py"],
                        "context_files_job": ["CONVENTIONS.md"],
                    },
                }
            ],
        }

        cfg_path = os.path.join(self.ws_dir, "test_config.yml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        # Run real workflow runner
        proc = self._run_cmd(
            [sys.executable, self.workflow_script, "test_config.yml", "iso_session"]
        )
        self.assertEqual(proc.returncode, 0)

        # Inspect disk: chat_history/ directory MUST exist
        session_path = os.path.join(self.sessions_dir, "iso_session")
        vault_path = os.path.join(session_path, "chat_history")
        self.assertTrue(os.path.exists(vault_path))

    def test_e2e_workflow_shared_execution(self):
        """Live test: execute real multi-file workflow in shared mode (shared_history: true)."""
        f1 = os.path.join(self.ws_dir, "mod1.py")
        f2 = os.path.join(self.ws_dir, "mod2.py")
        with open(f1, "w", encoding="utf-8") as f:
            f.write("# mod1\n")
        with open(f2, "w", encoding="utf-8") as f:
            f.write("# mod2\n")

        with open(
            os.path.join(self.ws_dir, "CONVENTIONS.md"), "w", encoding="utf-8"
        ) as f:
            f.write("# Conventions\n")

        config_data = {
            "name": "E2E Shared Pipeline",
            "working_directory": self.ws_dir,
            "phases": [
                {
                    "name": "Phase Shared",
                    "enabled": True,
                    "models": {
                        "architect_agent": "gemini/gemini-3.7-flash",
                        "editor_agent": "gemini/gemini-3.6-flash",
                    },
                    "toggles": {
                        "shared_history": True,
                        "pair_programming": False,
                        "run_job_one": False,
                        "run_job_two": False,
                        "run_job_three": False,
                        "iterate_test": False,
                    },
                    "rag": {"run_ocr_rag": True, "collection_name": "lib_shared"},
                    "files": {
                        "target_files": ["mod1.py", "mod2.py"],
                        "context_files_job": ["CONVENTIONS.md"],
                    },
                }
            ],
        }

        cfg_path = os.path.join(self.ws_dir, "shared_config.yml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        proc = self._run_cmd(
            [sys.executable, self.workflow_script, "shared_config.yml", "shared_session"]
        )
        self.assertEqual(proc.returncode, 0)

        # Inspect disk: chat_history/ directory MUST NOT exist
        session_path = os.path.join(self.sessions_dir, "shared_session")
        vault_path = os.path.join(session_path, "chat_history")
        self.assertFalse(os.path.exists(vault_path))

    def test_e2e_omitted_plans_produce_none_message_and_iterate_files(self):
        """Live test: verify that omitting plans in YAML does not inject default template paths into tasks."""
        f1 = os.path.join(self.ws_dir, "core_calc.py")
        with open(f1, "w", encoding="utf-8") as f:
            f.write("# calculation logic\n")

        with open(
            os.path.join(self.ws_dir, "CONVENTIONS.md"), "w", encoding="utf-8"
        ) as f:
            f.write("# Conventions\n")

        config_data = {
            "name": "E2E No-Plan Pipeline",
            "working_directory": self.ws_dir,
            "phases": [
                {
                    "name": "Phase No Plans",
                    "enabled": True,
                    "models": {
                        "architect_agent": "gemini/gemini-3.7-flash",
                        "editor_agent": "gemini/gemini-3.6-flash",
                    },
                    "toggles": {
                        "shared_history": False,
                        "pair_programming": False,
                        "run_job_one": False,
                        "run_job_two": False,
                        "run_job_three": False,
                        "iterate_test": False,
                    },
                    "rag": {"run_ocr_rag": True, "collection_name": "lib_docs"},
                    "files": {
                        "target_files": ["core_calc.py"],
                        "context_files_job": ["CONVENTIONS.md"],
                    },
                }
            ],
        }

        cfg_path = os.path.join(self.ws_dir, "no_plans_config.yml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        proc = self._run_cmd(
            [sys.executable, self.workflow_script, "no_plans_config.yml", "no_plan_session"]
        )
        self.assertEqual(proc.returncode, 0)

    def test_e2e_multi_file_resumption_warning(self):
        """Live test: verify stderr warning emitted when resuming multi-file isolated session."""
        sess_dir = os.path.join(self.sessions_dir, "resumed_session")
        vault_dir = os.path.join(sess_dir, "chat_history")
        os.makedirs(vault_dir, exist_ok=True)

        with open(
            os.path.join(vault_dir, ".aider.chat.history_file_a.md"), "w", encoding="utf-8"
        ) as f:
            f.write("# file a history")
        with open(
            os.path.join(vault_dir, ".aider.chat.history_file_b.md"), "w", encoding="utf-8"
        ) as f:
            f.write("# file b history")

        with open(
            os.path.join(self.ws_dir, "CONVENTIONS.md"), "w", encoding="utf-8"
        ) as f:
            f.write("# Conventions\n")

        with open(os.path.join(self.ws_dir, "dummy.py"), "w", encoding="utf-8") as f:
            f.write("# dummy\n")

        config_data = {
            "name": "E2E Resumption Pipeline",
            "working_directory": self.ws_dir,
            "phases": [
                {
                    "name": "Phase 1",
                    "enabled": True,
                    "models": {
                        "architect_agent": "gemini/gemini-3.7-flash",
                        "editor_agent": "gemini/gemini-3.6-flash",
                    },
                    "toggles": {
                        "shared_history": False,
                        "run_job_one": False,
                        "run_job_two": False,
                        "run_job_three": False,
                        "iterate_test": False,
                    },
                    "rag": {"run_ocr_rag": True, "collection_name": "lib_res"},
                    "files": {
                        "target_files": ["dummy.py"],
                        "context_files_job": ["CONVENTIONS.md"],
                    },
                }
            ],
        }

        cfg_path = os.path.join(self.ws_dir, "resume_config.yml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        proc = self._run_cmd(
            [sys.executable, self.workflow_script, "resume_config.yml", "resumed_session"]
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Resuming a multi-file isolated session", proc.stderr)


    def test_e2e_legacy_parity_shared_history_true_monotonic_growth(self):
        """Zero-Mock Live Test: verify shared_history: true preserves 100% legacy behavior.
        Context accumulates monotonically in root .aider.chat.history.md across multiple tasks,
        and chat_history/ vault is NEVER created."""
        from aider_factory.python.orchestrate import AiderFactory, Task

        session_name = "legacy_parity_session"
        factory = AiderFactory(project_dir=self.ws_dir, session_name=session_name)
        session_dir = str(factory.session_dir)
        chat_hist = os.path.join(session_dir, ".aider.chat.history.md")
        oracle_hist = os.path.join(session_dir, ".oracle_session.json")

        # Task 1: Simulated Job on File A (shared_history: true -> history_stem: None)
        task1 = Task(id="p0_job1_fileA", skip_aider=True, history_stem=None)
        factory.run_task(task1)
        with open(chat_hist, "a", encoding="utf-8") as f:
            f.write("Turn 1 (File A): Created initial scaffold.\n")
        with open(oracle_hist, "w", encoding="utf-8") as f:
            json.dump([{"role": "user", "content": "File A query"}], f)

        # Task 2: Simulated Job on File B (shared_history: true -> history_stem: None)
        task2 = Task(id="p0_job1_fileB", skip_aider=True, history_stem=None)
        factory.run_task(task2)
        with open(chat_hist, "a", encoding="utf-8") as f:
            f.write("Turn 2 (File B): Extended scaffold.\n")
        with open(oracle_hist, "r", encoding="utf-8") as f:
            oracle_data = json.load(f)
        oracle_data.append({"role": "assistant", "content": "File B answer"})
        with open(oracle_hist, "w", encoding="utf-8") as f:
            json.dump(oracle_data, f)

        # Assertions: 100% Legacy Parity
        with open(chat_hist, "r", encoding="utf-8") as f:
            full_content = f.read()
            self.assertIn("Turn 1 (File A)", full_content)
            self.assertIn("Turn 2 (File B)", full_content)

        with open(oracle_hist, "r", encoding="utf-8") as f:
            saved_oracle = json.load(f)
            self.assertEqual(len(saved_oracle), 2)

        vault_dir = os.path.join(session_dir, "chat_history")
        self.assertFalse(os.path.exists(vault_dir))

    def test_e2e_intra_file_multi_job_accumulation_isolated_mode(self):
        """Zero-Mock Live Test: verify shared_history: false preserves history across sequential jobs
        (Job 1 -> Job 2 -> Job 3) for the SAME file stem, while isolating from different stems."""
        from aider_factory.python.orchestrate import AiderFactory, Task

        session_name = "intra_file_chaining_session"
        factory = AiderFactory(project_dir=self.ws_dir, session_name=session_name)
        session_dir = str(factory.session_dir)
        chat_hist = os.path.join(session_dir, ".aider.chat.history.md")
        vault_dir = os.path.join(session_dir, "chat_history")

        # --- FILE A: JOB 1 ---
        task_a_j1 = Task(id="p0_job1_fileA", skip_aider=True, history_stem="job1_fileA")
        factory.run_task(task_a_j1)
        with open(chat_hist, "a", encoding="utf-8") as f:
            f.write("Turn 1 [File A Job 1]: Initial implementation.\n")
        factory._swap_out_state("job1_fileA")

        # --- FILE B: JOB 1 (Interleaved) ---
        task_b_j1 = Task(id="p0_job1_fileB", skip_aider=True, history_stem="job1_fileB")
        factory.run_task(task_b_j1)
        self.assertFalse(os.path.exists(chat_hist))
        with open(chat_hist, "a", encoding="utf-8") as f:
            f.write("Turn 1 [File B Job 1]: File B implementation.\n")
        factory._swap_out_state("job1_fileB")

        # --- FILE A: JOB 2 (Dual Isolation: Job 2 on File A starts fresh!) ---
        task_a_j2 = Task(id="p0_job2_fileA", skip_aider=True, history_stem="job2_fileA")
        factory.run_task(task_a_j2)
        # Stage is clean for Job 2 (Job 1 context is isolated)
        self.assertFalse(os.path.exists(chat_hist))

        with open(chat_hist, "a", encoding="utf-8") as f:
            f.write("Turn 1 [File A Job 2]: Audit checks.\n")
        factory._swap_out_state("job2_fileA")

        vault_a_j1 = os.path.join(vault_dir, ".aider.chat.history_job1_fileA.md")
        vault_b_j1 = os.path.join(vault_dir, ".aider.chat.history_job1_fileB.md")
        vault_a_j2 = os.path.join(vault_dir, ".aider.chat.history_job2_fileA.md")

        with open(vault_a_j1, "r", encoding="utf-8") as f:
            content_a_j1 = f.read()
            self.assertIn("Turn 1 [File A Job 1]", content_a_j1)
            self.assertNotIn("Job 2", content_a_j1)
            self.assertNotIn("File B", content_a_j1)

        with open(vault_b_j1, "r", encoding="utf-8") as f:
            content_b_j1 = f.read()
            self.assertIn("Turn 1 [File B Job 1]", content_b_j1)
            self.assertNotIn("File A", content_b_j1)

        with open(vault_a_j2, "r", encoding="utf-8") as f:
            content_a_j2 = f.read()
            self.assertIn("Turn 1 [File A Job 2]", content_a_j2)
            self.assertNotIn("Job 1", content_a_j2)

    def test_e2e_multi_round_debate_kv_cache_survives_intermediate_apply(self):
        """Zero-Mock Live Test: verify that Round 1 debate context in .oracle_debate_session.json
        survives an intermediate Apply (Aider) task and carries into Round 2 with pass_round_history: true."""
        from aider_factory.python.orchestrate import AiderFactory, Task

        session_name = "multi_round_kv_chain_session"
        factory = AiderFactory(project_dir=self.ws_dir, session_name=session_name)
        session_dir = str(factory.session_dir)
        oracle_debate_file = os.path.join(session_dir, ".oracle_debate_session.json")
        debate_aider_file = os.path.join(session_dir, ".debate_aider_history.md")
        vault_dir = os.path.join(session_dir, "chat_history")

        # 1. Round 1 Deliberate Task
        task_r1_delib = Task(
            id="p0_delib_core_r1",
            skip_aider=True,
            history_stem="core",
        )
        factory.run_task(task_r1_delib)
        # Simulate Round 1 writing debate context
        r1_context = [
            {"role": "system", "content": "Oracle System Prompt"},
            {"role": "user", "content": "Question Round 1"},
            {"role": "assistant", "content": "Answer Round 1 citation"},
        ]
        with open(oracle_debate_file, "w", encoding="utf-8") as f:
            json.dump(r1_context, f)
        with open(debate_aider_file, "w", encoding="utf-8") as f:
            f.write("Round 1 Proposal: Refactor function A\n")
        factory._swap_out_state("core")

        # 2. Round 1 Apply Task (Simulate Aider execution on the same stem)
        task_r1_apply = Task(
            id="p0_apply_core_r1",
            skip_aider=True,
            history_stem="core",
        )
        factory.run_task(task_r1_apply)
        # Verify that apply task did NOT destroy the debate context
        factory._swap_out_state("core")

        # 3. Round 2 Deliberate Task (Carries forward Round 1 context)
        task_r2_delib = Task(
            id="p0_delib_core_r2",
            skip_aider=True,
            history_stem="core",
        )
        factory.run_task(task_r2_delib)

        # Assert Round 1 debate context was restored to the active stage
        with open(oracle_debate_file, "r", encoding="utf-8") as f:
            active_debate = json.load(f)
            self.assertEqual(len(active_debate), 3)
            self.assertEqual(active_debate[1]["content"], "Question Round 1")

        with open(debate_aider_file, "r", encoding="utf-8") as f:
            self.assertIn("Round 1 Proposal: Refactor function A", f.read())

        # Round 2 appends next debate turn (Preserves KV Cache prefix!)
        active_debate.extend([
            {"role": "user", "content": "Question Round 2 (follow-up)"},
            {"role": "assistant", "content": "Answer Round 2 (grounded)"},
        ])
        with open(oracle_debate_file, "w", encoding="utf-8") as f:
            json.dump(active_debate, f)
        with open(debate_aider_file, "a", encoding="utf-8") as f:
            f.write("Round 2 Proposal: Refined fix\n")
        factory._swap_out_state("core")

        # Assert final vault has all 5 turns
        vault_oracle = os.path.join(vault_dir, ".oracle_debate_session_core.json")
        with open(vault_oracle, "r", encoding="utf-8") as f:
            final_oracle = json.load(f)
            self.assertEqual(len(final_oracle), 5)


class TestExecutionGatesAndModes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.temp_dir, "project")
        os.makedirs(self.project_dir, exist_ok=True)
        self.factory = AiderFactory(
            project_dir=self.project_dir,
            session_name="test_gates",
        )
        self.session_dir = str(self.factory.session_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("subprocess.Popen")
    def test_session_aider_conf_deterministic_compilation(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        task = Task(
            id="test_conf_compile",
            map_tokens=1024,
            map_refresh="auto",
            map_multiplier_no_files=2.0,
            max_chat_history_tokens=50000,
            yes_always=True,
            auto_accept_architect=True,
            auto_commits=False,
            suggest_shell_commands=False,
            detect_urls=True,
            disable_playwright=True,
        )
        self.factory._execute_task_node(task)

        session_conf_path = os.path.join(self.session_dir, ".aider.conf.yml")
        self.assertTrue(os.path.exists(session_conf_path))
        import yaml
        with open(session_conf_path, "r", encoding="utf-8") as f:
            compiled_conf = yaml.safe_load(f)

        self.assertEqual(compiled_conf.get("map-tokens"), 1024)
        self.assertEqual(compiled_conf.get("map-refresh"), "auto")
        self.assertEqual(compiled_conf.get("map-multiplier-no-files"), 2.0)
        self.assertEqual(compiled_conf.get("max-chat-history-tokens"), "50000")
        self.assertTrue(compiled_conf.get("yes-always"))
        self.assertTrue(compiled_conf.get("auto-accept-architect"))
        self.assertFalse(compiled_conf.get("auto-commits"))
        self.assertFalse(compiled_conf.get("suggest-shell-commands"))
        self.assertTrue(compiled_conf.get("detect-urls"))
        self.assertTrue(compiled_conf.get("disable-playwright"))

    @patch("deliberate.verdict_is_actionable")
    @patch("deliberate.verdict_status")
    def test_verdict_gate_evaluation(self, mock_status, mock_actionable):
        # 1. Non-actionable: clean
        mock_actionable.return_value = False
        mock_status.return_value = "clean"
        task_clean = Task(id="test_clean_gate", verdict_gate="/path/to/verdict.md")
        self.assertTrue(self.factory._execute_task_node(task_clean))

        # 2. Non-actionable: held
        mock_actionable.return_value = False
        mock_status.return_value = "held"
        task_held = Task(id="test_held_gate", verdict_gate="/path/to/verdict.md")
        self.assertTrue(self.factory._execute_task_node(task_held))

    @patch("subprocess.run")
    @patch("subprocess.Popen")
    def test_final_check_gate_on_loop_exhaustion(self, mock_popen, mock_run):
        # Initial test baseline in loop fails
        mock_init_test = MagicMock()
        mock_init_test.returncode = 1
        mock_init_test.stdout.read.side_effect = ["Error log", ""]
        mock_init_test.poll.return_value = 1
        mock_init_test.wait.return_value = 1

        # Aider run fails / continues
        mock_aider = MagicMock()
        mock_aider.returncode = 1
        mock_aider.wait.return_value = 1

        mock_popen.side_effect = [mock_init_test, mock_aider]

        # final_check subprocess.run passes (returns rc 0)
        mock_run.return_value = MagicMock(returncode=0)

        task = Task(
            id="test_final_check",
            test_cmd="pytest tests/",
            iterate_test=True,
            max_aider_loops=1,
            final_check=True,
        )
        res = self.factory._execute_task_node(task)
        self.assertTrue(res)
        mock_run.assert_called_once()

    @patch("subprocess.Popen")
    def test_soft_fail_gate_on_loop_exhaustion(self, mock_popen):
        mock_init_test = MagicMock()
        mock_init_test.returncode = 1
        mock_init_test.stdout.read.side_effect = ["Fail", ""]
        mock_init_test.poll.return_value = 1
        mock_init_test.wait.return_value = 1

        mock_aider = MagicMock()
        mock_aider.returncode = 1
        mock_aider.wait.return_value = 1

        mock_popen.side_effect = [mock_init_test, mock_aider]

        task = Task(
            id="test_soft_fail",
            test_cmd="pytest tests/",
            iterate_test=True,
            max_aider_loops=1,
            soft_fail=True,
        )
        res = self.factory._execute_task_node(task)
        self.assertTrue(res)


if __name__ == "__main__":
    unittest.main()
