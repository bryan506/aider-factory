import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
import yaml

from aider_factory.python.apply_agent import (
    parse_chat_history,
    find_active_session_chat_history,
    resolve_editor_config,
    run_apply,
)


class TestApplyAgentUnit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        self.old_env = dict(os.environ)

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_chat_history_single_turn(self):
        history_content = """
#### /ask Refactor the parser
<thinking-content-1234>
Analyzing the parser logic...
</thinking-content-1234>
► ANSWER
Here is the implementation plan:
1. Add zero-division guard.
2. Return None on empty list.

> Tokens: 1.2k sent, 300 received. Cost: $0.001 message, $0.01 session.
"""
        chat_path = os.path.join(self.temp_dir, "test.chat.history.md")
        with open(chat_path, "w", encoding="utf-8") as f:
            f.write(history_content)

        spec = parse_chat_history(chat_path, turns=1)
        self.assertIn("# Directive\nRefactor the parser", spec)
        self.assertIn("# Specification & Implementation Plan", spec)
        self.assertIn("1. Add zero-division guard.", spec)
        self.assertNotIn("thinking-content", spec)
        self.assertNotIn("► ANSWER", spec)
        self.assertNotIn("Tokens:", spec)

    def test_parse_chat_history_multi_turn(self):
        history_content = """
#### /ask First turn prompt
First turn assistant output.

> Tokens: 100 sent, 50 received. Cost: $0.001 message, $0.001 session.

#### /ask Second turn prompt
Second turn assistant output.

> Tokens: 200 sent, 100 received. Cost: $0.002 message, $0.003 session.
"""
        chat_path = os.path.join(self.temp_dir, "multi.chat.history.md")
        with open(chat_path, "w", encoding="utf-8") as f:
            f.write(history_content)

        spec = parse_chat_history(chat_path, turns=2)
        self.assertIn("## Prior Context Turn 1", spec)
        self.assertIn("First turn prompt", spec)
        self.assertIn("First turn assistant output.", spec)
        self.assertIn("## Active Directive", spec)
        self.assertIn("Second turn prompt", spec)
        self.assertIn("Second turn assistant output.", spec)

    def test_parse_chat_history_slash_commands_and_tools_filtered(self):
        history_content = """
#### /add src/parser.py
#### /run pytest
#### /ask Update parser logic
> Added src/parser.py to the chat.
> No files matched pattern.
Here is the updated logic.

> Tokens: 500 sent, 200 received. Cost: $0.005 message, $0.005 session.
"""
        chat_path = os.path.join(self.temp_dir, "filtered.chat.history.md")
        with open(chat_path, "w", encoding="utf-8") as f:
            f.write(history_content)

        spec = parse_chat_history(chat_path, turns=1)
        self.assertIn("# Directive\nUpdate parser logic", spec)
        self.assertIn("Here is the updated logic.", spec)
        self.assertNotIn("> Added src/parser.py", spec)
        self.assertNotIn("> No files matched", spec)

    def test_parse_chat_history_thinking_and_markers_stripped(self):
        history_content = """
#### /ask Refactor math functions
<think>Thinking about edge cases...</think>
<thinking-content-abcd>Deep thinking block...</thinking-content-abcd>
► **ANSWER**
Plan:
- Fix divide function.

> Tokens: 300 sent, 80 received.
"""
        chat_path = os.path.join(self.temp_dir, "think.chat.history.md")
        with open(chat_path, "w", encoding="utf-8") as f:
            f.write(history_content)

        spec = parse_chat_history(chat_path, turns=1)
        self.assertNotIn("Thinking about edge cases", spec)
        self.assertNotIn("Deep thinking block", spec)
        self.assertNotIn("► **ANSWER**", spec)
        self.assertIn("- Fix divide function.", spec)

    def test_parse_chat_history_user_prompt_with_blank_lines_and_subheaders(self):
        history_content = """
#### Fix bug in parser
#### 
#### More details in user prompt.

#### Subheader in Assistant Output
Details on the fix.

> Tokens: 400 sent, 100 received.
"""
        chat_path = os.path.join(self.temp_dir, "subheaders.chat.history.md")
        with open(chat_path, "w", encoding="utf-8") as f:
            f.write(history_content)

        spec = parse_chat_history(chat_path, turns=1)
        self.assertIn("Fix bug in parser\n\nMore details in user prompt.", spec)
        self.assertIn("#### Subheader in Assistant Output", spec)

    def test_find_active_session_chat_history_priority(self):
        af_dir = os.path.join(self.temp_dir, ".aider_factory")
        sess_dir1 = os.path.join(af_dir, "sessions", "sess1")
        sess_dir2 = os.path.join(af_dir, "sessions", "sess2")
        os.makedirs(sess_dir1, exist_ok=True)
        os.makedirs(sess_dir2, exist_ok=True)

        h1 = os.path.join(sess_dir1, ".aider.chat.history.md")
        h2 = os.path.join(sess_dir2, ".aider.chat.history.md")
        root_h = os.path.join(af_dir, ".aider.chat.history.md")

        with open(h1, "w") as f:
            f.write("sess1 history")
        time.sleep(0.01)
        with open(h2, "w") as f:
            f.write("sess2 history")
        with open(root_h, "w") as f:
            f.write("root history")

        # Priority 1: Explicit session argument
        path, sess = find_active_session_chat_history(self.temp_dir, session_name="sess1")
        self.assertEqual(path, h1)
        self.assertEqual(sess, "sess1")

        # Priority 2: AI_FACTORY_SESSION env var
        os.environ["AI_FACTORY_SESSION"] = "sess1"
        path, sess = find_active_session_chat_history(self.temp_dir)
        self.assertEqual(path, h1)
        self.assertEqual(sess, "sess1")
        os.environ.pop("AI_FACTORY_SESSION")

        # Priority 3: mtime discovery (sess2 is newer)
        path, sess = find_active_session_chat_history(self.temp_dir)
        self.assertEqual(path, h2)
        self.assertEqual(sess, "sess2")

        # Priority 4: Fallback to root chat history when no sessions exist
        shutil.rmtree(os.path.join(af_dir, "sessions"))
        path, sess = find_active_session_chat_history(self.temp_dir)
        self.assertEqual(path, root_h)
        self.assertEqual(sess, "")

    def test_resolve_editor_config_hierarchy(self):
        af_dir = os.path.join(self.temp_dir, ".aider_factory")
        sess_dir = os.path.join(af_dir, "sessions", "test_sess")
        os.makedirs(sess_dir, exist_ok=True)

        root_env_yml = os.path.join(self.temp_dir, ".env.yml")
        af_env_yml = os.path.join(af_dir, ".env.yml")
        sess_yml = os.path.join(sess_dir, "session.yml")
        custom_env_yml = os.path.join(self.temp_dir, "custom.env.yml")

        with open(root_env_yml, "w") as f:
            yaml.dump({"models": {"editor_agent": "model_root"}}, f)
        with open(af_env_yml, "w") as f:
            yaml.dump({"models": {"editor_agent": "model_af"}}, f)
        with open(sess_yml, "w") as f:
            yaml.dump({"models": {"editor_agent": "model_sess"}}, f)
        with open(custom_env_yml, "w") as f:
            yaml.dump({"models": {"editor_agent": "model_custom"}}, f)

        # 1. AI_FACTORY_CONFIG takes top precedence
        os.environ["AI_FACTORY_CONFIG"] = custom_env_yml
        cfg = resolve_editor_config(self.temp_dir, session_name="test_sess")
        self.assertEqual(cfg["editor_model"], "model_custom")
        os.environ.pop("AI_FACTORY_CONFIG")

        # 2. Session yml takes precedence over .aider_factory/.env.yml
        cfg = resolve_editor_config(self.temp_dir, session_name="test_sess")
        self.assertEqual(cfg["editor_model"], "model_sess")

        # 3. .aider_factory/.env.yml takes precedence over root .env.yml
        os.remove(sess_yml)
        cfg = resolve_editor_config(self.temp_dir, session_name="test_sess")
        self.assertEqual(cfg["editor_model"], "model_af")

        # 4. Fallback to root .env.yml
        os.remove(af_env_yml)
        cfg = resolve_editor_config(self.temp_dir, session_name="test_sess")
        self.assertEqual(cfg["editor_model"], "model_root")

    def test_parse_chat_history_empty_and_missing_file(self):
        self.assertEqual(parse_chat_history("non_existent_file.md"), "")
        empty_file = os.path.join(self.temp_dir, "empty.md")
        with open(empty_file, "w") as f:
            f.write("")
        self.assertEqual(parse_chat_history(empty_file), "")

    @patch("aider_factory.python.apply_agent.subprocess.run")
    def test_run_apply_failure_returncode(self, mock_sub_run):
        mock_sub_run.return_value.returncode = 1
        spec_file = os.path.join(self.temp_dir, "spec.md")
        with open(spec_file, "w") as f:
            f.write("# Spec\n")
        target_file = os.path.join(self.temp_dir, "target.py")
        with open(target_file, "w") as f:
            f.write("# code\n")
        success = run_apply([target_file], spec_file=spec_file, cwd=self.temp_dir, no_diff=True)
        self.assertFalse(success)

    @patch("aider_factory.python.apply_agent.subprocess.run")
    def test_run_apply_custom_spec_file(self, mock_sub_run):
        mock_sub_run.return_value.returncode = 0

        spec_file = os.path.join(self.temp_dir, "explicit_spec.md")
        with open(spec_file, "w", encoding="utf-8") as f:
            f.write("# Explicit Spec\nRefactor math.py")

        target_file = os.path.join(self.temp_dir, "math.py")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("def add(a, b): return a + b\n")

        success = run_apply([target_file], spec_file=spec_file, cwd=self.temp_dir, no_diff=True)
        self.assertTrue(success)

        # Assert active_spec.md was created in temp dir
        active_spec = os.path.join(self.temp_dir, ".aider_factory", "temp", "active_spec.md")
        self.assertTrue(os.path.isfile(active_spec))
        with open(active_spec, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "# Explicit Spec\nRefactor math.py")

        # Verify subprocess.run command arguments for aider invocation
        self.assertTrue(mock_sub_run.called)
        cmd = mock_sub_run.call_args_list[0][0][0]
        self.assertEqual(cmd[0], "aider")
        self.assertIn("--message-file", cmd)
        self.assertIn(active_spec, cmd)
        self.assertIn(target_file, cmd)


if __name__ == "__main__":
    import sys
    unittest.main(argv=[sys.argv[0]])
