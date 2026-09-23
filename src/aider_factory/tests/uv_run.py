#!/usr/bin/env python3
import os
import subprocess
import sys

# Force UTF-8 on Windows consoles to prevent cp1252 UnicodeEncodeError with emojis
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def main():
    # Ensure we are running from the project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
    os.chdir(project_root)

    from pathlib import Path

    search_dir = Path("src/aider_factory/tests/aider_factory_tests")
    all_files = sorted([str(p) for p in search_dir.rglob("test_*.py")])

    # Filter out tests ignored in CI to save time/money
    ignored_tests = {
        "test_e2e_docling_pipeline.py",
        "test_e2e_max_chat_history_tokens.py",
        "test_e2e_architect_summarization.py",
        "test_persistent_aider_e2e.py",
        "test_e2e_workflow_smoke.py",
        "test_e2e_real_session_lifecycle.py",
        "test_e2e_local_persistent_pipeline.py",
        "test_e2e_shared_history_live.py",
        "test_e2e_shared_history_and_prompt_isolation.py",
        "test_e2e_oracle_reranker_live.py",
        "test_e2e_cloud_embed_roundtrip.py",
        "test_e2e_pipeline.py"
    }

    test_files = [f for f in all_files if Path(f).name not in ignored_tests]

    if len(sys.argv) > 1:
        start_target = sys.argv[1]
        start_idx = -1
        for i, f in enumerate(test_files):
            # Match by exact filename or partial path
            if start_target == Path(f).name or start_target in f:
                start_idx = i
                break
        
        if start_idx > 0:
            print(f"⏩ Skipping {start_idx} tests. Starting from {test_files[start_idx]}")
            test_files = test_files[start_idx:]
        elif start_idx == -1:
            print(f"⚠️ Could not find '{start_target}' in the test list. Running all.")

    failed_files = []
    sub_env = os.environ.copy()
    sub_env["PYTHONUTF8"] = "1"
    sub_env["PYTHONIOENCODING"] = "utf-8"

    for f in test_files:
        print(f"\n{'='*80}\n🚀 RUNNING: {f}\n{'='*80}")
        cmd = ["uv", "run", "--with", "pytest", "pytest", "-s", "-v", f]
        rc = subprocess.call(cmd, env=sub_env)
        if rc != 0:
            print(f"\n❌ FAILED: {f}")
            failed_files.append(f)

    if failed_files:
        print("\n" + "="*80)
        print("🚨 TEST SUITE COMPLETED WITH FAILURES 🚨")
        print("="*80)
        for f in failed_files:
            print(f"  ❌ {f}")
        sys.exit(1)
    else:
        print("\n🎉 All tests passed successfully!")
        sys.exit(0)

if __name__ == "__main__":
    main()
