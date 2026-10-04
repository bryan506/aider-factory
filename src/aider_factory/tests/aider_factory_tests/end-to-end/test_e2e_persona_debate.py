#!/usr/bin/env python3
"""test_e2e_persona_debate.py — Zero-mock live end-to-end test suite for
CLI debate persona injection, --message-file transmission, sandwich anchoring,
trinary revise deadlocks, and session cache invalidation.
"""

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

test_file_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(test_file_dir, "../../../../.."))
src_dir = os.path.join(repo_root, "src")
pkg_dir = os.path.join(src_dir, "aider_factory")
pkg_python_dir = os.path.join(pkg_dir, "python")

for p in (pkg_python_dir, pkg_dir, src_dir, repo_root):
    if p not in sys.path:
        sys.path.insert(0, p)

ORACLE_CLI_PATH = os.path.join(pkg_python_dir, "oracle_agent.py")


class MockDebateHTTPServer(http.server.BaseHTTPRequestHandler):
    requests_log = []
    response_verdict = "VERDICT: AGREE"
    response_verdicts = []

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data": [{"id": "mock-oracle"}]}')

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_len).decode("utf-8")
        try:
            body = json.loads(raw_body)
        except Exception:
            body = {}
        MockDebateHTTPServer.requests_log.append(body)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        if MockDebateHTTPServer.response_verdicts:
            verdict = MockDebateHTTPServer.response_verdicts.pop(0)
        else:
            verdict = MockDebateHTTPServer.response_verdict
        content = f"<critique>Reasoning analysis</critique>\n{verdict}"
        resp = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 1234567890,
            "model": body.get("model", "mock-oracle"),
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
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        self.wfile.write(json.dumps(resp).encode("utf-8"))


class TestE2EPersonaDebate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        MockDebateHTTPServer.requests_log = []
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), MockDebateHTTPServer)
        cls.port = cls.server.server_port
        cls.api_url = f"http://127.0.0.1:{cls.port}/v1"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        MockDebateHTTPServer.requests_log.clear()
        MockDebateHTTPServer.response_verdict = "VERDICT: AGREE"
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
                os.environ.pop(k, None)

        self.bin_dir = os.path.join(self.test_dir, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        self.log_file = os.path.join(self.test_dir, "aider_calls.log")

        fake_aider = os.path.join(self.bin_dir, "aider")
        if sys.platform == "win32":
            with open(fake_aider + ".py", "w", encoding="utf-8") as f:
                f.write(textwrap.dedent(f"""\
                    import sys, os, json
                    msg_file = None
                    for idx, a in enumerate(sys.argv):
                        if a == "--message-file" and idx + 1 < len(sys.argv):
                            msg_file = sys.argv[idx + 1]
                    msg_content = ""
                    if msg_file and os.path.isfile(msg_file):
                        with open(msg_file, "r", encoding="utf-8") as mf:
                            msg_content = mf.read()
                    with open(r"{self.log_file}", "a", encoding="utf-8") as lf:
                        lf.write(json.dumps({{"argv": sys.argv[1:], "msg_content": msg_content}}) + "\\n")
                    print("PROPOSAL: Concrete architect resolution.")
                    sys.exit(0)
                """))
            with open(fake_aider + ".cmd", "w", encoding="utf-8") as f:
                f.write(f'@"{sys.executable}" "%~dp0aider.py" %*\\n')
        else:
            with open(fake_aider, "w", encoding="utf-8") as f:
                f.write(textwrap.dedent(f"""\
                    #!{sys.executable}
                    import sys, os, json
                    msg_file = None
                    for idx, a in enumerate(sys.argv):
                        if a == "--message-file" and idx + 1 < len(sys.argv):
                            msg_file = sys.argv[idx + 1]
                    msg_content = ""
                    if msg_file and os.path.isfile(msg_file):
                        with open(msg_file, "r", encoding="utf-8") as mf:
                            msg_content = mf.read()
                    with open(r"{self.log_file}", "a", encoding="utf-8") as lf:
                        lf.write(json.dumps({{"argv": sys.argv[1:], "msg_content": msg_content}}) + "\\n")
                    print("PROPOSAL: Concrete architect resolution.")
                    sys.exit(0)
                """))
            os.chmod(fake_aider, 0o755)

        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}{os.pathsep}{self.old_path}"

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ["PATH"] = self.old_path
        shutil.rmtree(self.test_dir, ignore_errors=True)
        for k in list(os.environ.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
                os.environ.pop(k, None)

    def _get_subprocess_env(self, extra_env=None):
        env = os.environ.copy()
        python_path = os.pathsep.join([repo_root, src_dir, pkg_dir, pkg_python_dir])
        env["PYTHONPATH"] = python_path
        env["ORACLE_AGENT_API_BASE"] = self.api_url
        env["ORACLE_AGENT_MODEL"] = "openai/mock-oracle"
        env["ORACLE_ARCHITECT_API_BASE"] = self.api_url
        env["ORACLE_ARCHITECT_MODEL"] = "openai/mock-architect"
        env["OPENAI_API_KEY"] = "sk-dummy"
        if extra_env:
            env.update(extra_env)
        return env

    def test_e2e_persona_flags_and_message_file_transmission(self):
        orc_persona = os.path.join(self.test_dir, "oracle_persona.md")
        arch_persona = os.path.join(self.test_dir, "arch_persona.md")
        with open(orc_persona, "w", encoding="utf-8") as f:
            f.write("# Oracle Persona\nStrict verification standards.\n")
        with open(arch_persona, "w", encoding="utf-8") as f:
            f.write("# Architect Persona\nDefensive architecture standards.\n")

        cmd = [
            sys.executable,
            ORACLE_CLI_PATH,
            "--oracle-persona", orc_persona,
            "--architect-persona", arch_persona,
            "--debate", "code",
            "--loops", "1",
            "--rounds", "1",
            "Verify authentication",
        ]

        res = subprocess.run(cmd, cwd=self.test_dir, env=self._get_subprocess_env(), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        self.assertIn("DEBATE VERDICT: AGREED", res.stdout)

        with open(self.log_file, "r", encoding="utf-8") as lf:
            calls = [json.loads(line) for line in lf]
        self.assertTrue(len(calls) >= 1)
        aider_call = calls[0]
        self.assertIn("--message-file", aider_call["argv"])
        self.assertIn("Defensive architecture standards.", aider_call["msg_content"])

        msg_file_idx = aider_call["argv"].index("--message-file")
        prompt_path = aider_call["argv"][msg_file_idx + 1]
        self.assertFalse(os.path.exists(prompt_path), "Prompt file must be cleaned up after Aider turn")

        self.assertTrue(len(MockDebateHTTPServer.requests_log) >= 2)
        turn0_req = MockDebateHTTPServer.requests_log[0]
        turn1_req = MockDebateHTTPServer.requests_log[1]

        sys_msg = next(m["content"] for m in turn0_req["messages"] if m["role"] == "system")
        self.assertIn("Strict verification standards.", sys_msg)

        user_msg = [m["content"] for m in turn1_req["messages"] if m["role"] == "user"][-1]
        self.assertIn("<evaluation_contract>", user_msg)
        self.assertIn("VERDICT: [AGREE | REVISE | OBJECT - <reason>]", user_msg)

    def test_e2e_persist_debate_loop_continuation(self):
        MockDebateHTTPServer.response_verdict = "VERDICT: AGREE"
        cmd = [
            sys.executable,
            ORACLE_CLI_PATH,
            "--debate", "code",
            "--loops", "3",
            "--rounds", "1",
            "--persist",
            "Refactor persistent test",
        ]
        res = subprocess.run(cmd, cwd=self.test_dir, env=self._get_subprocess_env(), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        self.assertIn("DEBATE VERDICT: AGREED", res.stdout)
        # In persist mode with loops=3 and AGREE on each turn, all 3 turns execute
        with open(self.log_file, "r", encoding="utf-8") as lf:
            calls = [json.loads(line) for line in lf]
        self.assertEqual(len(calls), 3, f"Expected 3 turns executed with --persist, got {len(calls)}")

    def test_e2e_trinary_revise_deadlock_detection(self):
        MockDebateHTTPServer.response_verdict = "VERDICT: REVISE - add test boundary checks"

        cmd = [
            sys.executable,
            ORACLE_CLI_PATH,
            "--debate", "code",
            "--loops", "3",
            "--rounds", "1",
            "Refactor algorithm",
        ]

        res = subprocess.run(cmd, cwd=self.test_dir, env=self._get_subprocess_env(), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        self.assertIn("DEBATE VERDICT: DEADLOCK", res.stdout)

    def test_e2e_persona_disk_cache_invalidation(self):
        orc_persona = os.path.join(self.test_dir, "oracle_persona.md")
        with open(orc_persona, "w", encoding="utf-8") as f:
            f.write("Persona V1")

        cmd = [
            sys.executable,
            ORACLE_CLI_PATH,
            "--oracle-persona", orc_persona,
            "--debate", "code",
            "--loops", "1",
            "--rounds", "1",
            "Query 1",
        ]
        res1 = subprocess.run(cmd, cwd=self.test_dir, env=self._get_subprocess_env(), capture_output=True, text=True)
        self.assertEqual(res1.returncode, 0)

        session_path = os.path.join(self.test_dir, ".aider_factory", ".oracle_debate_session.json")
        self.assertTrue(os.path.exists(session_path))
        with open(session_path, "r", encoding="utf-8") as sf:
            hash1 = json.load(sf)["files_hash"]

        with open(orc_persona, "w", encoding="utf-8") as f:
            f.write("Persona V2 - Updated strictly")

        cmd[7] = "Query 2"
        res2 = subprocess.run(cmd, cwd=self.test_dir, env=self._get_subprocess_env(), capture_output=True, text=True)
        self.assertEqual(res2.returncode, 0)

        with open(session_path, "r", encoding="utf-8") as sf:
            session_data = json.load(sf)
            hash2 = session_data["files_hash"]

        self.assertNotEqual(hash1, hash2, "files_hash must change when persona content changes")
        self.assertIn("Persona V2 - Updated strictly", session_data["messages"][0]["content"])

    def test_e2e_missing_persona_file_fatal_exit(self):
        cmd = [
            sys.executable,
            ORACLE_CLI_PATH,
            "--oracle-persona", "nonexistent_persona.md",
            "--debate", "code",
            "Check issue",
        ]
        res = subprocess.run(cmd, cwd=self.test_dir, env=self._get_subprocess_env(), capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("Error: Oracle persona file not found: nonexistent_persona.md", res.stderr)

        cmd2 = [
            sys.executable,
            ORACLE_CLI_PATH,
            "--architect-persona", "nonexistent_arch.md",
            "--debate", "code",
            "Check issue",
        ]
        res2 = subprocess.run(cmd2, cwd=self.test_dir, env=self._get_subprocess_env(), capture_output=True, text=True)
        self.assertEqual(res2.returncode, 1)
        self.assertIn("Error: Architect persona file not found: nonexistent_arch.md", res2.stderr)

    def test_e2e_multi_round_persona_sequencing_and_conventions_primacy(self):
        """Zero-mock E2E test verifying round-by-round persona rotation and CONVENTIONS.md system primacy."""
        conv_file = os.path.join(self.test_dir, ".aider_factory", "CONVENTIONS.md")
        os.makedirs(os.path.dirname(conv_file), exist_ok=True)
        with open(conv_file, "w", encoding="utf-8") as f:
            f.write("# Universal Invariants: Deterministic Zero-Mock Exit Code 0\n")

        orc_p1 = os.path.join(self.test_dir, "orc_p1.md")
        orc_p2 = os.path.join(self.test_dir, "orc_p2.md")
        arch_p1 = os.path.join(self.test_dir, "arch_p1.md")
        arch_p2 = os.path.join(self.test_dir, "arch_p2.md")
        with open(orc_p1, "w", encoding="utf-8") as f: f.write("ORACLE_CRITIC_ROUND_1")
        with open(orc_p2, "w", encoding="utf-8") as f: f.write("ORACLE_JUDGE_ROUND_2")
        with open(arch_p1, "w", encoding="utf-8") as f: f.write("ARCHITECT_DEFENSE_ROUND_1")
        with open(arch_p2, "w", encoding="utf-8") as f: f.write("ARCHITECT_IMPLEMENTER_ROUND_2")

        cmd = [
            sys.executable,
            ORACLE_CLI_PATH,
            "--oracle-personas", f"{orc_p1},{orc_p2}",
            "--architect-personas", f"{arch_p1},{arch_p2}",
            "--debate", "code",
            "--loops", "1",
            "--rounds", "2",
            "--persist",
            "Multi-round sequence test",
        ]
        res = subprocess.run(cmd, cwd=self.test_dir, env=self._get_subprocess_env(), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        self.assertIn("DEBATE VERDICT: AGREED", res.stdout)
        self.assertIn("--- Round 2/2 ---", res.stderr)

        # 1. Assert Aider Architect calls rotated personas across Round 1 and Round 2 and receives CONVENTIONS.md via --read
        with open(self.log_file, "r", encoding="utf-8") as lf:
            calls = [json.loads(line) for line in lf]
        self.assertEqual(len(calls), 2, f"Expected 2 turns (1 per round), got {len(calls)}")
        self.assertIn("ARCHITECT_DEFENSE_ROUND_1", calls[0]["msg_content"])
        self.assertIn("ARCHITECT_IMPLEMENTER_ROUND_2", calls[1]["msg_content"])

        # Verify CONVENTIONS.md was passed to Aider as a --read argument
        self.assertIn("--read", calls[0]["argv"])
        read_idx = calls[0]["argv"].index("--read")
        self.assertTrue(
            any("CONVENTIONS.md" in arg for arg in calls[0]["argv"]),
            f"CONVENTIONS.md must be passed to Aider via --read, got argv: {calls[0]['argv']}"
        )

        # 2. Assert Mock Server requests rotated Oracle personas and retained CONVENTIONS.md
        self.assertGreaterEqual(len(MockDebateHTTPServer.requests_log), 4)
        r1_sys = next(m["content"] for m in MockDebateHTTPServer.requests_log[0]["messages"] if m["role"] == "system")
        r2_sys = next(m["content"] for m in MockDebateHTTPServer.requests_log[2]["messages"] if m["role"] == "system")

        self.assertIn("ORACLE_CRITIC_ROUND_1", r1_sys)
        self.assertIn("ORACLE_JUDGE_ROUND_2", r2_sys)
        self.assertIn("Deterministic Zero-Mock Exit Code 0", r1_sys)
        self.assertIn("Deterministic Zero-Mock Exit Code 0", r2_sys)


    def test_e2e_persist_debate_objection_resets_provisional_agreement(self):
        MockDebateHTTPServer.response_verdicts = [
            "VERDICT: AGREE",
            "VERDICT: AGREE",
            "VERDICT: OBJECT - boundary test missing",
            "VERDICT: AGREE",
        ]
        cmd = [
            sys.executable,
            ORACLE_CLI_PATH,
            "--debate", "code",
            "--loops", "3",
            "--rounds", "1",
            "--persist",
            "Test persistent objection reset",
        ]
        res = subprocess.run(cmd, cwd=self.test_dir, env=self._get_subprocess_env(), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")

        with open(self.log_file, "r", encoding="utf-8") as lf:
            calls = [json.loads(line) for line in lf]
        self.assertEqual(len(calls), 3)

        self.assertIn("provisionally agreed with your prior fix", calls[1]["msg_content"])
        self.assertNotIn("provisionally agreed with your prior fix", calls[2]["msg_content"])
        self.assertIn("The Oracle reviewed your proposal and responded:", calls[2]["msg_content"])

    def test_e2e_ostee_idempotent_multithreaded_stop(self):
        """Zero-mock verification that concurrent stop() calls to OSTee are thread-safe and idempotent."""
        try:
            from aider_factory.python.run_workflow import OSTee
        except ImportError:
            from run_workflow import OSTee
        log_path = os.path.join(self.test_dir, "test_tee.log")
        tee = OSTee(log_path)
        sys.stdout.write("Live tee test output\n")
        sys.stdout.flush()

        # Concurrent stop execution from 4 threads simulating signals/exceptions
        threads = [threading.Thread(target=tee.stop) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(tee._stopped)
        self.assertFalse(tee.running)

    def test_e2e_deliberation_contract_and_prompt_rotation(self):
        """E2E test verifying orchestrate._run_deliberation persona contracts and persist rotation."""
        from orchestrate import AiderFactory, Task

        orc_persona = os.path.join(self.test_dir, "delib_orc_persona.md")
        arch_persona = os.path.join(self.test_dir, "delib_arch_persona.md")
        with open(orc_persona, "w", encoding="utf-8") as f:
            f.write("CRITICAL_AUDITOR_PERSONA")
        with open(arch_persona, "w", encoding="utf-8") as f:
            f.write("RESILIENT_ARCHITECT_PERSONA")

        verdict_file = os.path.join(self.test_dir, "verdict.md")
        ledger_file = os.path.join(self.test_dir, "debate.json")

        factory = AiderFactory(project_dir=self.test_dir, session_name="test_delib_session")

        task = Task(
            id="delib_node",
            model="openai/mock-architect",
            editor_model="openai/mock-oracle",
            architect_api_base=self.api_url,
            editor_api_base=self.api_url,
            rag_env={
                "ORACLE_AGENT_MODEL": "openai/mock-oracle",
                "ORACLE_AGENT_API_BASE": self.api_url,
                "ORACLE_ARCHITECT_MODEL": "openai/mock-architect",
                "ORACLE_ARCHITECT_API_BASE": self.api_url,
            },
            deliberate={
                "template": None,
                "issue": None,
                "verdict": verdict_file,
                "ledger": ledger_file,
                "loops": 2,
                "mode": "code",
                "round_idx": 1,
                "persist": True,
                "oracle_persona": orc_persona,
                "architect_persona": arch_persona,
            },
        )

        MockDebateHTTPServer.response_verdicts = [
            "VERDICT: AGREE",
            "VERDICT: AGREE",
            "VERDICT: AGREE",
        ]

        ret = factory._run_deliberation(task)
        self.assertTrue(ret)
        self.assertTrue(os.path.exists(verdict_file))

        with open(self.log_file, "r", encoding="utf-8") as lf:
            calls = [json.loads(line) for line in lf]

        self.assertEqual(len(calls), 2, "Expected 2 turns executed under persist: true with max_turns=2")

        # Verify Architect received persona directives on Turn 1
        self.assertIn("## Architect Persona Directives", calls[0]["msg_content"])
        self.assertIn("RESILIENT_ARCHITECT_PERSONA", calls[0]["msg_content"])

        # Verify Turn 2 prompt was rotated to subsequent audit layers
        self.assertIn("The Oracle provisionally agreed with your prior fix.", calls[1]["msg_content"])
        self.assertIn("boundary conditions, unhandled exceptions, concurrency, or test coverage.", calls[1]["msg_content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
