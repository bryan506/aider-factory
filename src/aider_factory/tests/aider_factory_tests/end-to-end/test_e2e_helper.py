
import os
import sys
import json
import shutil
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

print("==================================================")
print("Starting E2E Golden Smoke Test (aider-helper)...")
print("==================================================")

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(script_dir, "../../../../.."))
sys.path.insert(0, os.path.join(project_dir, "src", "aider_factory", "python"))
sys.path.insert(0, os.path.join(project_dir, "src", "aider_factory"))

import cli
import bootstrap

# 1. Test CLI Help Invariant
with patch.object(sys, "argv", ["aider-helper", "--help"]), \
     patch("sys.exit", side_effect=SystemExit) as mock_exit:
    try:
        cli.helper_cli()
    except SystemExit:
        pass
    assert mock_exit.called, "aider-helper --help should exit cleanly"
print("  ✅ CLI Help Invariant PASS")

# 1b. Test Unquoted Instruction Parsing
with patch("bootstrap.run_query") as mock_run_query, \
     patch.object(sys, "argv", ["aider-helper", "query", "change", "model", "to", "gpt-4o"]):
    cli.helper_cli()
    mock_run_query.assert_called_once()
    assert mock_run_query.call_args[0][0] == "change model to gpt-4o", "Unquoted instructions must be fully joined"
print("  ✅ Unquoted Instruction Parsing PASS")

# 1c. Test Missing File Graceful Exit
with patch.object(sys, "argv", ["aider-helper", "query", "test", "-f", "definitely_does_not_exist_99999.yml"]), \
     patch("sys.exit", side_effect=SystemExit) as mock_exit, \
     patch("litellm.completion"):
    try:
        cli.helper_cli()
    except SystemExit:
        pass
    mock_exit.assert_called_with(1)
print("  ✅ Missing File Graceful Exit PASS")

# 2. Test Key Gate Validation
old_env = {k: os.environ.get(k) for k in ["GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "OPENCODE_API_KEY", "AIDER_HELPER_API_BASE"]}
for k in old_env:
    os.environ.pop(k, None)

try:
    with patch.object(sys, "argv", ["aider-helper", "query", "Explain loops"]), \
         patch("sys.exit", side_effect=SystemExit) as mock_exit, \
         patch("litellm.completion"):
        try:
            cli.helper_cli()
        except SystemExit:
            pass
        assert mock_exit.called, "Should exit when no API keys are present"
    print("  ✅ API Key Gate Validation PASS")
finally:
    for k, v in old_env.items():
        if v is not None:
            os.environ[k] = v

# 2b. Test Bootstrap Interactive Flow with RAG prompts and Menu Fallback
print("  Starting Bootstrap Interactive Flow E2E Test...")
# Mock a complete user bootstrap session choosing R, model selection first, then RAG, custom embedding model, and fallback query prefix option 1
mock_inputs = [
    "src/main.py",                         # Target files
    "src/read_only.py",                    # Context files
    "2",                                   # Framework: R (testthat)
    "1",                                   # Operating Mode: Autonomous
    "gemini/gemini-2.5-flash",             # Architect model
    "gemini/gemini-2.5-flash",             # Editor model
    "y",                                   # Attach RAG: Yes
    "custom_docs",                         # RAG collection directory
    "gemini/gemini-2.5-flash",             # RAG agent
    "gemini/gemini-2.5-flash",             # OCR agent
    "custom-unknown-embedder",             # Embedding Model (triggers fallback menu)
    "sentence-transformers",               # Embedding Backend
    "1"                                    # Select preset option 1 (BGE prefix)
]

with patch("builtins.input", side_effect=mock_inputs), \
     patch("bootstrap.detect_api_key", return_value=("GEMINI_API_KEY", "mock-key")), \
     patch("subprocess.run") as mock_sub:
    
    # Run the bootstrapper on a temporary folder to verify file creation
    with tempfile.TemporaryDirectory() as tmp_dir:
        bootstrap.run_bootstrap(tmp_dir)
        repo_name = bootstrap.get_repo_name()
        generated_yaml = os.path.join(tmp_dir, ".aider_factory", f".env_{repo_name}.yml")
        
        assert os.path.exists(generated_yaml), "Bootstrapper must create the target YAML file"
        with open(generated_yaml, "r", encoding="utf-8") as f:
            yaml_content = f.read()
            assert "collection_name: \"custom_docs\"" in yaml_content, "RAG collection name should be injected"
            assert "run_ocr_rag: true" in yaml_content, "run_ocr_rag should be enabled"
            assert "custom-unknown-embedder" in yaml_content, "Custom embedding model should be injected"
            assert "Query: " not in yaml_content or "Instruct:" in yaml_content, "BGE query prefix option 1 should be injected"
            assert 'grounding_agent: ""' in yaml_content, "MiniCheck grounding_agent should be disabled/empty by default"
            
        # Verify language-specific test runner provisioning copied run_tests.R
        local_tests_dir = os.path.join(tmp_dir, ".aider_factory", "tests")
        assert os.path.exists(local_tests_dir), "Tests directory must be provisioned"
        assert os.path.exists(os.path.join(local_tests_dir, "run_tests.R")), "run_tests.R must be copied dynamically for R framework"

print("  ✅ Bootstrap Interactive Flow with RAG PASS")

# 3. Test Conversational vs Edit Mode (--ask)
tmp_yaml = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False)
tmp_yaml.write("name: \"E2E Helper Smoke Test\"\n")
tmp_yaml.close()

# Mock a streaming response structure for litellm.completion(..., stream=True)
mock_chunk = MagicMock()
mock_chunk.choices = [MagicMock()]
mock_chunk.choices[0].delta.content = "```yaml\nname: \"E2E Modified\"\n```"
mock_stream = [mock_chunk]

try:
    os.environ["GEMINI_API_KEY"] = "mock-key"
    
    # A. Conversational Mode -> should NOT write to disk
    with patch.object(sys, "argv", ["aider-helper", "query", "Modify", "-f", tmp_yaml.name, "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()
        
    with open(tmp_yaml.name, "r") as f:
        assert "E2E Helper Smoke Test" in f.read(), "Conversational mode must not modify file"
    print("  ✅ Conversational Mode (--ask) Safety PASS")

    # B. Edit Mode -> should write back the modified YAML
    with patch.object(sys, "argv", ["aider-helper", "query", "Modify", "-f", tmp_yaml.name]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()
        
    with open(tmp_yaml.name, "r") as f:
        assert "E2E Modified" in f.read(), "Edit mode must write back modified content"
    print("  ✅ Edit Mode (Write-Back) PASS")

    # C. E2E Session Persistence Check (Multi-turn query)
    session_file = os.path.join(".aider_factory", ".helper_session.json")
    if os.path.exists(session_file):
        os.remove(session_file)

    # First turn
    with patch.object(sys, "argv", ["aider-helper", "query", "Explain loops", "-f", tmp_yaml.name, "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()
    
    assert os.path.exists(session_file), "Session file must be created on first query"
    with open(session_file, "r") as f:
        sess_data = json.load(f)
    assert len(sess_data) == 5, "Should contain system + warm-up + turn 1 prompt/response"

    # Second turn
    with patch.object(sys, "argv", ["aider-helper", "query", "And condition?", "-f", tmp_yaml.name, "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()
        
    with open(session_file, "r") as f:
        sess_data_2 = json.load(f)
    assert len(sess_data_2) == 7, "Session must accumulate messages directly across subsequent CLI calls"
    print("  ✅ E2E Session Persistence PASS")

    # D. E2E Standalone --clear Command
    with patch.object(sys, "argv", ["aider-helper", "query", "--clear"]), \
         patch("sys.exit", side_effect=SystemExit) as mock_exit:
        try:
            cli.helper_cli()
        except SystemExit:
            pass
        assert mock_exit.called, "Should exit cleanly after clearing session"
    assert not os.path.exists(session_file), "Clear command must delete the session file"
    print("  ✅ E2E Standalone --clear PASS")

    # E. E2E Terminal Mode (--terminal / -t) Session & Context Check
    term_session_file = os.path.join(".aider_factory", ".helper_terminal_session.json")
    if os.path.exists(term_session_file):
        os.remove(term_session_file)

    # First terminal query with -t and --context
    with patch.object(sys, "argv", ["aider-helper", "query", "Analyze code", "-t", "--context", tmp_yaml.name]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()

    assert os.path.exists(term_session_file), "Terminal session file must be created on terminal query"
    with open(term_session_file, "r") as f:
        term_sess_data = json.load(f)
    assert len(term_sess_data) == 4, "Terminal session should contain system + greeting + turn 1 prompt/response (4 messages)"

    # Second terminal query
    with patch.object(sys, "argv", ["aider-helper", "query", "Follow up on terminal session", "--terminal"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()

    with open(term_session_file, "r") as f:
        term_sess_data_2 = json.load(f)
    assert len(term_sess_data_2) == 6, "Terminal session must accumulate messages across CLI calls (6 messages)"
    print("  ✅ E2E Terminal Mode (--terminal / -t) Persistence PASS")

    # F. E2E Standalone Terminal --clear Command
    with patch.object(sys, "argv", ["aider-helper", "query", "--terminal", "--clear"]), \
         patch("sys.exit", side_effect=SystemExit) as mock_exit:
        try:
            cli.helper_cli()
        except SystemExit:
            pass
        assert mock_exit.called, "Should exit cleanly after clearing terminal session"
    assert not os.path.exists(term_session_file), "Clear terminal command must delete the terminal session file"
    print("  ✅ E2E Standalone Terminal --clear PASS")

    # G. E2E Local Endpoint kwargs Injection
    os.environ["AIDER_HELPER_API_BASE"] = "http://localhost:8080/v1"
    with patch.object(sys, "argv", ["aider-helper", "query", "test", "--ask"]), \
         patch("litellm.completion", return_value=mock_stream) as mock_litellm:
        cli.helper_cli()
        kwargs = mock_litellm.call_args[1]
        assert kwargs.get("api_base") == "http://localhost:8080/v1", "Must pass api_base"
        assert kwargs.get("api_key") == "dummy", "Must pass dummy api_key for local endpoints to prevent litellm crash"
    os.environ.pop("AIDER_HELPER_API_BASE")
    print("  ✅ Local Endpoint kwargs Injection PASS")

    # H. E2E Master Mode (--master / -m) Context Check
    if os.path.exists(session_file):
        os.remove(session_file)

    with patch.object(sys, "argv", ["aider-helper", "query", "Explain skills", "--master", "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()

    assert os.path.exists(session_file), "Session file must be created on master query"
    with open(session_file, "r") as f:
        master_sess_data = json.load(f)
    
    user_msg = master_sess_data[1]["content"]
    assert "SKILLS REFERENCE:" in user_msg, "Master mode must inject the skills reference"
    assert "FACTORY SERVICE MANUAL:" not in user_msg, "Master mode must NOT inject the service manual"
    
    ast_msg = master_sess_data[2]["content"]
    assert "and the skills reference" in ast_msg, "Master mode must update the acknowledgment message"
    
    print("  ✅ E2E Master Mode (--master / -m) Context Check PASS")

    # I. E2E Expert Mode (--expert / -e) Context Check
    if os.path.exists(session_file):
        os.remove(session_file)

    with patch.object(sys, "argv", ["aider-helper", "query", "Explain architecture", "--expert", "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()

    assert os.path.exists(session_file), "Session file must be created on expert query"
    with open(session_file, "r") as f:
        expert_sess_data = json.load(f)
    
    user_msg = expert_sess_data[1]["content"]
    assert "SKILLS REFERENCE:" in user_msg, "Expert mode must inject the skills reference"
    assert "FACTORY SERVICE MANUAL:" in user_msg, "Expert mode must inject the service manual"
    
    ast_msg = expert_sess_data[2]["content"]
    assert "the skills reference, and the full Factory Service Manual" in ast_msg, "Expert mode must update the acknowledgment message"
    
    print("  ✅ E2E Expert Mode (--expert / -e) Context Check PASS")

finally:
    if os.path.exists(tmp_yaml.name):
        os.remove(tmp_yaml.name)
    for sf in [
        os.path.join(".aider_factory", ".helper_session.json"),
        os.path.join(".aider_factory", ".helper_terminal_session.json"),
    ]:
        if os.path.exists(sf):
            os.remove(sf)

print("\n🎉 E2E Golden Smoke Test (aider-helper) Completed Successfully!")
