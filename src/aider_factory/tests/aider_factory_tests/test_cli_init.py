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
    if sys.platform == "win32":
        return
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


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_init_sample_yaml_config_provisioned(mock_sub, mock_bash, mock_searxng):
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            cli.init_user_project(tmp_dir)
            sample_dir = os.path.join(tmp_dir, ".aider_factory", "sample_yaml_config")
            assert os.path.isdir(sample_dir), ".aider_factory/sample_yaml_config must be created"
            assert os.path.isfile(os.path.join(sample_dir, "env_plan_do.yml")), "env_plan_do.yml must exist"
            assert os.path.isfile(os.path.join(sample_dir, "complete_env.yml")), "complete_env.yml must exist"
            assert os.path.isfile(os.path.join(sample_dir, "minimal_env.yml")), "minimal_env.yml must exist"

            catered_plan_do = os.path.join(tmp_dir, ".aider_factory", ".env_plan_do.yml")
            assert os.path.isfile(catered_plan_do), ".aider_factory/.env_plan_do.yml must be created"
            assert os.path.isdir(os.path.join(tmp_dir, "tests")), "tests/ directory must be created"
            with open(catered_plan_do, "r", encoding="utf-8") as f:
                plan_do_txt = f.read()
            assert tmp_dir.replace("\\", "/") in plan_do_txt
            assert 'test_naming_and_path: "tests/test_{stem}.py"' in plan_do_txt
        finally:
            os.chdir(original_cwd)
    print("✅ Sample YAML Config Provisioning PASS")


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_init_sample_yaml_config_does_not_overwrite_existing(mock_sub, mock_bash, mock_searxng):
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            custom_dir = os.path.join(tmp_dir, ".aider_factory", "sample_yaml_config")
            os.makedirs(custom_dir, exist_ok=True)
            custom_yaml = os.path.join(custom_dir, "env_plan_do.yml")
            with open(custom_yaml, "w", encoding="utf-8") as f:
                f.write("CUSTOM_CONFIG_PRESERVE: true\n")

            catered_plan_do = os.path.join(tmp_dir, ".aider_factory", ".env_plan_do.yml")
            with open(catered_plan_do, "w", encoding="utf-8") as f:
                f.write("CUSTOM_CATERED_PLAN_DO: true\n")

            cli.init_user_project(tmp_dir)

            with open(custom_yaml, "r", encoding="utf-8") as f:
                assert f.read() == "CUSTOM_CONFIG_PRESERVE: true\n", "Existing sample yaml must not be overwritten"
            with open(catered_plan_do, "r", encoding="utf-8") as f:
                assert f.read() == "CUSTOM_CATERED_PLAN_DO: true\n", "Existing .env_plan_do.yml must not be overwritten"
        finally:
            os.chdir(original_cwd)
    print("✅ Sample YAML Config Non-Destructive Copy PASS")


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


@patch("cli.ensure_searxng_service")
@patch("cli.ensure_bash_wrappers")
@patch("subprocess.run")
def test_aiderignore_unignores_only_strategy_template(mock_sub, mock_bash, mock_searxng):
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            ignore_path = os.path.join(tmp_dir, ".aiderignore")
            with open(ignore_path, "w", encoding="utf-8") as f:
                f.write("# Legacy\n.aider_factory/\ntemp/\n")

            cli.init_user_project(tmp_dir)

            with open(ignore_path, "r", encoding="utf-8") as f:
                upgraded = f.read()
            assert "!.aiderignore" not in upgraded
            assert upgraded.endswith(cli.AIDERIGNORE_STRATEGY_NEGATION + "\n")
            assert upgraded.index("temp/") < upgraded.index("!.aider_factory/temp/")
            for rule in (
                "!.aider_factory/",
                ".aider_factory/*",
                "!.aider_factory/CONVENTIONS.md",
                "!.aider_factory/.env.yml",
                "!.aider_factory/.env_*.yml",
                "!.aider_factory/temp/",
                "!.aider_factory/markdown/oracle_pre_plan/strategy_template.md",
                "!.aider_factory/markdown/templates/",
                "!.aider_factory/sessions/*/session.yml",
                "!.aider_factory/sessions/*/feature_adr/",
                "!.aider_factory/sessions/*/templates/",
            ):
                assert rule in upgraded

            gitignore_path = os.path.join(tmp_dir, ".gitignore")
            assert os.path.isfile(gitignore_path), ".gitignore must be created by init_user_project"
            with open(gitignore_path, "r", encoding="utf-8") as f:
                git_upgraded = f.read()
            assert git_upgraded.endswith(cli.AIDERIGNORE_STRATEGY_NEGATION + "\n")
            assert git_upgraded.index(".aider*") < git_upgraded.index("!.aider_factory/")

            pkg_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
            default_aiderignore_path = os.path.join(pkg_dir, "default_configs", "aiderignore")
            with open(default_aiderignore_path, "r", encoding="utf-8") as f:
                assert f.read().strip() == cli.BASELINE_AIDERIGNORE.strip()

            repomap_rules = cli._read_user_aiderignore(tmp_dir)
            assert repomap_rules[0] == ".aider_factory/"
            assert not any(r.startswith("!.aider_factory") for r in repomap_rules)
            assert not any(r.startswith(".aider_factory/") and r != ".aider_factory/" for r in repomap_rules)
        finally:
            os.chdir(original_cwd)
    print("✅ .aiderignore Expanded Workspace Negation PASS")


def test_legacy_multiline_aiderignore_and_gitignore_check_ignore():
    import hashlib
    import subprocess as real_subprocess

    with tempfile.TemporaryDirectory() as tmp_dir:
        real_subprocess.run(["git", "init"], cwd=tmp_dir, check=True, capture_output=True)
        real_subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_dir, check=True)
        real_subprocess.run(["git", "config", "user.email", "test@aider.local"], cwd=tmp_dir, check=True)

        ignore_path = os.path.join(tmp_dir, ".aiderignore")
        with open(ignore_path, "w", encoding="utf-8") as f:
            f.write(
                "# Ignore RAG database, logs, and caches\n"
                ".aider_factory/\n"
                ".aider_factory/markdown/internal\n"
                ".aider_factory/markdown/lanceDB\n"
                ".aider_factory/bash\n"
                ".aider_factory/.aider*\n"
                ".aider_factory/.helper*\n"
                ".aider_factory/.oracle_*\n"
                "temp/\n"
            )
        gitignore_path = os.path.join(tmp_dir, ".gitignore")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("temp/\n.aider_factory/\n.DS_Store\n.aider*\n")

        cli._ensure_baseline_aiderignore(tmp_dir)
        cli._ensure_baseline_gitignore(tmp_dir)

        with open(ignore_path, "r", encoding="utf-8") as f:
            upgraded_aider = f.read()
        with open(gitignore_path, "r", encoding="utf-8") as f:
            upgraded_git = f.read()

        assert upgraded_aider.count("# Ignore RAG database, logs, and caches") == 1
        assert upgraded_git.count("# Ignore RAG database, logs, and caches") == 1
        for stale in (
            ".aider_factory/markdown/internal",
            ".aider_factory/markdown/lanceDB",
            ".aider_factory/bash",
            ".aider_factory/.aider*",
            ".aider_factory/.helper*",
            ".aider_factory/.oracle_*",
        ):
            assert stale not in upgraded_aider
        assert upgraded_aider.endswith(cli.AIDERIGNORE_STRATEGY_NEGATION + "\n")
        assert upgraded_git.endswith(cli.AIDERIGNORE_STRATEGY_NEGATION + "\n")
        assert upgraded_aider.index("temp/") < upgraded_aider.index("!.aider_factory/temp/")
        assert upgraded_git.index("temp/") < upgraded_git.index("!.aider_factory/temp/")

        # K=4 SHA-256 byte-level idempotency check
        aider_digests = [hashlib.sha256(upgraded_aider.encode("utf-8")).hexdigest()]
        git_digests = [hashlib.sha256(upgraded_git.encode("utf-8")).hexdigest()]
        for _ in range(3):
            cli._ensure_baseline_aiderignore(tmp_dir)
            cli._ensure_baseline_gitignore(tmp_dir)
            with open(ignore_path, "rb") as f:
                aider_digests.append(hashlib.sha256(f.read()).hexdigest())
            with open(gitignore_path, "rb") as f:
                git_digests.append(hashlib.sha256(f.read()).hexdigest())
        assert len(set(aider_digests)) == 1, f".aiderignore mutated across runs: {aider_digests}"
        assert len(set(git_digests)) == 1, f".gitignore mutated across runs: {git_digests}"

        unignored_paths = (
            ".aider_factory/CONVENTIONS.md",
            ".aider_factory/.env.yml",
            ".aider_factory/.env_repo.yml",
            ".aider_factory/.env_plan_do.yml",
            ".aider_factory/temp/scratch.py",
            ".aider_factory/temp/sub/notes.md",
            ".aider_factory/markdown/oracle_pre_plan/strategy_template.md",
            ".aider_factory/markdown/templates/validate.md",
            ".aider_factory/markdown/templates/agent_persona/code-reviewer.md",
            ".aider_factory/markdown/templates/debate_instruct/oracle_contract_audit_r1.md",
            ".aider_factory/sessions/my_sess/session.yml",
            ".aider_factory/sessions/my_sess/feature_adr/adr_001.md",
            ".aider_factory/sessions/my_sess/templates/calc_validate_rendered.md",
        )

        ignored_paths_common = (
            "temp/scratch.txt",
            ".aider_factory/.aider.conf.yml",
            ".aider_factory/.aider.model.settings.yml",
            ".aider_factory/sample_yaml_config/env_plan_do.yml",
            ".aider_factory/static_repo_map.md",
            ".aider_factory/static_repo_map_tests.md",
            ".aider_factory/markdown/CONVENTIONS.md",
            ".aider_factory/markdown/oracle_pre_plan/strategy_instruct_template.md",
            ".aider_factory/markdown/internal/analyze_bugs.md",
            ".aider_factory/markdown/docs/factory_service_manual.md",
            ".aider_factory/markdown/skills/factory.md",
            ".aider_factory/markdown/lanceDB/db.lance",
            ".aider_factory/bash/factory",
            ".aider_factory/logs/run.log",
            ".aider_factory/tests/run_tests.py",
            ".aider_factory/sessions/my_sess/.aider.chat.history.md",
            ".aider_factory/sessions/my_sess/.oracle_session.json",
            ".aider_factory/sessions/my_sess/.oracle_debate_session.json",
            ".aider_factory/sessions/my_sess/.aiderignore_task",
            ".aider_factory/sessions/my_sess/chat_history/.aider.chat.history_job1.md",
        )

        # 1. Verify git check-ignore against .gitignore
        for rel in unignored_paths:
            res = real_subprocess.run(["git", "check-ignore", "-q", rel], cwd=tmp_dir)
            assert res.returncode == 1, f"{rel} must NOT be ignored by .gitignore"

        for rel in (".aiderignore",) + ignored_paths_common:
            res = real_subprocess.run(["git", "check-ignore", "-q", rel], cwd=tmp_dir)
            assert res.returncode == 0, f"{rel} MUST be ignored by .gitignore"

        # 2. Verify gitwildmatch rules in .aiderignore via git check-ignore
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write(upgraded_aider)
        try:
            for rel in unignored_paths:
                res = real_subprocess.run(["git", "check-ignore", "-q", rel], cwd=tmp_dir)
                assert res.returncode == 1, f"{rel} must NOT be ignored by .aiderignore"
            for rel in ignored_paths_common:
                res = real_subprocess.run(["git", "check-ignore", "-q", rel], cwd=tmp_dir)
                assert res.returncode == 0, f"{rel} MUST be ignored by .aiderignore"
        finally:
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(upgraded_git)

        # 3. Verify physical files with git status --porcelain and git add
        for rel in unignored_paths + ignored_paths_common:
            abs_p = os.path.join(tmp_dir, rel)
            os.makedirs(os.path.dirname(abs_p), exist_ok=True)
            with open(abs_p, "w", encoding="utf-8") as f:
                f.write("# test artifact\n")

        status_proc = real_subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=tmp_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        status_out = status_proc.stdout
        for rel in unignored_paths:
            assert f"?? {rel}" in status_out, f"Expected untracked {rel} in git status:\n{status_out}"
        for rel in ignored_paths_common:
            assert rel not in status_out, f"Ignored {rel} leaked into git status:\n{status_out}"

        add_proc = real_subprocess.run(
            ["git", "add"] + list(unignored_paths),
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        assert add_proc.returncode == 0, f"git add on un-ignored files failed:\n{add_proc.stderr}"
    print("✅ Legacy Multi-line .aiderignore & .gitignore check-ignore PASS")


def test_orchestrate_task_aiderignore_isolation():
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmp_dir:
        cli._ensure_baseline_aiderignore(tmp_dir)
        factory = AiderFactory(project_dir=tmp_dir, session_name="test_ig_sess")
        root_ignore = os.path.join(tmp_dir, ".aiderignore")

        # 1. Interactive pair_programming task uses root .aiderignore
        t_pair = Task(id="t_pair", files=["src/app.py"], pair_programming=True)
        assert factory._resolve_task_aiderignore(t_pair, ask_mode=False) == root_ignore

        # 2. Headless tasks targeting any un-ignored .aider_factory/ path use root .aiderignore
        for idx, af_target in enumerate(
            (
                ".aider_factory/CONVENTIONS.md",
                ".aider_factory/.env.yml",
                ".aider_factory/.env_plan_do.yml",
                ".aider_factory/temp/scratch.py",
                ".aider_factory/markdown/oracle_pre_plan/strategy_template.md",
                ".aider_factory/markdown/templates/validate.md",
                ".aider_factory/sessions/s1/session.yml",
                ".aider_factory/sessions/s1/feature_adr/adr_001.md",
                ".aider_factory/sessions/s1/templates/rendered.md",
            )
        ):
            t_af = Task(id=f"t_af_{idx}", files=[af_target], pair_programming=False)
            assert factory._targets_aider_factory(t_af) is True, f"Expected True for {af_target}"
            assert factory._resolve_task_aiderignore(t_af, ask_mode=False) == root_ignore

        # 3. Headless code task uses session-scoped .aiderignore_task blocking all of .aider_factory/
        t_code = Task(id="t_code", files=["src/app.py"], pair_programming=False)
        assert factory._targets_aider_factory(t_code) is False
        resolved_code_ignore = factory._resolve_task_aiderignore(t_code, ask_mode=False)
        assert resolved_code_ignore != root_ignore
        assert resolved_code_ignore.endswith(".aiderignore_task")
        with open(resolved_code_ignore, "r", encoding="utf-8") as f:
            task_ig_lines = [ln.strip() for ln in f if ln.strip()]
        assert task_ig_lines[0] == ".aider_factory/"
        assert not any(ln.startswith("!.aider_factory") for ln in task_ig_lines)

        # 4. Ask mode always uses session-scoped .aiderignore_task
        assert factory._resolve_task_aiderignore(t_pair, ask_mode=True) == resolved_code_ignore
        t_strat = Task(
            id="t_strat",
            files=[".aider_factory/markdown/oracle_pre_plan/strategy_template.md"],
            pair_programming=False,
        )
        assert factory._resolve_task_aiderignore(t_strat, ask_mode=True) == resolved_code_ignore
    print("✅ Orchestrate Task-Scoped .aiderignore Isolation PASS")


def test_aiderignore_strip_and_fault_boundaries():
    # 1. In-memory _strip_aider_factory_ignore_lines with forward/backslash and exact tokens
    raw_content = (
        "# Ignore RAG database, logs, and caches (legacy comment)\n"
        ".aider_factory\n"
        "!.aider_factory\n"
        "!.aiderignore\n"
        ".aider_factory/logs\n"
        "!.aider_factory/temp/\n"
        ".aider_factory\\windows_path\n"
        "custom_rule/\n"
        "*.custom\n"
    )
    cleaned = cli._strip_aider_factory_ignore_lines(raw_content)
    assert cleaned == ["custom_rule/", "*.custom"], f"Unexpected cleaned lines: {cleaned}"

    # 2. Fallback in _read_user_aiderignore when .aiderignore is missing, then empty/whitespace upgrade
    with tempfile.TemporaryDirectory() as tmp_dir:
        fallback_rules = cli._read_user_aiderignore(tmp_dir)
        assert fallback_rules[0] == ".aider_factory/"
        assert not any(r.startswith("!.aider_factory") for r in fallback_rules)

        ignore_path = os.path.join(tmp_dir, ".aiderignore")
        gitignore_path = os.path.join(tmp_dir, ".gitignore")
        with open(ignore_path, "w", encoding="utf-8") as f:
            f.write("   \n\n  \n")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("\n\n.aider_factory/\n\n")

        cli._ensure_baseline_aiderignore(tmp_dir)
        cli._ensure_baseline_gitignore(tmp_dir)

        with open(ignore_path, "r", encoding="utf-8") as f:
            assert f.read() == cli.AIDERIGNORE_STRATEGY_NEGATION + "\n"
        with open(gitignore_path, "r", encoding="utf-8") as f:
            assert f.read() == cli.AIDERIGNORE_STRATEGY_NEGATION + "\n"

        # 3. Read-only (0o444) PermissionError fault tolerance
        with open(ignore_path, "w", encoding="utf-8") as f:
            f.write("temp/\n.aider_factory/\n")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("temp/\n.aider_factory/\n")
        os.chmod(ignore_path, 0o444)
        os.chmod(gitignore_path, 0o444)
        try:
            cli._ensure_baseline_aiderignore(tmp_dir)
            cli._ensure_baseline_gitignore(tmp_dir)
        finally:
            os.chmod(ignore_path, 0o644)
            os.chmod(gitignore_path, 0o644)

    # 4. Directory collision (IsADirectoryError) fault tolerance
    with tempfile.TemporaryDirectory() as tmp_dir_collision:
        os.makedirs(os.path.join(tmp_dir_collision, ".aiderignore"))
        os.makedirs(os.path.join(tmp_dir_collision, ".gitignore"))
        cli._ensure_baseline_aiderignore(tmp_dir_collision)
        cli._ensure_baseline_gitignore(tmp_dir_collision)
    print("✅ .aiderignore Strip & Fault Boundaries PASS")


if __name__ == "__main__":
    test_init_empty_dir_creates_scratchpad()
    test_init_discovers_existing_files()
    test_init_playwright_provisioning()
    test_ensure_bash_wrappers_provisions_all_launchers()
    test_init_markdown_tree_provisioned()
    test_init_markdown_does_not_overwrite_existing()
    test_init_sample_yaml_config_provisioned()
    test_init_sample_yaml_config_does_not_overwrite_existing()
    test_cli_flags_in_uninitialized_directory_creates_zero_artifacts()
    test_all_cli_tools_help_flags()
    test_init_embed_defaults_are_local()
    test_bootstrap_cloud_embedder_flips_backend()
    test_bootstrap_local_embedder_keeps_backend()
    test_aiderignore_unignores_only_strategy_template()
    test_legacy_multiline_aiderignore_and_gitignore_check_ignore()
    test_orchestrate_task_aiderignore_isolation()
    test_aiderignore_strip_and_fault_boundaries()
    print("\n🎉 All CLI Quickstart Unit Tests Passed!")
