
#!/usr/bin/env python3
# test_e2e_helper.py — Zero-Mock Physical Smoke Test for aider-helper CLI.

import os
import subprocess
import sys
import tempfile

script_dir = os.path.dirname(os.path.abspath(__file__))
pkg_dir = os.path.abspath(os.path.join(script_dir, "../../.."))
src_dir = os.path.abspath(os.path.join(pkg_dir, ".."))
repo_root = os.path.abspath(os.path.join(src_dir, ".."))

print("==================================================")
print("Starting Zero-Mock E2E Smoke Test (aider-helper)...")
print("==================================================")

env = os.environ.copy()
python_path = f"{repo_root}:{src_dir}:{pkg_dir}:{os.path.join(pkg_dir, 'python')}"
env["PYTHONPATH"] = python_path

# 1. Test CLI Help Invariant via Real Subprocess
res_help = subprocess.run(
    [sys.executable, "-c", "import cli; cli.helper_cli()", "--help"],
    env=env,
    capture_output=True,
    text=True,
)
assert res_help.returncode == 0, f"aider-helper --help failed: {res_help.stderr}"
assert "aider-helper" in res_help.stdout or "usage:" in res_help.stdout.lower()
print("  ✅ Physical CLI Help Invariant PASS")

# 2. Test Standalone --clear via Real Subprocess
with tempfile.TemporaryDirectory() as tmp_dir:
    sess_dir = os.path.join(tmp_dir, ".aider_factory")
    os.makedirs(sess_dir, exist_ok=True)
    sess_file = os.path.join(sess_dir, ".helper_session.json")
    with open(sess_file, "w", encoding="utf-8") as f:
        f.write("[]")

    res_clear = subprocess.run(
        [sys.executable, "-c", "import cli; cli.helper_cli()", "query", "--clear"],
        cwd=tmp_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_clear.returncode == 0, f"--clear failed: {res_clear.stderr}"
    assert not os.path.exists(sess_file), "Session file must be deleted on --clear"
    print("  ✅ Physical Standalone --clear PASS")

# 3. Test Terminal --clear via Real Subprocess
with tempfile.TemporaryDirectory() as tmp_dir:
    sess_dir = os.path.join(tmp_dir, ".aider_factory")
    os.makedirs(sess_dir, exist_ok=True)
    term_sess_file = os.path.join(sess_dir, ".helper_terminal_session.json")
    with open(term_sess_file, "w", encoding="utf-8") as f:
        f.write("[]")

    res_term_clear = subprocess.run(
        [sys.executable, "-c", "import cli; cli.helper_cli()", "query", "-t", "--clear"],
        cwd=tmp_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_term_clear.returncode == 0
    assert not os.path.exists(term_sess_file), "Terminal session file must be deleted on -t --clear"
    print("  ✅ Physical Terminal --clear PASS")

# 4. Test Missing File Error Code via Real Subprocess
res_missing = subprocess.run(
    [sys.executable, "-c", "import cli; cli.helper_cli()", "query", "test", "-f", "non_existent_9999.yml"],
    env=env,
    capture_output=True,
    text=True,
)
assert res_missing.returncode == 1, "Missing file should exit with return code 1"
print("  ✅ Physical Missing File Graceful Exit PASS")

print("\n🎉 Zero-Mock E2E Smoke Test (aider-helper) Completed Successfully!")
