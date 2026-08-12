#!/usr/bin/env python3
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "../../python"))

import oracle_agent
from oracle_agent import _extract_overrides

print("Starting Oracle CLI Tests...\n")


def test_no_rag_flag():
    if "ORACLE_RETRIEVE_MODE" in os.environ:
        del os.environ["ORACLE_RETRIEVE_MODE"]

    args = ["--file", "test.txt", "--no-rag", "What is this?"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["--file", "test.txt", "What is this?"], f"Unexpected out: {out}"
    assert os.environ.get("ORACLE_RETRIEVE_MODE") == "no_retrieve", (
        f"Mode was {os.environ.get('ORACLE_RETRIEVE_MODE')}"
    )
    assert do_list is False
    print("  ✅ --no-rag correctly sets ORACLE_RETRIEVE_MODE and filters args.")


def test_no_rag_absolute_override():
    if "ORACLE_RETRIEVE_MODE" in os.environ:
        del os.environ["ORACLE_RETRIEVE_MODE"]

    # Even if --mode top_k is passed, --no-rag should win because it applies at the end of the loop
    args = ["--mode", "top_k", "--no-rag", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["Query"]
    assert os.environ.get("ORACLE_RETRIEVE_MODE") == "no_retrieve"
    assert do_list is False
    print("  ✅ --no-rag acts as an absolute override over --mode.")


def test_standard_mode():
    if "ORACLE_RETRIEVE_MODE" in os.environ:
        del os.environ["ORACLE_RETRIEVE_MODE"]

    args = ["--mode", "full_document", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["Query"]
    assert os.environ.get("ORACLE_RETRIEVE_MODE") == "full_document"
    assert do_list is False
    print("  ✅ standard --mode parsing still works.")


def test_oracle_session_context_not_duplicated():
    """Verify follow-up queries in an active session do not duplicate context blocks."""
    if "ORACLE_RETRIEVE_MODE" in os.environ:
        del os.environ["ORACLE_RETRIEVE_MODE"]

    tmp_session = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp_session.close()

    ctx_file = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    ctx_file.write("Important context file content")
    ctx_file.close()

    try:
        os.environ["ORACLE_SESSION_FILE"] = tmp_session.name
        os.environ["ORACLE_CONTEXT_FILES"] = ctx_file.name
        os.environ["ORACLE_AGENT_MODEL"] = "mock-model"

        if os.path.exists(tmp_session.name):
            os.remove(tmp_session.name)

        captured_kwargs = []

        def mock_completion(**kwargs):
            captured_kwargs.append(kwargs)
            return {
                "choices": [{"message": {"content": "Mock answer"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            }

        # Turn 1
        with patch.object(sys, "argv", ["oracle", "Question 1"]), \
             patch("litellm.completion", side_effect=mock_completion), \
             patch("oracle_agent._retrieve", return_value="Retrieved DB chunk 1"):
            oracle_agent.main()

        # Turn 2 (Follow-up)
        with patch.object(sys, "argv", ["oracle", "Question 2"]), \
             patch("litellm.completion", side_effect=mock_completion), \
             patch("oracle_agent._retrieve", return_value="Retrieved DB chunk 2"):
            oracle_agent.main()

        assert len(captured_kwargs) == 2, f"Expected 2 completion calls, got {len(captured_kwargs)}"

        # Turn 1 message includes CONTEXT block with retrieved chunk 1 and static context file
        t1_user_msg = captured_kwargs[0]["messages"][1]["content"]
        assert "CONTEXT:" in t1_user_msg
        assert "Important context file content" in t1_user_msg
        assert "Retrieved DB chunk 1" in t1_user_msg

        # Turn 2 message includes fresh RAG retrieved chunk 2, but NOT static context files
        t2_user_msg = captured_kwargs[1]["messages"][3]["content"]
        assert "Retrieved DB chunk 2" in t2_user_msg
        assert "Question 2" in t2_user_msg
        assert "Important context file content" not in t2_user_msg

        print("  ✅ multi-turn session context is correctly passed on Turn 1 and NOT duplicated on Turn 2.")

    finally:
        for f in [tmp_session.name, tmp_session.name + ".costs.json", ctx_file.name]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        for k in ["ORACLE_SESSION_FILE", "ORACLE_CONTEXT_FILES", "ORACLE_AGENT_MODEL"]:
            os.environ.pop(k, None)


def test_oracle_passes_session_id():
    if "ORACLE_RETRIEVE_MODE" in os.environ:
        del os.environ["ORACLE_RETRIEVE_MODE"]

    with patch("litellm.completion") as mock_completion:
        mock_resp = MagicMock()
        mock_completion.return_value = mock_resp

        with patch("sys.argv", ["oracle", "test query"]), \
             patch.dict("os.environ", {"ORACLE_AGENT_MODEL": "dummy-model", "ORACLE_RETRIEVE_MODE": "no_retrieve"}), \
             patch("oracle_agent._response_content", return_value="answer"), \
             patch("oracle_agent._litellm_cost_line", return_value=""), \
             patch("oracle_agent._append_transcript"), \
             patch("oracle_agent._validate_oracle_response"):
            
            oracle_agent.main()

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args[1]
        assert "custom_headers" in kwargs, "custom_headers must be passed"
        assert "x-litellm-session-id" in kwargs["custom_headers"], "Session ID must be in headers"
        assert kwargs["custom_headers"]["x-litellm-session-id"] == oracle_agent._PIPELINE_SESSION_ID, "Session ID must match pipeline ID"
    print("  ✅ Session ID is correctly passed to litellm.")


if __name__ == "__main__":
    test_no_rag_flag()
    test_no_rag_absolute_override()
    test_standard_mode()
    test_oracle_session_context_not_duplicated()
    test_oracle_passes_session_id()
    print("\n🎉 All CLI Oracle Tests Passed!")
