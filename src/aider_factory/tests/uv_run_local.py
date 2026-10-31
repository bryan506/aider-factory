#!/usr/bin/env python3
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# Force UTF-8 on Windows consoles to prevent cp1252 UnicodeEncodeError with emojis
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_ILLEGAL_XML_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_xml_text(text: str) -> str:
    clean = _ANSI_RE.sub("", text or "")
    return _ILLEGAL_XML_RE.sub("", clean)


def main():
    # Ensure we are running from the project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
    os.chdir(project_root)

    search_dir = Path("src/aider_factory/tests/aider_factory_tests")
    all_files = sorted([str(p) for p in search_dir.rglob("test_*.py")])

    # Upstream Aider internal summarization tests — skipped to prevent slow token-bloat loops
    slow_upstream_tests = {
        "test_e2e_architect_summarization.py",
        "test_e2e_max_chat_history_tokens.py",
    }
    all_files = [f for f in all_files if Path(f).name not in slow_upstream_tests]

    # Tests skipped in GitHub Actions CI due to resource/rate limits
    ci_skipped = {
        "test_e2e_docling_pipeline.py",
        "test_persistent_aider_e2e.py",
        "test_e2e_workflow_smoke.py",
        "test_e2e_real_session_lifecycle.py",
        "test_e2e_local_persistent_pipeline.py",
        "test_e2e_shared_history_live.py",
        "test_e2e_shared_history_and_prompt_isolation.py",
        "test_e2e_oracle_reranker_live.py",
        "test_e2e_cloud_embed_roundtrip.py",
        "test_e2e_pipeline.py",
    }

    test_files = all_files

    if "--ci-only" in sys.argv:
        test_files = [f for f in all_files if Path(f).name in ci_skipped]
        print(f"🎯 Running {len(test_files)} tests that are skipped in GitHub CI.")

    positional_args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if positional_args:
        start_target = positional_args[0]
        start_idx = -1
        for i, f in enumerate(test_files):
            if start_target == Path(f).name or start_target in f:
                start_idx = i
                break

        if start_idx > 0:
            print(f"⏩ Skipping {start_idx} tests. Starting from {test_files[start_idx]}")
            test_files = test_files[start_idx:]
        elif start_idx == -1:
            print(f"⚠️ Could not find '{start_target}' in the test list. Running all selected.")

    failed_files = []
    sub_env = os.environ.copy()
    sub_env["PYTHONUTF8"] = "1"
    sub_env["PYTHONIOENCODING"] = "utf-8"

    # Defeat CI restrictions so local GPU, cluster, and cloud models activate
    sub_env.pop("CI", None)
    sub_env["AIDER_FACTORY_LIVE_CLOUD_E2E"] = "1"
    sub_env["AIDER_YES"] = "1"
    sub_env["AIDER_NO_GITIGNORE"] = "1"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    xml_report_path = Path(f".pytest_results_{timestamp}.xml")
    master_root = ET.Element("testsuites")

    for f in test_files:
        print(f"\n{'='*80}\n🚀 RUNNING: {f}\n{'='*80}", flush=True)
        fd, tmp_xml = tempfile.mkstemp(prefix=".pytest_tmp_", suffix=".xml")
        os.close(fd)
        output_chunks = []
        try:
            cmd = [
                "uv",
                "run",
                "--with",
                "pytest",
                "pytest",
                "-s",
                "-v",
                "-ra",
                "-o",
                "junit_logging=all",
                f"--junitxml={tmp_xml}",
                f,
            ]
            proc = subprocess.Popen(
                cmd,
                env=sub_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                errors="replace",
            )
            if proc.stdout:
                for line in proc.stdout:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    output_chunks.append(line)
                proc.stdout.close()
            rc = proc.wait()
            if rc != 0:
                print(f"\n❌ FAILED: {f}", flush=True)
                failed_files.append(f)

            if os.path.exists(tmp_xml) and os.path.getsize(tmp_xml) > 0:
                try:
                    tree = ET.parse(tmp_xml)
                    root_el = tree.getroot()
                    suites = (
                        list(root_el.findall("testsuite"))
                        if root_el.tag == "testsuites"
                        else ([root_el] if root_el.tag == "testsuite" else [])
                    )
                    log_text = _sanitize_xml_text("".join(output_chunks))
                    for suite in suites:
                        suite.set("file", str(f))
                        sys_out = suite.find("system-out")
                        if sys_out is None:
                            sys_out = ET.SubElement(suite, "system-out")
                        if not (sys_out.text or "").strip() and log_text.strip():
                            sys_out.text = log_text
                        master_root.append(suite)
                    ET.ElementTree(master_root).write(
                        xml_report_path, encoding="utf-8", xml_declaration=True
                    )
                except Exception as xml_err:
                    print(
                        f"⚠️ Warning: Could not merge JUnit XML for {f}: {xml_err}",
                        file=sys.stderr,
                    )
        finally:
            if os.path.exists(tmp_xml):
                try:
                    os.remove(tmp_xml)
                except OSError:
                    pass

    print(f"\n📄 JUnit XML report saved to: {xml_report_path}")

    if failed_files:
        print("\n" + "=" * 80)
        print("🚨 TEST SUITE COMPLETED WITH FAILURES 🚨")
        print("=" * 80)
        for f in failed_files:
            print(f"  ❌ {f}")
        sys.exit(1)
    else:
        print("\n🎉 All tests passed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
