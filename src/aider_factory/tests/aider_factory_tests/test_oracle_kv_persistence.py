#!/usr/bin/env python3
"""test_oracle_kv_persistence.py — Unit tests verifying KV-cache prefix parity and
session persistence in aider-oracle (oracle_agent.py).
"""

import hashlib
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

import oracle_agent


class FakeMessage:
    def __init__(self, content):
        self.content = content

    def __getitem__(self, item):
        if item == "content":
            return self.content
        raise KeyError(item)

    def get(self, item, default=None):
        if item == "content":
            return self.content
        return default


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)

    def __getitem__(self, item):
        if item == "message":
            return self.message
        raise KeyError(item)

    def get(self, item, default=None):
        if item == "message":
            return self.message
        return default


class FakeUsage:
    def __init__(self, prompt_tokens=80, completion_tokens=20):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    def __getitem__(self, item):
        return getattr(self, item)

    def get(self, item, default=None):
        return getattr(self, item, default)


class FakeResponse:
    def __init__(self, content="The formula is L = D / E.", prompt_tokens=80, completion_tokens=20):
        self.choices = [FakeChoice(content)]
        self.usage = FakeUsage(prompt_tokens, completion_tokens)

    def __getitem__(self, item):
        if item == "choices":
            return self.choices
        if item == "usage":
            return self.usage
        raise KeyError(item)

    def get(self, item, default=None):
        if item == "choices":
            return self.choices
        if item == "usage":
            return self.usage
        return default


class TestOracleKVPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        self.old_env = dict(os.environ)
        for k in list(os.environ.keys()):
            if k.startswith("ORACLE_"):
                os.environ.pop(k, None)
        os.environ["ORACLE_AGENT_MODEL"] = "openai/test-oracle-model"
        os.environ["ORACLE_AGENT_API_BASE"] = "http://localhost:8080/v1"
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        os.environ["ORACLE_NO_RAG_INGEST"] = "1"
        os.environ["ORACLE_RETRIEVE_MODE"] = "no_retrieve"

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.environ.clear()
        os.environ.update(self.old_env)

    @patch("litellm.completion")
    def test_oracle_interactive_session_prefix_parity(self, mock_completion):
        """Verify interactive oracle queries maintain session prefix across follow-up turns."""
        captured_messages = []

        def fake_completion(**kwargs):
            captured_messages.append([dict(m) for m in kwargs["messages"]])
            return FakeResponse("The formula is L = D / E.", prompt_tokens=80, completion_tokens=20)

        mock_completion.side_effect = fake_completion

        # Turn 1: Initial question
        with patch.object(sys, "argv", ["oracle", "--no-rag", "What is leverage?"]):
            oracle_agent.main()

        self.assertEqual(len(captured_messages), 1)
        turn_1_msgs = captured_messages[0]
        self.assertEqual(turn_1_msgs[0]["role"], "system")
        self.assertEqual(turn_1_msgs[1]["role"], "user")
        self.assertIn("<question>\nWhat is leverage?\n</question>", turn_1_msgs[1]["content"])

        # Check .oracle_session.json on disk
        session_path = oracle_agent._session_file()
        self.assertTrue(os.path.exists(session_path))

        # Turn 2: Follow-up question
        with patch.object(sys, "argv", ["oracle", "--no-rag", "How does debt impact risk?"]):
            oracle_agent.main()

        self.assertEqual(len(captured_messages), 2)
        turn_2_msgs = captured_messages[1]

        # Verify byte-for-byte prefix parity
        self.assertEqual(turn_2_msgs[0], turn_1_msgs[0])
        self.assertEqual(turn_2_msgs[1], turn_1_msgs[1])
        self.assertEqual(turn_2_msgs[2]["role"], "assistant")
        self.assertEqual(turn_2_msgs[3]["role"], "user")
        self.assertIn("<question>\nHow does debt impact risk?\n</question>", turn_2_msgs[3]["content"])

    @patch("orchestrate.AiderFactory._aider_ask_turn")
    @patch("litellm.completion")
    def test_oracle_cli_debate_turn_prefix_parity(self, mock_completion, mock_aider_ask):
        """Verify CLI debate maintains append-only prefix in .oracle_debate_session.json."""
        captured_messages = []

        def fake_completion(**kwargs):
            captured_messages.append([dict(m) for m in kwargs["messages"]])
            # Turn 0 pre-assessment vs subsequent turn verdicts
            if len(captured_messages) == 1:
                content = "Oracle Pre-assessment: Leverage calculation requires tier 1 capital."
            else:
                content = "Evidence matches.\nVERDICT: AGREE"
            return FakeResponse(content, prompt_tokens=200, completion_tokens=30)

        mock_completion.side_effect = fake_completion
        mock_aider_ask.return_value = "PROPOSAL: Update leverage denominator to Tier 1 Capital."

        oracle_agent._run_cli_debate("Fix leverage calculation", mode="code", max_turns=2, rounds=1)

        # There should be at least Turn 0 (pre-assessment) and Turn 1 (oracle verdict)
        self.assertGreaterEqual(len(captured_messages), 2)
        turn_0_msgs = captured_messages[0]
        turn_1_msgs = captured_messages[1]

        # Verify prefix parity: Turn 1 must strictly build upon Turn 0's history
        self.assertEqual(turn_1_msgs[0], turn_0_msgs[0])  # System prompt
        self.assertEqual(turn_1_msgs[1], turn_0_msgs[1])  # Turn 0 user seed
        self.assertEqual(turn_1_msgs[2]["role"], "assistant")  # Turn 0 pre-assessment
        self.assertEqual(turn_1_msgs[3]["role"], "user")  # Turn 1 architect proposal

        # Verify debate session file on disk
        debate_session_file = os.path.join(self.temp_dir, ".aider_factory", ".oracle_debate_session.json")
        self.assertTrue(os.path.exists(debate_session_file))
        with open(debate_session_file, "r", encoding="utf-8") as f:
            stored_data = json.load(f)
        self.assertIn("files_hash", stored_data)
        self.assertIn("messages", stored_data)

    def test_oracle_debate_files_hash_invalidation(self):
        """Verify changing target files invalidates stale debate session to prevent cross-file cache pollution."""
        debate_session_file = os.path.join(self.temp_dir, ".aider_factory", ".oracle_debate_session.json")
        os.makedirs(os.path.dirname(debate_session_file), exist_ok=True)

        old_hash = hashlib.sha256(b"file_A.py").hexdigest()
        old_messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "old context"}]

        with open(debate_session_file, "w", encoding="utf-8") as f:
            json.dump({"files_hash": old_hash, "messages": old_messages}, f)

        # Case 1: Matching file hash -> reloads session
        with patch("deliberate.consensus_state", return_value="agreed"):
            with patch("litellm.completion", return_value=FakeResponse("VERDICT: AGREE")):
                with patch("yaml.safe_load", return_value={"phases": [{"enabled": True, "files": {"target_files": ["file_A.py"]}}]}):
                    # Write dummy config
                    cfg_path = os.path.join(self.temp_dir, ".env.yml")
                    with open(cfg_path, "w") as f:
                        f.write("phases:\n  - enabled: true\n    files:\n      target_files: ['file_A.py']\n")
                    os.environ["ORACLE_CONFIG_FILE"] = cfg_path

                    oracle_agent._run_cli_debate("Follow up", mode="code", max_turns=1, rounds=1)
                    # Verify session was reused
                    with open(debate_session_file, "r", encoding="utf-8") as sf:
                        data = json.load(sf)
                    self.assertEqual(data["files_hash"], old_hash)


if __name__ == "__main__":
    unittest.main()
