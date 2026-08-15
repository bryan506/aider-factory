
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
    with patch.object(sys, "argv", ["aider-helper", "query", "Modify", "-f", tmp_yaml.name, "-a"]), \
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
    assert len(sess_data) == 3, "Should contain system + turn 1 prompt/response"

    # Second turn
    with patch.object(sys, "argv", ["aider-helper", "query", "And condition?", "-f", tmp_yaml.name, "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()
        
    with open(session_file, "r") as f:
        sess_data_2 = json.load(f)
    assert len(sess_data_2) == 5, "Session must accumulate messages directly across subsequent CLI calls"
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
    assert len(term_sess_data) == 3, "Terminal session should contain system + turn 1 prompt/response (3 messages)"

    # Second terminal query
    with patch.object(sys, "argv", ["aider-helper", "query", "Follow up on terminal session", "--terminal"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()

    with open(term_session_file, "r") as f:
        term_sess_data_2 = json.load(f)
    assert len(term_sess_data_2) == 5, "Terminal session must accumulate messages across CLI calls (5 messages)"
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

    # Turn 1: Master Mode
    with patch.object(sys, "argv", ["aider-helper", "query", "Explain skills", "--master", "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()

    with open(session_file, "r") as f:
        master_sess_data = json.load(f)
    
    user_msg = master_sess_data[1]["content"]
    assert "SKILLS REFERENCE:" in user_msg, "Master mode must append the skills reference persistently"
    assert "FACTORY SERVICE MANUAL:" not in user_msg, "Master mode must NOT inject the service manual"
    
    # Turn 2: Follow-up without Master Mode
    with patch.object(sys, "argv", ["aider-helper", "query", "Follow up", "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()
        
    with open(session_file, "r") as f:
        master_sess_data_2 = json.load(f)
        
    assert "SKILLS REFERENCE:" in master_sess_data_2[1]["content"], "Skills reference must survive in Turn 1 history"
    assert "SKILLS REFERENCE:" not in master_sess_data_2[3]["content"], "Skills reference must NOT be duplicated in Turn 2"
    
    print("  ✅ E2E Master Mode (--master / -m) Context Check PASS")

    # I. E2E Expert Mode (--expert / -e) Context Check
    if os.path.exists(session_file):
        os.remove(session_file)

    # Turn 1: Expert Mode
    with patch.object(sys, "argv", ["aider-helper", "query", "Explain architecture", "--expert", "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()

    with open(session_file, "r") as f:
        expert_sess_data = json.load(f)
    
    user_msg = expert_sess_data[1]["content"]
    assert "SKILLS REFERENCE:" in user_msg, "Expert mode must append the skills reference persistently"
    assert "FACTORY SERVICE MANUAL:" in user_msg, "Expert mode must append the service manual persistently"

    # Turn 2: Follow-up without Expert Mode
    with patch.object(sys, "argv", ["aider-helper", "query", "Follow up", "--ask"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()
        
    with open(session_file, "r") as f:
        expert_sess_data_2 = json.load(f)
        
    assert "FACTORY SERVICE MANUAL:" in expert_sess_data_2[1]["content"], "Manual must survive in Turn 1 history"
    assert "FACTORY SERVICE MANUAL:" not in expert_sess_data_2[3]["content"], "Manual must NOT be duplicated in Turn 2"
    
    print("  ✅ E2E Expert Mode (--expert / -e) Context Check PASS")

    # I2. E2E Repo Map Persistence Check
    if os.path.exists(session_file):
        os.remove(session_file)
        
    os.makedirs(".aider_factory", exist_ok=True)
    e2e_repo_map_path = os.path.join(".aider_factory", "static_repo_map.md")
    with open(e2e_repo_map_path, "w", encoding="utf-8") as f:
        f.write("src/e2e_module.py\n  def e2e_func()\n")

    try:
        # Turn 1: Pass --repo-map (-r)
        with patch.object(sys, "argv", ["aider-helper", "query", "Analyze codebase", "--ask", "-r"]), \
             patch("litellm.completion", return_value=mock_stream):
            cli.helper_cli()
            
        with open(session_file, "r") as f:
            repo_map_sess_data = json.load(f)
            
        assert "REPOSITORY MAP:" in repo_map_sess_data[1]["content"], "Repo map must be saved persistently to the turn"
        assert "src/e2e_module.py" in repo_map_sess_data[1]["content"], "Repo map content must be present"
        
        # Turn 2: Do NOT pass --repo-map
        with patch.object(sys, "argv", ["aider-helper", "query", "Follow up", "--ask"]), \
             patch("litellm.completion", return_value=mock_stream):
            cli.helper_cli()
            
        with open(session_file, "r") as f:
            repo_map_sess_data_2 = json.load(f)
            
        assert "REPOSITORY MAP:" in repo_map_sess_data_2[1]["content"], "Repo map from Turn 1 must survive in the persistent history for Turn 2"
        assert "REPOSITORY MAP:" not in repo_map_sess_data_2[3]["content"], "Repo map must NOT be duplicated into Turn 2"
        
        print("  ✅ E2E Repo Map Persistence PASS")
    finally:
        if os.path.exists(e2e_repo_map_path):
            os.remove(e2e_repo_map_path)

    # I3. E2E Context File Persistence Check
    if os.path.exists(session_file):
        os.remove(session_file)
        
    tmp_ctx = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    tmp_ctx.write("def dummy(): pass")
    tmp_ctx.close()

    try:
        # Turn 1: Pass the file
        with patch.object(sys, "argv", ["aider-helper", "query", "Analyze this", "--ask", "-c", tmp_ctx.name]), \
             patch("litellm.completion", return_value=mock_stream):
            cli.helper_cli()
            
        with open(session_file, "r") as f:
            ctx_sess_data = json.load(f)
            
        assert "def dummy(): pass" in ctx_sess_data[1]["content"], "Context file must be saved persistently to the turn"
        
        # Turn 2: Do NOT pass the file
        with patch.object(sys, "argv", ["aider-helper", "query", "Follow up", "--ask"]), \
             patch("litellm.completion", return_value=mock_stream):
            cli.helper_cli()
            
        with open(session_file, "r") as f:
            ctx_sess_data_2 = json.load(f)
            
        assert "def dummy(): pass" in ctx_sess_data_2[1]["content"], "Context file from Turn 1 must survive in the persistent history for Turn 2"
        assert "def dummy(): pass" not in ctx_sess_data_2[3]["content"], "Context file must NOT be duplicated into Turn 2"
        
        print("  ✅ E2E Context File Persistence PASS")
    finally:
        os.remove(tmp_ctx.name)

    # J. E2E Combined Short Flags (-mta)
    term_session_file = os.path.join(".aider_factory", ".helper_terminal_session.json")
    if os.path.exists(term_session_file):
        os.remove(term_session_file)

    with patch.object(sys, "argv", ["aider-helper", "query", "-mta", "Combined test"]), \
         patch("litellm.completion", return_value=mock_stream):
        cli.helper_cli()

    assert os.path.exists(term_session_file), "Terminal session file must be created for -t"
    with open(term_session_file, "r") as f:
        mta_sess_data = json.load(f)
        
    assert len(mta_sess_data) == 3, "Session must contain system + turn 1 prompt/response"
    assert "SKILLS REFERENCE:" in mta_sess_data[1]["content"], "Master mode context must be injected for -m"
    assert mta_sess_data[0]["content"] == bootstrap.TERMINAL_PERSONA_PROMPT, "Must use terminal persona for -t"
    print("  ✅ E2E Combined Short Flags (-mta) PASS")

    # K. E2E Cluster Config Discovery
    print("  Starting E2E Cluster Config Discovery Test...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("builtins.input") as mock_input, \
             patch("subprocess.run"), \
             patch("bootstrap._discover_cluster_config") as mock_discover, \
             patch("bootstrap.detect_api_key") as mock_detect:

            mock_detect.return_value = ("OPENAI_API_KEY", "dummy")
            mock_input.side_effect = [
                "src/main.py", # target files
                "",            # context files
                "1",           # framework
                "1",           # mode
                "dummy-arch",  # arch model
                "dummy-edit",  # edit model
                "n",           # use rag
            ]

            mock_discover.return_value = {
                "architect_api_base": "http://e2e-cluster:8080/v1",
                "editor_ollama_api": "http://e2e-cluster:8080/v1",
                "rag_agent_api": "http://e2e-cluster:8080/v1",
                "api_key": "dummy",
                "available_models": ["e2e-model"],
                "architect_agent": "e2e-model",
                "editor_agent": "e2e-model"
            }

            original_cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                bootstrap.run_bootstrap(tmp_dir)
                repo_name = bootstrap.get_repo_name()
                yaml_path = os.path.join(tmp_dir, ".aider_factory", f".env_{repo_name}.yml")

                assert os.path.exists(yaml_path), "Generated YAML must exist"
                with open(yaml_path, "r") as f:
                    content = f.read()

                assert "http://e2e-cluster:8080/v1" in content, "Cluster API base must be injected"
                assert "e2e-model" in content, "Cluster model must be injected"
            finally:
                os.chdir(original_cwd)
    print("  ✅ E2E Cluster Config Discovery PASS")

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
