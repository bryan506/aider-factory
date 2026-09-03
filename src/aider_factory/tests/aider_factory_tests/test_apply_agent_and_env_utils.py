#!/usr/bin/env python3
# test_apply_agent_and_env_utils.py — Full-coverage regression tests for
# apply_agent.py (parse, find, resolve, run, main) and env_utils.py
# (is_dummy_key, load_env_files, resolve_api_key).

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
src_dir = os.path.abspath(os.path.join(script_dir, "../../.."))

for _p in (python_module_dir, src_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from env_utils import is_dummy_key, load_env_files, resolve_api_key, DUMMY_KEYS
from apply_agent import (
    parse_chat_history,
    find_active_session_chat_history,
    resolve_editor_config,
    run_apply,
    main,
)


class TestEnvUtils(unittest.TestCase):
    """Tests for env_utils.py functions."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        self._tmp.cleanup()

    def test_is_dummy_key(self):
        self.assertTrue(is_dummy_key(None))
        self.assertTrue(is_dummy_key(""))
        self.assertTrue(is_dummy_key("   "))
        self.assertTrue(is_dummy_key("sk-dummy"))
        self.assertTrue(is_dummy_key("SK-DUMMY"))
        self.assertTrue(is_dummy_key("dummy"))
        self.assertTrue(is_dummy_key("none"))
        self.assertTrue(is_dummy_key("null"))
        self.assertFalse(is_dummy_key("sk-validkey123"))

    def test_load_env_files(self):
        af_dir = self.root / ".aider_factory"
        af_dir.mkdir(parents=True)

        env1 = self.root / ".env"
        env1.write_text(
            "TEST_VAR_A=valA # comment\n"
            "export TEST_VAR_B='valB'\n"
            "# comment line\n"
            "INVALID_LINE\n"
            "TEST_VAR_C=\"valC\"\n",
            encoding="utf-8",
        )

        env2 = af_dir / ".env.local"
        env2.write_text("TEST_VAR_D=valD\n", encoding="utf-8")

        load_env_files(cwd=str(self.root))

        self.assertEqual(os.environ.get("TEST_VAR_A"), "valA")
        self.assertEqual(os.environ.get("TEST_VAR_B"), "valB")
        self.assertEqual(os.environ.get("TEST_VAR_C"), "valC")
        self.assertEqual(os.environ.get("TEST_VAR_D"), "valD")

    def test_resolve_api_key_api_base(self):
        os.environ.pop("ORACLE_AGENT_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        self.assertEqual(resolve_api_key(api_base="http://localhost:8000"), "sk-dummy")

        os.environ["ORACLE_AGENT_API_KEY"] = "oracle-secret"
        self.assertEqual(resolve_api_key(api_base="http://localhost:8000"), "oracle-secret")

        self.assertEqual(
            resolve_api_key(api_base="http://localhost:8000", explicit_key="explicit-key"),
            "explicit-key",
        )

    def test_resolve_api_key_explicit_and_model_matching(self):
        self.assertEqual(resolve_api_key(explicit_key="my-key"), "my-key")

        os.environ["GEMINI_API_KEY"] = "gem-key-123"
        self.assertEqual(resolve_api_key(model="gemini/gemini-2.5-flash"), "gem-key-123")

        os.environ.pop("GEMINI_API_KEY", None)
        os.environ["ANTHROPIC_API_KEY"] = "ant-key-123"
        self.assertEqual(resolve_api_key(), "ant-key-123")


class TestParseChatHistory(unittest.TestCase):
    """Tests for parse_chat_history in apply_agent.py."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_chat(self, content: str, name: str = ".aider.chat.history.md") -> str:
        p = self.root / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_file_not_found_returns_empty(self):
        self.assertEqual(parse_chat_history(str(self.root / "nonexistent.md")), "")

    def test_no_token_anchor_returns_empty(self):
        path = self._write_chat("Just some text without token anchors.\n")
        self.assertEqual(parse_chat_history(path), "")

    def test_single_turn_format(self):
        content = textwrap.dedent("""\
            #### Implement login endpoint
            Create a /login POST route.

            > Tokens: 1.2k sent, 3.4k received
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=1)
        self.assertIn("# Directive\nImplement login endpoint", result)
        self.assertIn("# Specification & Implementation Plan\nCreate a /login POST route.", result)

    def test_multiple_turns_tagging(self):
        content = textwrap.dedent("""\
            #### First request
            First assistant response.

            > Tokens: 1k sent, 2k received
            #### Second request
            Second assistant response.

            > Tokens: 1k sent, 2k received
            #### Third request
            Third assistant response.

            > Tokens: 1k sent, 2k received
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=2)
        self.assertIn("Prior Context Turn 1", result)
        self.assertIn("Active Directive", result)
        self.assertIn("Second request", result)
        self.assertIn("Third request", result)
        self.assertNotIn("First request", result)

    def test_slash_command_and_ask_filtering(self):
        content = textwrap.dedent("""\
            #### /run cat src/main.py
            #### /ask How do I parse YAML?
            Use PyYAML library.

            > Tokens: 1k sent, 2k received
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=1)
        self.assertNotIn("/run cat", result)
        self.assertIn("How do I parse YAML?", result)

    def test_a8_thinking_content_hex_stripped(self):
        content = textwrap.dedent("""\
            #### How do I parse YAML?
            <thinking-content-1a2b3c>Step 1: Parse YAML</thinking-content-1a2b3c>
            Use yaml.safe_load() for untrusted input.

            > Tokens: 1k sent, 2k received
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=1)
        self.assertIn("Use yaml.safe_load()", result)
        self.assertNotIn("Step 1:", result)
        self.assertNotIn("thinking-content", result)

    def test_a9_im_start_think_stripped(self):
        content = textwrap.dedent("""\
            #### Sort a list
            <think>First consider sorted() vs list.sort()</think>
            Use `sorted(lst)` to return a new list.

            > Tokens: 1k sent, 2k received
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=1)
        self.assertIn("Use `sorted(lst)`", result)
        self.assertNotIn("First consider", result)


class TestParseChatHistoryGaps(unittest.TestCase):
    """Fill remaining gaps A5, A8+A9, A10–A14 for parse_chat_history()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_chat(self, content: str) -> str:
        p = self.root / ".aider.chat.history.md"
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_a5_turns_exceeds_available(self):
        content = textwrap.dedent("""\
            #### Only one turn here
            The single response body.

            > Tokens: 1k sent, 2k received
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=999)
        self.assertIn("Only one turn here", result)
        self.assertIn("The single response body.", result)
        self.assertIn("# Directive", result)

    def test_a10_answer_markers_stripped(self):
        content = (
            "#### What is 2+2?\n"
            "\u25ba ANSWER\n"
            "The answer is 4.\n"
            "\u25ba**ANSWER**\n"
            "Confirmed: 4.\n"
            "\u25ba **ANSWER**\n"
            "Final: 4.\n"
            "\n"
            "> Tokens: 1k sent, 2k received\n"
        )
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=1)
        self.assertIn("The answer is 4.", result)
        self.assertIn("Confirmed: 4.", result)
        self.assertIn("Final: 4.", result)
        self.assertNotIn("ANSWER", result)
        self.assertNotIn("\u25ba", result)

    def test_a11_tool_artifact_lines_filtered(self):
        content = textwrap.dedent("""\
            #### Add a new module
            > Added src/new_module.py
            > Moved old.py to archive/old.py
            > No files modified in tests/
            > Tokens: 500 sent, 1.2k received
            Here is the real implementation plan for the new module.

            > Tokens: 1k sent, 2k received
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=1)
        self.assertIn("real implementation plan", result)
        self.assertNotIn("Added src/", result)
        self.assertNotIn("Moved old.py", result)
        self.assertNotIn("No files modified", result)

    def test_a12_empty_user_text_still_produces_output(self):
        content = textwrap.dedent("""\
            This is assistant-only content with no user header.
            It contains a full specification.

            > Tokens: 1k sent, 2k received
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=1)
        self.assertIn("# Specification & Implementation Plan", result)
        self.assertIn("assistant-only content", result)
        self.assertIn("full specification", result)

    def test_a13_assistant_all_artifacts_excluded(self):
        content = textwrap.dedent("""\
            #### Valid turn one
            Real response content here.

            > Tokens: 1k sent, 2k received
            #### Turn with only artifacts
            > Added file.py
            > Moved other.py
            > No files changed

            > Tokens: 1k sent, 2k received
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=2)
        self.assertIn("Valid turn one", result)
        self.assertIn("Real response content here.", result)
        self.assertNotIn("Turn with only artifacts", result)
        self.assertNotIn("Added file.py", result)

    def test_a14_trailing_content_after_last_anchor_ignored(self):
        content = textwrap.dedent("""\
            #### Real question
            Real answer here.

            > Tokens: 1k sent, 2k received
            This is trailing garbage after the last anchor.
            It should NOT appear in parsed output.
            #### Phantom turn
            This should also be ignored.
        """)
        path = self._write_chat(content)
        result = parse_chat_history(path, turns=1)
        self.assertIn("Real question", result)
        self.assertIn("Real answer here.", result)
        self.assertNotIn("trailing garbage", result)
        self.assertNotIn("Phantom turn", result)


class TestFindActiveSessionChatHistory(unittest.TestCase):
    """Tests for find_active_session_chat_history."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        self._tmp.cleanup()

    def test_explicit_session_env(self):
        sess_dir = self.root / ".aider_factory" / "sessions" / "my_session"
        sess_dir.mkdir(parents=True)
        hist = sess_dir / ".aider.chat.history.md"
        hist.write_text("dummy history", encoding="utf-8")

        os.environ["AI_FACTORY_SESSION"] = "my_session"
        path, session = find_active_session_chat_history(str(self.root))
        self.assertEqual(path, str(hist))
        self.assertEqual(session, "my_session")

    def test_root_fallback(self):
        af_dir = self.root / ".aider_factory"
        af_dir.mkdir(parents=True)
        hist = af_dir / ".aider.chat.history.md"
        hist.write_text("root history", encoding="utf-8")

        os.environ.pop("AI_FACTORY_SESSION", None)
        path, session = find_active_session_chat_history(str(self.root))
        self.assertEqual(path, str(hist))
        self.assertEqual(session, "")


class TestFindActiveSessionChatHistoryGaps(unittest.TestCase):
    """Fill gaps B2, B3, B4, B6 for find_active_session_chat_history()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        self._tmp.cleanup()

    def test_b2_param_overrides_env(self):
        sess_a = self.root / ".aider_factory" / "sessions" / "alpha"
        sess_b = self.root / ".aider_factory" / "sessions" / "beta"
        sess_a.mkdir(parents=True)
        sess_b.mkdir(parents=True)
        (sess_a / ".aider.chat.history.md").write_text("alpha", encoding="utf-8")
        (sess_b / ".aider.chat.history.md").write_text("beta", encoding="utf-8")

        os.environ["AI_FACTORY_SESSION"] = "alpha"
        path, name = find_active_session_chat_history(
            str(self.root), session_name="beta"
        )
        self.assertIn("beta", name)
        self.assertIn("beta", path)

    def test_b3_session_file_missing_falls_through(self):
        sess_target = self.root / ".aider_factory" / "sessions" / "ghost"
        sess_target.mkdir(parents=True)

        sess_other = self.root / ".aider_factory" / "sessions" / "real"
        sess_other.mkdir(parents=True)
        (sess_other / ".aider.chat.history.md").write_text("real content", encoding="utf-8")

        path, name = find_active_session_chat_history(
            str(self.root), session_name="ghost"
        )
        self.assertIn("real", name)
        self.assertIn("real", path)

    def test_b4_multiple_sessions_mtime_wins(self):
        sess_old = self.root / ".aider_factory" / "sessions" / "old_sess"
        sess_new = self.root / ".aider_factory" / "sessions" / "new_sess"
        sess_old.mkdir(parents=True)
        sess_new.mkdir(parents=True)

        hist_old = sess_old / ".aider.chat.history.md"
        hist_new = sess_new / ".aider.chat.history.md"
        hist_old.write_text("old data", encoding="utf-8")
        hist_new.write_text("new data", encoding="utf-8")

        os.utime(hist_old, (1577836800, 1577836800))  # Jan 1, 2020
        os.utime(hist_new, (1704067200, 1704067200))  # Jan 1, 2024

        os.environ.pop("AI_FACTORY_SESSION", None)
        path, name = find_active_session_chat_history(str(self.root))
        self.assertEqual(name, "new_sess")
        self.assertIn("new_sess", path)

    def test_b6_nothing_found_returns_empty_tuple(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)

        os.environ.pop("AI_FACTORY_SESSION", None)
        path, name = find_active_session_chat_history(str(self.root))
        self.assertEqual(path, "")
        self.assertEqual(name, "")


class TestResolveEditorConfig(unittest.TestCase):
    """Tests for resolve_editor_config."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_editor_config_resolution(self):
        af_dir = self.root / ".aider_factory"
        af_dir.mkdir(parents=True)
        cfg_file = af_dir / ".env.yml"
        cfg_file.write_text(
            yaml.dump(
                {
                    "models": {"editor_agent": "anthropic/claude-3-5-sonnet-20241022"},
                    "endpoints": {"editor_api": "http://localhost:11434/v1"},
                }
            ),
            encoding="utf-8",
        )

        cfg = resolve_editor_config(str(self.root))
        self.assertEqual(cfg["editor_model"], "anthropic/claude-3-5-sonnet-20241022")
        self.assertEqual(cfg["editor_api_base"], "http://localhost:11434/v1")


class TestResolveEditorConfigGaps(unittest.TestCase):
    """Fill gaps C2, C3, C4, C5 for resolve_editor_config()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        self._tmp.cleanup()

    def test_c2_explicit_model_overrides_config(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        (af / ".env.yml").write_text(
            yaml.dump({"models": {"editor_agent": "anthropic/claude-3-5-sonnet-20241022"}}),
            encoding="utf-8",
        )

        cfg = resolve_editor_config(str(self.root), explicit_model="openai/gpt-4o")
        self.assertEqual(cfg["editor_model"], "openai/gpt-4o")

    def test_c3_phases_override_top_level_models(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        config_data = {
            "models": {"editor_agent": "top-level/model-a"},
            "phases": [
                {"name": "Phase 1", "models": {"editor_agent": "phase/model-b"}},
            ],
        }
        (af / ".env.yml").write_text(yaml.dump(config_data), encoding="utf-8")

        cfg = resolve_editor_config(str(self.root))
        self.assertEqual(cfg["editor_model"], "phase/model-b")

    def test_c4_no_config_returns_defaults(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)

        os.environ.pop("AI_FACTORY_CONFIG", None)
        cfg = resolve_editor_config(str(self.root))
        self.assertEqual(cfg["editor_model"], "gemini/gemini-2.5-flash")
        self.assertIsNone(cfg["editor_api_base"])

    def test_c5_malformed_yaml_no_crash(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        (af / ".env.yml").write_text(
            "models:\n  editor_agent: 'unterminated\n  bad: [{invalid\n",
            encoding="utf-8",
        )

        os.environ.pop("AI_FACTORY_CONFIG", None)
        cfg = resolve_editor_config(str(self.root))
        self.assertEqual(cfg["editor_model"], "gemini/gemini-2.5-flash")
        self.assertIsNone(cfg["editor_api_base"])

    def test_c5b_empty_yaml_file(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        (af / ".env.yml").write_text("", encoding="utf-8")

        os.environ.pop("AI_FACTORY_CONFIG", None)
        cfg = resolve_editor_config(str(self.root))
        self.assertEqual(cfg["editor_model"], "gemini/gemini-2.5-flash")
        self.assertIsNone(cfg["editor_api_base"])

    def test_c5c_env_config_path_respected(self):
        custom = self.root / "custom_config.yml"
        custom.write_text(
            yaml.dump({
                "models": {"editor_agent": "custom/from-env"},
                "endpoints": {"editor_api": "http://custom:9999/v1"},
            }),
            encoding="utf-8",
        )
        os.environ["AI_FACTORY_CONFIG"] = str(custom)

        cfg = resolve_editor_config(str(self.root))
        self.assertEqual(cfg["editor_model"], "custom/from-env")
        self.assertEqual(cfg["editor_api_base"], "http://custom:9999/v1")


class TestRunApplyAndMain(unittest.TestCase):
    """Integration test suite for run_apply and main CLI entry point."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()

        # Create mock aider binary
        self.mock_aider = self.bin_dir / "aider"
        fake_script = textwrap.dedent("""\
            #!/usr/bin/env python3
            import sys
            from pathlib import Path
            print("Mock Aider running...")
            # Modify target file to simulate edit
            for arg in sys.argv:
                if arg.endswith(".py") and not arg.startswith("-"):
                    Path(arg).write_text("# edited by mock aider\\n")
            sys.exit(0)
        """)
        self.mock_aider.write_text(fake_script, encoding="utf-8")
        self.mock_aider.chmod(self.mock_aider.stat().st_mode | stat.S_IEXEC)

        # Create mock git binary
        self.mock_git = self.bin_dir / "git"
        fake_git = textwrap.dedent("""\
            #!/usr/bin/env python3
            import sys
            if "diff" in sys.argv:
                print("diff --git a/test.py b/test.py")
                print("+ # edited by mock aider")
            sys.exit(0)
        """)
        self.mock_git.write_text(fake_git, encoding="utf-8")
        self.mock_git.chmod(self.mock_git.stat().st_mode | stat.S_IEXEC)

        self._orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}:{self._orig_path}"

    def tearDown(self):
        os.environ["PATH"] = self._orig_path
        self._tmp.cleanup()

    def test_run_apply_success(self):
        target_file = self.root / "target.py"
        target_file.write_text("# original\\n", encoding="utf-8")

        spec_file = self.root / "spec.md"
        spec_file.write_text("Refactor target.py\\n", encoding="utf-8")

        success = run_apply(
            files=[str(target_file)],
            spec_file=str(spec_file),
            no_diff=True,
            cwd=str(self.root),
        )
        self.assertTrue(success)
        self.assertEqual(target_file.read_text(encoding="utf-8"), "# edited by mock aider\n")

    def test_main_cli_entrypoint(self):
        target_file = self.root / "main_target.py"
        target_file.write_text("# original\\n", encoding="utf-8")

        spec_file = self.root / "spec.md"
        spec_file.write_text("Update file\\n", encoding="utf-8")

        cmd = [
            sys.executable,
            os.path.join(python_module_dir, "apply_agent.py"),
            str(target_file),
            "--spec",
            str(spec_file),
            "--no-diff",
        ]
        res = subprocess.run(cmd, cwd=str(self.root), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(target_file.read_text(encoding="utf-8"), "# edited by mock aider\n")

    def test_e2_turns_flag_passed_through(self):
        """--turns 3 must cause parse_chat_history to include 3 turns in spec."""
        sess = self.root / ".aider_factory" / "sessions" / "turns_sess"
        sess.mkdir(parents=True)
        hist = sess / ".aider.chat.history.md"
        hist.write_text(
            "#### Turn one request\nResponse one.\n\n"
            "> Tokens: 1k sent, 2k received\n"
            "#### Turn two request\nResponse two.\n\n"
            "> Tokens: 1k sent, 2k received\n"
            "#### Turn three request\nResponse three.\n\n"
            "> Tokens: 1k sent, 2k received\n",
            encoding="utf-8",
        )
        target = self.root / "turns_target.py"
        target.write_text("# original\n", encoding="utf-8")

        cmd = [
            sys.executable,
            os.path.join(python_module_dir, "apply_agent.py"),
            str(target),
            "--session", "turns_sess",
            "--turns", "3",
            "--no-diff",
        ]
        res = subprocess.run(cmd, cwd=str(self.root), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"stderr: {res.stderr}")

        active_spec = self.root / ".aider_factory" / "temp" / "active_spec.md"
        self.assertTrue(active_spec.exists())
        spec_text = active_spec.read_text(encoding="utf-8")
        self.assertIn("Turn one request", spec_text)
        self.assertIn("Turn two request", spec_text)
        self.assertIn("Turn three request", spec_text)
        self.assertIn("Prior Context Turn 1", spec_text)
        self.assertIn("Active Directive", spec_text)

    def test_e3_session_flag_selects_correct_history(self):
        """--session flag must target the specified session's history file."""
        sess_a = self.root / ".aider_factory" / "sessions" / "sess_alpha"
        sess_b = self.root / ".aider_factory" / "sessions" / "sess_beta"
        sess_a.mkdir(parents=True)
        sess_b.mkdir(parents=True)
        (sess_a / ".aider.chat.history.md").write_text(
            "#### ALPHA_MARKER_SPEC\nAlpha response.\n\n"
            "> Tokens: 1k sent, 2k received\n",
            encoding="utf-8",
        )
        (sess_b / ".aider.chat.history.md").write_text(
            "#### BETA_MARKER_SPEC\nBeta response.\n\n"
            "> Tokens: 1k sent, 2k received\n",
            encoding="utf-8",
        )
        target = self.root / "sess_target.py"
        target.write_text("# original\n", encoding="utf-8")

        cmd = [
            sys.executable,
            os.path.join(python_module_dir, "apply_agent.py"),
            str(target),
            "--session", "sess_alpha",
            "--no-diff",
        ]
        res = subprocess.run(cmd, cwd=str(self.root), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"stderr: {res.stderr}")

        active_spec = self.root / ".aider_factory" / "temp" / "active_spec.md"
        spec_text = active_spec.read_text(encoding="utf-8")
        self.assertIn("ALPHA_MARKER_SPEC", spec_text)
        self.assertNotIn("BETA_MARKER_SPEC", spec_text)


class TestRunApplyGaps(unittest.TestCase):
    """Fill gaps D2–D10 for run_apply()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()

        self._env_dump = self.root / "aider_env_dump.txt"
        fake_aider = textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import os, sys
            from pathlib import Path
            with open(r"{self._env_dump}", "w") as f:
                for k, v in sorted(os.environ.items()):
                    f.write(f"{{k}}={{v}}\\n")
            for arg in sys.argv:
                if arg.endswith(".py") and not arg.startswith("-"):
                    Path(arg).write_text("# edited\\n")
            sys.exit(int(os.environ.get("AIDER_FAKE_EXIT", "0")))
        """)
        self.mock_aider = self.bin_dir / "aider"
        self.mock_aider.write_text(fake_aider, encoding="utf-8")
        self.mock_aider.chmod(self.mock_aider.stat().st_mode | stat.S_IEXEC)

        self.mock_git = self.bin_dir / "git"
        fake_git = textwrap.dedent("""\
            #!/usr/bin/env python3
            import sys
            if "diff" in sys.argv:
                print("diff --git FAKE_DIFF_MARKER b/test.py")
                print("+ edited line")
            sys.exit(0)
        """)
        self.mock_git.write_text(fake_git, encoding="utf-8")
        self.mock_git.chmod(self.mock_git.stat().st_mode | stat.S_IEXEC)

        self._orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}:{self._orig_path}"
        self._orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        os.environ["PATH"] = f"{self.bin_dir}:{self._orig_path}"
        self._tmp.cleanup()

    def _make_target_and_spec(self):
        target = self.root / "target.py"
        target.write_text("# original\n", encoding="utf-8")
        spec = self.root / "spec.md"
        spec.write_text("Refactor this file.\n", encoding="utf-8")
        return target, spec

    def test_d2_spec_missing_falls_back_to_chat(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        sess = af / "sessions" / "fallback_sess"
        sess.mkdir(parents=True)
        hist = sess / ".aider.chat.history.md"
        hist.write_text(
            "#### Fix the bug\nApply patch.\n\n> Tokens: 1k sent, 2k received\n",
            encoding="utf-8",
        )
        target = self.root / "target.py"
        target.write_text("# original\n", encoding="utf-8")

        success = run_apply(
            files=[str(target)],
            spec_file=str(self.root / "nonexistent_spec.md"),
            session_name="fallback_sess",
            no_diff=True,
            cwd=str(self.root),
        )
        self.assertTrue(success)
        active_spec = af / "temp" / "active_spec.md"
        self.assertTrue(active_spec.exists())
        spec_text = active_spec.read_text(encoding="utf-8")
        self.assertIn("Fix the bug", spec_text)

    def test_d3_no_chat_history_returns_false(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        target = self.root / "target.py"
        target.write_text("# original\n", encoding="utf-8")

        os.environ.pop("AI_FACTORY_SESSION", None)
        success = run_apply(
            files=[str(target)],
            spec_file=None,
            no_diff=True,
            cwd=str(self.root),
        )
        self.assertFalse(success)

    def test_d4_empty_parsed_spec_returns_false(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        sess = af / "sessions" / "empty_sess"
        sess.mkdir(parents=True)
        (sess / ".aider.chat.history.md").write_text(
            "No token anchors here at all.\n", encoding="utf-8"
        )
        target = self.root / "target.py"
        target.write_text("# original\n", encoding="utf-8")

        success = run_apply(
            files=[str(target)],
            spec_file=None,
            session_name="empty_sess",
            no_diff=True,
            cwd=str(self.root),
        )
        self.assertFalse(success)

    def test_d5_aider_nonzero_exit_returns_false(self):
        target, spec = self._make_target_and_spec()
        os.environ["AIDER_FAKE_EXIT"] = "42"
        try:
            success = run_apply(
                files=[str(target)],
                spec_file=str(spec),
                no_diff=True,
                cwd=str(self.root),
            )
            self.assertFalse(success)
        finally:
            os.environ.pop("AIDER_FAKE_EXIT", None)

    def test_d6_active_spec_written(self):
        target, spec = self._make_target_and_spec()
        spec.write_text("UNIQUE_SPEC_CONTENT_12345\n", encoding="utf-8")

        run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            cwd=str(self.root),
        )
        active_spec = self.root / ".aider_factory" / "temp" / "active_spec.md"
        self.assertTrue(active_spec.exists())
        self.assertIn("UNIQUE_SPEC_CONTENT_12345", active_spec.read_text(encoding="utf-8"))

    def test_d7_no_diff_suppresses_output(self):
        target, spec = self._make_target_and_spec()
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            run_apply(
                files=[str(target)],
                spec_file=str(spec),
                no_diff=True,
                cwd=str(self.root),
            )
        self.assertNotIn("Git Diff Result", buf.getvalue())

    def test_d8_diff_present_on_stdout(self):
        target, spec = self._make_target_and_spec()

        # redirect_stdout only captures Python print(), not subprocess fd writes.
        # Use os.dup2 to redirect OS fd 1 so git subprocess output is captured.
        capture_path = self.root / "stdout_capture.txt"
        saved_fd = os.dup(1)
        try:
            with open(capture_path, "w") as capture_fh:
                os.dup2(capture_fh.fileno(), 1)
                run_apply(
                    files=[str(target)],
                    spec_file=str(spec),
                    no_diff=False,
                    cwd=str(self.root),
                )
                # Force Python's buffered sys.stdout to flush into redirected fd 1
                # before we restore the original fd.
                sys.stdout.flush()
        finally:
            os.dup2(saved_fd, 1)
            os.close(saved_fd)

        output = capture_path.read_text(encoding="utf-8")
        self.assertIn("Git Diff Result", output)
        self.assertIn("FAKE_DIFF_MARKER", output)

    def test_d9_architect_false_in_env(self):
        target, spec = self._make_target_and_spec()
        run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            cwd=str(self.root),
        )
        self.assertTrue(self._env_dump.exists())
        env_text = self._env_dump.read_text(encoding="utf-8")
        self.assertIn("AIDER_ARCHITECT=false", env_text)

    def test_d10_api_base_propagation(self):
        af = self.root / ".aider_factory"
        af.mkdir(parents=True)
        (af / ".env.yml").write_text(
            yaml.dump({"endpoints": {"editor_api": "http://my-proxy:4000/v1"}}),
            encoding="utf-8",
        )
        target = self.root / "target.py"
        target.write_text("# original\n", encoding="utf-8")
        spec = self.root / "spec.md"
        spec.write_text("Do something.\n", encoding="utf-8")

        os.environ.pop("AI_FACTORY_CONFIG", None)
        run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            cwd=str(self.root),
        )
        env_text = self._env_dump.read_text(encoding="utf-8")
        self.assertIn("OPENAI_API_BASE=http://my-proxy:4000/v1", env_text)
        self.assertIn("OLLAMA_API_BASE=http://my-proxy:4000/v1", env_text)
        self.assertIn("LM_STUDIO_API_BASE=http://my-proxy:4000/v1", env_text)


# ===========================================================================
# --stream flag tests: S1–S6
# ===========================================================================

class TestStreamFlag(unittest.TestCase):
    """Tests for the --stream flag added to run_apply() and main()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()

        # Fake aider that emits noisy output to stdout (simulating inner aider)
        self._env_dump = self.root / "aider_env_dump.txt"
        fake_aider = textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import os, sys
            from pathlib import Path
            # Emit noisy content to stdout (what inner aider would do)
            for i in range(500):
                print(f"NOISE_LINE_{{i}}: file echo and thinking block content")
            # Dump env
            with open(r"{self._env_dump}", "w") as f:
                for k, v in sorted(os.environ.items()):
                    f.write(f"{{k}}={{v}}\\n")
            # Edit target files
            for arg in sys.argv:
                if arg.endswith(".py") and not arg.startswith("-"):
                    Path(arg).write_text("# edited\\n")
            sys.exit(0)
        """)
        self.mock_aider = self.bin_dir / "aider"
        self.mock_aider.write_text(fake_aider, encoding="utf-8")
        self.mock_aider.chmod(self.mock_aider.stat().st_mode | stat.S_IEXEC)

        # Fake git
        self.mock_git = self.bin_dir / "git"
        fake_git = textwrap.dedent("""\
            #!/usr/bin/env python3
            import sys
            if "diff" in sys.argv:
                print("diff --git STREAM_TEST_MARKER b/test.py")
                print("+ edited line")
            sys.exit(0)
        """)
        self.mock_git.write_text(fake_git, encoding="utf-8")
        self.mock_git.chmod(self.mock_git.stat().st_mode | stat.S_IEXEC)

        self._orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}:{self._orig_path}"
        self._orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        os.environ["PATH"] = self._orig_path
        self._tmp.cleanup()

    def _make_target_and_spec(self):
        target = self.root / "target.py"
        target.write_text("# original\n", encoding="utf-8")
        spec = self.root / "spec.md"
        spec.write_text("Do the thing.\n", encoding="utf-8")
        return target, spec

    # --- S1: Default (stream=False) — inner aider noise does NOT reach stdout
    def test_s1_default_silent_stdout_only_has_diff(self):
        target, spec = self._make_target_and_spec()

        capture_path = self.root / "stdout_capture.txt"
        saved_fd = os.dup(1)
        try:
            with open(capture_path, "w") as capture_fh:
                os.dup2(capture_fh.fileno(), 1)
                run_apply(
                    files=[str(target)],
                    spec_file=str(spec),
                    no_diff=False,
                    stream=False,
                    cwd=str(self.root),
                )
                sys.stdout.flush()
        finally:
            os.dup2(saved_fd, 1)
            os.close(saved_fd)

        output = capture_path.read_text(encoding="utf-8")
        # Git diff IS present
        self.assertIn("Git Diff Result", output)
        self.assertIn("STREAM_TEST_MARKER", output)
        # Inner aider noise is NOT present
        self.assertNotIn("NOISE_LINE_", output)

    # --- S2: stream=True — completes successfully, git diff still on stdout
    def test_s2_stream_flag_completes_and_diff_present(self):
        target, spec = self._make_target_and_spec()

        capture_path = self.root / "stdout_capture.txt"
        saved_fd = os.dup(1)
        try:
            with open(capture_path, "w") as capture_fh:
                os.dup2(capture_fh.fileno(), 1)
                run_apply(
                    files=[str(target)],
                    spec_file=str(spec),
                    no_diff=False,
                    stream=True,
                    cwd=str(self.root),
                )
                sys.stdout.flush()
        finally:
            os.dup2(saved_fd, 1)
            os.close(saved_fd)

        output = capture_path.read_text(encoding="utf-8")
        # Git diff IS present (goes to stdout regardless of stream mode)
        self.assertIn("Git Diff Result", output)
        self.assertIn("STREAM_TEST_MARKER", output)
        # Inner aider noise goes to /dev/tty (or discarded if no TTY), NOT stdout
        self.assertNotIn("NOISE_LINE_", output)

    # --- S3: stream=False with large output does NOT deadlock (pipe drained)
    def test_s3_large_output_no_deadlock(self):
        """500 lines of output must be drained without hanging."""
        target, spec = self._make_target_and_spec()

        # run_apply must complete within a reasonable time (no deadlock)
        import time
        start = time.monotonic()
        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=False,
            cwd=str(self.root),
        )
        elapsed = time.monotonic() - start
        self.assertTrue(success)
        # Should complete well under 5 seconds (no pipe-buffer stall)
        self.assertLess(elapsed, 5.0)

    # --- S4: stream=True with no TTY available falls back gracefully
    def test_s4_stream_no_tty_falls_back(self):
        """When /dev/tty is unavailable, stream=True must not crash."""
        target, spec = self._make_target_and_spec()

        # In CI/headless, /dev/tty may not exist. The code handles OSError.
        # We just verify it completes without exception.
        success = run_apply(
            files=[str(target)],
            spec_file=str(spec),
            no_diff=True,
            stream=True,
            cwd=str(self.root),
        )
        self.assertTrue(success)

    # --- S5: CLI --stream flag is accepted and threaded to run_apply
    def test_s5_cli_stream_flag_accepted(self):
        target, spec = self._make_target_and_spec()

        cmd = [
            sys.executable,
            os.path.join(python_module_dir, "apply_agent.py"),
            str(target),
            "--spec", str(spec),
            "--no-diff",
            "--stream",
        ]
        res = subprocess.run(cmd, cwd=str(self.root), capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, f"stderr: {res.stderr}")
        # Target was edited
        self.assertEqual(target.read_text(encoding="utf-8"), "# edited\n")

    # --- S6: CLI without --stream also works (default silent)
    def test_s6_cli_without_stream_default(self):
        target, spec = self._make_target_and_spec()

        cmd = [
            sys.executable,
            os.path.join(python_module_dir, "apply_agent.py"),
            str(target),
            "--spec", str(spec),
            "--no-diff",
        ]
        res = subprocess.run(cmd, cwd=str(self.root), capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, f"stderr: {res.stderr}")
        self.assertEqual(target.read_text(encoding="utf-8"), "# edited\n")
        # stdout should NOT contain inner aider noise
        self.assertNotIn("NOISE_LINE_", res.stdout)


if __name__ == "__main__":
    unittest.main()
