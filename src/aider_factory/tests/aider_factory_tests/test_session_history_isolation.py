#!/usr/bin/env python3
# test_session_history_isolation.py — Regression tests for the chat-history
# config-leak fix (Task 001) and shared_history toggle invariants.
#
# Validates:
#   1. Generated session .aider.conf.yml NEVER contains history-path keys.
#   2. CLI --chat-history-file flags are the sole history authority.
#   3. shared_history=true  -> history_stem=None -> no vault swap (shared).
#   4. shared_history=false -> history_stem set  -> vault swap isolates.
#   5. Session resume: same session name -> prior on-disk history persists.
#   6. No dependency on global .aider_factory/.aider.chat.history.md.
#   7. Debate/ask turns retain 1,000,000 token ceiling + own history file.
#   8. Pair-programming: no --message, plan via --read, config is clean.
#   9. Vault swap round-trip: swap_out then swap_in restores exact bytes.
#  10. Multiple sessions in same project do not cross-contaminate.

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
src_dir = os.path.abspath(os.path.join(script_dir, "../../.."))

for _p in (python_module_dir, src_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Force eviction of any pre-imported orchestrate module from earlier test collection
for mod in list(sys.modules.keys()):
    if mod == "orchestrate" or mod.startswith("aider_factory.python.orchestrate"):
        sys.modules.pop(mod, None)

importlib.invalidate_caches()

from orchestrate import AiderFactory, Task  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HISTORY_KEYS = (
    "chat-history-file",
    "input-history-file",
    "llm-history-file",
    "restore-chat-history",
)


def _make_project(temp_root: Path) -> Path:
    """Create a minimal project tree with .aider_factory/ and a target file."""
    af = temp_root / ".aider_factory"
    af.mkdir(parents=True, exist_ok=True)
    (temp_root / "target.py").write_text("x = 1\n", encoding="utf-8")
    (temp_root / "plan.md").write_text("Execute the plan.\n", encoding="utf-8")
    return af


def _write_base_conf(af: Path, extra: dict = None):
    """Write a base .aider.conf.yml that INCLUDES global history paths (bug trigger)."""
    conf = {
        "chat-history-file": ".aider_factory/.aider.chat.history.md",
        "input-history-file": ".aider_factory/.aider.input.history",
        "llm-history-file": ".aider_factory/.aider.llm.history",
        "restore-chat-history": True,
        "map-tokens": "0",
        "yes-always": False,
        "architect": True,
    }
    if extra:
        conf.update(extra)
    with open(af / ".aider.conf.yml", "w", encoding="utf-8") as f:
        yaml.safe_dump(conf, f)


def _mock_popen(returncode=0):
    """Return a patch context that mocks subprocess.Popen for non-pair tasks."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdin = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.read.side_effect = ["", ""]
    mock_proc.poll.return_value = 0
    mock_popen = MagicMock(return_value=mock_proc)
    return patch("subprocess.Popen", mock_popen), mock_popen


# ---------------------------------------------------------------------------
# T1 / T2: Config stripping + CLI authority
# ---------------------------------------------------------------------------

class TestConfigHistoryKeyStripping(unittest.TestCase):
    """The generated session .aider.conf.yml must NOT carry history-path keys."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)
        _write_base_conf(self.af)

    def tearDown(self):
        self._tmp.cleanup()

    def test_generated_config_has_no_history_keys(self):
        factory = AiderFactory(str(self.root), session_name="strip_check")
        task = Task(
            id="t1", model="mock/m", editor_model="mock/e",
            files=["target.py"], pair_programming=False,
        )
        factory.add_task(task)
        task.message_file = str(self.root / "plan.md")

        ctx, _ = _mock_popen()
        with ctx:
            factory._execute_task_node(task)

        conf_path = os.path.join(str(factory.session_dir), ".aider.conf.yml")
        self.assertTrue(os.path.exists(conf_path))
        with open(conf_path, "r", encoding="utf-8") as f:
            gen = yaml.safe_load(f) or {}

        for key in HISTORY_KEYS:
            self.assertNotIn(key, gen,
                             f"'{key}' must be stripped from session config")

    def test_other_config_keys_preserved(self):
        factory = AiderFactory(str(self.root), session_name="keep_check")
        task = Task(
            id="t1b", model="mock/m", editor_model="mock/e",
            files=["target.py"], pair_programming=False,
            map_tokens=500, yes_always=True,
        )
        factory.add_task(task)
        task.message_file = str(self.root / "plan.md")

        ctx, _ = _mock_popen()
        with ctx:
            factory._execute_task_node(task)

        conf_path = os.path.join(str(factory.session_dir), ".aider.conf.yml")
        with open(conf_path, "r", encoding="utf-8") as f:
            gen = yaml.safe_load(f) or {}

        self.assertEqual(gen.get("map-tokens"), 500)
        self.assertEqual(gen.get("yes-always"), True)
        self.assertIn("architect", gen)  # non-history key survives


class TestCliFlagsAreSoleAuthority(unittest.TestCase):
    """The aider cmd must carry --chat-history-file pointing to session dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)
        _write_base_conf(self.af)

    def tearDown(self):
        self._tmp.cleanup()

    def test_cmd_contains_session_history_path(self):
        factory = AiderFactory(str(self.root), session_name="cli_auth")
        task = Task(
            id="t2", model="mock/m", editor_model="mock/e",
            files=["target.py"], pair_programming=False,
        )
        factory.add_task(task)
        task.message_file = str(self.root / "plan.md")

        ctx, mock_proc = _mock_popen()
        with ctx:
            factory._execute_task_node(task)

        # Extract cmd list from Popen call
        call_args = mock_proc.call_args
        cmd = call_args.args[0] if call_args.args else call_args.kwargs.get("cmd")
        if isinstance(cmd, str):
            import shlex
            cmd = shlex.split(cmd)

        self.assertIn("--chat-history-file", cmd)
        idx = cmd.index("--chat-history-file")
        self.assertIn(str(factory.session_dir), cmd[idx + 1])

        self.assertIn("--restore-chat-history", cmd)

    def test_config_flag_points_to_session_not_global(self):
        factory = AiderFactory(str(self.root), session_name="cli_cfg")
        task = Task(
            id="t2b", model="mock/m", editor_model="mock/e",
            files=["target.py"], pair_programming=False,
        )
        factory.add_task(task)
        task.message_file = str(self.root / "plan.md")

        ctx, mock_proc = _mock_popen()
        with ctx:
            factory._execute_task_node(task)

        cmd = mock_proc.call_args.args[0]
        if isinstance(cmd, str):
            import shlex
            cmd = shlex.split(cmd)

        self.assertIn("--config", cmd)
        cfg_idx = cmd.index("--config")
        cfg_val = cmd[cfg_idx + 1]
        self.assertIn("sessions", cfg_val)
        # Must NOT be the global .aider_factory/.aider.conf.yml
        self.assertNotIn(
            str(self.af / ".aider.conf.yml"), cfg_val,
            "--config must point to session-scoped config, not global"
        )


# ---------------------------------------------------------------------------
# T3 / T4: shared_history toggle
# ---------------------------------------------------------------------------

class TestSharedHistoryTrue(unittest.TestCase):
    """history_stem=None (shared_history=true): no vault swap, shared file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)
        _write_base_conf(self.af)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_vault_swap_called(self):
        factory = AiderFactory(str(self.root), session_name="sh_true")
        task = Task(
            id="sh_t", model="mock/m", editor_model="mock/e",
            files=["target.py"], history_stem=None,
        )
        factory.add_task(task)
        task.message_file = str(self.root / "plan.md")

        chat_hist = os.path.join(str(factory.session_dir), ".aider.chat.history.md")
        Path(chat_hist).write_text("## Shared\nUser: hi\n", encoding="utf-8")

        ctx, _ = _mock_popen()
        with patch.object(factory, "_swap_in_state") as m_in, \
             patch.object(factory, "_swap_out_state") as m_out, \
             ctx:
            factory.run_task(task)

        m_in.assert_not_called()
        m_out.assert_not_called()

    def test_shared_file_not_truncated_by_swap(self):
        factory = AiderFactory(str(self.root), session_name="sh_content")
        task = Task(
            id="sh_c", model="mock/m", editor_model="mock/e",
            files=["target.py"], history_stem=None,
        )
        factory.add_task(task)
        task.message_file = str(self.root / "plan.md")

        chat_hist = os.path.join(str(factory.session_dir), ".aider.chat.history.md")
        Path(chat_hist).write_text("## Keep me\nUser: persist\n", encoding="utf-8")

        ctx, _ = _mock_popen()
        with ctx:
            factory.run_task(task)

        content = Path(chat_hist).read_text(encoding="utf-8")
        self.assertIn("Keep me", content)


class TestSharedHistoryFalse(unittest.TestCase):
    """history_stem set (shared_history=false): vault swap isolates per-task."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)
        _write_base_conf(self.af)

    def tearDown(self):
        self._tmp.cleanup()

    def test_vault_swap_in_populates_active(self):
        factory = AiderFactory(str(self.root), session_name="sh_false")
        vault_dir = os.path.join(str(factory.session_dir), "chat_history")
        os.makedirs(vault_dir, exist_ok=True)

        vault_file = os.path.join(vault_dir, ".aider.chat.history_task_a.md")
        Path(vault_file).write_text("## Vault A\nUser: alpha\n", encoding="utf-8")

        active = os.path.join(str(factory.session_dir), ".aider.chat.history.md")
        Path(active).write_text("## Active B\nUser: beta\n", encoding="utf-8")

        task = Task(
            id="task_a", model="mock/m", editor_model="mock/e",
            files=["target.py"], history_stem="task_a",
        )
        factory.add_task(task)
        task.message_file = str(self.root / "plan.md")

        # Capture what the active file contains at the moment Popen is called
        captured_content = []

        def _capture_popen(*args, **kwargs):
            captured_content.append(Path(active).read_text(encoding="utf-8"))
            m = MagicMock()
            m.returncode = 0
            m.stdin = MagicMock()
            return m

        with patch("subprocess.Popen", side_effect=_capture_popen):
            factory.run_task(task)

        self.assertEqual(len(captured_content), 1)
        self.assertIn("Vault A", captured_content[0],
                      "Active file must contain vault content after swap_in")
        self.assertNotIn("Active B", captured_content[0],
                         "Prior active content must be removed before swap_in")

    def test_vault_swap_out_preserves_task_history(self):
        factory = AiderFactory(str(self.root), session_name="sh_out")
        task = Task(
            id="task_b", model="mock/m", editor_model="mock/e",
            files=["target.py"], history_stem="task_b",
        )
        factory.add_task(task)
        task.message_file = str(self.root / "plan.md")

        active = os.path.join(str(factory.session_dir), ".aider.chat.history.md")

        def _popen_writes_history(*args, **kwargs):
            # Simulate aider writing chat history during execution
            Path(active).write_text("## Task B run\nUser: gamma\n", encoding="utf-8")
            m = MagicMock()
            m.returncode = 0
            m.stdin = MagicMock()
            return m

        with patch("subprocess.Popen", side_effect=_popen_writes_history):
            factory.run_task(task)

        vault_file = os.path.join(
            str(factory.session_dir), "chat_history", ".aider.chat.history_task_b.md"
        )
        self.assertTrue(os.path.exists(vault_file), "Vault file must exist after swap_out")
        vault_content = Path(vault_file).read_text(encoding="utf-8")
        self.assertIn("Task B run", vault_content)


# ---------------------------------------------------------------------------
# T5: Session resume
# ---------------------------------------------------------------------------

class TestSessionResume(unittest.TestCase):
    """Same session name across factory instances -> history persists on disk."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)
        _write_base_conf(self.af)

    def tearDown(self):
        self._tmp.cleanup()

    def test_history_survives_factory_recreation(self):
        f1 = AiderFactory(str(self.root), session_name="resume")
        hist = os.path.join(str(f1.session_dir), ".aider.chat.history.md")
        Path(hist).write_text("## Old turn\nUser: remember\nAssistant: yes\n", encoding="utf-8")

        f2 = AiderFactory(str(self.root), session_name="resume")
        hist2 = os.path.join(str(f2.session_dir), ".aider.chat.history.md")
        self.assertTrue(os.path.exists(hist2))
        self.assertIn("remember", Path(hist2).read_text(encoding="utf-8"))

    def test_different_session_names_are_isolated(self):
        f1 = AiderFactory(str(self.root), session_name="alpha")
        f2 = AiderFactory(str(self.root), session_name="beta")

        self.assertNotEqual(str(f1.session_dir), str(f2.session_dir))

        Path(os.path.join(str(f1.session_dir), ".aider.chat.history.md")).write_text(
            "alpha only\n", encoding="utf-8"
        )
        beta_hist = os.path.join(str(f2.session_dir), ".aider.chat.history.md")
        self.assertFalse(os.path.exists(beta_hist))


# ---------------------------------------------------------------------------
# T6: No global history dependency
# ---------------------------------------------------------------------------

class TestNoGlobalHistoryDependency(unittest.TestCase):
    """Sessions work even when global .aider.chat.history.md is deleted."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)
        _write_base_conf(self.af)
        # Create the global file (pre-fix would leak it)
        (self.af / ".aider.chat.history.md").write_text(
            "## GLOBAL LEAK\nUser: should not appear\n", encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_delete_global_still_works(self):
        (self.af / ".aider.chat.history.md").unlink()

        factory = AiderFactory(str(self.root), session_name="no_global")
        task = Task(
            id="ng", model="mock/m", editor_model="mock/e",
            files=["target.py"], pair_programming=False,
        )
        factory.add_task(task)
        task.message_file = str(self.root / "plan.md")

        ctx, _ = _mock_popen()
        with ctx:
            result = factory._execute_task_node(task)

        self.assertTrue(result)

        # Session config must not reference the deleted global file
        conf_path = os.path.join(str(factory.session_dir), ".aider.conf.yml")
        with open(conf_path, "r", encoding="utf-8") as f:
            gen = yaml.safe_load(f) or {}
        for key in HISTORY_KEYS:
            self.assertNotIn(key, gen)


# ---------------------------------------------------------------------------
# T7: Debate turn — 1M ceiling + isolated history
# ---------------------------------------------------------------------------

class TestDebateTurnCeiling(unittest.TestCase):
    """_aider_ask_turn retains 1,000,000 and uses debate-specific history."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _call_ask_turn(self, history_file=None):
        factory = AiderFactory(str(self.root), session_name="debate_ceil")
        task = Task(id="dt", model="mock/arch", editor_model="mock/ed")

        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.side_effect = ["x", ""]
        mock_proc.poll.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mp:
            factory._aider_ask_turn(
                task, message="Debate msg", read_files=[],
                label="turn 1/3", history_file=history_file,
            )
        return mp.call_args.args[0]

    def test_1m_ceiling_present(self):
        cmd = self._call_ask_turn()
        self.assertIn("--max-chat-history-tokens", cmd)
        idx = cmd.index("--max-chat-history-tokens")
        self.assertEqual(cmd[idx + 1], "1000000")

    def test_debate_history_file_used_when_provided(self):
        debate_h = os.path.join(str(self.root), ".aider_factory", "sessions",
                                "debate_ceil", ".debate_aider_history.md")
        cmd = self._call_ask_turn(history_file=debate_h)
        # The LAST --chat-history-file should be the debate file
        indices = [i for i, a in enumerate(cmd) if a == "--chat-history-file"]
        self.assertTrue(len(indices) >= 1)
        self.assertIn(".debate_aider_history.md", cmd[indices[-1] + 1])

    def test_no_debate_history_means_session_file(self):
        cmd = self._call_ask_turn(history_file=None)
        indices = [i for i, a in enumerate(cmd) if a == "--chat-history-file"]
        self.assertTrue(len(indices) >= 1)
        self.assertIn(".aider.chat.history.md", cmd[indices[-1] + 1])


# ---------------------------------------------------------------------------
# T8: Pair-programming specifics
# ---------------------------------------------------------------------------

class TestPairProgrammingConfig(unittest.TestCase):
    """Pair mode: no --message, plan via --read, config clean."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)
        _write_base_conf(self.af)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_pair(self):
        factory = AiderFactory(str(self.root), session_name="pair")
        task = Task(
            id="pp", model="mock/m", editor_model="mock/e",
            files=["target.py"],
            message_file=str(self.root / "plan.md"),
            pair_programming=True,
        )
        factory.add_task(task)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        with patch("subprocess.Popen", return_value=mock_proc) as mp:
            factory._execute_task_node(task)
        return factory, mp.call_args

    def test_config_no_history_keys(self):
        factory, _ = self._run_pair()
        conf_path = os.path.join(str(factory.session_dir), ".aider.conf.yml")
        with open(conf_path, "r", encoding="utf-8") as f:
            gen = yaml.safe_load(f) or {}
        for key in HISTORY_KEYS:
            self.assertNotIn(key, gen,
                             f"Pair config must not contain '{key}'")

    def test_no_message_flag(self):
        _, call_args = self._run_pair()
        cmd_str = " ".join(call_args.args[0])
        self.assertNotIn("--message", cmd_str,
                         "Pair mode must not pass --message")

    def test_plan_loaded_via_read(self):
        _, call_args = self._run_pair()
        cmd_str = " ".join(call_args.args[0])
        self.assertIn("--read", cmd_str)
        self.assertIn("plan.md", cmd_str)

    def test_wrapped_in_script_for_pty(self):
        _, call_args = self._run_pair()
        cmd_list = call_args.args[0]
        self.assertEqual(cmd_list[0], "script",
                         "Pair mode must wrap aider in 'script' for PTY")


# ---------------------------------------------------------------------------
# T9: Vault swap round-trip byte fidelity
# ---------------------------------------------------------------------------

class TestVaultSwapRoundTrip(unittest.TestCase):
    """swap_out then swap_in restores exact file bytes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip_preserves_bytes(self):
        factory = AiderFactory(str(self.root), session_name="roundtrip")
        active = os.path.join(str(factory.session_dir), ".aider.chat.history.md")
        original = "## Exact content\nUser: 日本語テスト\nAssistant: ✓\n"
        Path(active).write_text(original, encoding="utf-8")

        factory._swap_out_state("rt_stem")
        Path(active).write_text("## Overwritten\n", encoding="utf-8")
        factory._swap_in_state("rt_stem")

        restored = Path(active).read_text(encoding="utf-8")
        self.assertEqual(restored, original,
                         "Vault round-trip must preserve exact bytes")


# ---------------------------------------------------------------------------
# T10: Multi-session cross-contamination guard
# ---------------------------------------------------------------------------

class TestMultiSessionIsolation(unittest.TestCase):
    """Two sessions in the same project never read each other's history."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.af = _make_project(self.root)
        _write_base_conf(self.af)

    def tearDown(self):
        self._tmp.cleanup()

    def test_two_sessions_have_separate_files(self):
        f1 = AiderFactory(str(self.root), session_name="sess_1")
        f2 = AiderFactory(str(self.root), session_name="sess_2")

        h1 = os.path.join(str(f1.session_dir), ".aider.chat.history.md")
        h2 = os.path.join(str(f2.session_dir), ".aider.chat.history.md")

        Path(h1).write_text("session 1 data\n", encoding="utf-8")

        self.assertFalse(os.path.exists(h2),
                         "Session 2 must not see session 1's history file")
        self.assertIn("session 1", Path(h1).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
