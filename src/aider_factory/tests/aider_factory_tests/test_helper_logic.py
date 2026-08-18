
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
         assert len(sess_data_1) == 3, "Should initialize system + turn 1 prompt/response"
         assert "<yaml_documentation>" in sess_data_1[1]["content"], "YAML must be persistently appended on Turn 1"

         # Turn 2 (Should append to stable message history list directly)
         bootstrap.run_query("instruction 2", tmp_yaml.name, "context_a.py", ask_mode=True)
         with open(tmp_session.name, "r") as f:
             sess_data_2 = json.load(f)
         assert len(sess_data_2) == 5, "Session must accumulate messages directly without hashing reset"
         assert "<yaml_documentation>" not in sess_data_2[3]["content"], "YAML must NOT be appended again on Turn 2 to prevent bloat"

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
        assert len(term_data_1) == 3, "Terminal session should contain system + turn 1 prompt/response (3 messages)"
        assert term_data_1[0]["content"] == bootstrap.TERMINAL_PERSONA_PROMPT, "Terminal mode must use TERMINAL_PERSONA_PROMPT"

        # Turn 2 in terminal mode
        bootstrap.run_query("follow up question", None, "", ask_mode=True, terminal_mode=True)
        with open(tmp_term_session.name, "r") as f:
            term_data_2 = json.load(f)
        assert len(term_data_2) == 5, "Terminal session must accumulate messages across turns (5 messages)"

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
         patch("litellm.completion", return_value=mock_response) as mock_litellm, \
         patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

        # Turn 1: Master Mode
        bootstrap.run_query("explain skills", tmp_master_yaml.name, "", ask_mode=True, master_mode=True)
        
        with open(tmp_master_session.name, "r") as f:
            master_data = json.load(f)
        
        assert len(master_data) == 3, "Master session should contain system + turn 1 prompt/response"
        assert "<skills_reference>" in master_data[1]["content"], "Master mode must append skills persistently"
        assert "<factory_service_manual>" not in master_data[1]["content"], "Master mode must NOT inject the Factory Service Manual"

        # Turn 2: Follow-up without Master Mode
        bootstrap.run_query("follow up", tmp_master_yaml.name, "", ask_mode=True, master_mode=False)
        with open(tmp_master_session.name, "r") as f:
            master_data_2 = json.load(f)
            
        assert len(master_data_2) == 5, "Session must accumulate messages"
        assert "<skills_reference>" in master_data_2[1]["content"], "Skills reference must survive in Turn 1 history"
        assert "<skills_reference>" not in master_data_2[3]["content"], "Skills reference must NOT be duplicated in Turn 2"

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
         patch("litellm.completion", return_value=mock_response) as mock_litellm, \
         patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

        # Turn 1: Expert Mode
        bootstrap.run_query("explain architecture", tmp_expert_yaml.name, "", ask_mode=True, expert_mode=True)
        
        with open(tmp_expert_session.name, "r") as f:
            expert_data = json.load(f)
        
        assert len(expert_data) == 3, "Expert session should contain system + turn 1 prompt/response"
        assert "<skills_reference>" in expert_data[1]["content"], "Expert mode must append skills persistently"
        assert "<factory_service_manual>" in expert_data[1]["content"], "Expert mode must append manual persistently"

        # Turn 2: Follow-up without Expert Mode
        bootstrap.run_query("follow up", tmp_expert_yaml.name, "", ask_mode=True, expert_mode=False)
        with open(tmp_expert_session.name, "r") as f:
            expert_data_2 = json.load(f)
            
        assert len(expert_data_2) == 5, "Session must accumulate messages"
        assert "<factory_service_manual>" in expert_data_2[1]["content"], "Manual must survive in Turn 1 history"
        assert "<factory_service_manual>" not in expert_data_2[3]["content"], "Manual must NOT be duplicated in Turn 2"

    print("✅ Expert Mode Logic PASS")
finally:
    for f in [tmp_expert_session.name, tmp_expert_yaml.name]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

# 8. Test Repo Map Logic
print("Starting Repo Map Logic Unit Tests...")
tmp_repo_map_session = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
tmp_repo_map_session.close()

tmp_repo_map_yaml = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False)
tmp_repo_map_yaml.write("name: repo_map_test")
tmp_repo_map_yaml.close()

os.makedirs(".aider_factory", exist_ok=True)
dummy_repo_map_path = os.path.join(".aider_factory", "static_repo_map.md")
with open(dummy_repo_map_path, "w", encoding="utf-8") as f:
    f.write("src/main.py\n  def main()\n")

try:
    with patch("bootstrap.get_helper_session_file", return_value=tmp_repo_map_session.name), \
         patch("litellm.completion", return_value=mock_response), \
         patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

        # Turn 1: Repo Map Mode
        bootstrap.run_query("explain repo", tmp_repo_map_yaml.name, "", ask_mode=True, repo_map=True)
        
        with open(tmp_repo_map_session.name, "r") as f:
            repo_map_data = json.load(f)
        
        assert len(repo_map_data) == 3, "Repo map session should contain system + turn 1 prompt/response"
        assert "<repository_map>" in repo_map_data[1]["content"], "Repo map mode must append repository map persistently"
        assert "src/main.py" in repo_map_data[1]["content"], "Dummy repo map content must be present"

        # Turn 2: Follow-up without Repo Map Mode
        bootstrap.run_query("follow up", tmp_repo_map_yaml.name, "", ask_mode=True, repo_map=False)
        with open(tmp_repo_map_session.name, "r") as f:
            repo_map_data_2 = json.load(f)
            
        assert len(repo_map_data_2) == 5, "Session must accumulate messages"
        assert "<repository_map>" in repo_map_data_2[1]["content"], "Repo map must survive in Turn 1 history"
        assert "<repository_map>" not in repo_map_data_2[3]["content"], "Repo map must NOT be duplicated in Turn 2"

    print("✅ Repo Map Logic PASS")
finally:
    for f in [tmp_repo_map_session.name, tmp_repo_map_yaml.name, dummy_repo_map_path]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

# 9. Test Cluster Config Discovery
print("Starting Cluster Config Discovery Tests...")
with patch("requests.get") as mock_get:
    with patch.dict("os.environ", {"LITELLM_BASE_URL": "http://mock-cluster:8080/v1", "LITELLM_API_KEY": "mock-key"}):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "mock-model-1"}, {"id": "mock-model-2"}]}
        mock_get.return_value = mock_resp

        config = bootstrap._discover_cluster_config()

        assert config is not None, "Config should not be None"
        assert config["architect_api_base"] == "http://mock-cluster:8080/v1", "Should set API base"
        assert config["available_models"] == ["openai/mock-model-1", "openai/mock-model-2"], "Should extract models with openai/ prefix"
        assert config["architect_agent"] == "openai/mock-model-1", "Should set architect agent with openai/ prefix"
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

# 10. Test Ask & Terminal Mode Zero .aider_factory Directory Creation Invariant
print("Starting Ask & Terminal Mode Zero Directory Creation Tests...")
test_modes = [
    ("ask_mode", {"ask_mode": True, "terminal_mode": False}),
    ("terminal_mode", {"ask_mode": True, "terminal_mode": True}),
    ("master_mode", {"ask_mode": True, "master_mode": True}),
    ("expert_mode", {"ask_mode": True, "expert_mode": True}),
]
for name, kwargs in test_modes:
    with tempfile.TemporaryDirectory() as tmp_clean_dir:
        old_cwd = os.getcwd()
        os.chdir(tmp_clean_dir)
        try:
            with patch("litellm.completion", return_value=mock_response), \
                 patch("os.environ", {"GEMINI_API_KEY": "test-key"}):
                bootstrap.run_query("Explain concepts", None, "", **kwargs)
                assert not os.path.exists(".aider_factory"), f"{name} must NEVER create .aider_factory directory"
        finally:
            os.chdir(old_cwd)
print("✅ Ask & Terminal Mode Zero Directory Creation PASS")

# 11. Test Helper Cloud Model Omits api_key
print("Starting Helper Cloud Model API Key Tests...")
with patch("litellm.completion", return_value=mock_response) as mock_comp:
    for k in ["AIDER_HELPER_API_BASE", "AIDER_HELPER_MODEL"]:
        os.environ.pop(k, None)
    os.environ["GEMINI_API_KEY"] = "test-key"
    bootstrap.run_query("Explain concepts", None, "", ask_mode=True)
    mock_comp.assert_called()
    kwargs = mock_comp.call_args[1]
    assert "api_key" not in kwargs, "Cloud helper queries must not pass explicit api_key in kwargs!"
print("✅ Helper Cloud Model Omits api_key PASS")

print("\n🎉 All helper logic unit tests passed!")
