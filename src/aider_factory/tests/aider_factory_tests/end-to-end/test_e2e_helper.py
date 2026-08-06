
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
     patch("sys.exit") as mock_exit:
    try:
        cli.helper_cli()
    except SystemExit:
        pass
    assert mock_exit.called, "aider-helper --help should exit cleanly"
print("  ✅ CLI Help Invariant PASS")

# 2. Test Key Gate Validation
old_env = {k: os.environ.get(k) for k in ["GEMINI_API_KEY", "OPENAI_API_KEY"]}
for k in old_env:
    os.environ.pop(k, None)

try:
    with patch.object(sys, "argv", ["aider-helper", "query", "Explain loops"]), \
         patch("sys.exit") as mock_exit:
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
# Mock a complete user bootstrap session choosing R, RAG, custom embedding model, and fallback query prefix option 1
mock_inputs = [
    "src/main.py",                         # Target files
    "src/read_only.py",                    # Context files
    "2",                                   # Framework: R (testthat)
    "1",                                   # Operating Mode: Autonomous
    "y",                                   # Attach RAG: Yes
    "custom_docs",                         # RAG collection directory
    "gemini/gemini-2.5-flash",             # RAG agent
    "gemini/gemini-2.5-flash",             # OCR agent
    "custom-unknown-embedder",             # Embedding Model (triggers fallback menu)
    "sentence-transformers",               # Embedding Backend
    "1",                                   # Select preset option 1 (BGE prefix)
    "gemini/gemini-2.5-flash",             # Architect model
    "gemini/gemini-2.5-flash"              # Editor model
]

with patch("builtins.input", side_effect=mock_inputs), \
     patch("bootstrap.detect_api_key", return_value=("GEMINI_API_KEY", "mock-key")), \
     patch("litellm.completion") as mock_completion, \
     patch("subprocess.run") as mock_sub:
    
    # Mock LLM synthesis returning a valid standardized template
    mock_choice = MagicMock()
    mock_choice.message.content = """```yaml
name: "My Project"
working_directory: "/path/to/project"
test_runner: "Rscript .aider_factory/tests/run_tests.R {file}"
phases:
  - name: "Reconcile"
    rag:
      collection_name: ""
      run_ocr_rag: false
      ocr_agent: "glm-ocr-f16:latest"
      embed_model: "qwen3-embedding-8b-8k:LATEST"
      embed_backend: "sentence-transformers"
      query_prefix: "Query: "
      grounding_agent: "openai/minicheck-flan-t5-large"
```"""
    mock_completion.return_value.choices = [mock_choice]
    
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

finally:
    if os.path.exists(tmp_yaml.name):
        os.remove(tmp_yaml.name)
    session_file = os.path.join(".aider_factory", ".helper_session.json")
    if os.path.exists(session_file):
        os.remove(session_file)

print("\n🎉 E2E Golden Smoke Test (aider-helper) Completed Successfully!")
