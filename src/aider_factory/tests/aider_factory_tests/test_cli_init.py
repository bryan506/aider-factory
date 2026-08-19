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


if __name__ == "__main__":
    test_init_empty_dir_creates_scratchpad()
    test_init_discovers_existing_files()
    test_init_playwright_provisioning()
    test_ensure_bash_wrappers_provisions_all_launchers()
    print("\n🎉 All CLI Quickstart Unit Tests Passed!")
