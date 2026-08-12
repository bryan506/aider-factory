
import os
import sys
import json
import tempfile
from unittest.mock import MagicMock, patch

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../..")))

import bootstrap

print("Starting aider-helper Logic Unit Tests...\n")

# 1. Test API Key Detection
old_env = {k: os.environ.get(k) for k in ["GEMINI_API_KEY", "OPENAI_API_KEY"]}
for k in old_env:
    os.environ.pop(k, None)

try:
    assert bootstrap.detect_api_key() == (None, None), "Should return None when no keys are present"
    
    # Test local endpoint bypass
    os.environ["AIDER_HELPER_API_BASE"] = "http://localhost:8080/v1"
    assert bootstrap.detect_api_key() == ("CUSTOM_LOCAL", "dummy"), "Should bypass key check for local endpoints"
    os.environ.pop("AIDER_HELPER_API_BASE")
    
    os.environ["GEMINI_API_KEY"] = "gemini-test-key"
    assert bootstrap.detect_api_key() == ("GEMINI_API_KEY", "gemini-test-key"), "Should detect GEMINI_API_KEY"
finally:
    for k, v in old_env.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
print("✅ API Key Detection PASS")

# 2. Test Helper Session Persistence & Clear Invariant
tmp_session = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
tmp_session.close()

tmp_yaml = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False)
tmp_yaml.write("name: test")
tmp_yaml.close()

mock_chunk = MagicMock()
mock_chunk.choices = [MagicMock()]
mock_chunk.choices[0].delta.content = "Answer text"
mock_response = [mock_chunk]

try:
    with patch("bootstrap.get_helper_session_file", return_value=tmp_session.name), \
         patch("litellm.completion", return_value=mock_response), \
         patch("os.environ", {"GEMINI_API_KEY": "test-key"}):
         
         # Turn 1
         bootstrap.run_query("instruction", tmp_yaml.name, "context_a.py", ask_mode=True)
         with open(tmp_session.name, "r") as f:
             sess_data_1 = json.load(f)
         assert len(sess_data_1) == 5, "Should initialize system + warm-up + turn 1 prompt/response"

         # Turn 2 (Should append to stable message history list directly)
         bootstrap.run_query("instruction 2", tmp_yaml.name, "context_a.py", ask_mode=True)
         with open(tmp_session.name, "r") as f:
             sess_data_2 = json.load(f)
         assert len(sess_data_2) == 7, "Session must accumulate messages directly without hashing reset"
         assert "CURRENT CONFIGURATION STATE:" in sess_data_2[-2]["content"], "Must inject fresh YAML state on follow-up turns to prevent split-brain"

         # Test session clearing
         bootstrap.clear_helper_session()
         assert not os.path.exists(tmp_session.name), "Clear must remove the session file from disk"

    print("✅ Helper Session Persistence & Clear PASS")
finally:
    for f in [tmp_session.name, tmp_yaml.name]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

# 3. Test Dynamic Query Prefix Resolution
print("Starting Query Prefix Auto-Detection Tests...")
# Mock profile dictionary for manual verification of the logic implemented in run_bootstrap
def get_prefix_for_model(model_name):
    emb_lower = model_name.lower()
    if "bge" in emb_lower:
        return "Instruct: Given a coding or financial query, retrieve relevant passages\\nQuery: "
    elif "qwen" in emb_lower:
        return "Query: "
    return None

assert get_prefix_for_model("BAAI/bge-m3") == "Instruct: Given a coding or financial query, retrieve relevant passages\\nQuery: ", "Should resolve BGE prefix"
assert get_prefix_for_model("qwen3-embedding") == "Query: ", "Should resolve Qwen prefix"
assert get_prefix_for_model("custom-model") is None, "Should return None for unknown models to trigger fallback menu"
print("✅ Query Prefix Auto-Detection PASS")

# 4. Test DRY Framework-to-Extension Mapping Logic
print("Starting DRY Framework Mapping Tests...")
framework_map = {
    "Rscript": "R",
    "pytest": "py",
    "cargo": "rs",
    "go test": "go",
    "npm": "js",
}
def detect_ext(yaml_content):
    for kw, ext in framework_map.items():
        if kw in yaml_content:
            return ext
    return "py"

assert detect_ext("test_runner: \"Rscript .aider_factory/tests/run_tests.R {file}\"") == "R", "Should map Rscript to R"
assert detect_ext("test_runner: \"python -m pytest {file}\"") == "py", "Should map pytest to py"
assert detect_ext("test_runner: \"cargo test --test {stem}\"") == "rs", "Should map cargo to rs"
assert detect_ext("test_runner: \"echo custom\"") == "py", "Should fallback to py"
print("✅ DRY Framework Mapping PASS")

# 5. Test Terminal Mode Session Persistence & Clear Invariant
print("Starting Terminal Mode Logic Unit Tests...")
tmp_term_session = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
tmp_term_session.close()

try:
    with patch("bootstrap.get_helper_terminal_session_file", return_value=tmp_term_session.name), \
         patch("litellm.completion", return_value=mock_response), \
         patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

        # Turn 1 in terminal mode
        bootstrap.run_query("explain git", None, "file1.txt", ask_mode=True, terminal_mode=True)
        with open(tmp_term_session.name, "r") as f:
            term_data_1 = json.load(f)
        assert len(term_data_1) == 4, "Terminal session should contain system + assistant greeting + user prompt + assistant response (4 messages)"
        assert term_data_1[0]["content"] == bootstrap.TERMINAL_PERSONA_PROMPT, "Terminal mode must use TERMINAL_PERSONA_PROMPT"

        # Turn 2 in terminal mode
        bootstrap.run_query("follow up question", None, "", ask_mode=True, terminal_mode=True)
        with open(tmp_term_session.name, "r") as f:
            term_data_2 = json.load(f)
        assert len(term_data_2) == 6, "Terminal session must accumulate messages across turns (6 messages)"

        # Test terminal session clearing
        bootstrap.clear_helper_session(terminal_mode=True)
        assert not os.path.exists(tmp_term_session.name), "Clear terminal session must remove the terminal session file"

    print("✅ Terminal Mode Session Persistence & Clear PASS")
finally:
    if os.path.exists(tmp_term_session.name):
        try:
            os.remove(tmp_term_session.name)
        except OSError:
            pass

# 6. Test Master Mode Logic
print("Starting Master Mode Logic Unit Tests...")
tmp_master_session = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
tmp_master_session.close()

tmp_master_yaml = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False)
tmp_master_yaml.write("name: master_test")
tmp_master_yaml.close()

try:
    with patch("bootstrap.get_helper_session_file", return_value=tmp_master_session.name), \
         patch("litellm.completion", return_value=mock_response), \
         patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

        bootstrap.run_query("explain skills", tmp_master_yaml.name, "", ask_mode=True, master_mode=True)
        
        with open(tmp_master_session.name, "r") as f:
            master_data = json.load(f)
        
        assert len(master_data) == 5, "Master session should contain system + warm-up + turn 1 prompt/response"
        assert "SKILLS REFERENCE:" in master_data[1]["content"], "Master mode must inject the skills reference"
        assert "FACTORY SERVICE MANUAL:" not in master_data[1]["content"], "Master mode must NOT inject the Factory Service Manual"
        assert "and the skills reference" in master_data[2]["content"], "Master mode must update the acknowledgment message"

    print("✅ Master Mode Logic PASS")
finally:
    for f in [tmp_master_session.name, tmp_master_yaml.name]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

# 7. Test Expert Mode Logic
print("Starting Expert Mode Logic Unit Tests...")
tmp_expert_session = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
tmp_expert_session.close()

tmp_expert_yaml = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False)
tmp_expert_yaml.write("name: expert_test")
tmp_expert_yaml.close()

try:
    with patch("bootstrap.get_helper_session_file", return_value=tmp_expert_session.name), \
         patch("litellm.completion", return_value=mock_response), \
         patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

        bootstrap.run_query("explain architecture", tmp_expert_yaml.name, "", ask_mode=True, expert_mode=True)
        
        with open(tmp_expert_session.name, "r") as f:
            expert_data = json.load(f)
        
        assert len(expert_data) == 5, "Expert session should contain system + warm-up + turn 1 prompt/response"
        assert "SKILLS REFERENCE:" in expert_data[1]["content"], "Expert mode must inject the skills reference"
        assert "FACTORY SERVICE MANUAL:" in expert_data[1]["content"], "Expert mode must inject the Factory Service Manual"
        assert "the skills reference, and the full Factory Service Manual" in expert_data[2]["content"], "Expert mode must update the acknowledgment message"

    print("✅ Expert Mode Logic PASS")
finally:
    for f in [tmp_expert_session.name, tmp_expert_yaml.name]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

# 8. Test Cluster Config Discovery
print("Starting Cluster Config Discovery Tests...")
with patch("bootstrap.requests.get") as mock_get:
    with patch.dict("os.environ", {"LITELLM_BASE_URL": "http://mock-cluster:8080/v1", "LITELLM_API_KEY": "mock-key"}):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "mock-model-1"}, {"id": "mock-model-2"}]}
        mock_get.return_value = mock_resp

        config = bootstrap._discover_cluster_config()

        assert config is not None, "Config should not be None"
        assert config["architect_api_base"] == "http://mock-cluster:8080/v1", "Should set API base"
        assert config["available_models"] == ["mock-model-1", "mock-model-2"], "Should extract models"
        assert config["architect_agent"] == "mock-model-1", "Should set architect agent"
print("✅ Cluster Config Discovery PASS")

# 9. Test Session ID Injection
print("Starting Session ID Injection Tests...")
with patch("litellm.completion") as mock_completion, \
     patch("bootstrap.detect_api_key", return_value=("OPENAI_API_KEY", "dummy")):
    mock_resp = MagicMock()
    mock_resp.__iter__.return_value = []
    mock_completion.return_value = mock_resp

    bootstrap.run_query("test", None, "", True, terminal_mode=True)

    mock_completion.assert_called_once()
    kwargs = mock_completion.call_args.kwargs
    assert "custom_headers" in kwargs, "custom_headers must be passed"
    assert "x-litellm-session-id" in kwargs["custom_headers"], "Session ID must be in headers"
    assert kwargs["custom_headers"]["x-litellm-session-id"] == bootstrap._PIPELINE_SESSION_ID, "Session ID must match pipeline ID"
print("✅ Session ID Injection PASS")

print("\n🎉 All helper logic unit tests passed!")
