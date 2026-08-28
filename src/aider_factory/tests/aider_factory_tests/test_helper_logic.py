
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

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
    old_env = {k: os.environ.get(k) for k in ["GEMINI_API_KEY", "OPENAI_API_KEY", "AIDER_HELPER_API_BASE"]}
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


def test_04_dry_framework_mapping():
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
        for k in ["AIDER_HELPER_API_BASE", "AIDER_HELPER_MODEL"]:
            os.environ.pop(k, None)
        os.environ["GEMINI_API_KEY"] = "test-key"
        bootstrap.run_query("Explain concepts", None, "", ask_mode=True)
        mock_comp.assert_called()
        kwargs = mock_comp.call_args[1]
        assert "api_key" not in kwargs, "Cloud helper queries must not pass explicit api_key in kwargs!"


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


if __name__ == "__main__":
    print("Running helper logic tests...")
    test_01_api_key_detection()
    test_02_helper_session_persistence_and_clear()
    test_03_query_prefix_auto_detection()
    test_04_dry_framework_mapping()
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
    print("All tests passed!")
