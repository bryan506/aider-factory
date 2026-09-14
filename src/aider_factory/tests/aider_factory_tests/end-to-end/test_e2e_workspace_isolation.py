#!/usr/bin/env python3
# test_e2e_workspace_isolation.py — Zero-Mock Multi-Workspace State & Session Isolation Test Suite.

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
cli_script = os.path.abspath(os.path.join(script_dir, "../../../cli.py"))
python_dir = os.path.abspath(os.path.join(script_dir, "../../../python"))

sys.path.insert(0, python_dir)
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, "../../..")))


def _get_clean_env(extra_env=None):
    env = os.environ.copy()
    for k in list(env.keys()):
        if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_") or k == "AIDER_ARCHITECT":
            env.pop(k, None)
    if extra_env:
        env.update(extra_env)
    return env


class TestE2EWorkspaceIsolation(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_root.name)
        self.ws_a = self.root_path / "Workspace_Alpha"
        self.ws_b = self.root_path / "Workspace_Beta"
        self.config_dir = self.root_path / "global_config"
        self.ws_a.mkdir()
        self.ws_b.mkdir()
        self.config_dir.mkdir()

        self.env = _get_clean_env({
            "XDG_CONFIG_HOME": str(self.config_dir),
            "HOME": str(self.root_path),
            "AIDER_HELPER_API_BASE": "http://127.0.0.1:9999/v1",
            "OPENAI_API_KEY": "sk-dummy",
        })

    def tearDown(self):
        self.temp_root.cleanup()

    def test_e2e_two_workspaces_complete_isolation(self):
        """Zero-mock verification: 2 distinct workspaces initialize and maintain separate files, sessions, and configs."""
        # 1. Initialize Workspace Alpha with unique file
        (self.ws_a / "alpha_feature.py").write_text("def alpha_logic(): pass\n", encoding="utf-8")
        proc_a = subprocess.run(
            [sys.executable, cli_script, "--repo-map"],
            cwd=str(self.ws_a),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_a.returncode, 0, f"Alpha init failed: {proc_a.stderr}")

        # 2. Initialize Workspace Beta with unique file
        (self.ws_b / "beta_feature.py").write_text("def beta_logic(): pass\n", encoding="utf-8")
        proc_b = subprocess.run(
            [sys.executable, cli_script, "--repo-map"],
            cwd=str(self.ws_b),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_b.returncode, 0, f"Beta init failed: {proc_b.stderr}")

        # 3. Assert Workspace Alpha's configuration contains only Alpha's target files
        env_a = (self.ws_a / ".aider_factory" / ".env.yml").read_text(encoding="utf-8")
        self.assertIn("alpha_feature.py", env_a)
        self.assertNotIn("beta_feature.py", env_a)

        # 4. Assert Workspace Beta's configuration contains only Beta's target files
        env_b = (self.ws_b / ".aider_factory" / ".env.yml").read_text(encoding="utf-8")
        self.assertIn("beta_feature.py", env_b)
        self.assertNotIn("alpha_feature.py", env_b)

        # 5. Assert static repo maps are isolated
        repo_map_a = (self.ws_a / ".aider_factory" / "static_repo_map.md").read_text(encoding="utf-8")
        repo_map_b = (self.ws_b / ".aider_factory" / "static_repo_map.md").read_text(encoding="utf-8")
        self.assertIn("alpha_feature.py", repo_map_a)
        self.assertNotIn("beta_feature.py", repo_map_a)
        self.assertIn("beta_feature.py", repo_map_b)
        self.assertNotIn("alpha_feature.py", repo_map_b)

    def test_e2e_workspace_session_clear_isolation(self):
        """Clearing sessions in Workspace Alpha does not modify or delete sessions in Workspace Beta."""
        # Setup fake session directories in Alpha and Beta
        sess_a = self.ws_a / ".aider_factory" / "sessions" / "session_alpha_123"
        sess_b = self.ws_b / ".aider_factory" / "sessions" / "session_beta_456"
        sess_a.mkdir(parents=True, exist_ok=True)
        sess_b.mkdir(parents=True, exist_ok=True)
        (sess_a / "session.yml").write_text("name: Alpha Session\n", encoding="utf-8")
        (sess_b / "session.yml").write_text("name: Beta Session\n", encoding="utf-8")

        # Clear session in Alpha
        proc = subprocess.run(
            [sys.executable, cli_script, "--clear-session", "session_alpha_123", "--forever"],
            cwd=str(self.ws_a),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)

        # Assert Alpha session is removed, Beta session remains intact
        self.assertFalse(sess_a.exists(), "Alpha session must be deleted")
        self.assertTrue(sess_b.exists(), "Beta session must remain untouched")
        self.assertTrue((sess_b / "session.yml").exists(), "Beta session configuration must be preserved")

    def test_e2e_workspace_side_session_isolation(self):
        """Side-agent sessions (.helper_session.json, .oracle_session.json) are strictly isolated per workspace."""
        af_a = self.ws_a / ".aider_factory"
        af_b = self.ws_b / ".aider_factory"
        af_a.mkdir(parents=True, exist_ok=True)
        af_b.mkdir(parents=True, exist_ok=True)

        helper_a = af_a / ".helper_session.json"
        helper_b = af_b / ".helper_session.json"
        helper_a.write_text(json.dumps([{"role": "user", "content": "Alpha question"}]), encoding="utf-8")
        helper_b.write_text(json.dumps([{"role": "user", "content": "Beta question"}]), encoding="utf-8")

        # Clear helper session from Alpha
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.argv=['aider-helper', '--clear']; from aider_factory.cli import helper_cli; helper_cli()",
            ],
            cwd=str(self.ws_a),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)

        # Alpha helper session is removed; Beta helper session remains intact
        self.assertFalse(helper_a.exists(), "Alpha helper session must be deleted")
        self.assertTrue(helper_b.exists(), "Beta helper session must be preserved")
        self.assertIn("Beta question", helper_b.read_text(encoding="utf-8"))

    def test_e2e_apply_context_and_config_isolation(self):
        """Zero-mock verification: aider-apply sanitizes configs, blocks leaks, and isolates context."""
        bin_dir = self.root_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        args_dump = self.root_path / "aider_args_dump.txt"
        rejections_dump = self.root_path / "aider_rejections.txt"

        fake_aider = bin_dir / "aider"
        fake_aider.write_text(
            textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import os, sys
                from pathlib import Path
                with open(r"{args_dump}", "w") as f:
                    for a in sys.argv[1:]:
                        f.write(f"{{a}}\\n")

                target_args = set()
                msg_file = None
                for idx, arg in enumerate(sys.argv):
                    if arg == "--message-file" and idx + 1 < len(sys.argv):
                        msg_file = sys.argv[idx + 1]
                    elif arg.endswith(".py") and not arg.startswith("-"):
                        target_args.add(os.path.basename(arg))

                rejections = []
                if msg_file and os.path.isfile(msg_file):
                    spec_text = Path(msg_file).read_text(encoding="utf-8")
                    for word in spec_text.split():
                        clean_word = word.strip("`'\\"(),:;[]{{}}").rstrip(".")
                        base = os.path.basename(clean_word)
                        if base.endswith(".py") and base not in target_args and os.path.isfile(clean_word):
                            if "--yes-always" in sys.argv:
                                rejections.append(f"auto-accepted:{{base}}")
                                Path(clean_word).write_text("# edited via mention\\n")
                            else:
                                ans = sys.stdin.readline().strip() if not sys.stdin.closed else ""
                                if ans == "n":
                                    rejections.append(f"rejected:{{base}}")
                                else:
                                    rejections.append(f"accepted:{{base}}")
                                    Path(clean_word).write_text("# edited via mention\\n")

                with open(r"{rejections_dump}", "w") as f:
                    for r in rejections:
                        f.write(f"{{r}}\\n")

                for a in sys.argv[1:]:
                    if a.endswith(".py") and not a.startswith("-"):
                        Path(a).write_text("# edited by mock aider\\n")
                sys.exit(0)
            """),
            encoding="utf-8",
        )
        fake_aider.chmod(fake_aider.stat().st_mode | stat.S_IEXEC)

        af = self.ws_a / ".aider_factory"
        af.mkdir(parents=True, exist_ok=True)

        conf = af / ".aider.conf.yml"
        conf.write_text(
            yaml.dump({
                "read": ["static_repo_map.md", "static_repo_map_tests.md", "CONVENTIONS.md"],
                "files": ["ambient_leak.py"],
                "architect": True,
                "model": "openai/test-model",
            }),
            encoding="utf-8",
        )

        ambient = self.ws_a / "ambient_leak.py"
        ambient.write_text("# ambient untouched\n", encoding="utf-8")
        target = self.ws_a / "target.py"
        target.write_text("# original\n", encoding="utf-8")

        chat_hist = af / ".aider.chat.history.md"
        chat_hist.write_text(
            "#### /run ls -la\ncommand output\n\n> Tokens: 1k sent, 100 received\n"
            "#### Old Turn 1\n<think>old reasoning</think>\nOld plan referencing ambient_leak.py\n\n> Tokens: 1k sent, 100 received\n"
            "#### /ask Active Task: Update target\n<think>new reasoning</think>\nExact target plan with reference to ambient_leak.py\n\n> Tokens: 1k sent, 100 received\n",
            encoding="utf-8",
        )

        env = _get_clean_env({
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "HOME": str(self.root_path),
        })
        apply_script = os.path.join(python_dir, "apply_agent.py")

        proc = subprocess.run(
            [sys.executable, apply_script, str(target), "--no-diff"],
            cwd=str(self.ws_a),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")

        # 1. Assert physical modification isolation
        self.assertEqual(target.read_text(encoding="utf-8"), "# edited by mock aider\n")
        self.assertEqual(ambient.read_text(encoding="utf-8"), "# ambient untouched\n")

        # 2. Assert on-disk configuration sanitization
        sanitized_conf = af / "temp" / ".apply.aider.conf.yml"
        self.assertTrue(sanitized_conf.exists())
        with open(sanitized_conf, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.assertNotIn("read", cfg)
        self.assertNotIn("files", cfg)
        self.assertFalse(cfg.get("architect"))

        # 3. Assert active specification hygiene
        active_spec = af / "temp" / "active_spec.md"
        self.assertTrue(active_spec.exists())
        spec_text = active_spec.read_text(encoding="utf-8")
        self.assertIn("Active Task: Update target", spec_text)
        self.assertIn("Exact target plan", spec_text)
        self.assertNotIn("Old Turn 1", spec_text)
        self.assertNotIn("/run", spec_text)
        self.assertNotIn("<think>", spec_text)

        # 4. Assert command line boundaries & stdin prompt rejection
        args_text = args_dump.read_text(encoding="utf-8").splitlines()
        self.assertIn("--exit", args_text)
        self.assertNotIn("--yes-always", args_text)
        self.assertNotIn("--architect", args_text)
        self.assertNotIn("--no-architect", args_text)
        self.assertNotIn("--read", args_text)
        self.assertIn("--map-tokens", args_text)
        self.assertEqual(args_text[args_text.index("--map-tokens") + 1], "0")
        self.assertIn(str(target), args_text)
        self.assertNotIn(str(ambient), args_text)

        rejections = rejections_dump.read_text(encoding="utf-8").splitlines()
        self.assertIn("rejected:ambient_leak.py", rejections)

    def test_e2e_apply_multi_target_isolation(self):
        """Zero-mock verification: multi-target positional arguments edit only targeted files."""
        bin_dir = self.root_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        args_dump = self.root_path / "aider_args_multi.txt"

        fake_aider = bin_dir / "aider"
        fake_aider.write_text(
            textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import sys
                from pathlib import Path
                with open(r"{args_dump}", "w") as f:
                    for a in sys.argv[1:]:
                        f.write(f"{{a}}\\n")
                for a in sys.argv[1:]:
                    if a.endswith(".py") and not a.startswith("-"):
                        Path(a).write_text("# edited by mock aider\\n")
                sys.exit(0)
            """),
            encoding="utf-8",
        )
        fake_aider.chmod(fake_aider.stat().st_mode | stat.S_IEXEC)

        target_1 = self.ws_b / "target_1.py"
        target_2 = self.ws_b / "target_2.py"
        ambient = self.ws_b / "ambient_unaffected.py"
        spec = self.ws_b / "spec.md"

        target_1.write_text("# orig 1\n", encoding="utf-8")
        target_2.write_text("# orig 2\n", encoding="utf-8")
        ambient.write_text("# untouched\n", encoding="utf-8")
        spec.write_text("Update both files.\n", encoding="utf-8")

        env = _get_clean_env({
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "HOME": str(self.root_path),
        })
        apply_script = os.path.join(python_dir, "apply_agent.py")

        proc = subprocess.run(
            [sys.executable, apply_script, str(target_1), str(target_2), "--spec", str(spec), "--no-diff"],
            cwd=str(self.ws_b),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")

        self.assertEqual(target_1.read_text(encoding="utf-8"), "# edited by mock aider\n")
        self.assertEqual(target_2.read_text(encoding="utf-8"), "# edited by mock aider\n")
        self.assertEqual(ambient.read_text(encoding="utf-8"), "# untouched\n")

        args_text = args_dump.read_text(encoding="utf-8").splitlines()
        self.assertIn(str(target_1), args_text)
        self.assertIn(str(target_2), args_text)
        self.assertNotIn(str(ambient), args_text)

    def test_e2e_apply_custom_session_isolation(self):
        """Zero-mock verification: session flag targets only the specified session history."""
        bin_dir = self.root_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        args_dump = self.root_path / "aider_args_sess.txt"

        fake_aider = bin_dir / "aider"
        fake_aider.write_text(
            textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import sys
                from pathlib import Path
                with open(r"{args_dump}", "w") as f:
                    for a in sys.argv[1:]:
                        f.write(f"{{a}}\\n")
                for a in sys.argv[1:]:
                    if a.endswith(".py") and not a.startswith("-"):
                        Path(a).write_text("# edited by mock aider\\n")
                sys.exit(0)
            """),
            encoding="utf-8",
        )
        fake_aider.chmod(fake_aider.stat().st_mode | stat.S_IEXEC)

        af = self.ws_a / ".aider_factory"
        sess_dir = af / "sessions" / "custom_branch"
        sess_dir.mkdir(parents=True, exist_ok=True)

        # Root history (should NOT be picked up)
        (af / ".aider.chat.history.md").write_text(
            "#### ROOT LEAK\nRoot plan\n\n> Tokens: 1k sent, 100 received\n",
            encoding="utf-8",
        )
        # Session history (MUST be picked up)
        (sess_dir / ".aider.chat.history.md").write_text(
            "#### SESSION DIRECTIVE\nSession plan\n\n> Tokens: 1k sent, 100 received\n",
            encoding="utf-8",
        )

        target = self.ws_a / "sess_target.py"
        target.write_text("# original\n", encoding="utf-8")

        env = _get_clean_env({
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "HOME": str(self.root_path),
        })
        apply_script = os.path.join(python_dir, "apply_agent.py")

        proc = subprocess.run(
            [sys.executable, apply_script, str(target), "--session", "custom_branch", "--no-diff"],
            cwd=str(self.ws_a),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")

        active_spec = af / "temp" / "active_spec.md"
        self.assertTrue(active_spec.exists())
        spec_text = active_spec.read_text(encoding="utf-8")
        self.assertIn("SESSION DIRECTIVE", spec_text)
        self.assertIn("Session plan", spec_text)
        self.assertNotIn("ROOT LEAK", spec_text)


if __name__ == "__main__":
    unittest.main()
