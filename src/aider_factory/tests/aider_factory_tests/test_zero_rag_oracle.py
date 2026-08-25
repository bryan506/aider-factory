#!/usr/bin/env python3
import os
import sys
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
        return self.content if item == "content" else None

    def get(self, item, default=None):
        return self.content if item == "content" else default


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)

    def __getitem__(self, item):
        return self.message if item == "message" else None

    def get(self, item, default=None):
        return self.message if item == "message" else default


class FakeResponse:
    def __init__(self, content="Direct LLM response without RAG."):
        self.choices = [FakeChoice(content)]

    def __getitem__(self, item):
        return self.choices if item == "choices" else None

    def get(self, item, default=None):
        return self.choices if item == "choices" else default


class TestZeroRagOracle(unittest.TestCase):
    def setUp(self):
        self.old_env = dict(os.environ)
        os.environ.pop("ORACLE_NO_RAG_INGEST", None)
        os.environ.pop("ORACLE_RETRIEVE_MODE", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)

    def test_extract_overrides_no_rag_flag(self):
        args = ["--no-rag", "What is the summary?"]
        out, do_list, did_clear, action, target = oracle_agent._extract_overrides(args)

        self.assertEqual(out, ["What is the summary?"])
        self.assertEqual(os.environ.get("ORACLE_NO_RAG_INGEST"), "1")
        self.assertEqual(os.environ.get("ORACLE_RETRIEVE_MODE"), "no_retrieve")

    @patch("litellm.completion")
    def test_oracle_agent_no_retrieve_mode_skips_vector_search(self, mock_completion):
        os.environ["ORACLE_AGENT_MODEL"] = "gemini/gemini-2.5-flash"
        os.environ["ORACLE_RETRIEVE_MODE"] = "no_retrieve"

        mock_completion.return_value = FakeResponse("Direct LLM response without RAG.")

        with patch("oracle_agent._retrieve") as mock_retrieve:
            args = ["oracle_agent.py", "Explain the concept directly."]
            with patch.object(sys, "argv", args):
                oracle_agent.main()

            mock_retrieve.assert_not_called()
            mock_completion.assert_called_once()


if __name__ == "__main__":
    unittest.main()
