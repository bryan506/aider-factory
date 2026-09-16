
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

ALL_KEYS_TO_POP = [
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "AIDER_GEMINI_API_KEY", "GOOGLE_GEMINI_API_KEY",
    "ANTHROPIC_API_KEY", "AIDER_ANTHROPIC_API_KEY",
    "OPENAI_API_KEY", "AIDER_OPENAI_API_KEY",
    "OPENROUTER_API_KEY", "AIDER_OPENROUTER_API_KEY",
    "GROQ_API_KEY", "AIDER_GROQ_API_KEY",
    "DEEPSEEK_API_KEY", "AIDER_DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY", "AIDER_MISTRAL_API_KEY",
    "OPENCODE_API_KEY", "LITELLM_API_KEY", "LITELLM_BASE_URL",
    "AIDER_HELPER_API_BASE", "AIDER_HELPER_MODEL"
]

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
if python_module_dir not in sys.path:
    sys.path.insert(0, python_module_dir)
if os.path.abspath(os.path.join(script_dir, "../../..")) not in sys.path:
    sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../../..")))

import bootstrap

mock_chunk = MagicMock()
mock_chunk.choices = [MagicMock()]
mock_chunk.choices[0].delta.content = "Answer text"
mock_response = [mock_chunk]


def test_01_api_key_detection():
    old_env = {k: os.environ.get(k) for k in ALL_KEYS_TO_POP}
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


def test_02_helper_session_persistence_and_clear():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_session, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as tmp_yaml:
        tmp_yaml.write("name: test")
        tmp_yaml.flush()

        try:
            with patch("bootstrap.get_helper_session_file", return_value=tmp_session.name), \
                 patch("litellm.completion", return_value=mock_response), \
                 patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

                # Turn 1
                bootstrap.run_query("instruction", tmp_yaml.name, "context_a.py", ask_mode=True)
                with open(tmp_session.name, "r") as f:
                    sess_data_1 = json.load(f)
                assert len(sess_data_1) == 3, "Should initialize system + turn 1 prompt/response"
                assert "<reference_schema>" in sess_data_1[1]["content"], "Reference schema must be persistently appended on Turn 1"
                assert "endpoints:" in sess_data_1[1]["content"], "Must load complete_env.yml into reference schema"
                assert "<yaml_documentation>" not in sess_data_1[1]["content"], "YAML docs must NOT be loaded in default mode"

                # Turn 2
                bootstrap.run_query("instruction 2", tmp_yaml.name, "context_a.py", ask_mode=True)
                with open(tmp_session.name, "r") as f:
                    sess_data_2 = json.load(f)
                assert len(sess_data_2) == 5, "Session must accumulate messages directly without hashing reset"
                assert "<reference_schema>" not in sess_data_2[3]["content"], "Reference schema must NOT be appended again on Turn 2"

                # Test session clearing
                bootstrap.clear_helper_session()
                assert not os.path.exists(tmp_session.name), "Clear must remove the session file from disk"
        finally:
            for f in [tmp_session.name, tmp_yaml.name]:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass


def test_03_query_prefix_auto_detection():
    def get_prefix_for_model(model_name):
        emb_lower = model_name.lower()
        if "bge" in emb_lower:
            return "Instruct: Given a coding or financial query, retrieve relevant passages\\nQuery: "
        elif "qwen" in emb_lower:
            return "Query: "
        return None

    assert get_prefix_for_model("BAAI/bge-m3") == "Instruct: Given a coding or financial query, retrieve relevant passages\\nQuery: "
    assert get_prefix_for_model("qwen3-embedding") == "Query: "
    assert get_prefix_for_model("custom-model") is None


def test_04_framework_mapping_from_yaml_content():
    """Verify the inverse mapping: detecting framework from YAML runner string."""
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

    assert detect_ext('test_runner: "Rscript .aider_factory/tests/run_tests.R {file}"') == "R"
    assert detect_ext('test_runner: "python -m pytest {file}"') == "py"
    assert detect_ext('test_runner: "cargo test --test {stem}"') == "rs"
    assert detect_ext('test_runner: "echo custom"') == "py"


def test_05_terminal_mode_session_persistence_and_clear():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_term_session:
        pass

    try:
        with patch("bootstrap.get_helper_terminal_session_file", return_value=tmp_term_session.name), \
             patch("litellm.completion", return_value=mock_response), \
             patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

            # Turn 1
            bootstrap.run_query("explain git", None, "file1.txt", ask_mode=True, terminal_mode=True)
            with open(tmp_term_session.name, "r") as f:
                term_data_1 = json.load(f)
            assert len(term_data_1) == 3, "Terminal session should contain system + turn 1 prompt/response"
            assert term_data_1[0]["content"] == bootstrap.TERMINAL_PERSONA_PROMPT

            # Turn 2
            bootstrap.run_query("follow up question", None, "", ask_mode=True, terminal_mode=True)
            with open(tmp_term_session.name, "r") as f:
                term_data_2 = json.load(f)
            assert len(term_data_2) == 5, "Terminal session must accumulate messages across turns"

            # Clear
            bootstrap.clear_helper_session(terminal_mode=True)
            assert not os.path.exists(tmp_term_session.name), "Clear terminal session must remove the file"
    finally:
        if os.path.exists(tmp_term_session.name):
            try:
                os.remove(tmp_term_session.name)
            except OSError:
                pass


def test_06_master_mode_logic():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_master_session, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as tmp_master_yaml:
        tmp_master_yaml.write("name: master_test")
        tmp_master_yaml.flush()

        try:
            with patch("bootstrap.get_helper_session_file", return_value=tmp_master_session.name), \
                 patch("litellm.completion", return_value=mock_response), \
                 patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

                bootstrap.run_query("explain skills", tmp_master_yaml.name, "", ask_mode=True, master_mode=True)
                with open(tmp_master_session.name, "r") as f:
                    master_data = json.load(f)

                assert len(master_data) == 3
                assert "<skills_reference>" in master_data[1]["content"]
                assert "<yaml_documentation>" in master_data[1]["content"]
                assert "File: factory.md" in master_data[1]["content"]
                assert "File: helper.md" in master_data[1]["content"]
                assert "<factory_service_manual>" not in master_data[1]["content"]

                # Turn 2: Follow-up without Master Mode
                bootstrap.run_query("follow up", tmp_master_yaml.name, "", ask_mode=True, master_mode=False)
                with open(tmp_master_session.name, "r") as f:
                    master_data_2 = json.load(f)

                assert len(master_data_2) == 5
                assert "<skills_reference>" in master_data_2[1]["content"]
                assert "<yaml_documentation>" in master_data_2[1]["content"]
                assert "<skills_reference>" not in master_data_2[3]["content"]
                assert "<yaml_documentation>" not in master_data_2[3]["content"]
        finally:
            for f in [tmp_master_session.name, tmp_master_yaml.name]:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass


def test_07_expert_mode_logic():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_expert_session, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as tmp_expert_yaml:
        tmp_expert_yaml.write("name: expert_test")
        tmp_expert_yaml.flush()

        try:
            with patch("bootstrap.get_helper_session_file", return_value=tmp_expert_session.name), \
                 patch("litellm.completion", return_value=mock_response), \
                 patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

                bootstrap.run_query("explain architecture", tmp_expert_yaml.name, "", ask_mode=True, expert_mode=True)
                with open(tmp_expert_session.name, "r") as f:
                    expert_data = json.load(f)

                assert len(expert_data) == 3
                assert "<skills_reference>" in expert_data[1]["content"]
                assert "<yaml_documentation>" in expert_data[1]["content"]
                assert "<factory_service_manual>" in expert_data[1]["content"]
                assert "File: factory.md" in expert_data[1]["content"]

                # Turn 2: Follow-up without Expert Mode
                bootstrap.run_query("follow up", tmp_expert_yaml.name, "", ask_mode=True, expert_mode=False)
                with open(tmp_expert_session.name, "r") as f:
                    expert_data_2 = json.load(f)

                assert len(expert_data_2) == 5
                assert "<factory_service_manual>" in expert_data_2[1]["content"]
                assert "<factory_service_manual>" not in expert_data_2[3]["content"]
        finally:
            for f in [tmp_expert_session.name, tmp_expert_yaml.name]:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass


def test_08_repo_map_logic():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_repo_map_session, \
         tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as tmp_repo_map_yaml:
        tmp_repo_map_yaml.write("name: repo_map_test")
        tmp_repo_map_yaml.flush()

    os.makedirs(".aider_factory", exist_ok=True)
    dummy_repo_map_path = os.path.join(".aider_factory", "static_repo_map.md")
    with open(dummy_repo_map_path, "w", encoding="utf-8") as f:
        f.write("src/main.py\n  def main()\n")

    try:
        with patch("bootstrap.get_helper_session_file", return_value=tmp_repo_map_session.name), \
             patch("litellm.completion", return_value=mock_response), \
             patch("os.environ", {"GEMINI_API_KEY": "test-key"}):

            bootstrap.run_query("explain repo", tmp_repo_map_yaml.name, "", ask_mode=True, repo_map=True)
            with open(tmp_repo_map_session.name, "r") as f:
                repo_map_data = json.load(f)

            assert len(repo_map_data) == 3
            assert "<repository_map>" in repo_map_data[1]["content"]
            assert "src/main.py" in repo_map_data[1]["content"]

            # Turn 2: Follow-up without Repo Map Mode
            bootstrap.run_query("follow up", tmp_repo_map_yaml.name, "", ask_mode=True, repo_map=False)
            with open(tmp_repo_map_session.name, "r") as f:
                repo_map_data_2 = json.load(f)

            assert len(repo_map_data_2) == 5
            assert "<repository_map>" in repo_map_data_2[1]["content"]
            assert "<repository_map>" not in repo_map_data_2[3]["content"]
    finally:
        for f in [tmp_repo_map_session.name, tmp_repo_map_yaml.name, dummy_repo_map_path]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass


def test_09_cluster_config_discovery():
    with patch("requests.get") as mock_get:
        with patch.dict("os.environ", {"LITELLM_BASE_URL": "http://mock-cluster:8080/v1", "LITELLM_API_KEY": "mock-key"}):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": [{"id": "mock-model-1"}, {"id": "mock-model-2"}]}
            mock_get.return_value = mock_resp

            config = bootstrap._discover_cluster_config()

            assert config is not None
            assert config["architect_api_base"] == "http://mock-cluster:8080/v1"
            assert config["available_models"] == ["openai/mock-model-1", "openai/mock-model-2"]
            assert config["architect_agent"] == "openai/mock-model-1"


def test_10_session_id_injection():
    with patch("litellm.completion") as mock_completion, \
         patch("bootstrap.detect_api_key", return_value=("OPENAI_API_KEY", "dummy")):
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = []
        mock_completion.return_value = mock_resp

        bootstrap.run_query("test", None, "", True, terminal_mode=True)

        mock_completion.assert_called_once()
        kwargs = mock_completion.call_args.kwargs
        assert "custom_headers" in kwargs
        assert "x-litellm-session-id" in kwargs["custom_headers"]
        assert kwargs["custom_headers"]["x-litellm-session-id"] == bootstrap._PIPELINE_SESSION_ID


def test_11_ask_and_terminal_zero_directory_creation():
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


def test_12_helper_cloud_model_omits_api_key():
    with patch("litellm.completion", return_value=mock_response) as mock_comp:
        old_env = {k: os.environ.pop(k, None) for k in ALL_KEYS_TO_POP}
        try:
            os.environ["GEMINI_API_KEY"] = "test-key"
            bootstrap.run_query("Explain concepts", None, "", ask_mode=True)
            mock_comp.assert_called()
            kwargs = mock_comp.call_args[1]
            assert "api_key" not in kwargs, "Cloud helper queries must not pass explicit api_key in kwargs!"
        finally:
            for k, v in old_env.items():
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)


def test_13_workspace_doc_override_precedence():
    with tempfile.TemporaryDirectory() as tmp_override_dir:
        old_cwd = os.getcwd()
        os.chdir(tmp_override_dir)
        try:
            local_docs_dir = os.path.join(".aider_factory", "markdown", "docs")
            local_yaml_dir = os.path.join(".aider_factory", "sample_yaml_config")
            os.makedirs(local_docs_dir, exist_ok=True)
            os.makedirs(local_yaml_dir, exist_ok=True)

            local_sample = os.path.join(local_docs_dir, "yaml_docs_sample.md")
            with open(local_sample, "w", encoding="utf-8") as f:
                f.write("# CUSTOM WORKSPACE OVERRIDE YAML DOCS")

            local_schema = os.path.join(local_yaml_dir, "complete_env.yml")
            with open(local_schema, "w", encoding="utf-8") as f:
                f.write("name: 'CUSTOM WORKSPACE COMPLETE SCHEMA'")

            with patch("litellm.completion", return_value=mock_response), \
                 patch("os.environ", {"GEMINI_API_KEY": "test-key"}):
                # Default query overrides complete_env.yml
                bootstrap.run_query("Explain config", None, "", ask_mode=True)
                sess_file = bootstrap.get_helper_session_file()
                with open(sess_file, "r", encoding="utf-8") as sf:
                    data = json.load(sf)
                assert "CUSTOM WORKSPACE COMPLETE SCHEMA" in data[1]["content"]

                # Clear session
                bootstrap.clear_helper_session(terminal_mode=False)

                # Master query overrides yaml_docs_sample.md
                bootstrap.run_query("Explain config", None, "", ask_mode=True, master_mode=True)
                with open(sess_file, "r", encoding="utf-8") as sf:
                    data_m = json.load(sf)
                assert "CUSTOM WORKSPACE OVERRIDE YAML DOCS" in data_m[1]["content"]
        finally:
            os.chdir(old_cwd)


def test_14_reference_schema_fallback_resolution():
    with patch("litellm.completion", return_value=mock_response) as mock_comp, \
         patch("os.environ", {"GEMINI_API_KEY": "test-key"}):
        with tempfile.TemporaryDirectory() as tmp_res_dir:
            old_cwd = os.getcwd()
            os.chdir(tmp_res_dir)
            try:
                bootstrap.run_query("Check schema", None, "", ask_mode=True)
                mock_comp.assert_called()
                call_msgs = mock_comp.call_args[1]["messages"]
                assert "<reference_schema>" in call_msgs[1]["content"], "Must inject <reference_schema> even in blank directories"
                assert "endpoints:" in call_msgs[1]["content"], "Must fallback to bundled package complete_env.yml"
            finally:
                os.chdir(old_cwd)


def test_15_persona_prompt_contract_invariant():
    assert "<reference_schema>" in bootstrap.PERSONA_PROMPT
    assert "<active_configuration>" in bootstrap.PERSONA_PROMPT
    assert "minimal-delta" in bootstrap.PERSONA_PROMPT
    assert "Do NOT copy unused keys" in bootstrap.PERSONA_PROMPT


def test_16_detect_framework_from_filesystem():
    """_detect_framework() scans filesystem markers and returns correct tuple."""
    with tempfile.TemporaryDirectory() as tmp:
        # Empty dir → default py
        result = bootstrap._detect_framework(tmp)
        assert result[0] == "py"
        assert "pytest" in result[1]

    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "pytest.ini"), "w").close()
        result = bootstrap._detect_framework(tmp)
        assert result[0] == "py"

    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "Cargo.toml"), "w").close()
        result = bootstrap._detect_framework(tmp)
        assert result[0] == "rs"
        assert "cargo" in result[1]

    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "go.mod"), "w").close()
        result = bootstrap._detect_framework(tmp)
        assert result[0] == "go"

    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "package.json"), "w").close()
        result = bootstrap._detect_framework(tmp)
        assert result[0] == "js"


def test_17_bootstrap_router_model_selection():
    """When router is reachable, bootstrap selects 27b model for architect/editor."""
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "pytest.ini"), "w").close()
        with patch("env_utils.probe_router", return_value=[
            "openai/mock-flash-model",
            "openai/mock-27b-model",
            "openai/mock-embed-8b",
            "openai/mock-reranker-v3",
        ]):
            with patch.dict(os.environ, {
                "LITELLM_BASE_URL": "http://mock-router:4000/v1",
                "LITELLM_API_KEY": "sk-test",
            }):
                bootstrap.run_bootstrap(tmp)
                yaml_path = os.path.join(
                    tmp, ".aider_factory", f".env_{os.path.basename(tmp)}.yml"
                )
                assert os.path.exists(yaml_path)
                with open(yaml_path, "r") as f:
                    content = f.read()
                assert 'architect_agent: "openai/mock-27b-model"' in content
                assert 'editor_agent: "openai/mock-27b-model"' in content
                assert 'embed_model: "openai/mock-embed-8b"' in content
                assert 'ranking_agent: "openai/mock-reranker-v3"' in content
                assert "http://mock-router:4000/v1" in content


def test_18_bootstrap_zero_key_still_writes_file():
    """With no keys and no router, bootstrap still produces valid YAML."""
    old_env = {k: os.environ.pop(k, None) for k in ALL_KEYS_TO_POP}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "pytest.ini"), "w").close()
            bootstrap.run_bootstrap(tmp)
            yaml_path = os.path.join(
                tmp, ".aider_factory", f".env_{os.path.basename(tmp)}.yml"
            )
            assert os.path.exists(yaml_path), "Must produce file even with zero keys"
            import yaml
            with open(yaml_path, "r") as f:
                cfg = yaml.safe_load(f)
            assert cfg["working_directory"] == tmp
            assert "name:" in open(yaml_path).read()
    finally:
        for k, v in old_env.items():
            if v is not None:
                os.environ[k] = v


def test_19_bootstrap_no_router_preserves_placeholders():
    """Without LITELLM_BASE_URL, template placeholder endpoints are preserved."""
    old_env = {k: os.environ.pop(k, None) for k in ALL_KEYS_TO_POP}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "pytest.ini"), "w").close()
            bootstrap.run_bootstrap(tmp)
            yaml_path = os.path.join(
                tmp, ".aider_factory", f".env_{os.path.basename(tmp)}.yml"
            )
            with open(yaml_path, "r") as f:
                content = f.read()
            # Template default placeholder must remain
            assert "<your-router-host>" in content
    finally:
        for k, v in old_env.items():
            if v is not None:
                os.environ[k] = v


def test_20_probe_router_returns_none_on_failure():
    """probe_router must never raise; returns None on timeout, DNS, auth, or bad JSON."""
    from env_utils import probe_router

    # Non-200 response
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=401)
        assert probe_router("http://fake:4000/v1", "sk-bad") is None

    # Connection timeout / network error
    with patch("requests.get", side_effect=Exception("connection timeout")):
        assert probe_router("http://fake:4000/v1") is None

    # Malformed JSON body
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.side_effect = ValueError("not json")
        mock_get.return_value = mock_resp
        assert probe_router("http://fake:4000/v1") is None

    # Empty data list → returns empty list (not None)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"data": []}
        assert probe_router("http://fake:4000/v1") == []


def test_21_probe_router_prepends_openai_prefix():
    """Bare model IDs get 'openai/' prefix; already-prefixed IDs stay unchanged."""
    from env_utils import probe_router

    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"data": [
            {"id": "qwen3-27b"},
            {"id": "openai/already-prefixed"},
            {"id": "jinaai/reranker-v3"},
        ]}
        result = probe_router("http://fake:4000/v1")
        assert "openai/qwen3-27b" in result
        assert "openai/already-prefixed" in result
        assert "jinaai/reranker-v3" in result
        # Result must be sorted
        assert result == sorted(result)


def test_22_ambiguous_framework_priority():
    """When multiple markers exist, first in priority order wins (py > R > rs > js > go)."""
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "pytest.ini"), "w").close()
        open(os.path.join(tmp, "Cargo.toml"), "w").close()
        open(os.path.join(tmp, "go.mod"), "w").close()
        result = bootstrap._detect_framework(tmp)
        assert result[0] == "py", "py must win when multiple markers present"

    # R should win over rs when both present
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "DESCRIPTION"), "w").close()
        open(os.path.join(tmp, "Cargo.toml"), "w").close()
        result = bootstrap._detect_framework(tmp)
        assert result[0] == "R", "R must win over rs"


def test_23_select_models_edge_cases():
    """_select_models handles empty list, no 27b, no embed/reranker gracefully."""
    # Empty list → empty dict
    assert bootstrap._select_models([]) == {}

    # No 27b → first model wins as architect/editor
    result = bootstrap._select_models(["openai/small-model", "openai/medium-model"])
    assert result["architect"] == "openai/small-model"
    assert result["editor"] == "openai/small-model"
    assert result["embed"] is None
    assert result["reranker"] is None

    # 27b present (case-insensitive) → wins over first
    result = bootstrap._select_models(["openai/small", "openai/big-27B-v2"])
    assert result["architect"] == "openai/big-27B-v2"
    assert result["editor"] == "openai/big-27B-v2"

    # embed and reranker detection
    result = bootstrap._select_models([
        "openai/qwen3-27b",
        "openai/qwen3-embedding-8b",
        "openai/jina-reranker-v3",
    ])
    assert result["embed"] == "openai/qwen3-embedding-8b"
    assert result["reranker"] == "openai/jina-reranker-v3"


def test_24_generated_yaml_is_valid_yaml():
    """Regex substitution must never corrupt YAML syntax on any path."""
    import yaml
    old_env = {k: os.environ.pop(k, None) for k in ALL_KEYS_TO_POP}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "pytest.ini"), "w").close()
            bootstrap.run_bootstrap(tmp)
            yaml_path = os.path.join(
                tmp, ".aider_factory", f".env_{os.path.basename(tmp)}.yml"
            )
            with open(yaml_path, "r") as f:
                cfg = yaml.safe_load(f)
            assert isinstance(cfg, dict), "Generated file must be a YAML mapping"
            assert "phases" in cfg
            assert "endpoints" in cfg
            assert "name" in cfg
            assert "test_runner" in cfg
            assert isinstance(cfg["phases"], list)
            assert len(cfg["phases"]) >= 1
            assert "models" in cfg["phases"][0]
    finally:
        for k, v in old_env.items():
            if v is not None:
                os.environ[k] = v


def test_25_bootstrap_provisions_bash_wrappers():
    """After run_bootstrap(), .aider_factory/bash/ must contain executable wrappers."""
    old_env = {k: os.environ.pop(k, None) for k in ALL_KEYS_TO_POP}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "pytest.ini"), "w").close()
            bootstrap.run_bootstrap(tmp)
            bash_dir = os.path.join(tmp, ".aider_factory", "bash")
            assert os.path.isdir(bash_dir), "bash/ directory must exist"
            assert os.path.isfile(os.path.join(bash_dir, "factory"))
            assert os.access(os.path.join(bash_dir, "factory"), os.X_OK)
            assert os.path.isfile(os.path.join(bash_dir, "oracle"))
            assert os.path.isfile(os.path.join(bash_dir, "validate"))
            assert os.path.isfile(os.path.join(bash_dir, "apply"))
    finally:
        for k, v in old_env.items():
            if v is not None:
                os.environ[k] = v


if __name__ == "__main__":
    print("Running helper logic tests...")
    test_01_api_key_detection()
    test_02_helper_session_persistence_and_clear()
    test_03_query_prefix_auto_detection()
    test_04_framework_mapping_from_yaml_content()
    test_05_terminal_mode_session_persistence_and_clear()
    test_06_master_mode_logic()
    test_07_expert_mode_logic()
    test_08_repo_map_logic()
    test_09_cluster_config_discovery()
    test_10_session_id_injection()
    test_11_ask_and_terminal_zero_directory_creation()
    test_12_helper_cloud_model_omits_api_key()
    test_13_workspace_doc_override_precedence()
    test_14_reference_schema_fallback_resolution()
    test_15_persona_prompt_contract_invariant()
    test_16_detect_framework_from_filesystem()
    test_17_bootstrap_router_model_selection()
    test_18_bootstrap_zero_key_still_writes_file()
    test_19_bootstrap_no_router_preserves_placeholders()
    test_20_probe_router_returns_none_on_failure()
    test_21_probe_router_prepends_openai_prefix()
    test_22_ambiguous_framework_priority()
    test_23_select_models_edge_cases()
    test_24_generated_yaml_is_valid_yaml()
    test_25_bootstrap_provisions_bash_wrappers()
    print("All tests passed!")
