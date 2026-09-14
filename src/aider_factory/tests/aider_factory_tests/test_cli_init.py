#!/usr/bin/env python3
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../../python")))
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../..")))

import cli

print("Starting CLI Quickstart Unit Tests...\n")

@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_init_empty_dir_creates_scratchpad(mock_sub, mock_bash, mock_searxng):
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            cli.init_user_project(tmp_dir)
            
            assert os.path.exists("scratchpad.py"), "scratchpad.py should be created in an empty dir"
            
            env_yaml = os.path.join(".aider_factory", ".env.yml")
            assert os.path.exists(env_yaml), ".env.yml should be created"
            
            with open(env_yaml, "r") as f:
                content = f.read()
            
            assert 'target_files:\n        - "scratchpad.py"' in content, "scratchpad.py must be injected as target"
        finally:
            os.chdir(original_cwd)
    print("✅ Empty Directory Scratchpad Creation PASS")


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_init_discovers_existing_files(mock_sub, mock_bash, mock_searxng):
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            # Create dummy files
            with open("main.py", "w") as f: f.write("# main")
            with open("README.md", "w") as f: f.write("# readme")
            
            cli.init_user_project(tmp_dir)
            
            env_yaml = os.path.join(".aider_factory", ".env.yml")
            with open(env_yaml, "r") as f:
                content = f.read()
            
            assert 'target_files:\n        - "main.py"' in content, "main.py must be injected as target"
            assert 'context_files_job:\n        - "README.md"' in content, "README.md must be injected as context"
            assert not os.path.exists("scratchpad.py"), "scratchpad.py should NOT be created if files exist"
        finally:
            os.chdir(original_cwd)
    print("✅ Existing File Discovery PASS")


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_init_playwright_provisioning(mock_sub, mock_bash, mock_searxng):
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            # Mock the playwright import and force an empty cache directory
            import sys
            sys.modules["playwright"] = MagicMock()
            
            # Capture the original os.path.exists to avoid infinite recursion
            original_exists = os.path.exists
            
            with patch("os.path.exists", side_effect=lambda p: False if "ms-playwright" in str(p) else original_exists(p)):
                cli.init_user_project(tmp_dir)
                
            # Verify subprocess.run was called to install playwright browsers
            called_install = any("playwright" in args[0][0] and "install" in args[0][0] for args in mock_sub.call_args_list)
            assert called_install, "Playwright install command should be triggered if cache is empty"
            
            del sys.modules["playwright"]
        finally:
            os.chdir(original_cwd)
    print("✅ Playwright Auto-Provisioning PASS")


def test_ensure_bash_wrappers_provisions_all_launchers():
    with tempfile.TemporaryDirectory() as tmp_dir:
        af_dir = os.path.join(tmp_dir, ".aider_factory")
        cli.ensure_bash_wrappers(af_dir)
        bash_dir = os.path.join(af_dir, "bash")
        for launcher in ["factory", "oracle", "validate", "research", "apply"]:
            launcher_path = os.path.join(bash_dir, launcher)
            assert os.path.isfile(launcher_path), f"Missing launcher script: {launcher}"
            assert os.access(launcher_path, os.X_OK), f"Launcher script not executable: {launcher}"
    print("✅ All Bash Wrappers Provisioning PASS")


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_init_markdown_tree_provisioned(mock_sub, mock_bash, mock_searxng):
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            cli.init_user_project(tmp_dir)
            local_markdown_dir = os.path.join(tmp_dir, ".aider_factory", "markdown")
            assert os.path.isdir(local_markdown_dir), ".aider_factory/markdown must be created"
            for subdir in ["docs", "oracle_pre_plan", "skills", "templates", "internal"]:
                assert os.path.isdir(
                    os.path.join(local_markdown_dir, subdir)
                ), f"Missing markdown/{subdir}"
        finally:
            os.chdir(original_cwd)
    print("✅ Markdown Tree Provisioning PASS")


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_init_markdown_does_not_overwrite_existing(mock_sub, mock_bash, mock_searxng):
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            custom_dir = os.path.join(
                tmp_dir, ".aider_factory", "markdown", "templates"
            )
            os.makedirs(custom_dir, exist_ok=True)
            custom_file = os.path.join(custom_dir, "custom_template.md")
            with open(custom_file, "w", encoding="utf-8") as f:
                f.write("CUSTOM CONTENT DO NOT OVERWRITE")

            cli.init_user_project(tmp_dir)

            with open(custom_file, "r", encoding="utf-8") as f:
                assert (
                    f.read() == "CUSTOM CONTENT DO NOT OVERWRITE"
                ), "Existing user files must not be overwritten"
        finally:
            os.chdir(original_cwd)
    print("✅ Markdown Non-Destructive Copy PASS")


def test_cli_flags_in_uninitialized_directory_creates_zero_artifacts():
    """Verify management and help flags do not scaffold .git or .aider_factory in arbitrary uninitialized directories."""
    with tempfile.TemporaryDirectory() as temp_dir:
        original_cwd = os.getcwd()
        os.chdir(temp_dir)
        try:
            # Test --help flag creates zero files
            with patch("sys.argv", ["aider-factory", "--help"]), patch("sys.exit") as mock_exit:
                mock_exit.side_effect = SystemExit(0)
                try:
                    cli.main()
                except SystemExit as e:
                    assert e.code == 0
            assert os.listdir(temp_dir) == [], f"Expected empty dir after --help, found: {os.listdir(temp_dir)}"

            # Test --clear-all -g --forever creates zero files
            with patch("sys.argv", ["aider-factory", "--clear-all", "-g", "--forever"]), \
                 patch("cli._get_registered_projects", return_value=[]), \
                 patch("sys.exit") as mock_exit:
                mock_exit.side_effect = SystemExit(0)
                try:
                    cli.main()
                except SystemExit as e:
                    assert e.code == 0
            assert os.listdir(temp_dir) == [], f"Expected empty dir after --clear-all -g --forever, found: {os.listdir(temp_dir)}"
        finally:
            os.chdir(original_cwd)
    print("✅ Zero Artifact Scaffolding in Uninitialized Dir PASS")


def test_all_cli_tools_help_flags():
    """Verify that --help and -h flags across all CLI entry points output usage and exit 0."""
    import oracle_agent
    import research_agent
    import apply_agent
    import validator

    # 1. Test oracle_agent --help and -h
    with patch("sys.argv", ["aider-oracle", "--help"]):
        assert oracle_agent.main() == 0

    with patch("sys.argv", ["aider-oracle", "-h"]):
        assert oracle_agent.main() == 0

    # 2. Test research_agent --help and search -h
    for flag_combo in [["aider-research", "--help"], ["aider-research", "search", "-h"], ["aider-research"]]:
        with patch("sys.argv", flag_combo), patch("sys.exit") as mock_exit:
            mock_exit.side_effect = SystemExit(0)
            try:
                research_agent.main()
            except SystemExit as e:
                assert e.code == 0

    # 3. Test apply_agent --help
    with patch("sys.argv", ["aider-apply", "--help"]), patch("sys.exit") as mock_exit:
        mock_exit.side_effect = SystemExit(0)
        try:
            apply_agent.main()
        except SystemExit as e:
            assert e.code == 0

    # 4. Test validator --help
    with patch("sys.argv", ["aider-validate", "--help"]), patch("sys.exit") as mock_exit:
        mock_exit.side_effect = SystemExit(0)
        try:
            validator.main()
        except SystemExit as e:
            assert e.code == 0

    print("✅ All CLI Tools --help / -h Parity PASS")


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_init_embed_defaults_are_local(mock_sub, mock_bash, mock_searxng):
    """The shipped template must ship BAAI/bge-m3 + sentence-transformers (no cloud model)."""
    pkg_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
    template_path = os.path.join(
        pkg_dir, "default_configs", "sample_yaml_config", "complete_env.yml"
    )
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert 'embed_model: "BAAI/bge-m3"' in content, \
        "Template must ship BAAI/bge-m3 as default embed model"
    assert 'embed_backend: "sentence-transformers"' in content, \
        "Template must ship sentence-transformers backend"
    assert "gemini/text-embedding-004" not in content, \
        "Template must not reference cloud embedder"
    print("✅ Embed default is BAAI/bge-m3 + sentence-transformers PASS")


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_bootstrap_cloud_embedder_flips_backend(mock_sub, mock_bash, mock_searxng):
    """When probe_router returns a cloud embedder, embed_backend must become openai."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        original_env = os.environ.get("LITELLM_BASE_URL")
        try:
            os.environ["LITELLM_BASE_URL"] = "http://fake-router:4000/v1"
            import bootstrap
            with patch("env_utils.probe_router",
                       return_value=["gemini/text-embedding-004", "gemini/gemini-3.6-flash"]), \
                 patch.object(bootstrap, "_detect_framework",
                              return_value=("py", "uv run --with pytest pytest", "tests/test_{stem}.py", "")), \
                 patch.object(bootstrap, "detect_api_key",
                              return_value=("LITELLM_API_KEY", "sk-test")), \
                 patch("cli.init_user_project"):
                bootstrap.run_bootstrap(tmp_dir)

            repo_name = os.path.basename(tmp_dir).strip().replace(" ", "_")
            with open(os.path.join(".aider_factory", f".env_{repo_name}.yml"), "r") as f:
                content = f.read()
            assert 'embed_model: "gemini/text-embedding-004"' in content
            assert 'embed_backend: "openai"' in content
        finally:
            if original_env is None:
                os.environ.pop("LITELLM_BASE_URL", None)
            else:
                os.environ["LITELLM_BASE_URL"] = original_env
            os.chdir(original_cwd)
    print("✅ Cloud embedder flips backend to openai PASS")


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_bootstrap_local_embedder_keeps_backend(mock_sub, mock_bash, mock_searxng):
    """When probe_router returns a local embedder, embed_backend stays sentence-transformers."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        original_env = os.environ.get("LITELLM_BASE_URL")
        try:
            os.environ["LITELLM_BASE_URL"] = "http://fake-router:4000/v1"
            import bootstrap
            # Model name must contain "embed" so _select_models() picks it,
            # but must NOT contain gemini/openai/embedding/qwen so backend stays sentence-transformers.
            with patch("env_utils.probe_router",
                       return_value=["baai-embed-v1", "qwen3-27b"]), \
                 patch.object(bootstrap, "_detect_framework",
                              return_value=("py", "uv run --with pytest pytest", "tests/test_{stem}.py", "")), \
                 patch.object(bootstrap, "detect_api_key",
                              return_value=("LITELLM_API_KEY", "sk-test")), \
                 patch("cli.init_user_project"):
                bootstrap.run_bootstrap(tmp_dir)

            repo_name = os.path.basename(tmp_dir).strip().replace(" ", "_")
            with open(os.path.join(".aider_factory", f".env_{repo_name}.yml"), "r") as f:
                content = f.read()
            assert 'embed_model: "baai-embed-v1"' in content
            assert 'embed_backend: "sentence-transformers"' in content
        finally:
            if original_env is None:
                os.environ.pop("LITELLM_BASE_URL", None)
            else:
                os.environ["LITELLM_BASE_URL"] = original_env
            os.chdir(original_cwd)
    print("✅ Local embedder keeps sentence-transformers backend PASS")


if __name__ == "__main__":
    test_init_empty_dir_creates_scratchpad()
    test_init_discovers_existing_files()
    test_init_playwright_provisioning()
    test_ensure_bash_wrappers_provisions_all_launchers()
    test_init_markdown_tree_provisioned()
    test_init_markdown_does_not_overwrite_existing()
    test_cli_flags_in_uninitialized_directory_creates_zero_artifacts()
    test_all_cli_tools_help_flags()
    test_init_embed_defaults_are_local()
    test_bootstrap_cloud_embedder_flips_backend()
    test_bootstrap_local_embedder_keeps_backend()
    print("\n🎉 All CLI Quickstart Unit Tests Passed!")
