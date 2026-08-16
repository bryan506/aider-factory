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


def test_explicit_collection_overrides_leaked_db_dir():
    for k in ["ORACLE_COLLECTION", "ORACLE_RAG_DB_DIR", "ORACLE_EXPLICIT_COLLECTION"]:
        os.environ.pop(k, None)

    # Simulate a leaked environment variable from a previous run
    os.environ["ORACLE_RAG_DB_DIR"] = "/some/leaked/path/Aider_Factory_DB/lancedb"

    args = ["--collection", "Docling_DB", "query"]
    oracle_agent._extract_overrides(args)

    assert os.environ.get("ORACLE_RAG_DB_DIR") != "/some/leaked/path/Aider_Factory_DB/lancedb"
    assert "Docling_DB" in os.environ.get("ORACLE_RAG_DB_DIR")
    print("  ✅ --collection explicitly overrides leaked ORACLE_RAG_DB_DIR.")


def test_explicit_collection_override_preserves_rag_db_dir():
    for k in ["ORACLE_COLLECTION", "ORACLE_RAG_DB_DIR", "ORACLE_EXPLICIT_COLLECTION"]:
        os.environ.pop(k, None)

    args = ["--collection", "Custom_DB", "What is the leverage formula?"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert os.environ.get("ORACLE_EXPLICIT_COLLECTION") == "1"
    assert os.environ.get("ORACLE_COLLECTION") == "Custom_DB"
    expected_db = os.path.join(os.getcwd(), ".aider_factory", "markdown", "lanceDB", "Custom_DB", "lancedb")
    assert os.environ.get("ORACLE_RAG_DB_DIR") == expected_db

    fake_yaml = {
        "phases": [
            {"enabled": True, "rag": {"collection_name": "Default_YAML_DB"}}
        ]
    }
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open"), \
         patch("yaml.safe_load", return_value=fake_yaml):
        oracle_agent._ensure_oracle_config()

    assert os.environ.get("ORACLE_COLLECTION") == "Custom_DB", "Explicit collection was overwritten by YAML default!"
    assert os.environ.get("ORACLE_RAG_DB_DIR") == expected_db, "Explicit DB path was overwritten by YAML default!"
    print("  ✅ explicit --collection override is preserved across _ensure_oracle_config.")


def test_standard_mode():
    if "ORACLE_RETRIEVE_MODE" in os.environ:
        del os.environ["ORACLE_RETRIEVE_MODE"]

    args = ["--mode", "full_document", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["Query"]
    assert os.environ.get("ORACLE_RETRIEVE_MODE") == "full_document"
    assert do_list is False
    print("  ✅ standard --mode parsing still works.")


def test_oracle_xml_prompt_formatting():
    for k in ["ORACLE_SESSION_FILE", "ORACLE_CONTEXT_FILES", "ORACLE_AGENT_MODEL", "ORACLE_RETRIEVE_MODE"]:
        os.environ.pop(k, None)

    # Isolate session to prevent reading leaked user sessions
    os.environ["ORACLE_SESSION_FILE"] = os.path.join(tempfile.gettempdir(), "isolated_test_session_xml.json")

    ctx_file = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    ctx_file.write("System instructions")
    ctx_file.close()

    os.environ["ORACLE_CONTEXT_FILES"] = ctx_file.name
    os.environ["ORACLE_AGENT_MODEL"] = "mock-model"
    os.environ["ORACLE_RETRIEVE_MODE"] = "top_k"

    captured_kwargs = []
    def mock_completion(**kwargs):
        captured_kwargs.append(kwargs)
        return {"choices": [{"message": {"content": "Mock answer"}}], "usage": {}}

    try:
        with patch.object(sys, "argv", ["oracle", "What is docling?"]), \
             patch("litellm.completion", side_effect=mock_completion), \
             patch("oracle_agent._retrieve", return_value="[source: doc | docling.md]\nDocling is a parser."):
            oracle_agent.main()

        user_msg = captured_kwargs[0]["messages"][1]["content"]
        assert "<project_files>" in user_msg
        assert "<knowledge_base>" in user_msg
        assert "<question>" in user_msg
        assert "System instructions" in user_msg
        assert "Docling is a parser." in user_msg
        print("  ✅ Oracle correctly formats prompts with XML tags.")
    finally:
        os.remove(ctx_file.name)
        if os.path.exists(os.environ["ORACLE_SESSION_FILE"]):
            os.remove(os.environ["ORACLE_SESSION_FILE"])
        for k in ["ORACLE_SESSION_FILE", "ORACLE_CONTEXT_FILES", "ORACLE_AGENT_MODEL", "ORACLE_RETRIEVE_MODE"]:
            os.environ.pop(k, None)


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
        assert "<knowledge_base>" in t1_user_msg
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


def test_oracle_prints_source_files_to_stderr():
    for k in ["ORACLE_SESSION_FILE", "ORACLE_AGENT_MODEL", "ORACLE_RETRIEVE_MODE"]:
        os.environ.pop(k, None)
        
    os.environ["ORACLE_SESSION_FILE"] = os.path.join(tempfile.gettempdir(), "isolated_test_session_stderr.json")
    os.environ["ORACLE_AGENT_MODEL"] = "mock-model"
    os.environ["ORACLE_RETRIEVE_MODE"] = "top_k"

    def mock_completion(**kwargs):
        return {"choices": [{"message": {"content": "Mock answer"}}], "usage": {}}

    import io
    captured_stderr = io.StringIO()

    try:
        with patch.object(sys, "argv", ["oracle", "query"]), \
             patch("litellm.completion", side_effect=mock_completion), \
             patch("oracle_agent._retrieve", return_value="[source: doc | docling_api.md]\nAPI details"), \
             patch("sys.stderr", captured_stderr):
            oracle_agent.main()

        output = captured_stderr.getvalue()
        assert "1 source chunk(s) from 1 file(s): docling_api.md" in output
        print("  ✅ Oracle prints unique source filenames to stderr.")
    finally:
        if os.path.exists(os.environ["ORACLE_SESSION_FILE"]):
            os.remove(os.environ["ORACLE_SESSION_FILE"])
        for k in ["ORACLE_SESSION_FILE", "ORACLE_AGENT_MODEL", "ORACLE_RETRIEVE_MODE"]:
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
    test_explicit_collection_overrides_leaked_db_dir()
    test_explicit_collection_override_preserves_rag_db_dir()
    test_no_rag_absolute_override()
    test_standard_mode()
    test_oracle_xml_prompt_formatting()
    test_oracle_prints_source_files_to_stderr()
    test_oracle_session_context_not_duplicated()
    test_oracle_passes_session_id()
    print("\n🎉 All CLI Oracle Tests Passed!")
