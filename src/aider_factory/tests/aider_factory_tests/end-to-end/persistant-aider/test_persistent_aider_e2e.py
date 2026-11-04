#!/usr/bin/env python3
# test_persistent_aider_e2e.py — Zero-Mock Physical Pipeline Smoke Test.

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import yaml


def test_persistent_aider_smoke():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pkg_dir = os.path.abspath(os.path.join(script_dir, "../../../.."))
    src_dir = os.path.abspath(os.path.join(pkg_dir, ".."))
    repo_root = os.path.abspath(os.path.join(src_dir, ".."))
    cli_path = os.path.join(pkg_dir, "cli.py")

    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    from aider_factory.cli import init_user_project
    from aider_factory.python.env_utils import is_dummy_key, resolve_api_key

    api_key = resolve_api_key("gemini/gemini-3.8-flash")
    if not api_key or is_dummy_key(api_key):
        import pytest
        pytest.skip("GEMINI_API_KEY required for live persistent Aider smoke test.")

    print("==================================================")
    print("Starting Zero-Mock Persistent Aider Pipeline Smoke Test...")
    print("==================================================")

    with tempfile.TemporaryDirectory() as tmp_dir:
        init_user_project(tmp_dir)
        env_yml_path = os.path.join(tmp_dir, ".aider_factory", ".env.yml")
        with open(env_yml_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        phase = cfg["phases"][0]
        phase["models"]["architect_agent"] = "gemini/gemini-3.8-flash"
        phase["models"]["editor_agent"] = "gemini/gemini-3.7-flash"
        phase["models"]["editor_agent_test"] = "gemini/gemini-3.7-flash"
        phase["models"]["editor_agent_test_fallback"] = "gemini/gemini-3.7-flash"
        phase["models"]["rag_agent"] = "gemini/gemini-3.8-flash"
        phase["toggles"]["pair_programming"] = True
        phase["toggles"]["run_job_one"] = True
        phase["toggles"]["iterate_test"] = True
        phase["escalation_debate"]["loops"] = 1
        phase["escalation_debate"]["rounds"] = 1

        with open(env_yml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)

        env = os.environ.copy()
        for k in list(env.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_"):
                env.pop(k, None)
        python_path = os.pathsep.join(
            [repo_root, src_dir, pkg_dir, os.path.join(pkg_dir, "python")]
        )
        env["PYTHONPATH"] = python_path
        env["AI_FACTORY_SESSION"] = "persistent_smoke"
        env["AI_FACTORY_CONFIG"] = env_yml_path
        env["SHELL"] = shutil.which("bash") or "/bin/sh"
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

        if sys.platform != "win32":
            import pty

            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen(
                [sys.executable, cli_path, "persistent_smoke"],
                cwd=tmp_dir,
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)

            def _pty_pump():
                buf = ""
                waiting_for_prompt = False
                while True:
                    try:
                        data = os.read(master_fd, 1024)
                        if not data:
                            break
                        text = data.decode("utf-8", errors="replace")
                        if "\x1b[6n" in text:
                            try:
                                os.write(master_fd, b"\x1b[1;1R")
                            except OSError:
                                pass
                            text = text.replace("\x1b[6n", "")
                        sys.stdout.write(text)
                        sys.stdout.flush()
                        clean = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
                        buf += clean
                        if "STARTING INTERACTIVE PAIR-PROGRAMMING" in buf:
                            waiting_for_prompt = True
                            buf = buf.split("STARTING INTERACTIVE PAIR-PROGRAMMING", 1)[-1]
                        if waiting_for_prompt and ("architect>" in buf or "\n> " in buf):
                            waiting_for_prompt = False
                            buf = ""
                            time.sleep(0.4)
                            os.write(master_fd, b"/exit\n")
                    except OSError:
                        break

            pump_thread = threading.Thread(target=_pty_pump, daemon=True)
            pump_thread.start()
            returncode = proc.wait(timeout=300)
            try:
                os.close(master_fd)
            except OSError:
                pass
            pump_thread.join(timeout=2.0)
        else:
            res = subprocess.run(
                [sys.executable, cli_path, "persistent_smoke"],
                cwd=tmp_dir,
                env=env,
                input="/exit\n/exit\n/exit\n",
                text=True,
                timeout=300,
            )
            returncode = res.returncode

        assert returncode == 0, f"Pipeline execution failed with return code {returncode}"

        # Verify session artifacts created on disk
        sess_dir = os.path.join(tmp_dir, ".aider_factory", "sessions", "persistent_smoke")
        assert os.path.exists(sess_dir), "Session directory was not created."
        assert os.path.exists(os.path.join(sess_dir, "session.yml")), "session.yml was not paired."

        # Verify logs and debate artifacts generated
        logs_dir = os.path.join(tmp_dir, ".aider_factory", "logs")
        assert os.path.exists(logs_dir), "Logs directory must exist."
        debates_dir = os.path.join(logs_dir, "debates")
        assert os.path.exists(os.path.join(debates_dir, "scratchpad.verdict.md")), "Debate verdict must exist."
        assert os.path.exists(os.path.join(debates_dir, "scratchpad.debate.json")), "Debate ledger must exist."

    print("\n✅ Zero-Mock Persistent Aider Pipeline Smoke Test PASS")
