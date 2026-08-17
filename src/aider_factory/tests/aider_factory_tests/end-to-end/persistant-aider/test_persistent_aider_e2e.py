#!/usr/bin/env python3
# test_persistent_aider_e2e.py — Zero-Mock Physical Pipeline Smoke Test.

import os
import shutil
import subprocess
import sys
import tempfile

script_dir = os.path.dirname(os.path.abspath(__file__))
pkg_dir = os.path.abspath(os.path.join(script_dir, "../../../.."))
src_dir = os.path.abspath(os.path.join(pkg_dir, ".."))
repo_root = os.path.abspath(os.path.join(src_dir, ".."))
cli_path = os.path.join(pkg_dir, "cli.py")

print("==================================================")
print("Starting Zero-Mock Persistent Aider Pipeline Smoke Test...")
print("==================================================")

with tempfile.TemporaryDirectory() as tmp_dir:
    env = os.environ.copy()
    python_path = f"{repo_root}:{src_dir}:{pkg_dir}:{os.path.join(pkg_dir, 'python')}"
    env["PYTHONPATH"] = python_path
    env["AI_FACTORY_SESSION"] = "persistent_smoke"

    # Run the real CLI entrypoint
    res = subprocess.run(
        [sys.executable, cli_path, "persistent_smoke"],
        cwd=tmp_dir,
        env=env,
        stdout=None,
        stderr=None,
    )

    assert res.returncode == 0, f"Pipeline execution failed with return code {res.returncode}"

    # Verify session artifacts created on disk
    sess_dir = os.path.join(tmp_dir, ".aider_factory", "sessions", "persistent_smoke")
    assert os.path.exists(sess_dir), "Session directory was not created."
    assert os.path.exists(os.path.join(sess_dir, "session.yml")), "session.yml was not paired."

    # Verify logs directory generated
    logs_dir = os.path.join(tmp_dir, ".aider_factory", "logs")
    assert os.path.exists(logs_dir), "Logs directory must exist."

print("\n✅ Zero-Mock Persistent Aider Pipeline Smoke Test PASS")
