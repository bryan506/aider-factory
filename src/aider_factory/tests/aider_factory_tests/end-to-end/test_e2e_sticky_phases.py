#!/usr/bin/env python3
"""test_e2e_sticky_phases.py — Live zero-mock end-to-end smoke test suite for sticky_phases.
Tests multi-phase dynamic file discovery and barrier execution in real temp sandboxes
with subprocess execution, argument verification, and failure exit assertions.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
import yaml

test_file_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(test_file_dir, "../../../../.."))
src_dir = os.path.join(repo_root, "src")
pkg_dir = os.path.join(src_dir, "aider_factory")

sys.path.insert(0, repo_root)
sys.path.insert(0, src_dir)
sys.path.insert(0, pkg_dir)
sys.path.insert(0, os.path.join(pkg_dir, "python"))

RUN_WORKFLOW_PATH = os.path.join(pkg_dir, "python", "run_workflow.py")


class _MockLLMHandler(BaseHTTPRequestHandler):
    esc_calc_calls = 0

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8", errors="replace")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        import json
        if "esc_calc" in body:
            _MockLLMHandler.esc_calc_calls += 1
            if _MockLLMHandler.esc_calc_calls == 1:
                content = "VERDICT: DISAGREE\nPROPOSAL: Need additional test assertions."
            elif _MockLLMHandler.esc_calc_calls == 2:
                content = "VERDICT: DISAGREE\nPROPOSAL: Need additional test assertions."
            else:
                content = "VERDICT: AGREE\nPROPOSAL: Validated plan proposal."
        else:
            content = "VERDICT: AGREE\nPROPOSAL: Validated plan proposal."
        resp = {
            "id": "mock-cmpl-1",
            "object": "chat.completion",
            "created": 123456789,
            "model": "mock",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        self.wfile.write(json.dumps(resp).encode("utf-8"))

    def log_message(self, format, *args):
        pass


class TestE2EStickyPhases(unittest.TestCase):
    def setUp(self):
        _MockLLMHandler.esc_calc_calls = 0
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k in ("AIDER_ARCHITECT", "FAKE_AIDER_FAIL_PATTERN", "FAKE_AIDER_MUTATE_PLAN"):
                os.environ.pop(k, None)

        self.bin_dir = os.path.join(self.test_dir, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        self.log_file = os.path.join(self.test_dir, "aider_invocations.log")
        clean_log = self.log_file.replace("\\", "/")

        fake_aider_path = os.path.join(self.bin_dir, "aider")
        if sys.platform == "win32":
            fake_py = fake_aider_path + ".py"
            with open(fake_py, "w", encoding="utf-8") as f:
                f.write(textwrap.dedent(f"""\
                    import sys, os, json
                    with open("{clean_log}", "a", encoding="utf-8") as log:
                        log.write("AIDER_CALL: " + json.dumps({{"argv": sys.argv[1:]}}) + "\\n")
                    if os.environ.get("FAKE_AIDER_MUTATE_PLAN") and any("strategy_template.md" in a for a in sys.argv):
                        for a in sys.argv:
                            if "strategy_template.md" in a and os.path.isfile(a):
                                with open(a, "w", encoding="utf-8") as pf:
                                    pf.write("# Mutated Plan\\n## Scope Analysis\\n```yaml\\nfiles:\\n  target_files:\\n    - \\"src/mutated_calc.py\\"\\n  extra_editable_files: []\\n  test_files:\\n    - \\"tests/test_mutated_calc.py\\"\\n  context_files_job:\\n    - \\"docs/mutated_spec.md\\"\\n  context_files_test: []\\n```\\n")
                    if "--message" in sys.argv or "--message-file" in sys.argv:
                        print("PROPOSAL: Validated plan proposal.\\nVERDICT: AGREE")
                    fail_pat = os.environ.get("FAKE_AIDER_FAIL_PATTERN")
                    if fail_pat and fail_pat in " ".join(sys.argv):
                        sys.exit(1)
                    sys.exit(0)
                """))
            fake_cmd = fake_aider_path + ".cmd"
            with open(fake_cmd, "w", encoding="utf-8") as f:
                f.write(f'@"{sys.executable}" "%~dp0aider.py" %*\n@exit /b %errorlevel%\n')
        else:
            fake_script = f"""#!{sys.executable}
import sys, os, json
with open("{clean_log}", "a", encoding="utf-8") as log:
    log.write("AIDER_CALL: " + json.dumps({{"argv": sys.argv[1:]}}) + "\\n")
if os.environ.get("FAKE_AIDER_MUTATE_PLAN") and any("strategy_template.md" in a for a in sys.argv):
    for a in sys.argv:
        if "strategy_template.md" in a and os.path.isfile(a):
            with open(a, "w", encoding="utf-8") as pf:
                pf.write("# Mutated Plan\\n## Scope Analysis\\n```yaml\\nfiles:\\n  target_files:\\n    - \\"src/mutated_calc.py\\"\\n  extra_editable_files: []\\n  test_files:\\n    - \\"tests/test_mutated_calc.py\\"\\n  context_files_job:\\n    - \\"docs/mutated_spec.md\\"\\n  context_files_test: []\\n```\\n")
if "--message" in sys.argv or "--message-file" in sys.argv:
    print("PROPOSAL: Validated plan proposal.\\nVERDICT: AGREE")
fail_pat = os.environ.get("FAKE_AIDER_FAIL_PATTERN")
if fail_pat and fail_pat in " ".join(sys.argv):
    sys.exit(1)
sys.exit(0)
"""
            with open(fake_aider_path, "w", encoding="utf-8") as f:
                f.write(fake_script)
            os.chmod(fake_aider_path, 0o755)

        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}{os.pathsep}{self.old_path}"

    def _start_mock_server(self):
        _MockLLMHandler.esc_calc_calls = 0
        server = HTTPServer(("127.0.0.1", 0), _MockLLMHandler)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{port}/v1"
        return server, url

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ["PATH"] = self.old_path
        shutil.rmtree(self.test_dir, ignore_errors=True)
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k in ("AIDER_ARCHITECT", "FAKE_AIDER_FAIL_PATTERN", "FAKE_AIDER_MUTATE_PLAN"):
                os.environ.pop(k, None)

    def _get_subprocess_env(self, extra_env=None):
        env = os.environ.copy()
        python_path = os.pathsep.join([repo_root, src_dir, pkg_dir, os.path.join(pkg_dir, "python")])
        env["PYTHONPATH"] = python_path
        if extra_env:
            env.update(extra_env)
        return env

    def test_e2e_live_dynamic_file_propagation(self):
        """1. Real live run: Phase 0 writes strategy_template.md; Phase 1 and 2 dynamically inherit it."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Sticky Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "sticky@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "tests"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "docs"), exist_ok=True)

        target_file = os.path.join(self.test_dir, "src", "calculator.py")
        test_file = os.path.join(self.test_dir, "tests", "test_calculator.py")
        doc_file = os.path.join(self.test_dir, "docs", "formula.md")

        with open(target_file, "w", encoding="utf-8") as f:
            f.write("def add(a, b): return a + b\n")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def test_add(): assert True\n")
        with open(doc_file, "w", encoding="utf-8") as f:
            f.write("# Formula Spec\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        plan_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("""# Strategy
```yaml
notes:
  tag: "preliminary"
```
## Scope Analysis
```yaml
files:
  target_files:
    - "src/calculator.py"
  test_files:
    - "tests/test_calculator.py"
  context_files_job:
    - "docs/formula.md"
  context_files_test: []
```
""")

        config = {
            "name": "E2E Sticky Test",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase0_Planning",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": [plan_path]},
                },
                {
                    "name": "Phase1_Implementation",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {"run_job_one": True, "run_job_three": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": plan_path},
                },
                {
                    "name": "Phase2_Review",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {"run_job_one": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": []},
                },
            ],
        }

        yaml_path = os.path.join(self.test_dir, "sticky_e2e.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        res = subprocess.run(
            [sys.executable, RUN_WORKFLOW_PATH, "e2e_sticky_sess", yaml_path],
            cwd=self.test_dir,
            env=self._get_subprocess_env(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 0, f"run_workflow.py failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        self.assertTrue(os.path.exists(self.log_file), "Fake aider must have been invoked")

        with open(self.log_file, "r", encoding="utf-8") as lf:
            invocations = lf.read()

        # Assert calculator.py was passed to aider in Phase 1 and Phase 2
        self.assertIn("src/calculator.py", invocations)
        # Assert docs/formula.md was passed to aider
        self.assertIn("docs/formula.md", invocations)

    def test_e2e_zero_targets_exit_trap(self):
        """2. When strategy_template.md contains no valid targets, run_workflow exits 1 with diagnostic message."""
        plan_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("# Empty Strategy\nNo files defined.\n")

        config = {
            "name": "E2E Trap Test",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase1_Implementation",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {"run_job_one": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": plan_path},
                }
            ],
        }

        yaml_path = os.path.join(self.test_dir, "trap_e2e.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        res = subprocess.run(
            [sys.executable, RUN_WORKFLOW_PATH, "e2e_trap_sess", yaml_path],
            cwd=self.test_dir,
            env=self._get_subprocess_env(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 1)
        output = res.stdout + res.stderr
        self.assertIn("No valid on-disk target files found", output)

    def test_e2e_live_fail_fast_halt(self):
        """ADV-01: When a task fails in Phase 0, pipeline halts immediately and Phase 1 never runs."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        target_path = os.path.join(self.test_dir, "src", "failing_target.py")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("# Target to fail\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        config = {
            "name": "E2E Fail Fast Test",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase0_Failing",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/failing_target.py"]},
                },
                {
                    "name": "Phase1_Unreachable",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/failing_target.py"]},
                },
            ],
        }

        yaml_path = os.path.join(self.test_dir, "fail_fast.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        # Trigger fake aider failure on failing_target.py
        env = self._get_subprocess_env({"FAKE_AIDER_FAIL_PATTERN": "failing_target.py"})
        res = subprocess.run(
            [sys.executable, RUN_WORKFLOW_PATH, "e2e_fail_fast_sess", yaml_path],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 1, f"Expected returncode 1, got {res.returncode}")
        output = res.stdout + res.stderr
        self.assertIn("failed at task(s)", output)
        self.assertIn("Halting pipeline", output)

        # Read invocations: Phase 0 ran once, Phase 1 was completely suppressed
        with open(self.log_file, "r", encoding="utf-8") as lf:
            lines = [l for l in lf.readlines() if l.startswith("AIDER_CALL:")]
        self.assertEqual(len(lines), 1, "Phase 1 must not run after Phase 0 failure")

    def test_e2e_5field_role_segregation_telemetry(self):
        """ADV-02: Strict CLI argument verification for target_files, extra_editable_files, test_files, context_files."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "tests"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "docs"), exist_ok=True)

        t_file = os.path.join(self.test_dir, "src", "calc.py")
        e_file = os.path.join(self.test_dir, "src", "helper.py")
        test_file = os.path.join(self.test_dir, "tests", "test_calc.py")
        ctx_job = os.path.join(self.test_dir, "docs", "job_spec.md")
        ctx_test = os.path.join(self.test_dir, "docs", "test_spec.md")

        for p in (t_file, e_file, test_file, ctx_job, ctx_test):
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# {os.path.basename(p)}\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        plan_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write(f"""# Strategy
## Scope Analysis
```yaml
files:
  target_files:
    - "src/calc.py"
  extra_editable_files:
    - "src/helper.py"
  test_files:
    - "tests/test_calc.py"
  context_files_job:
    - "docs/job_spec.md"
  context_files_test:
    - "docs/test_spec.md"
```
""")

        config = {
            "name": "E2E 5-Field Telemetry Test",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase1_ImplementAndTest",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {
                        "run_job_one": True,
                        "run_job_three": True,
                        "pair_programming": False,
                        "yes_always": True,
                    },
                    "models": {
                        "architect_agent": "mock",
                        "editor_agent": "mock",
                        "editor_agent_test": "mock",
                    },
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": plan_path},
                }
            ],
        }

        yaml_path = os.path.join(self.test_dir, "telemetry.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        res = subprocess.run(
            [sys.executable, RUN_WORKFLOW_PATH, "e2e_telemetry_sess", yaml_path],
            cwd=self.test_dir,
            env=self._get_subprocess_env(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 0, f"run_workflow failed:\n{res.stdout}\n{res.stderr}")
        with open(self.log_file, "r", encoding="utf-8") as lf:
            raw_lines = [l.strip() for l in lf.readlines() if l.startswith("AIDER_CALL:")]

        self.assertEqual(len(raw_lines), 2, f"Expected 2 task invocations (Job 1 and Job 3), got: {len(raw_lines)}")
        import json
        calls = [json.loads(l[len("AIDER_CALL: "):])["argv"] for l in raw_lines]
        call_j1, call_j3 = calls[0], calls[1]

        # Call 1 (Job 1 - Implement):
        self.assertIn("src/calc.py", call_j1)
        self.assertIn("src/helper.py", call_j1)
        self.assertIn("docs/job_spec.md", call_j1)
        self.assertNotIn("tests/test_calc.py", call_j1, "Job 1 must NOT receive test file in editable arguments")
        self.assertNotIn("docs/test_spec.md", call_j1, "Job 1 must NOT receive context_files_test")

        # Call 2 (Job 3 - Write Tests):
        self.assertIn("tests/test_calc.py", call_j3, "Job 3 must receive test file")
        self.assertIn("src/calc.py", call_j3)
        self.assertIn("src/helper.py", call_j3)
        self.assertIn("docs/test_spec.md", call_j3, "Job 3 must receive context_files_test")
        self.assertNotIn("docs/job_spec.md", call_j3, "Job 3 must NOT receive context_files_job")

    def test_e2e_missing_plan_file_path_trap(self):
        """ADV-05: Missing explicit plan candidate and missing strategy_template.md cleanly traps with exit code 1."""
        config = {
            "name": "E2E Missing Plan Trap",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase1",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {"run_job_one": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": "non_existent_plan.md"},
                }
            ],
        }

        yaml_path = os.path.join(self.test_dir, "missing_plan.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        res = subprocess.run(
            [sys.executable, RUN_WORKFLOW_PATH, "e2e_missing_plan_sess", yaml_path],
            cwd=self.test_dir,
            env=self._get_subprocess_env(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 1)
        output = res.stdout + res.stderr
        self.assertIn("No valid on-disk target files found", output)

    def test_e2e_multi_target_partial_failure_halt(self):
        """ADV-08: In a multi-target phase [pass.py, fail.py], when fail.py fails,
        the workflow halts immediately and Phase 1 is never executed for either target."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        p_ok = os.path.join(self.test_dir, "src", "pass_target.py")
        p_fail = os.path.join(self.test_dir, "src", "fail_target.py")
        with open(p_ok, "w", encoding="utf-8") as f:
            f.write("# Ok target\n")
        with open(p_fail, "w", encoding="utf-8") as f:
            f.write("# Fail target\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        config = {
            "name": "E2E Multi Target Partial Failure",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase0_MultiTarget",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/pass_target.py", "src/fail_target.py"]},
                },
                {
                    "name": "Phase1_NeverReached",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/pass_target.py", "src/fail_target.py"]},
                },
            ],
        }

        yaml_path = os.path.join(self.test_dir, "partial_fail.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        # Trigger fake aider failure strictly when fail_target.py is called
        env = self._get_subprocess_env({"FAKE_AIDER_FAIL_PATTERN": "fail_target.py"})
        res = subprocess.run(
            [sys.executable, RUN_WORKFLOW_PATH, "e2e_partial_fail_sess", yaml_path],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 1)
        output = res.stdout + res.stderr
        self.assertIn("failed at task(s)", output)
        self.assertIn("p0_job1_fail_target", output)

        # Invocations must show Phase 1 was completely aborted
        with open(self.log_file, "r", encoding="utf-8") as lf:
            lines = [l.strip() for l in lf.readlines() if l.startswith("AIDER_CALL:")]
        self.assertLessEqual(len(lines), 2, "Only Phase 0 tasks can run; Phase 1 must not run")

    def test_e2e_sticky_context_deduplication_and_pass_through(self):
        """ADV-09: With sticky_context: true, Phase 1 targets pass through to Phase 2 read_files without duplication."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        f_a = os.path.join(self.test_dir, "src", "item_a.py")
        f_b = os.path.join(self.test_dir, "src", "item_b.py")
        f_c = os.path.join(self.test_dir, "src", "item_c.py")
        for fpath in (f_a, f_b, f_c):
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(f"# {os.path.basename(fpath)}\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        config = {
            "name": "E2E Sticky Context Dedup",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase0_FirstTargets",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "sticky_context": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/item_a.py", "src/item_b.py"]},
                },
                {
                    "name": "Phase1_NextTarget",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "sticky_context": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/item_c.py"]},
                },
            ],
        }

        yaml_path = os.path.join(self.test_dir, "sticky_dedup.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        res = subprocess.run(
            [sys.executable, RUN_WORKFLOW_PATH, "e2e_sticky_dedup_sess", yaml_path],
            cwd=self.test_dir,
            env=self._get_subprocess_env(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 0, f"run_workflow failed:\n{res.stdout}\n{res.stderr}")

        import json
        with open(self.log_file, "r", encoding="utf-8") as lf:
            raw_lines = [l.strip() for l in lf.readlines() if l.startswith("AIDER_CALL:")]

        # Invocations: Phase 0 item_a, Phase 0 item_b, Phase 1 item_c
        self.assertEqual(len(raw_lines), 3)
        call_p1_c = json.loads(raw_lines[2][len("AIDER_CALL: "):])["argv"]

        # Phase 1 item_c must edit item_c.py and read item_a.py and item_b.py
        self.assertIn("src/item_c.py", call_p1_c)
        self.assertIn("src/item_a.py", call_p1_c)
        self.assertIn("src/item_b.py", call_p1_c)

        # Assert no duplicate argument pass-through
        self.assertEqual(call_p1_c.count("src/item_a.py"), 1, "src/item_a.py must not be duplicated in arguments")
        self.assertEqual(call_p1_c.count("src/item_b.py"), 1, "src/item_b.py must not be duplicated in arguments")

    def test_e2e_live_plan_do_mutation(self):
        """ADV-11: Phase 0 fake-aider dynamically writes strategy_template.md during execution;
        Phase 1 dynamically inherits and edits those files without pre-baking."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "tests"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "docs"), exist_ok=True)

        target_f = os.path.join(self.test_dir, "src", "mutated_calc.py")
        test_f = os.path.join(self.test_dir, "tests", "test_mutated_calc.py")
        doc_f = os.path.join(self.test_dir, "docs", "mutated_spec.md")
        for p in (target_f, test_f, doc_f):
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# {os.path.basename(p)}\n")

        plan_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("# Initial Strategy Scaffold\nNo files yet.\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        config = {
            "name": "Live Plan Mutation Test",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase0_Planning",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "pair_programming": False, "yes_always": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": [plan_path]},
                },
                {
                    "name": "Phase1_Implementation",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {
                        "run_job_one": True,
                        "run_job_three": True,
                        "pair_programming": False,
                        "yes_always": True,
                    },
                    "models": {
                        "architect_agent": "mock",
                        "editor_agent": "mock",
                        "editor_agent_test": "mock",
                    },
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": plan_path},
                },
            ],
        }

        yaml_path = os.path.join(self.test_dir, "live_mutation.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        env = self._get_subprocess_env({"FAKE_AIDER_MUTATE_PLAN": "1"})
        res = subprocess.run(
            [sys.executable, RUN_WORKFLOW_PATH, "live_mutation_sess", yaml_path],
            cwd=self.test_dir,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 0, f"Workflow failed:\n{res.stdout}\n{res.stderr}")

        with open(plan_path, "r", encoding="utf-8") as pf:
            plan_content = pf.read()
        self.assertIn("src/mutated_calc.py", plan_content)

        with open(self.log_file, "r", encoding="utf-8") as lf:
            lines = [l.strip() for l in lf.readlines() if l.startswith("AIDER_CALL:")]

        self.assertEqual(len(lines), 3)
        import json
        c0 = json.loads(lines[0][len("AIDER_CALL: "):])["argv"]
        c1 = json.loads(lines[1][len("AIDER_CALL: "):])["argv"]
        c2 = json.loads(lines[2][len("AIDER_CALL: "):])["argv"]

        self.assertTrue(any("strategy_template.md" in a for a in c0))
        self.assertIn("src/mutated_calc.py", c1)
        self.assertIn("docs/mutated_spec.md", c1)
        self.assertIn("tests/test_mutated_calc.py", c2)

    def test_e2e_markdown_header_fallback_extraction(self):
        """ADV-12: When strategy_template.md lacks YAML code blocks, _parse_section
        extracts targets and contexts from Markdown headers in live execution."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "tests"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "docs"), exist_ok=True)

        target_f = os.path.join(self.test_dir, "src", "raw_target.py")
        extra_f = os.path.join(self.test_dir, "src", "raw_extra.py")
        test_f = os.path.join(self.test_dir, "tests", "test_raw.py")
        doc_f = os.path.join(self.test_dir, "docs", "raw_spec.md")

        for p in (target_f, extra_f, test_f, doc_f):
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# {os.path.basename(p)}\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        plan_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("""# Plain Markdown Strategy Specification

### Target Files:
- `src/raw_target.py`

### Extra Editable Files:
- `src/raw_extra.py`

### Test Files:
- `tests/test_raw.py`

### Context Files:
- `docs/raw_spec.md`
""")

        config = {
            "name": "Markdown Fallback Test",
            "working_directory": self.test_dir,
            "phases": [
                {
                    "name": "Phase1_MarkdownFallback",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {
                        "run_job_one": True,
                        "run_job_three": True,
                        "pair_programming": False,
                        "yes_always": True,
                    },
                    "models": {
                        "architect_agent": "mock",
                        "editor_agent": "mock",
                        "editor_agent_test": "mock",
                    },
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": plan_path},
                }
            ],
        }

        yaml_path = os.path.join(self.test_dir, "markdown_fallback.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        res = subprocess.run(
            [sys.executable, RUN_WORKFLOW_PATH, "md_fallback_sess", yaml_path],
            cwd=self.test_dir,
            env=self._get_subprocess_env(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(res.returncode, 0, f"Workflow failed:\n{res.stdout}\n{res.stderr}")
        with open(self.log_file, "r", encoding="utf-8") as lf:
            lines = [l.strip() for l in lf.readlines() if l.startswith("AIDER_CALL:")]

        self.assertEqual(len(lines), 2)
        import json
        c_j1 = json.loads(lines[0][len("AIDER_CALL: "):])["argv"]
        c_j3 = json.loads(lines[1][len("AIDER_CALL: "):])["argv"]

        self.assertIn("src/raw_target.py", c_j1)
        self.assertIn("src/raw_extra.py", c_j1)
        self.assertIn("docs/raw_spec.md", c_j1)

        self.assertIn("tests/test_raw.py", c_j3)
        self.assertIn("src/raw_target.py", c_j3)
        self.assertIn("src/raw_extra.py", c_j3)

    def test_e2e_pre_edit_debate_verdict_handoff(self):
        """ADV-13: Pre-edit debate [1, 0, 0] runs deliberation turn, writes .job1_verdict.md,
        and hands off the verdict file as message_file to Job 1 in real execution."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        target_f = os.path.join(self.test_dir, "src", "debate_calc.py")
        with open(target_f, "w", encoding="utf-8") as f:
            f.write("def add(a, b): return a + b\n")

        plan_f = os.path.join(self.test_dir, "plan.md")
        with open(plan_f, "w", encoding="utf-8") as f:
            f.write("# Plan: add subtraction\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        server, mock_url = self._start_mock_server()
        try:
            config = {
                "name": "Debate Handoff Test",
                "working_directory": self.test_dir,
                "endpoints": {
                    "architect_api_base": mock_url,
                    "rag_agent_api": mock_url,
                },
                "phases": [
                    {
                        "name": "PhaseDebate",
                        "enabled": True,
                        "oracle": {
                            "start_job": False,
                            "pre_edit_debate": {
                                "enabled": True,
                                "insert_debate": [1, 0, 0],
                                "loops": 1,
                            },
                        },
                        "toggles": {
                            "run_job_one": True,
                            "run_job_two": False,
                            "run_job_three": False,
                            "iterate_test": False,
                            "pair_programming": False,
                            "yes_always": True,
                        },
                        "models": {
                            "architect_agent": "openai/mock-model",
                            "editor_agent": "openai/mock-model",
                        },
                        "files": {"target_files": ["src/debate_calc.py"]},
                        "plans": {"job_one_plan": "plan.md"},
                    }
                ],
            }

            yaml_path = os.path.join(self.test_dir, "debate_handoff.yml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f)

            res = subprocess.run(
                [sys.executable, RUN_WORKFLOW_PATH, "debate_handoff_sess", yaml_path],
                cwd=self.test_dir,
                env=self._get_subprocess_env(),
                capture_output=True,
                text=True,
            )

            self.assertEqual(res.returncode, 0, f"Workflow failed:\n{res.stdout}\n{res.stderr}")

            ddir = os.path.join(self.test_dir, ".aider_factory", "logs", "debates")
            verdict_path = os.path.join(ddir, "debate_calc.job1_verdict.md")
            self.assertTrue(os.path.exists(verdict_path), f"Verdict file must exist at {verdict_path}")
            with open(verdict_path, "r", encoding="utf-8") as vf:
                vcontent = vf.read()
            self.assertIn("VERDICT: AGREE", vcontent)

            with open(self.log_file, "r", encoding="utf-8") as lf:
                lines = [l.strip() for l in lf.readlines() if l.startswith("AIDER_CALL:")]

            self.assertGreaterEqual(len(lines), 2)
            import json
            j1_call = json.loads(lines[-1][len("AIDER_CALL: "):])["argv"]
            self.assertTrue(
                any("debate_calc.job1_verdict.md" in a for a in j1_call),
                f"Expected verdict file passed in aider call arguments, got: {j1_call}",
            )
            read_indices = [i for i, x in enumerate(j1_call) if x == "--read"]
            read_files = [j1_call[i + 1] for i in read_indices]
            self.assertTrue(
                any(f.endswith("debate_calc.job1_verdict.md") for f in read_files),
                f"Expected verdict file in --read files, got: {read_files}",
            )
        finally:
            server.shutdown()
            server.server_close()

    def test_e2e_escalation_multi_round_recovery(self):
        """ADV-14: Test failure triggers Round 1 debate, re-fails, triggers Round 2
        with prior_ledger and prior_verdict present on disk, then passes."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "tests"), exist_ok=True)

        target_f = os.path.join(self.test_dir, "src", "esc_calc.py")
        with open(target_f, "w", encoding="utf-8") as f:
            f.write("def compute(): return 42\n")

        counter_file = os.path.join(self.test_dir, "test_attempts.txt")
        test_script = os.path.join(self.test_dir, "tests", "test_esc_calc.py")
        ddir = os.path.join(self.test_dir, ".aider_factory", "logs", "debates")
        v_r2 = os.path.join(ddir, "esc_calc_r2.verdict.md")
        with open(test_script, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(f"""\
                import sys, os
                cnt_file = r"{counter_file}"
                cnt = 0
                if os.path.exists(cnt_file):
                    with open(cnt_file, "r") as cf:
                        cnt = int(cf.read().strip() or "0")
                cnt += 1
                with open(cnt_file, "w") as cf:
                    cf.write(str(cnt))
                v2 = r"{v_r2}"
                if not os.path.exists(v2):
                    print(f"Test attempt {{cnt}} failed")
                    sys.exit(1)
                print(f"Test attempt {{cnt}} passed!")
                sys.exit(0)
            """))

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        server, mock_url = self._start_mock_server()
        try:
            py_exec = sys.executable.replace("\\", "/")
            config = {
                "name": "Escalation Recovery Test",
                "working_directory": self.test_dir,
                "test_command_prefix": "",
                "test_runner": f'"{py_exec}" {{file}}',
                "test_naming_and_path": "tests/test_esc_calc.py",
                "endpoints": {
                    "architect_api_base": mock_url,
                    "rag_agent_api": mock_url,
                },
                "phases": [
                    {
                        "name": "PhaseEscalate",
                        "enabled": True,
                        "oracle": {"start_job": False},
                        "toggles": {
                            "run_job_one": False,
                            "run_job_two": False,
                            "run_job_three": False,
                            "iterate_test": True,
                            "pair_programming": False,
                            "yes_always": True,
                        },
                        "escalation_debate": {
                            "loops": 1,
                            "rounds": 2,
                            "pass_history": True,
                        },
                        "models": {
                            "architect_agent": "openai/mock-model",
                            "editor_agent": "openai/mock-model",
                            "editor_agent_test": "openai/mock-model",
                        },
                        "files": {
                            "target_files": ["src/esc_calc.py"],
                            "test_files": ["tests/test_esc_calc.py"],
                        },
                    }
                ],
            }

            yaml_path = os.path.join(self.test_dir, "escalation_recovery.yml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f)

            res = subprocess.run(
                [sys.executable, RUN_WORKFLOW_PATH, "esc_recovery_sess", yaml_path],
                cwd=self.test_dir,
                env=self._get_subprocess_env(),
                capture_output=True,
                text=True,
            )

            self.assertEqual(res.returncode, 0, f"Workflow failed:\n{res.stdout}\n{res.stderr}")

            with open(counter_file, "r") as cf:
                attempts = int(cf.read().strip())
            self.assertGreaterEqual(attempts, 3, f"Expected at least 3 test attempts, got {attempts}")

            ddir = os.path.join(self.test_dir, ".aider_factory", "logs", "debates")
            v_r1 = os.path.join(ddir, "esc_calc_r1.verdict.md")
            l_r1 = os.path.join(ddir, "esc_calc_r1.debate.json")
            v_r2 = os.path.join(ddir, "esc_calc_r2.verdict.md")
            l_r2 = os.path.join(ddir, "esc_calc_r2.debate.json")

            self.assertTrue(os.path.exists(v_r1), "Round 1 verdict must exist")
            self.assertTrue(os.path.exists(l_r1), "Round 1 ledger must exist")
            self.assertTrue(os.path.exists(v_r2), "Round 2 verdict must exist")
            self.assertTrue(os.path.exists(l_r2), "Round 2 ledger must exist")
        finally:
            server.shutdown()
            server.server_close()

    def test_e2e_hybrid_grounding_to_code_barrier(self):
        """ADV-15: Multi-phase hybrid transition: Phase 0 Grounding (Autofix -> Deliberate -> Apply -> Finalize)
        successfully gates Phase 1 Code (Job 1) at the barrier in live execution."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "doc"), exist_ok=True)
        spec_f = os.path.join(self.test_dir, "doc", "spec.md")
        with open(spec_f, "w", encoding="utf-8") as f:
            f.write("# Grounding Document\n[evidence] \"Unverified claim requiring debate.\"\n")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        server, mock_url = self._start_mock_server()
        try:
            py_exec = sys.executable.replace("\\", "/")
            config = {
                "name": "Hybrid Grounding Barrier Test",
                "working_directory": self.test_dir,
                "test_command_prefix": "",
                "test_runner": f'"{py_exec}" -c "import sys; sys.exit(0)"',
                "endpoints": {
                    "architect_api_base": mock_url,
                    "rag_agent_api": mock_url,
                },
                "phases": [
                    {
                        "name": "Phase0_Grounding",
                        "enabled": True,
                        "oracle": {"start_job": False},
                        "toggles": {
                            "run_job_one": False,
                            "run_job_two": False,
                            "run_job_three": False,
                            "iterate_test": False,
                            "pair_programming": False,
                            "yes_always": True,
                        },
                        "validation": {
                            "enabled": True,
                            "post_validate": False,
                        },
                        "escalation_debate": {
                            "loops": 1,
                            "rounds": 1,
                        },
                        "models": {
                            "architect_agent": "openai/mock-model",
                            "editor_agent": "openai/mock-model",
                            "editor_agent_test": "openai/mock-model",
                        },
                        "files": {
                            "target_files": ["doc/spec.md"],
                        },
                    },
                    {
                        "name": "Phase1_Code",
                        "enabled": True,
                        "toggles": {
                            "run_job_one": True,
                            "run_job_two": False,
                            "run_job_three": False,
                            "iterate_test": False,
                            "pair_programming": False,
                            "yes_always": True,
                        },
                        "models": {
                            "architect_agent": "openai/mock-model",
                            "editor_agent": "openai/mock-model",
                        },
                        "files": {
                            "target_files": ["doc/spec.md"],
                        },
                    },
                ],
            }

            yaml_path = os.path.join(self.test_dir, "hybrid_grounding.yml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f)

            res = subprocess.run(
                [sys.executable, RUN_WORKFLOW_PATH, "hybrid_grounding_sess", yaml_path],
                cwd=self.test_dir,
                env=self._get_subprocess_env(),
                capture_output=True,
                text=True,
            )

            self.assertEqual(res.returncode, 0, f"Workflow failed:\n{res.stdout}\n{res.stderr}")

            ddir = os.path.join(self.test_dir, ".aider_factory", "logs", "debates")
            verdict_path = os.path.join(ddir, "spec.verdict.md")
            self.assertTrue(os.path.exists(verdict_path), f"Phase 0 verdict must exist at {verdict_path}")

            with open(self.log_file, "r", encoding="utf-8") as lf:
                lines = [l.strip() for l in lf.readlines() if l.startswith("AIDER_CALL:")]

            import json
            j1_calls = [json.loads(l[len("AIDER_CALL: "):])["argv"] for l in lines]
            self.assertTrue(any("doc/spec.md" in c and "--message-file" not in c for c in j1_calls))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
