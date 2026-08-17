#!/usr/bin/env python3
# test_e2e_factory_quickstart.py — Zero-Mock Physical Factory Quickstart & Provisioning Test.

import os
import stat
import sys
import tempfile
from pathlib import Path

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../../../python")))
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../../..")))

import cli


def run_e2e_test():
    print("\n==================================================")
    print("Starting Zero-Mock Factory Quickstart Smoke Test...")
    print("==================================================")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # 1. Execute physical project initialization
        cli.init_user_project(tmp_dir)

        # 2. Assert core configuration files exist on disk
        factory_dir = tmp_path / ".aider_factory"
        assert factory_dir.exists(), ".aider_factory directory must be created"

        env_yaml = factory_dir / ".env.yml"
        assert env_yaml.exists(), ".env.yml must be created"
        with open(env_yaml, "r", encoding="utf-8") as f:
            yaml_content = f.read()
        assert "scratchpad.py" in yaml_content, "Default scratchpad target must be in .env.yml"

        assert (tmp_path / ".aiderignore").exists(), ".aiderignore must be created"
        assert (factory_dir / ".aider.conf.yml").exists(), ".aider.conf.yml must be created"
        assert (factory_dir / ".aider.model.settings.yml").exists(), ".aider.model.settings.yml must be created"
        assert (factory_dir / "CONVENTIONS.md").exists(), "CONVENTIONS.md must be created"
        assert (tmp_path / "scratchpad.py").exists(), "scratchpad.py must be created"

        # 3. Assert executable bash wrappers are provisioned with executable permissions
        bash_dir = factory_dir / "bash"
        for wrapper_name in ["factory", "oracle", "validate", "research"]:
            wrapper_path = bash_dir / wrapper_name
            assert wrapper_path.exists(), f"Wrapper script {wrapper_name} must exist"
            mode = os.stat(wrapper_path).st_mode
            assert bool(mode & stat.S_IXUSR), f"Wrapper script {wrapper_name} must be executable (+x)"

        # 4. Assert session management operates cleanly on physical directory
        sessions = cli._list_sessions(tmp_dir)
        assert isinstance(sessions, list)

        print("  ✅ Zero-Mock Project Initialization PASS")
        print("  ✅ File Inode & Directory Tree PASS")
        print("  ✅ Executable Wrappers (+x) PASS")


if __name__ == "__main__":
    run_e2e_test()
    print("\n🎉 E2E Factory Quickstart Test Completed Successfully!")
