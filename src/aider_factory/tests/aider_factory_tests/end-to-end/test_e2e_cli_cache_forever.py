import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


class TestE2ECLICacheAndForever(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.temp_root, "cache")
        self.config_dir = os.path.join(self.temp_root, "config")
        self.ws_dir = os.path.join(self.temp_root, "workspace_alpha")
        self.af_dir = os.path.join(self.ws_dir, ".aider_factory")

        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.af_dir, exist_ok=True)

        self.env = os.environ.copy()
        self.env["XDG_CACHE_HOME"] = self.cache_dir
        self.env["XDG_CONFIG_HOME"] = self.config_dir
        self.env["HOME"] = self.temp_root

        # Ensure package src is in PYTHONPATH
        pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
        self.env["PYTHONPATH"] = f"{pkg_root}{os.pathsep}{self.env.get('PYTHONPATH', '')}"

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _run_cli(self, args: list[str], cwd: str = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "aider_factory.cli"] + args,
            cwd=cwd or self.ws_dir,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_e2e_clear_session_default_vs_forever(self):
        # 1. Setup session 1
        s1 = os.path.join(self.af_dir, "sessions", "sess_01")
        os.makedirs(s1, exist_ok=True)
        with open(os.path.join(s1, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: sess_01\n")

        # Clear session default (expect backup)
        res = self._run_cli(["--clear-session", "sess_01"])
        self.assertEqual(res.returncode, 0, msg=f"CLI stderr: {res.stderr}")
        self.assertFalse(os.path.exists(s1))

        cached_s1 = os.path.join(
            self.cache_dir, "aider_factory_cache", "workspace_alpha", ".aider_factory", "sessions", "sess_01", "session.yml"
        )
        self.assertTrue(os.path.exists(cached_s1))
        with open(cached_s1, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "name: sess_01\n")

        # 2. Setup session 2 and clear with --forever (expect no cache)
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        os.makedirs(self.cache_dir, exist_ok=True)

        s2 = os.path.join(self.af_dir, "sessions", "sess_02")
        os.makedirs(s2, exist_ok=True)
        with open(os.path.join(s2, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: sess_02\n")

        res = self._run_cli(["--clear-session", "sess_02", "--forever"])
        self.assertEqual(res.returncode, 0, msg=f"CLI stderr: {res.stderr}")
        self.assertFalse(os.path.exists(s2))
        self.assertFalse(os.path.exists(os.path.join(self.cache_dir, "aider_factory_cache")))

    def test_e2e_clear_all_sessions_default_vs_forever(self):
        # 1. Create multiple sessions
        s1 = os.path.join(self.af_dir, "sessions", "batch_1")
        s2 = os.path.join(self.af_dir, "sessions", "batch_2")
        os.makedirs(s1, exist_ok=True)
        os.makedirs(s2, exist_ok=True)
        with open(os.path.join(s1, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: batch_1\n")
        with open(os.path.join(s2, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: batch_2\n")

        res = self._run_cli(["--clear-all"])
        self.assertEqual(res.returncode, 0, msg=f"CLI stderr: {res.stderr}")
        self.assertFalse(os.path.exists(s1))
        self.assertFalse(os.path.exists(s2))

        c_root = os.path.join(self.cache_dir, "aider_factory_cache", "workspace_alpha", ".aider_factory", "sessions")
        self.assertTrue(os.path.exists(os.path.join(c_root, "batch_1", "session.yml")))
        self.assertTrue(os.path.exists(os.path.join(c_root, "batch_2", "session.yml")))

        # 2. Create new session and purge with --forever
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        s3 = os.path.join(self.af_dir, "sessions", "batch_3")
        os.makedirs(s3, exist_ok=True)
        with open(os.path.join(s3, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: batch_3\n")

        res = self._run_cli(["--clear-all", "--forever"])
        self.assertEqual(res.returncode, 0, msg=f"CLI stderr: {res.stderr}")
        self.assertFalse(os.path.exists(s3))
        self.assertFalse(os.path.exists(os.path.join(self.cache_dir, "aider_factory_cache")))

    def test_e2e_clear_side_sessions_default_vs_forever(self):
        helper_file = os.path.join(self.af_dir, ".helper_session.json")
        oracle_file = os.path.join(self.af_dir, ".oracle_session.json")
        with open(helper_file, "w", encoding="utf-8") as f:
            f.write("[{\"role\": \"user\", \"content\": \"e2e test\"}]")
        with open(oracle_file, "w", encoding="utf-8") as f:
            f.write("{\"messages\": []}")

        # Clear all side sessions default
        res = self._run_cli(["--clear-side-sessions"])
        self.assertEqual(res.returncode, 0, msg=f"CLI stderr: {res.stderr}")
        self.assertFalse(os.path.exists(helper_file))
        self.assertFalse(os.path.exists(oracle_file))

        c_af = os.path.join(self.cache_dir, "aider_factory_cache", "workspace_alpha", ".aider_factory")
        self.assertTrue(os.path.exists(os.path.join(c_af, ".helper_session.json")))
        self.assertTrue(os.path.exists(os.path.join(c_af, ".oracle_session.json")))

        # Clear side session with --forever
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(helper_file, "w", encoding="utf-8") as f:
            f.write("[]")

        res = self._run_cli(["--clear-side-session", "helper", "--forever"])
        self.assertEqual(res.returncode, 0, msg=f"CLI stderr: {res.stderr}")
        self.assertFalse(os.path.exists(helper_file))
        self.assertFalse(os.path.exists(os.path.join(self.cache_dir, "aider_factory_cache")))

    def test_e2e_global_multi_workspace_clear_all(self):
        # Create second workspace
        ws_beta = os.path.join(self.temp_root, "workspace_beta")
        af_beta = os.path.join(ws_beta, ".aider_factory")
        os.makedirs(af_beta, exist_ok=True)

        s_alpha = os.path.join(self.af_dir, "sessions", "sess_a")
        s_beta = os.path.join(af_beta, "sessions", "sess_b")
        os.makedirs(s_alpha, exist_ok=True)
        os.makedirs(s_beta, exist_ok=True)
        with open(os.path.join(s_alpha, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: sess_a\n")
        with open(os.path.join(s_beta, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: sess_b\n")

        # Register both workspaces by running a benign CLI command in each
        self._run_cli(["--list-sessions"], cwd=self.ws_dir)
        self._run_cli(["--list-sessions"], cwd=ws_beta)

        # Global clear-all default -> both workspaces backed up and cleared
        res = self._run_cli(["--clear-all", "--global"], cwd=self.ws_dir)
        self.assertEqual(res.returncode, 0, msg=f"CLI stderr: {res.stderr}")
        self.assertFalse(os.path.exists(s_alpha))
        self.assertFalse(os.path.exists(s_beta))

        c_alpha = os.path.join(self.cache_dir, "aider_factory_cache", "workspace_alpha", ".aider_factory", "sessions", "sess_a", "session.yml")
        c_beta = os.path.join(self.cache_dir, "aider_factory_cache", "workspace_beta", ".aider_factory", "sessions", "sess_b", "session.yml")
        self.assertTrue(os.path.exists(c_alpha))
        self.assertTrue(os.path.exists(c_beta))

        # Recreate and run global with --forever
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        s_alpha2 = os.path.join(self.af_dir, "sessions", "sess_a2")
        s_beta2 = os.path.join(af_beta, "sessions", "sess_b2")
        os.makedirs(s_alpha2, exist_ok=True)
        os.makedirs(s_beta2, exist_ok=True)

        res = self._run_cli(["--clear-all", "-g", "--forever"], cwd=self.ws_dir)
        self.assertEqual(res.returncode, 0, msg=f"CLI stderr: {res.stderr}")
        self.assertFalse(os.path.exists(s_alpha2))
        self.assertFalse(os.path.exists(s_beta2))
        self.assertFalse(os.path.exists(os.path.join(self.cache_dir, "aider_factory_cache")))

    def test_e2e_global_clear_from_arbitrary_uninitialized_directory(self):
        """Zero-mock E2E: Execute 'aider-factory --clear-all -g --forever' from an empty uninitialized directory."""
        # 1. Setup an active registered workspace with a dummy session
        sess_dir = os.path.join(self.af_dir, "sessions", "session_alpha")
        os.makedirs(sess_dir, exist_ok=True)
        with open(os.path.join(sess_dir, "session.yml"), "w", encoding="utf-8") as f:
            f.write("name: Alpha\n")

        # Register workspace_alpha in registry.json
        reg_file = os.path.join(self.config_dir, "aider_factory", "registry.json")
        os.makedirs(os.path.dirname(reg_file), exist_ok=True)
        with open(reg_file, "w", encoding="utf-8") as f:
            json.dump({"projects": [self.ws_dir]}, f)

        # 2. Create an isolated uninitialized external directory (representing ~)
        external_empty_dir = os.path.join(self.temp_root, "arbitrary_external_dir")
        os.makedirs(external_empty_dir, exist_ok=True)

        # 3. Run global clear command from inside the uninitialized directory
        res = self._run_cli(["--clear-all", "-g", "--forever"], cwd=external_empty_dir)
        self.assertEqual(res.returncode, 0, msg=f"CLI stderr: {res.stderr}")
        self.assertIn("All session archives cleared in 'workspace_alpha'", res.stdout)

        # 4. Invariant assertion: external directory must remain completely empty (zero blast radius)
        self.assertEqual(os.listdir(external_empty_dir), [])

        # 5. Invariant assertion: session in registered workspace was successfully wiped
        self.assertFalse(os.path.exists(sess_dir))

    def test_e2e_all_clients_help_and_terminal_flags_smoke(self):
        """Zero-mock E2E smoke test: Verify --help, -h, and terminal flags across all clients and bash wrappers."""
        py_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../python"))
        empty_dir = os.path.join(self.temp_root, "pristine_empty_dir")
        os.makedirs(empty_dir, exist_ok=True)

        # 1. Main CLI entry point: verify --help, -h, --status -g, --list-sessions -g from empty directory
        for flag in ["--help", "-h", "--status", "--list-sessions"]:
            args = [flag, "-g"] if flag in ("--status", "--list-sessions") else [flag]
            res = self._run_cli(args, cwd=empty_dir)
            self.assertEqual(res.returncode, 0, msg=f"Flag {flag} failed with stderr: {res.stderr}")
            if flag in ("--help", "-h"):
                self.assertIn("aider-factory: Multi-agent orchestration", res.stdout)
            elif flag == "--status":
                self.assertIn("AI Factory Session & Cluster Status", res.stdout)

        # Assert pristine directory has 0 created files/directories
        self.assertEqual(os.listdir(empty_dir), [])

        # 2. Standalone Python Agent Entrypoints: verify direct script execution
        scripts = [
            (os.path.join(py_dir, "oracle_agent.py"), ["--help", "-h"], "aider-oracle: Knowledge Oracle"),
            (os.path.join(py_dir, "research_agent.py"), ["--help", "-h"], "aider-research: SearXNG search client"),
            (os.path.join(py_dir, "apply_agent.py"), ["--help", "-h"], "aider-apply: Execute headless Aider"),
            (os.path.join(py_dir, "validator.py"), ["--help", "-h"], "Evidence grounding audit"),
        ]

        for script_path, flags, expected_snippet in scripts:
            for flag in flags:
                res = subprocess.run(
                    [sys.executable, script_path, flag],
                    cwd=empty_dir,
                    env=self.env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(res.returncode, 0, msg=f"{os.path.basename(script_path)} {flag} failed: {res.stderr}")
                self.assertIn(expected_snippet, res.stdout)

        # 3. Subcommand specific help: research search -h and research (no args)
        for args in [["search", "-h"], ["search", "--help"], []]:
            res = subprocess.run(
                [sys.executable, os.path.join(py_dir, "research_agent.py")] + args,
                cwd=empty_dir,
                env=self.env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res.returncode, 0, msg=f"research_agent {' '.join(args)} failed: {res.stderr}")
            self.assertIn("aider-research: SearXNG search client", res.stdout)

        # 4. Bash Wrappers: Generate wrappers in workspace and execute them directly
        import aider_factory.cli as cli
        cli.ensure_bash_wrappers(self.af_dir)
        bash_dir = os.path.join(self.af_dir, "bash")

        wrapper_expectations = [
            ("oracle", "aider-oracle: Knowledge Oracle"),
            ("research", "aider-research: SearXNG search client"),
            ("validate", "Evidence grounding audit"),
            ("apply", "aider-apply: Execute headless Aider"),
            ("factory", "aider-factory: Multi-agent orchestration"),
        ]

        for wrapper_name, expected_snippet in wrapper_expectations:
            wrapper_path = os.path.join(bash_dir, wrapper_name)
            for flag in ["--help", "-h"]:
                res = subprocess.run(
                    [wrapper_path, flag],
                    cwd=empty_dir,
                    env=self.env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(res.returncode, 0, msg=f"Bash wrapper {wrapper_name} {flag} failed: {res.stderr}")
                self.assertIn(expected_snippet, res.stdout)

        # Final assertion: pristine directory must remain completely empty throughout all executions
        self.assertEqual(os.listdir(empty_dir), [])


if __name__ == "__main__":
    unittest.main()
