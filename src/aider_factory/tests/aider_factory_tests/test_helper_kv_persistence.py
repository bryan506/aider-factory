#!/usr/bin/env python3
"""test_helper_kv_persistence.py — Unit tests verifying KV-cache prefix parity and
session persistence in aider-helper (bootstrap.py).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

script_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
if python_dir not in sys.path:
    sys.path.insert(0, python_dir)

import bootstrap


class MockStreamChunk:
    def __init__(self, content="", usage=None):
        self.choices = [MagicMock(delta=MagicMock(content=content))] if content else []
        self.usage = usage


def _create_mock_stream(text="Mocked assistant response."):
    chunks = [MockStreamChunk(content=text)]
    usage_mock = MagicMock(prompt_tokens=150, completion_tokens=30)
    chunks.append(MockStreamChunk(content="", usage=usage_mock))
    return iter(chunks)


class TestHelperKVPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        os.environ["AIDER_HELPER_API_BASE"] = "http://localhost:8080/v1"
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        os.makedirs(".aider_factory", exist_ok=True)
        with open(os.path.join(".aider_factory", ".env.yml"), "w", encoding="utf-8") as f:
            f.write('name: "My Project"\nworking_directory: "/path/to/project"\n')

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("litellm.completion")
    def test_helper_multi_turn_prefix_parity(self, mock_completion):
        """Verify multi-turn queries maintain strict byte-for-byte prefix parity for KV cache."""
        captured_messages = []

        def fake_completion(**kwargs):
            # Capture a deep copy of messages sent to litellm
            msgs = [dict(m) for m in kwargs["messages"]]
            captured_messages.append(msgs)
            # Verify session header is pinned
            custom_headers = kwargs.get("custom_headers", {})
            self.assertIn("x-litellm-session-id", custom_headers)
            return _create_mock_stream("Response for turn")

        mock_completion.side_effect = fake_completion

        # Turn 1: Ask a question
        bootstrap.run_query("What is the active architect model?", None, "", ask_mode=True)
        self.assertEqual(len(captured_messages), 1)
        turn_1_msgs = captured_messages[0]

        # Verify Turn 1 structure: System prompt + User prompt
        self.assertEqual(turn_1_msgs[0]["role"], "system")
        self.assertEqual(turn_1_msgs[1]["role"], "user")
        self.assertIn("<question>\nWhat is the active architect model?\n</question>", turn_1_msgs[1]["content"])

        # Turn 2: Follow-up question
        bootstrap.run_query("Change architect model to gemini-2.5-flash", None, "", ask_mode=False)
        self.assertEqual(len(captured_messages), 2)
        turn_2_msgs = captured_messages[1]

        # Invariant: Turn 2's prefix MUST strictly match Turn 1's messages + Turn 1's assistant reply
        self.assertEqual(turn_2_msgs[0], turn_1_msgs[0])  # System prompt identical
        self.assertEqual(turn_2_msgs[1], turn_1_msgs[1])  # Turn 1 user prompt identical
        self.assertEqual(turn_2_msgs[2]["role"], "assistant")  # Turn 1 assistant reply
        self.assertEqual(turn_2_msgs[3]["role"], "user")  # Turn 2 user prompt
        self.assertIn("<question>\nChange architect model to gemini-2.5-flash\n</question>", turn_2_msgs[3]["content"])

        # Turn 3: Follow-up in ask mode
        bootstrap.run_query("Confirm the change.", None, "", ask_mode=True)
        self.assertEqual(len(captured_messages), 3)
        turn_3_msgs = captured_messages[2]

        # Verify prefix retention across 3 turns
        self.assertEqual(turn_3_msgs[:4], turn_2_msgs[:4])
        self.assertEqual(turn_3_msgs[4]["role"], "assistant")
        self.assertEqual(turn_3_msgs[5]["role"], "user")

    @patch("litellm.completion")
    def test_helper_context_append_only_no_duplicate_injection(self, mock_completion):
        """Verify heavy context (--master) appends once and is not re-injected on follow-up turns."""
        captured_messages = []

        def fake_completion(**kwargs):
            captured_messages.append([dict(m) for m in kwargs["messages"]])
            return _create_mock_stream("Skills analysis.")

        mock_completion.side_effect = fake_completion

        # Turn 1: Query with --master
        bootstrap.run_query("Explain oracle debate loops.", None, "", ask_mode=True, master_mode=True)
        self.assertEqual(len(captured_messages), 1)
        turn_1_content = captured_messages[0][1]["content"]
        self.assertIn("<skills_reference>", turn_1_content)

        # Turn 2: Follow-up without --master
        bootstrap.run_query("How many turns should I use?", None, "", ask_mode=True, master_mode=False)
        self.assertEqual(len(captured_messages), 2)
        turn_2_new_user_msg = captured_messages[1][3]["content"]

        # Invariant: Turn 2's new user turn must NOT duplicate <skills_reference>
        self.assertNotIn("<skills_reference>", turn_2_new_user_msg)
        # But Turn 1 in history still holds it
        self.assertIn("<skills_reference>", captured_messages[1][1]["content"])

    @patch("litellm.completion")
    def test_helper_terminal_session_isolation(self, mock_completion):
        """Verify terminal assistant (-t) and standard config sessions use isolated history files."""
        mock_completion.side_effect = lambda **kwargs: _create_mock_stream("Terminal reply.")

        # Standard config query
        bootstrap.run_query("What is the editor model?", None, "", ask_mode=True, terminal_mode=False)
        config_session = os.path.join(".aider_factory", ".helper_session.json")
        terminal_session = os.path.join(".aider_factory", ".helper_terminal_session.json")

        self.assertTrue(os.path.exists(config_session))
        self.assertFalse(os.path.exists(terminal_session))

        # Terminal query
        bootstrap.run_query("How do I write a bash loop?", None, "", ask_mode=True, terminal_mode=True)
        self.assertTrue(os.path.exists(terminal_session))

        # Verify terminal session uses TERMINAL_PERSONA_PROMPT
        with open(terminal_session, "r", encoding="utf-8") as f:
            term_msgs = json.load(f)
        self.assertEqual(term_msgs[0]["content"], bootstrap.TERMINAL_PERSONA_PROMPT)

        # Clear terminal session only
        bootstrap.clear_helper_session(terminal_mode=True)
        self.assertFalse(os.path.exists(terminal_session))
        self.assertTrue(os.path.exists(config_session))

        # Clear config session
        bootstrap.clear_helper_session(terminal_mode=False)
        self.assertFalse(os.path.exists(config_session))


if __name__ == "__main__":
    unittest.main()
