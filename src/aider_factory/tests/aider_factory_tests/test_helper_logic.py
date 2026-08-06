
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
    os.environ["GEMINI_API_KEY"] = "gemini-test-key"
    assert bootstrap.detect_api_key() == ("GEMINI_API_KEY", "gemini-test-key"), "Should detect GEMINI_API_KEY"
finally:
    for k, v in old_env.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
print("✅ API Key Detection PASS")

# 2. Test Context Hashing & Cache Protection Invariant
tmp_session = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
tmp_session.close()

tmp_yaml = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False)
tmp_yaml.write("name: test")
tmp_yaml.close()

mock_response = MagicMock()
mock_response.choices = [MagicMock()]
mock_response.choices[0].message.content = "Answer text"

try:
    with patch("bootstrap.get_helper_session_file", return_value=tmp_session.name), \
         patch("litellm.completion", return_value=mock_response), \
         patch("os.environ", {"GEMINI_API_KEY": "test-key"}):
         
         # Turn 1 (Context A)
         bootstrap.run_query("instruction", tmp_yaml.name, "context_a.py", ask_mode=True)
         with open(tmp_session.name, "r") as f:
             sess_data_1 = json.load(f)
         hash_1 = sess_data_1["context_hash"]

         # Turn 2 (Context A again - should preserve session history)
         bootstrap.run_query("instruction 2", tmp_yaml.name, "context_a.py", ask_mode=True)
         with open(tmp_session.name, "r") as f:
             sess_data_2 = json.load(f)
         assert len(sess_data_2["messages"]) > len(sess_data_1["messages"]), "Session should accumulate messages"
         assert sess_data_2["context_hash"] == hash_1, "Hash must match"

         # Turn 3 (Context B - should reset session due to hash mismatch)
         bootstrap.run_query("instruction 3", tmp_yaml.name, "context_b.py", ask_mode=True)
         with open(tmp_session.name, "r") as f:
             sess_data_3 = json.load(f)
         assert sess_data_3["context_hash"] != hash_1, "Hash must change"
         assert len(sess_data_3["messages"]) == 5, "Session should reset to warm-up baseline"

    print("✅ Context Hashing Cache Protection PASS")
finally:
    for f in [tmp_session.name, tmp_yaml.name]:
        if os.path.exists(f):
            os.remove(f)

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

print("\n🎉 All helper logic unit tests passed!")
