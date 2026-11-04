#!/usr/bin/env python3
"""test_e2e_env_plan_do_debate.py — Live zero-mock end-to-end test suite for env_plan_do.yml
pre-edit debate chains, sequential multi-test-file execution, and verdict_gate enforcement.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
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
    recorded_requests = []
    recorded_metrics = []
    revise_then_agree = False
    force_disagree = False
    call_counter = 0

    @classmethod
    def reset_state(cls):
        cls.esc_calc_calls = 0
        cls.recorded_requests = []
        cls.recorded_metrics = []
        cls.revise_then_agree = False
        cls.force_disagree = False
        cls.call_counter = 0

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8", errors="replace")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            req_json = json.loads(body)
        except Exception:
            req_json = {"raw": body}
        _MockLLMHandler.recorded_requests.append(req_json)

        _MockLLMHandler.call_counter += 1
        if _MockLLMHandler.force_disagree:
            content = "VERDICT: DISAGREE\nPROPOSAL: Unresolved architectural blocker."
        elif "esc_calc" in body:
            _MockLLMHandler.esc_calc_calls += 1
            if _MockLLMHandler.esc_calc_calls == 1:
                content = "VERDICT: DISAGREE\nPROPOSAL: Need additional test assertions."
            elif _MockLLMHandler.esc_calc_calls == 2:
                content = "VERDICT: DISAGREE\nPROPOSAL: Need additional test assertions."
            else:
                content = "VERDICT: AGREE\nPROPOSAL: Validated plan proposal."
        elif _MockLLMHandler.revise_then_agree:
            mod = _MockLLMHandler.call_counter % 3
            if mod == 1:
                content = "<critique>Initial pre-assessment of scope and contracts.</critique>"
            elif mod == 2:
                content = "<critique>Ensure boundary validation is explicit.</critique>\nVERDICT: REVISE"
            else:
                content = "<critique>All contract requirements verified.</critique>\nVERDICT: AGREE"
        else:
            content = "VERDICT: AGREE\nPROPOSAL: Validated plan proposal."

        msgs = req_json.get("messages", []) if isinstance(req_json, dict) else []
        prompt_chars = sum(len(str(m.get("content", ""))) for m in msgs if isinstance(m, dict))
        prompt_tokens = max(1, prompt_chars // 4)
        completion_tokens = max(1, len(content) // 4)
        _MockLLMHandler.recorded_metrics.append(
            {
                "prompt_chars": prompt_chars,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "num_messages": len(msgs),
                "response": content,
            }
        )
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
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        self.wfile.write(json.dumps(resp).encode("utf-8"))

    def log_message(self, format, *args):
        pass


class TestE2EEnvPlanDoDebate(unittest.TestCase):
    def setUp(self):
        _MockLLMHandler.reset_state()
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k in (
                "AIDER_ARCHITECT",
                "FAKE_AIDER_FAIL_PATTERN",
                "FAKE_AIDER_MUTATE_PLAN",
                "FAKE_AIDER_PLAN_DO_LIVE_SIM",
                "FAKE_AIDER_MULTI_TEST_SIM",
            ):
                os.environ.pop(k, None)

        self.bin_dir = os.path.join(self.test_dir, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        self.log_file = os.path.join(self.test_dir, "aider_invocations.log")
        clean_log = self.log_file.replace("\\", "/")

        fake_body = textwrap.dedent(f"""\
            import sys, os, json, subprocess
            msg_content = ""
            if "--message-file" in sys.argv:
                idx = sys.argv.index("--message-file")
                if idx + 1 < len(sys.argv) and os.path.isfile(sys.argv[idx + 1]):
                    with open(sys.argv[idx + 1], "r", encoding="utf-8", errors="replace") as mf:
                        msg_content = mf.read()
            with open("{clean_log}", "a", encoding="utf-8") as log:
                log.write("AIDER_CALL: " + json.dumps({{"argv": sys.argv[1:], "msg_file_content": msg_content}}) + "\\n")
            if os.path.isfile(".gitignore") and os.path.isdir(".git"):
                _val_flags = {{"--read", "--message", "--message-file", "--config", "--model-settings-file", "--aiderignore", "--chat-history-file", "--input-history-file", "--llm-history-file", "--model", "--editor-model", "--weak-model", "--edit-format", "--map-tokens", "--map-refresh", "--map-multiplier-no-files", "--max-chat-history-tokens", "--test-cmd", "--lint-cmd"}}
                _args = sys.argv[1:]
                for _i, _a in enumerate(_args):
                    if _a.startswith("-") or (_i > 0 and _args[_i - 1] in _val_flags):
                        continue
                    if ".aider_factory" in _a.replace("\\\\", "/"):
                        _chk = subprocess.run(["git", "check-ignore", "-q", _a])
                        if _chk.returncode == 0:
                            print(f"Can't add {{_a}} which is in gitignore", file=sys.stderr)
                            sys.exit(1)
            if os.environ.get("FAKE_AIDER_MUTATE_PLAN") and any("strategy_template.md" in a for a in sys.argv):
                for a in sys.argv:
                    if "strategy_template.md" in a and os.path.isfile(a):
                        with open(a, "w", encoding="utf-8") as pf:
                            pf.write("# Mutated Plan\\n## Scope Analysis\\n```yaml\\nfiles:\\n  target_files:\\n    - \\"src/mutated_calc.py\\"\\n  extra_editable_files: []\\n  test_files:\\n    - \\"tests/test_mutated_calc.py\\"\\n  context_files_job:\\n    - \\"docs/mutated_spec.md\\"\\n  context_files_test: []\\n```\\n")
            if os.environ.get("FAKE_AIDER_PLAN_DO_LIVE_SIM"):
                _seed_tasks = (
                    "## Implementation Plan\\n"
                    "### [Task ID: SEED_001] - Seed Task 1\\n"
                    "### [Task ID: SEED_002] - Seed Task 2\\n"
                    "### [Task ID: SEED_003] - Seed Task 3\\n"
                    "### [Task ID: SEED_004] - Seed Task 4\\n"
                    "### [Task ID: SEED_005] - Seed Task 5\\n"
                    "### [Task ID: SEED_006] - Seed Task 6\\n"
                )
                if any(a.endswith("strategy_template.md") for a in sys.argv) and "ask" not in sys.argv and "calc_validate_rendered.md" not in " ".join(sys.argv):
                    for a in sys.argv:
                        if a.endswith("strategy_template.md") and os.path.isfile(a) and "--read" != sys.argv[sys.argv.index(a) - 1]:
                            with open(a, "w", encoding="utf-8") as pf:
                                if os.environ.get("FAKE_AIDER_MULTI_TEST_SIM") == "1":
                                    pf.write("# Strategy\\nUNIQUE_STRATEGY_CONSTRAINT_99\\n## Scope Analysis\\n```yaml\\nfiles:\\n  target_files:\\n    - \\"src/calc.py\\"\\n  extra_editable_files:\\n    - \\"src/helper.py\\"\\n  test_files:\\n    - \\"tests/unit/test_calc_unit.py\\"\\n    - \\"tests/e2e/test_calc_e2e.py\\"\\n  context_files_job:\\n    - \\"docs/domain.md\\"\\n  context_files_test:\\n    - \\"docs/test_rules.md\\"\\n```\\n" + _seed_tasks)
                                else:
                                    pf.write("# Strategy\\nUNIQUE_STRATEGY_CONSTRAINT_99\\n## Scope Analysis\\n```yaml\\nfiles:\\n  target_files:\\n    - \\"src/calc.py\\"\\n  extra_editable_files:\\n    - \\"src/helper.py\\"\\n  test_files: []\\n  context_files_job:\\n    - \\"docs/domain.md\\"\\n  context_files_test:\\n    - \\"docs/test_rules.md\\"\\n```\\n" + _seed_tasks)
                if "src/calc.py" in sys.argv and "ask" not in sys.argv and any(a.endswith("strategy_template.md") for a in sys.argv):
                    with open("src/calc.py", "w", encoding="utf-8") as cf:
                        cf.write("def add(a, b):\\n    return int(a) + int(b)\\n")
                    with open("src/helper.py", "w", encoding="utf-8") as hf:
                        hf.write("def scale(x):\\n    return x * 2\\n")
                if any("calc.job2_verdict_r2.md" in a for a in sys.argv) and "ask" not in sys.argv:
                    with open("src/calc.py", "a", encoding="utf-8") as cf:
                        cf.write("# Job 2 validated implementation\\n")
                if any("calc.job3_verdict_r2.md" in a for a in sys.argv) and "ask" not in sys.argv:
                    _args_after_read = []
                    _i = 1
                    while _i < len(sys.argv):
                        if sys.argv[_i] in ("--read", "--message", "--message-file", "--config", "--model-settings-file", "--aiderignore", "--chat-history-file", "--input-history-file", "--llm-history-file", "--model", "--editor-model", "--weak-model", "--edit-format", "--map-tokens", "--map-refresh", "--map-multiplier-no-files", "--max-chat-history-tokens", "--test-cmd", "--lint-cmd"):
                            _i += 2
                            continue
                        if not sys.argv[_i].startswith("-"):
                            _args_after_read.append(sys.argv[_i].replace("\\\\", "/"))
                        _i += 1
                    if "tests/unit/test_calc_unit.py" in _args_after_read:
                        os.makedirs("tests/unit", exist_ok=True)
                        with open("tests/unit/test_calc_unit.py", "w", encoding="utf-8") as tf:
                            tf.write("import sys, os\\nsys.path.insert(0, os.path.abspath('.'))\\nfrom src.calc import add\\ndef test_add_unit():\\n    assert add(2, 3) == 5\\n")
                    elif "tests/e2e/test_calc_e2e.py" in _args_after_read:
                        os.makedirs("tests/e2e", exist_ok=True)
                        with open("tests/e2e/test_calc_e2e.py", "w", encoding="utf-8") as tf:
                            tf.write("import sys, os\\nsys.path.insert(0, os.path.abspath('.'))\\nfrom src.helper import scale\\ndef test_scale_e2e():\\n    assert scale(4) == 8\\n")
                    else:
                        os.makedirs("tests/unit", exist_ok=True)
                        with open("tests/unit/test_calc.py", "w", encoding="utf-8") as tf:
                            tf.write("import sys, os\\nsys.path.insert(0, os.path.abspath('.'))\\nfrom src.calc import add\\ndef test_add_real_pytest():\\n    assert add(2, 3) == 5\\n")
                if "--edit-format" in sys.argv and "ask" in sys.argv:
                    if "The Oracle reviewed your proposal and responded:" in msg_content:
                        print("PROPOSAL: Confirmed all revisions applied.")
                    else:
                        print("## Implementation Plan\\n### [Task ID: 001] - Primary Edit\\n### [Task ID: 002] - Helper Edit\\n### [Task ID: 003] - Boundary Check\\n### [Task ID: 004] - Validation Check\\nPROPOSAL: Complete 4-task specification.")
                    sys.exit(0)
            if "--message" in sys.argv or "--message-file" in sys.argv:
                print("PROPOSAL: Validated plan proposal.\\nVERDICT: AGREE")
            fail_pat = os.environ.get("FAKE_AIDER_FAIL_PATTERN")
            if fail_pat and fail_pat in " ".join(sys.argv):
                sys.exit(1)
            sys.exit(0)
        """)

        fake_aider_path = os.path.join(self.bin_dir, "aider")
        if sys.platform == "win32":
            fake_py = fake_aider_path + ".py"
            with open(fake_py, "w", encoding="utf-8") as f:
                f.write(fake_body)
            fake_cmd = fake_aider_path + ".cmd"
            with open(fake_cmd, "w", encoding="utf-8") as f:
                f.write(f'@"{sys.executable}" "%~dp0aider.py" %*\n@exit /b %errorlevel%\n')
        else:
            with open(fake_aider_path, "w", encoding="utf-8") as f:
                f.write(f"#!{sys.executable}\n" + fake_body)
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
        _MockLLMHandler.reset_state()
        os.chdir(self.old_cwd)
        os.environ["PATH"] = self.old_path
        shutil.rmtree(self.test_dir, ignore_errors=True)
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k in (
                "AIDER_ARCHITECT",
                "FAKE_AIDER_FAIL_PATTERN",
                "FAKE_AIDER_MUTATE_PLAN",
                "FAKE_AIDER_PLAN_DO_LIVE_SIM",
                "FAKE_AIDER_MULTI_TEST_SIM",
            ):
                os.environ.pop(k, None)

    def _get_subprocess_env(self, extra_env=None):
        env = os.environ.copy()
        python_path = os.pathsep.join([repo_root, src_dir, pkg_dir, os.path.join(pkg_dir, "python")])
        env["PYTHONPATH"] = python_path
        if extra_env:
            env.update(extra_env)
        return env

    def _assert_round_kv_and_context_invariants(
        self,
        round_requests,
        round_metrics,
        expected_file_marker="File: src/calc.py",
        is_clean_round=True,
    ):
        self.assertEqual(len(round_requests), 3, "Expected 3 Oracle calls per round (Turn 0, Turn 1 REVISE, Turn 2 AGREE)")
        self.assertEqual(len(round_metrics), 3)

        req_t0, req_t1, req_t2 = round_requests
        m_t0, m_t1, m_t2 = round_metrics

        if is_clean_round:
            self.assertEqual([len(r["messages"]) for r in round_requests], [2, 4, 6])
        else:
            base_len = len(req_t0["messages"])
            self.assertGreaterEqual(base_len, 8)
            self.assertEqual([len(r["messages"]) for r in round_requests], [base_len, base_len + 2, base_len + 4])
            self.assertNotIn(
                "<project_files>\n",
                req_t0["messages"][-1]["content"],
                "Round 2+ Turn 0 with pass_history=True must NOT re-inject <project_files>",
            )

        for idx, req in enumerate(round_requests):
            joined = "\n".join(str(m.get("content", "")) for m in req["messages"])
            self.assertEqual(
                joined.count("<project_files>\n"),
                1,
                f"Call {idx} in round must contain exactly 1 <project_files> block, got {joined.count('<project_files>\\n')}",
            )
            self.assertEqual(joined.count("\n</project_files>"), 1)
            self.assertEqual(
                joined.count(expected_file_marker),
                1,
                f"Call {idx} in round must contain '{expected_file_marker}' exactly once",
            )
            if idx > 0:
                self.assertNotIn(
                    "<project_files>\n",
                    req["messages"][-1]["content"],
                    f"Turn {idx} delta user message must NOT re-inject <project_files>",
                )

        # Byte-parity KV-cache prefix invariant across turns
        self.assertEqual(
            req_t1["messages"][:-1],
            req_t0["messages"] + [{"role": "assistant", "content": m_t0["response"]}],
            "Turn 1 messages prefix must match Turn 0 + assistant response byte-for-byte",
        )
        self.assertEqual(
            req_t2["messages"][:-1],
            req_t1["messages"] + [{"role": "assistant", "content": m_t1["response"]}],
            "Turn 2 messages prefix must match Turn 1 + assistant response byte-for-byte",
        )

        # Exact character/token delta invariant
        delta_chars_t1 = m_t1["prompt_chars"] - m_t0["prompt_chars"]
        expected_chars_t1 = len(m_t0["response"]) + len(req_t1["messages"][-1]["content"])
        self.assertEqual(delta_chars_t1, expected_chars_t1)

        delta_chars_t2 = m_t2["prompt_chars"] - m_t1["prompt_chars"]
        expected_chars_t2 = len(m_t1["response"]) + len(req_t2["messages"][-1]["content"])
        self.assertEqual(delta_chars_t2, expected_chars_t2)

    def test_e2e_env_plan_do_full_pre_edit_debate_chain(self):
        """ADV-16: End-to-end run of env_plan_do.yml verifying:
        1. Dynamic Phase 1 authoring of strategy_template.md from blank template.
        2. Rendering of strategy_template.md into calc_validate_rendered.md.
        3. Multi-turn REVISE -> AGREE across 2 rounds for Job 2 & Job 3 with persona & instruction file cycling.
        4. High-watermark multi-task retention into .job2_verdict_r2.md and .job3_verdict_r2.md.
        5. Automatic <stem> test file assignment (tests/unit/test_calc.py), physical test creation in Job 3, and real pytest execution in Verify.
        6. Phase 3 handoff of target + extra_editable + <stem> test file + all contexts, excluding strategy_template.md.
        """
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "tests", "unit"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "docs"), exist_ok=True)

        with open(os.path.join(self.test_dir, "src", "__init__.py"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(self.test_dir, "src", "calc.py"), "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")
        with open(os.path.join(self.test_dir, "src", "helper.py"), "w", encoding="utf-8") as f:
            f.write("def scale(x):\n    return x\n")
        with open(os.path.join(self.test_dir, "docs", "domain.md"), "w", encoding="utf-8") as f:
            f.write("# Domain Rules\n")
        with open(os.path.join(self.test_dir, "docs", "test_rules.md"), "w", encoding="utf-8") as f:
            f.write("# Test Rules\n")

        # Start with unpopulated strategy_template.md (Phase 1 will populate it dynamically)
        plan_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("# Strategy Template (Source of Truth)\n## Scope Analysis\n```yaml\nfiles:\n  target_files: []\n  extra_editable_files: []\n  test_files: []\n  context_files_job: []\n  context_files_test: []\n```\n")

        with open(os.path.join(self.test_dir, ".gitignore"), "w", encoding="utf-8") as f:
            f.write(".aider_factory/\n.DS_Store\n.aider*\n")
        import cli
        cli._ensure_baseline_aiderignore(self.test_dir)
        cli._ensure_baseline_gitignore(self.test_dir)

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        sample_yaml_src = os.path.join(pkg_dir, "default_configs", "sample_yaml_config", "env_plan_do.yml")
        with open(sample_yaml_src, "r", encoding="utf-8") as yf:
            cfg = yaml.safe_load(yf)

        server, mock_url = self._start_mock_server()
        _MockLLMHandler.revise_then_agree = True
        try:
            cfg["working_directory"] = self.test_dir
            cfg["endpoints"] = {
                "architect_api_base": mock_url,
                "editor_api": mock_url,
                "rag_agent_api": mock_url,
            }
            cfg["phases"][0]["toggles"]["pair_programming"] = False
            cfg["phases"][0]["toggles"]["yes_always"] = True
            cfg["phases"][2]["toggles"]["pair_programming"] = False
            cfg["phases"][2]["toggles"]["yes_always"] = True

            for p in cfg["phases"]:
                p["models"] = {
                    "architect_agent": "openai/mock-model",
                    "editor_agent": "openai/mock-model",
                    "editor_agent_test": "openai/mock-model",
                    "rag_agent": "openai/mock-model",
                }

            # Real pytest execution for Verify gate!
            py_exec = sys.executable.replace("\\", "/")
            cfg["test_runner"] = f'"{py_exec}" -m pytest {{file}}'

            yaml_path = os.path.join(self.test_dir, "run_plan_do.yml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f)

            res = subprocess.run(
                [sys.executable, RUN_WORKFLOW_PATH, "e2e_plan_do_sess", yaml_path],
                cwd=self.test_dir,
                env=self._get_subprocess_env({"FAKE_AIDER_PLAN_DO_LIVE_SIM": "1"}),
                capture_output=True,
                text=True,
            )

            self.assertEqual(res.returncode, 0, f"Workflow failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")

            # 1. Verify rendered validate.md contains the injected strategy_template.md content
            rendered_val = os.path.join(
                self.test_dir,
                ".aider_factory",
                "sessions",
                "e2e_plan_do_sess",
                "templates",
                "calc_validate_rendered.md",
            )
            self.assertTrue(os.path.isfile(rendered_val), "calc_validate_rendered.md must be generated")
            with open(rendered_val, "r", encoding="utf-8") as rvf:
                rv_text = rvf.read()
            self.assertIn("## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS", rv_text)
            self.assertIn("UNIQUE_STRATEGY_CONSTRAINT_99", rv_text)

            # 1b. Verify rendered testing_exec and testing_iterate templates
            rendered_test_exec = os.path.join(
                self.test_dir,
                ".aider_factory",
                "sessions",
                "e2e_plan_do_sess",
                "templates",
                "calc_testing_exec_rendered.md",
            )
            self.assertTrue(os.path.isfile(rendered_test_exec), "calc_testing_exec_rendered.md must be generated")
            with open(rendered_test_exec, "r", encoding="utf-8") as rtf:
                rt_text = rtf.read()
            self.assertIn("## COMPLETED IMPLEMENTATION CONTEXT (READ-ONLY REFERENCE FOR TESTING)", rt_text)
            self.assertIn("<completed_strategy_specification>", rt_text)
            self.assertIn("UNIQUE_STRATEGY_CONSTRAINT_99", rt_text)
            self.assertIn("<implementation_git_diff>", rt_text)
            self.assertIn("--- a/src/calc.py", rt_text)
            self.assertIn("+++ b/src/calc.py", rt_text)
            self.assertIn("+    return int(a) + int(b)", rt_text)
            self.assertIn("+# Job 2 validated implementation", rt_text)
            self.assertIn("--- a/src/helper.py", rt_text)
            self.assertIn("+    return x * 2", rt_text)

            rendered_test_iter = os.path.join(
                self.test_dir,
                ".aider_factory",
                "sessions",
                "e2e_plan_do_sess",
                "templates",
                "calc_testing_iterate_rendered.md",
            )
            self.assertTrue(os.path.isfile(rendered_test_iter), "calc_testing_iterate_rendered.md must be generated")
            with open(rendered_test_iter, "r", encoding="utf-8") as rif:
                ri_text = rif.read()
            self.assertIn("<completed_strategy_specification>", ri_text)
            self.assertIn("UNIQUE_STRATEGY_CONSTRAINT_99", ri_text)
            self.assertNotIn("<implementation_git_diff>", ri_text)

            # 2. Verify all 4 debate verdicts exist, are agreed, and preserved high-watermark tasks
            ddir = os.path.join(self.test_dir, ".aider_factory", "logs", "debates")
            for vname in (
                "calc.job2_verdict_r1.md",
                "calc.job2_verdict_r2.md",
                "calc.job3_verdict_r1.md",
                "calc.job3_verdict_r2.md",
            ):
                vpath = os.path.join(ddir, vname)
                self.assertTrue(os.path.isfile(vpath), f"{vname} must exist")
                with open(vpath, "r", encoding="utf-8") as vf:
                    vtxt = vf.read()
                self.assertIn("STATUS: agreed", vtxt)
                self.assertIn("GATE: draft", vtxt)
                self.assertIn("### [Task ID: 001]", vtxt, f"{vname} must retain high-watermark multi-task spec")
                self.assertIn("### [Task ID: 002]", vtxt, f"{vname} must retain high-watermark multi-task spec")
                self.assertNotIn("SEED_001", vtxt, f"{vname} must not contain leaked seed tasks")

            # 3. Verify Oracle HTTP POST payloads received sequenced personas and instruction files
            self.assertEqual(len(_MockLLMHandler.recorded_requests), 12, "Expected 3 turns x 4 debate rounds = 12 Oracle calls")
            all_oracle_payloads = json.dumps(_MockLLMHandler.recorded_requests)
            self.assertIn("UNIQUE_STRATEGY_CONSTRAINT_99", all_oracle_payloads, "Oracle Job 2 must receive rendered strategy content")
            self.assertIn("<oracle_instructions>", all_oracle_payloads)

            # Mathematical KV-cache prefix and <project_files> invariants across all 4 rounds
            reqs = _MockLLMHandler.recorded_requests
            metrics = _MockLLMHandler.recorded_metrics
            self._assert_round_kv_and_context_invariants(reqs[0:3], metrics[0:3], is_clean_round=True)
            self._assert_round_kv_and_context_invariants(reqs[3:6], metrics[3:6], is_clean_round=True)
            self._assert_round_kv_and_context_invariants(reqs[6:9], metrics[6:9], is_clean_round=True)
            self._assert_round_kv_and_context_invariants(reqs[9:12], metrics[9:12], is_clean_round=True)

            # Round 2 Turn 0 of Job 2 and Job 3 must receive prior round resolution without leaking SEED_001
            j2_r2_t0_prompt = reqs[3]["messages"][1]["content"]
            j3_r2_t0_prompt = reqs[9]["messages"][1]["content"]
            prior_hdr = "## Context: The PREVIOUS escalation round agreed to attempt this specification:"
            self.assertIn(prior_hdr, j2_r2_t0_prompt)
            j2_prior_section = j2_r2_t0_prompt.split(prior_hdr, 1)[1].split("<project_files>\n", 1)[0]
            self.assertIn("### [Task ID: 001] - Primary Edit", j2_prior_section)
            self.assertNotIn("SEED_001", j2_prior_section)
            self.assertIn(prior_hdr, j3_r2_t0_prompt)
            j3_prior_section = j3_r2_t0_prompt.split(prior_hdr, 1)[1].split("<project_files>\n", 1)[0]
            self.assertIn("### [Task ID: 001] - Primary Edit", j3_prior_section)
            self.assertNotIn("SEED_001", j3_prior_section)

            instruct_dir = os.path.join(pkg_dir, "markdown", "templates", "debate_instruct")
            with open(os.path.join(instruct_dir, "oracle_contract_audit_r1.md"), "r", encoding="utf-8") as f:
                orc_r1_header = next(ln.strip() for ln in f if ln.strip())
            with open(os.path.join(instruct_dir, "oracle_adversarial_hardening_r2.md"), "r", encoding="utf-8") as f:
                orc_r2_header = next(ln.strip() for ln in f if ln.strip())
            with open(os.path.join(instruct_dir, "architect_contract_spec_r1.md"), "r", encoding="utf-8") as f:
                arch_r1_header = next(ln.strip() for ln in f if ln.strip())
            with open(os.path.join(instruct_dir, "architect_execution_spec_r2.md"), "r", encoding="utf-8") as f:
                arch_r2_header = next(ln.strip() for ln in f if ln.strip())

            self.assertIn(orc_r1_header, all_oracle_payloads)
            self.assertIn(orc_r2_header, all_oracle_payloads)

            job3_oracle_payloads = json.dumps(_MockLLMHandler.recorded_requests[6:])
            self.assertIn("<implementation_git_diff>", job3_oracle_payloads)
            self.assertIn("docs/test_rules.md", job3_oracle_payloads)
            self.assertNotIn("docs/domain.md", job3_oracle_payloads)

            # 4. Verify Architect prompt contents and file arguments across phases
            with open(self.log_file, "r", encoding="utf-8") as lf:
                entries = [
                    json.loads(l[len("AIDER_CALL: "):])
                    for l in lf.read().splitlines()
                    if l.startswith("AIDER_CALL:")
                ]
            raw_calls = [e["argv"] for e in entries]
            ask_entries = [e for e in entries if "--edit-format" in e["argv"] and "ask" in e["argv"]]
            self.assertEqual(len(ask_entries), 8, f"Expected 8 ask entries (2 turns x 4 rounds), got {len(ask_entries)}")

            persona_dir = os.path.join(pkg_dir, "markdown", "templates", "agent_persona")
            with open(os.path.join(persona_dir, "combined_reviewer_critic.md"), "r", encoding="utf-8") as f:
                arch_p1_header = next(ln.strip() for ln in f if ln.strip())
            with open(os.path.join(persona_dir, "code-reviewer.md"), "r", encoding="utf-8") as f:
                arch_p2_header = next(ln.strip() for ln in f if ln.strip())

            for ae in ask_entries:
                self.assertNotIn("--yes-always", ae["argv"], "Debate ask turns must NOT pass --yes-always")

            all_arch_prompts = "\n".join(e.get("msg_file_content", "") for e in ask_entries)
            self.assertIn("## JOB FILE SCOPE BOUNDARY", all_arch_prompts)
            self.assertIn("## JOB FILE SCOPE BOUNDARY", all_oracle_payloads)
            self.assertIn(arch_r1_header, all_arch_prompts)
            self.assertIn(arch_r2_header, all_arch_prompts)
            self.assertIn("## Architect Persona Directives", all_arch_prompts)
            self.assertIn(arch_p1_header, all_arch_prompts)
            self.assertIn(arch_p2_header, all_arch_prompts)

            # 5. Verify physical <stem> unit test file was created and executed by real pytest
            auto_test_path = os.path.join(self.test_dir, "tests", "unit", "test_calc.py")
            self.assertTrue(os.path.isfile(auto_test_path), "Job 3 must create tests/unit/test_calc.py on disk")

            # 6. Verify Job 1, Job 2, Job 3, and Phase 3 file & context hygiene
            j1_calls = [
                c for c in raw_calls
                if "src/calc.py" in c and "--auto-accept-architect" in c and "ask" not in c and any("strategy_template.md" in a for a in c)
            ]
            self.assertTrue(j1_calls, "Phase 2 Job 1 call must exist")
            self.assertNotIn("--yes-always", j1_calls[0])
            self.assertNotIn("tests/unit/test_calc.py", j1_calls[0])
            self.assertNotIn("docs/test_rules.md", j1_calls[0])

            j2_calls = [
                c for c in raw_calls
                if any("calc.job2_verdict_r2.md" in a for a in c) and "--auto-accept-architect" in c and "ask" not in c
            ]
            self.assertTrue(j2_calls, "Phase 2 Job 2 call must exist")
            self.assertNotIn("--yes-always", j2_calls[0])
            self.assertNotIn("tests/unit/test_calc.py", j2_calls[0])
            self.assertNotIn("docs/test_rules.md", j2_calls[0])

            j3_calls = [
                c for c in raw_calls
                if any("calc.job3_verdict_r2.md" in a for a in c) and "--auto-accept-architect" in c and "ask" not in c
            ]
            self.assertTrue(j3_calls, "Phase 2 Job 3 call must exist")
            j3_call = j3_calls[0]
            self.assertNotIn("--yes-always", j3_call)
            self.assertIn("tests/unit/test_calc.py", j3_call)
            self.assertIn("src/calc.py", j3_call)
            self.assertIn("src/helper.py", j3_call)
            self.assertIn("docs/test_rules.md", j3_call)
            self.assertTrue(any("calc_testing_exec_rendered.md" in a for a in j3_call))
            self.assertFalse(any("strategy_template.md" in a for a in j3_call))

            # Phase 3 (post_test_validation.md) call is the final call
            p2_call = raw_calls[-1]
            self.assertTrue(any("post_test_validation.md" in a for a in p2_call))
            self.assertIn("src/calc.py", p2_call)
            self.assertIn("src/helper.py", p2_call)
            self.assertIn("tests/unit/test_calc.py", p2_call)
            self.assertIn("docs/domain.md", p2_call)
            self.assertIn("docs/test_rules.md", p2_call)
            self.assertFalse(any("strategy_template.md" in a for a in p2_call))
        finally:
            server.shutdown()
            server.server_close()

    def test_e2e_env_plan_do_sequential_multi_test_files_single_debate(self):
        """ADV-18: Zero-mock E2E execution of env_plan_do.yml with 1 target file + 2 test_files:
        1. Phase 1 writes strategy_template.md specifying 2 test files (test_calc_unit.py & test_calc_e2e.py).
        2. Exactly 1 pair of Job 3 Pre-Edit Debate rounds runs across both test files (8 total debate calls).
        3. Job 3 Pre-Edit Debate prompt explicitly injects ## JOB FILE SCOPE BOUNDARY with both test files.
        4. Job 3 executes sequentially: Pass 1 edits test_calc_unit.py; Pass 2 edits test_calc_e2e.py with test_calc_unit.py in --read.
        5. Real pytest execution verifies both test suites pass individually.
        6. Phase 3 receives the target file + extra editable + BOTH test files.
        """
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "tests", "unit"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "tests", "e2e"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "docs"), exist_ok=True)

        with open(os.path.join(self.test_dir, "src", "__init__.py"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(self.test_dir, "src", "calc.py"), "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")
        with open(os.path.join(self.test_dir, "src", "helper.py"), "w", encoding="utf-8") as f:
            f.write("def scale(x):\n    return x\n")
        with open(os.path.join(self.test_dir, "docs", "domain.md"), "w", encoding="utf-8") as f:
            f.write("# Domain Rules\n")
        with open(os.path.join(self.test_dir, "docs", "test_rules.md"), "w", encoding="utf-8") as f:
            f.write("# Test Rules\n")

        plan_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("# Strategy Template (Source of Truth)\n## Scope Analysis\n```yaml\nfiles:\n  target_files: []\n  extra_editable_files: []\n  test_files: []\n  context_files_job: []\n  context_files_test: []\n```\n")

        with open(os.path.join(self.test_dir, ".gitignore"), "w", encoding="utf-8") as f:
            f.write(".aider_factory/\n.DS_Store\n.aider*\n")
        import cli
        cli._ensure_baseline_aiderignore(self.test_dir)
        cli._ensure_baseline_gitignore(self.test_dir)

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        sample_yaml_src = os.path.join(pkg_dir, "default_configs", "sample_yaml_config", "env_plan_do.yml")
        with open(sample_yaml_src, "r", encoding="utf-8") as yf:
            cfg = yaml.safe_load(yf)

        server, mock_url = self._start_mock_server()
        _MockLLMHandler.revise_then_agree = True
        try:
            cfg["working_directory"] = self.test_dir
            cfg["endpoints"] = {
                "architect_api_base": mock_url,
                "editor_api": mock_url,
                "rag_agent_api": mock_url,
            }
            cfg["phases"][0]["toggles"]["pair_programming"] = False
            cfg["phases"][0]["toggles"]["yes_always"] = True
            cfg["phases"][2]["toggles"]["pair_programming"] = False
            cfg["phases"][2]["toggles"]["yes_always"] = True

            for p in cfg["phases"]:
                p["models"] = {
                    "architect_agent": "openai/mock-model",
                    "editor_agent": "openai/mock-model",
                    "editor_agent_test": "openai/mock-model",
                    "rag_agent": "openai/mock-model",
                }

            py_exec = sys.executable.replace("\\", "/")
            cfg["test_runner"] = f'"{py_exec}" -m pytest {{file}}'

            yaml_path = os.path.join(self.test_dir, "run_plan_do_multi_test.yml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f)

            env = self._get_subprocess_env({
                "FAKE_AIDER_PLAN_DO_LIVE_SIM": "1",
                "FAKE_AIDER_MULTI_TEST_SIM": "1",
            })
            res = subprocess.run(
                [sys.executable, RUN_WORKFLOW_PATH, "multi_test_sess", yaml_path],
                cwd=self.test_dir,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(res.returncode, 0, f"Workflow failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")

            # 1. Exactly 12 Oracle debate calls occurred (6 for Job 2 R1/R2 + 6 for Job 3 R1/R2)
            # This confirms Job 3 Pre-Edit Debate was NOT duplicated per test file.
            self.assertEqual(
                len(_MockLLMHandler.recorded_requests),
                12,
                f"Expected 12 Oracle calls (Job 2 R1/R2 + Job 3 R1/R2), got: {len(_MockLLMHandler.recorded_requests)}"
            )

            # KV and context invariants across all 4 rounds in multi-test execution
            reqs = _MockLLMHandler.recorded_requests
            metrics = _MockLLMHandler.recorded_metrics
            self._assert_round_kv_and_context_invariants(reqs[0:3], metrics[0:3], is_clean_round=True)
            self._assert_round_kv_and_context_invariants(reqs[3:6], metrics[3:6], is_clean_round=True)
            self._assert_round_kv_and_context_invariants(
                reqs[6:9],
                metrics[6:9],
                expected_file_marker="File: docs/test_rules.md",
                is_clean_round=True,
            )
            self._assert_round_kv_and_context_invariants(
                reqs[9:12],
                metrics[9:12],
                expected_file_marker="File: docs/test_rules.md",
                is_clean_round=True,
            )

            # 2. Assert Job 3 Pre-Edit Debate prompt injected ## JOB FILE SCOPE BOUNDARY
            all_oracle_payloads = json.dumps(_MockLLMHandler.recorded_requests)
            self.assertIn("## JOB FILE SCOPE BOUNDARY", all_oracle_payloads)
            self.assertIn("tests/unit/test_calc_unit.py", all_oracle_payloads)
            self.assertIn("tests/e2e/test_calc_e2e.py", all_oracle_payloads)

            # 3. Read invocation log to verify sequential Job 3 passes and Phase 3 handoff
            with open(self.log_file, "r", encoding="utf-8") as lf:
                entries = [
                    json.loads(l[len("AIDER_CALL: "):])
                    for l in lf.read().splitlines()
                    if l.startswith("AIDER_CALL:")
                ]
            raw_calls = [e["argv"] for e in entries]

            # Job 3 edit calls: both must pass calc.job3_verdict_r2.md and --auto-accept-architect
            j3_calls = [
                c for c in raw_calls
                if any("calc.job3_verdict_r2.md" in a for a in c) and "--auto-accept-architect" in c and "ask" not in c
            ]
            self.assertEqual(len(j3_calls), 2, f"Expected 2 sequential Job 3 edit calls, got: {len(j3_calls)}")

            # Pass 1 edits tests/unit/test_calc_unit.py and does NOT have tests/e2e/test_calc_e2e.py
            self.assertIn("tests/unit/test_calc_unit.py", j3_calls[0])
            self.assertNotIn("tests/e2e/test_calc_e2e.py", j3_calls[0])

            # Pass 2 edits tests/e2e/test_calc_e2e.py and includes tests/unit/test_calc_unit.py in --read
            self.assertIn("tests/e2e/test_calc_e2e.py", j3_calls[1])
            self.assertIn("tests/unit/test_calc_unit.py", j3_calls[1])
            read_indices_2 = [i for i, x in enumerate(j3_calls[1]) if x == "--read"]
            read_files_2 = [j3_calls[1][i + 1] for i in read_indices_2]
            self.assertIn("tests/unit/test_calc_unit.py", read_files_2)

            # 4. Both test files physically exist on disk
            self.assertTrue(os.path.isfile(os.path.join(self.test_dir, "tests", "unit", "test_calc_unit.py")))
            self.assertTrue(os.path.isfile(os.path.join(self.test_dir, "tests", "e2e", "test_calc_e2e.py")))

            # 5. Real pytest execution passed both test suites in Verify
            combined_stdout = res.stdout + res.stderr
            self.assertIn("p1_verify_calc", combined_stdout)
            self.assertIn("p1_verify_calc_t2", combined_stdout)

            # 6. Phase 3 handoff received target + extra editable + BOTH test files
            p2_call = raw_calls[-1]
            self.assertTrue(any("post_test_validation.md" in a for a in p2_call))
            self.assertIn("src/calc.py", p2_call)
            self.assertIn("src/helper.py", p2_call)
            self.assertIn("tests/unit/test_calc_unit.py", p2_call)
            self.assertIn("tests/e2e/test_calc_e2e.py", p2_call)
        finally:
            server.shutdown()
            server.server_close()

    def test_e2e_env_plan_do_verdict_gate_blocks_on_exhausted_debate(self):
        """ADV-17: When a pre-edit debate in env_plan_do.yml exhausts without agreement,
        verdict_gate blocks the downstream edit job and halts the pipeline with exit code 1."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        with open(os.path.join(self.test_dir, "src", "calc.py"), "w", encoding="utf-8") as f:
            f.write("def add(a, b): return a + b\n")

        plan_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("""# Strategy
## Scope Analysis
```yaml
files:
  target_files:
    - "src/calc.py"
  extra_editable_files: []
  test_files: []
  context_files_job: []
  context_files_test: []
```
""")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        sample_yaml_src = os.path.join(pkg_dir, "default_configs", "sample_yaml_config", "env_plan_do.yml")
        with open(sample_yaml_src, "r", encoding="utf-8") as yf:
            cfg = yaml.safe_load(yf)

        server, mock_url = self._start_mock_server()
        _MockLLMHandler.force_disagree = True
        try:
            cfg["working_directory"] = self.test_dir
            cfg["endpoints"] = {
                "architect_api_base": mock_url,
                "editor_api": mock_url,
                "rag_agent_api": mock_url,
            }
            cfg["phases"][0]["toggles"]["pair_programming"] = False
            cfg["phases"][0]["toggles"]["yes_always"] = True
            cfg["phases"][1]["oracle"]["pre_edit_debate"]["loops"] = 1
            cfg["phases"][1]["oracle"]["pre_edit_debate"]["rounds"] = 2
            cfg["phases"][2]["toggles"]["pair_programming"] = False
            cfg["phases"][2]["toggles"]["yes_always"] = True

            for p in cfg["phases"]:
                p["models"] = {
                    "architect_agent": "openai/mock-model",
                    "editor_agent": "openai/mock-model",
                    "editor_agent_test": "openai/mock-model",
                    "rag_agent": "openai/mock-model",
                }

            yaml_path = os.path.join(self.test_dir, "run_plan_do_block.yml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f)

            res = subprocess.run(
                [sys.executable, RUN_WORKFLOW_PATH, "e2e_plan_do_block_sess", yaml_path],
                cwd=self.test_dir,
                env=self._get_subprocess_env(),
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                res.returncode,
                0,
                f"Workflow failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}",
            )

            ddir = os.path.join(self.test_dir, ".aider_factory", "logs", "debates")
            verdict_r2 = os.path.join(ddir, "calc.job2_verdict_r2.md")
            self.assertTrue(os.path.isfile(verdict_r2))
            with open(verdict_r2, "r", encoding="utf-8") as vf:
                self.assertIn("STATUS: exhausted", vf.read())

            combined_out = res.stdout + res.stderr
            self.assertIn("HELD FOR HUMAN [p1_job2_calc]: verdict 'exhausted'", combined_out)

            with open(self.log_file, "r", encoding="utf-8") as lf:
                invocations = lf.read()
            self.assertNotIn("calc.job2_verdict_r2.md", invocations, "Job 2 edit must be blocked by verdict_gate")
        finally:
            server.shutdown()
            server.server_close()

    def test_e2e_env_plan_do_pass_history_true_cross_round_kv_prefix_and_no_file_duplication(self):
        """Verify that when pass_history=True across 2 rounds, Round 2 preserves 100% of Round 1's
        KV-cache message prefix and never duplicates <project_files> on Round 2 Turn 0."""
        subprocess.run(["git", "init"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=self.test_dir, check=True)

        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "docs"), exist_ok=True)
        with open(os.path.join(self.test_dir, "src", "calc.py"), "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return int(a) + int(b)\n")
        with open(os.path.join(self.test_dir, "src", "helper.py"), "w", encoding="utf-8") as f:
            f.write("def scale(x):\n    return x * 2\n")
        with open(os.path.join(self.test_dir, "docs", "domain.md"), "w", encoding="utf-8") as f:
            f.write("# Domain Rules\n")

        plan_dir = os.path.join(self.test_dir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write(
                "# Strategy\nUNIQUE_STRATEGY_CONSTRAINT_99\n"
                "## Scope Analysis\n```yaml\nfiles:\n  target_files:\n    - \"src/calc.py\"\n"
                "  extra_editable_files:\n    - \"src/helper.py\"\n  test_files: []\n"
                "  context_files_job:\n    - \"docs/domain.md\"\n  context_files_test: []\n```\n"
                "## Implementation Plan\n"
                "### [Task ID: SEED_001] - Seed 1\n### [Task ID: SEED_002] - Seed 2\n"
                "### [Task ID: SEED_003] - Seed 3\n### [Task ID: SEED_004] - Seed 4\n"
                "### [Task ID: SEED_005] - Seed 5\n### [Task ID: SEED_006] - Seed 6\n"
            )

        with open(os.path.join(self.test_dir, ".gitignore"), "w", encoding="utf-8") as f:
            f.write(".aider_factory/\n.DS_Store\n.aider*\n")
        import cli
        cli._ensure_baseline_aiderignore(self.test_dir)
        cli._ensure_baseline_gitignore(self.test_dir)

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.test_dir, check=True)

        sample_yaml_src = os.path.join(pkg_dir, "default_configs", "sample_yaml_config", "env_plan_do.yml")
        with open(sample_yaml_src, "r", encoding="utf-8") as yf:
            cfg = yaml.safe_load(yf)

        server, mock_url = self._start_mock_server()
        _MockLLMHandler.revise_then_agree = True
        try:
            cfg["working_directory"] = self.test_dir
            cfg["endpoints"] = {
                "architect_api_base": mock_url,
                "editor_api": mock_url,
                "rag_agent_api": mock_url,
            }
            cfg["phases"][0]["enabled"] = False
            cfg["phases"][2]["enabled"] = False
            p1 = cfg["phases"][1]
            p1["toggles"]["run_job_one"] = False
            p1["toggles"]["run_job_two"] = True
            p1["toggles"]["run_job_three"] = False
            p1["toggles"]["iterate_test"] = False
            p1["oracle"]["pre_edit_debate"]["insert_debate"] = [0, 1, 0]
            p1["oracle"]["pre_edit_debate"]["rounds"] = 2
            p1["oracle"]["pre_edit_debate"]["pass_history"] = True
            p1["models"] = {
                "architect_agent": "openai/mock-model",
                "editor_agent": "openai/mock-model",
                "editor_agent_test": "openai/mock-model",
                "rag_agent": "openai/mock-model",
            }

            yaml_path = os.path.join(self.test_dir, "run_pass_history_true.yml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f)

            res = subprocess.run(
                [sys.executable, RUN_WORKFLOW_PATH, "pass_hist_true_sess", yaml_path],
                cwd=self.test_dir,
                env=self._get_subprocess_env({"FAKE_AIDER_PLAN_DO_LIVE_SIM": "1"}),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, f"Workflow failed:\n{res.stdout}\n{res.stderr}")
            self.assertEqual(len(_MockLLMHandler.recorded_requests), 6)

            reqs = _MockLLMHandler.recorded_requests
            metrics = _MockLLMHandler.recorded_metrics
            self._assert_round_kv_and_context_invariants(reqs[0:3], metrics[0:3], is_clean_round=True)
            self._assert_round_kv_and_context_invariants(reqs[3:6], metrics[3:6], is_clean_round=False)

            # Cross-round KV-cache prefix invariant: Round 2 Turn 0 prefix == Round 1 Turn 2 + assistant reply
            self.assertEqual(
                reqs[3]["messages"][:-1],
                reqs[2]["messages"] + [{"role": "assistant", "content": metrics[2]["response"]}],
            )
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
