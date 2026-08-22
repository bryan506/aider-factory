import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from aider_factory.python.env_utils import is_dummy_key, resolve_api_key
from aider_factory.python.run_workflow import _render_validate_template


class TestE2EWorkflowSmoke(unittest.TestCase):
    """Zero-mock End-to-End smoke test suite asserting on physical OS return codes,
    real on-disk session creation, template rendering, and subprocess logging.
    """

    def setUp(self):
        self.repo_root = str(Path(__file__).resolve().parents[5])
        self.src_dir = os.path.join(self.repo_root, "src")
        self.workflow_runner = os.path.join(
            self.src_dir, "aider_factory", "python", "run_workflow.py"
        )
        self.cli_runner = os.path.join(self.src_dir, "aider_factory", "cli.py")

    def _get_subprocess_env(self):
        env = os.environ.copy()
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{self.src_dir}{os.pathsep}{current_pythonpath}"
            if current_pythonpath
            else self.src_dir
        )
        return env

    def test_cli_status_and_session_lifecycle_smoke(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = self._get_subprocess_env()

            res_status = subprocess.run(
                [sys.executable, self.cli_runner, "--status"],
                cwd=tmpdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(
                res_status.returncode,
                0,
                f"CLI --status failed with stderr: {res_status.stderr}",
            )
            self.assertIn("AI Factory Session & Cluster Status", res_status.stdout)

            res_list = subprocess.run(
                [sys.executable, self.cli_runner, "--list-sessions"],
                cwd=tmpdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(res_list.returncode, 0)

            res_clear = subprocess.run(
                [sys.executable, self.cli_runner, "--clear-all"],
                cwd=tmpdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(res_clear.returncode, 0)

    def test_workflow_4stage_pipeline_e2e_smoke(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            src_dir = proj / "src"
            tests_dir = proj / "tests"
            strat_dir = proj / ".aider_factory" / "markdown" / "oracle_pre_plan"

            src_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)
            strat_dir.mkdir(parents=True)

            target_py = src_dir / "calculator.py"
            test_py = tests_dir / "test_calculator.py"
            strat_md = strat_dir / "strategy_template.md"

            target_py.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            test_py.write_text(
                "import sys\n"
                "sys.path.insert(0, 'src')\n"
                "from calculator import add\n"
                "assert add(2, 3) == 5\n"
                "print('All calculator tests passed successfully.')\n",
                encoding="utf-8",
            )
            strat_md.write_text(
                "# Phase 0 Mathematical Specification\n"
                "- Goal 1: Compute exact parity\n"
                "- Goal 2: No state leakage\n",
                encoding="utf-8",
            )

            config_data = {
                "name": "E2E Smoke Pipeline",
                "working_directory": str(proj),
                "test_command_prefix": "",
                "test_runner": f"{sys.executable} {{file}}",
                "test_naming_and_path": "tests/test_{stem}.py",
                "loop_aider_test": 1,
                "phases": [
                    {
                        "name": "Phase 0 - Strategy Session",
                        "enabled": True,
                        "models": {
                            "architect_agent": "gemini/gemini-2.5-flash",
                            "editor_agent": "gemini/gemini-2.5-flash",
                        },
                        "oracle": {
                            "start_job": False,
                            "pre_edit_debate": {
                                "enabled": False,
                                "insert_debate": [1, 0, 0],
                            },
                        },
                        "toggles": {
                            "run_job_one": False,
                            "run_job_two": False,
                            "run_job_three": False,
                            "iterate_test": False,
                            "sticky_context": True,
                        },
                        "files": {
                            "target_files": [
                                ".aider_factory/markdown/oracle_pre_plan/strategy_template.md"
                            ],
                        },
                    },
                    {
                        "name": "Phase 1 - Build Validate Test",
                        "enabled": True,
                        "models": {
                            "architect_agent": "gemini/gemini-2.5-flash",
                            "editor_agent": "gemini/gemini-2.5-flash",
                            "editor_agent_test": "gemini/gemini-2.5-flash",
                        },
                        "oracle": {
                            "start_job": False,
                            "pre_edit_debate": {
                                "enabled": False,
                                "insert_debate": [1, 0, 0],
                            },
                        },
                        "toggles": {
                            "run_job_one": False,
                            "run_job_two": True,
                            "run_job_three": False,
                            "iterate_test": True,
                            "sticky_context": True,
                            "pair_programming": False,
                        },
                        "files": {
                            "target_files": ["src/calculator.py"],
                            "test_files": ["tests/test_calculator.py"],
                            "context_files_job": [],
                            "context_files_test": [],
                        },
                        "plans": {
                            "job_one_plan": "markdown/templates/implement.md",
                            "job_two_plan": None,
                            "validate_strategy_file": ".aider_factory/markdown/oracle_pre_plan/strategy_template.md",
                            "job_three_plan": "markdown/templates/testing.md",
                            "iterate_plan": "markdown/templates/testing_unit_iterate.md",
                        },
                    },
                ],
            }

            config_file = proj / "smoke_pipeline.yml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f)

            env = self._get_subprocess_env()

            res_workflow = subprocess.run(
                [
                    sys.executable,
                    self.workflow_runner,
                    "smoke_session",
                    str(config_file),
                ],
                cwd=str(proj),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(
                res_workflow.returncode,
                0,
                f"Workflow execution failed with stderr:\n{res_workflow.stderr}\nStdout:\n{res_workflow.stdout}",
            )

            session_dir = proj / ".aider_factory" / "sessions" / "smoke_session"
            self.assertTrue(session_dir.exists())

            session_yaml = session_dir / "session.yml"
            self.assertTrue(session_yaml.exists())

            rendered_template = (
                session_dir / "templates" / "calculator_validate_rendered.md"
            )
            self.assertTrue(
                rendered_template.exists(),
                f"Rendered template not found at {rendered_template}",
            )

            rendered_text = rendered_template.read_text(encoding="utf-8")
            self.assertIn(
                "## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS", rendered_text
            )
            self.assertIn("# Phase 0 Mathematical Specification", rendered_text)
            self.assertIn("Compute exact parity", rendered_text)

            logs_dir = proj / ".aider_factory" / "logs"
            self.assertTrue(logs_dir.exists())
            log_files = list(logs_dir.glob("*_run_*.log"))
            self.assertTrue(len(log_files) > 0)

    def test_template_injection_e2e_smoke(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            tmpl_file = proj / "validate.md"
            out_file = (
                proj
                / ".aider_factory"
                / "sessions"
                / "test_sess"
                / "templates"
                / "calc_validate_rendered.md"
            )

            tmpl_file.write_text(
                "# Title\n## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS\nOLD\n---\nRules",
                encoding="utf-8",
            )
            strat_content = "# Target Goals\n1. Parity\n2. Precision"

            rendered_path = _render_validate_template(
                str(tmpl_file), strat_content, str(out_file)
            )

            self.assertEqual(rendered_path, str(out_file))
            self.assertTrue(out_file.exists())
            text = out_file.read_text(encoding="utf-8")
            self.assertIn("# Target Goals\n1. Parity\n2. Precision", text)
            self.assertNotIn("OLD", text)

    def test_phase_skip_gating_e2e_smoke(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            (proj / "src").mkdir(parents=True)
            (proj / "tests").mkdir(parents=True)
            (proj / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")

            config_data = {
                "name": "Skipped Pipeline",
                "working_directory": str(proj),
                "phases": [
                    {
                        "name": "Disabled Phase",
                        "enabled": True,
                        "models": {
                            "architect_agent": "gemini/gemini-2.5-flash",
                            "editor_agent": "gemini/gemini-2.5-flash",
                        },
                        "toggles": {
                            "run_job_one": False,
                            "run_job_two": False,
                            "run_job_three": False,
                            "iterate_test": False,
                        },
                        "files": {
                            "target_files": ["src/mod.py"],
                        },
                    }
                ],
            }

            config_file = proj / "skip_pipeline.yml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f)

            env = self._get_subprocess_env()

            res = subprocess.run(
                [
                    sys.executable,
                    self.workflow_runner,
                    "skip_session",
                    str(config_file),
                ],
                cwd=str(proj),
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )

            combined_output = res.stdout + res.stderr
            self.assertEqual(res.returncode, 0)
            self.assertIn("Skipping phase 'Disabled Phase'", combined_output)

    def test_e2e_master_4job_live_cloud_model_workflow(self):
        """Zero-mock E2E live cloud model test executing physical subprocesses across
        all 4 jobs, insert_debate: [1, 1, 1], loops: 0 lone consultation, heterogeneous
        debate templates, multi-corpus vector routing, and template injection.
        """
        active_model = "gemini/gemini-2.5-flash"
        api_key = resolve_api_key(active_model)
        if not api_key or is_dummy_key(api_key):
            self.skipTest(
                "Live API key required for real cloud model E2E execution. "
                "Export GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY to run."
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            src_dir = proj / "src"
            tests_dir = proj / "tests"
            strat_dir = proj / ".aider_factory" / "markdown" / "oracle_pre_plan"
            tmpl_dir = proj / "templates"

            src_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)
            strat_dir.mkdir(parents=True)
            tmpl_dir.mkdir(parents=True)

            # Initialize physical git repository required by Aider
            subprocess.run(["git", "init"], cwd=str(proj), capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "AI Factory Tester"], cwd=str(proj), capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "tester@aiderfactory.local"], cwd=str(proj), capture_output=True, check=True)

            # Initial source and test fixtures
            target_py = src_dir / "math_ops.py"
            test_py = tests_dir / "test_math_ops.py"
            strat_md = strat_dir / "strategy_template.md"

            target_py.write_text(
                "def add(a: int, b: int) -> int:\n    return a + b\n",
                encoding="utf-8",
            )
            test_py.write_text(
                "import sys\nsys.path.insert(0, 'src')\nfrom math_ops import add\n\n"
                "def test_add():\n    assert add(2, 3) == 5\n",
                encoding="utf-8",
            )
            strat_md.write_text(
                "# Phase 0 Mathematical Specification\n\n"
                "## Implemented Requirements\n"
                "- Implement function `def square(n: int) -> int:` that returns `n * n`.\n"
                "- Preserve existing `add` function completely.\n"
                "- Write comprehensive unit test `test_square()` asserting `square(4) == 16` and `square(-3) == 9`.\n",
                encoding="utf-8",
            )

            # Specialized per-job debate templates
            j1_tmpl = tmpl_dir / "j1_debate.md"
            j2_tmpl = tmpl_dir / "j2_debate.md"
            j3_tmpl = tmpl_dir / "j3_debate.md"
            j1_tmpl.write_text("# Job 1 Architecture Contract\nValidate that square(n) is planned.", encoding="utf-8")
            j2_tmpl.write_text("# Job 2 Specification Audit\nVerify mathematical consistency.", encoding="utf-8")
            j3_tmpl.write_text("# Job 3 Mocking & Unit Test Contract\nVerify test_square assertions.", encoding="utf-8")

            # Custom validator template for Job 2
            val_base_tmpl = tmpl_dir / "validate_custom.md"
            val_base_tmpl.write_text(
                "# Custom Validator\n"
                "## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS\n"
                "PLACEHOLDER\n"
                "---\n"
                "## 2. Editor Execution Strategy\n",
                encoding="utf-8",
            )

            # Commit initial files to git
            subprocess.run(["git", "add", "."], cwd=str(proj), capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(proj), capture_output=True, check=True)

            config_data = {
                "name": "Live Master 4-Job Debate Pipeline",
                "working_directory": str(proj),
                "test_command_prefix": "",
                "test_runner": f"{sys.executable} -m pytest {{file}}",
                "test_naming_and_path": "tests/test_{stem}.py",
                "loop_aider_test": 2,
                "phases": [
                    {
                        "name": "Phase 0 - Strategy Session",
                        "enabled": True,
                        "models": {
                            "architect_agent": active_model,
                            "editor_agent": active_model,
                        },
                        "toggles": {
                            "run_job_one": False,
                            "run_job_two": False,
                            "run_job_three": False,
                            "iterate_test": False,
                            "sticky_context": True,
                        },
                        "files": {
                            "target_files": [
                                ".aider_factory/markdown/oracle_pre_plan/strategy_template.md"
                            ],
                        },
                    },
                    {
                        "name": "Phase 1 - 4-Job Live Build",
                        "enabled": True,
                        "models": {
                            "architect_agent": active_model,
                            "editor_agent": active_model,
                            "editor_agent_test": active_model,
                            "rag_agent": active_model,
                        },
                        "oracle": {
                            "start_job": False,
                            "pre_edit_debate": {
                                "enabled": True,
                                "insert_debate": [1, 1, 1],
                                "loops": 0,  # 1-shot lone consultation with real cloud model
                                "job_debate_template": [
                                    "templates/j1_debate.md",
                                    "templates/j2_debate.md",
                                    "templates/j3_debate.md",
                                ],
                                "job_debate_collection": [
                                    "coll_math",
                                    "coll_audit",
                                    "coll_tests",
                                ],
                            },
                        },
                        "toggles": {
                            "run_job_one": True,
                            "run_job_two": True,
                            "run_job_three": True,
                            "iterate_test": True,
                            "sticky_context": True,
                            "pair_programming": False,
                            "yes_always": True,
                            "auto_accept_architect": True,
                            "auto_commits": False,
                        },
                        "files": {
                            "target_files": ["src/math_ops.py"],
                            "test_files": ["tests/test_math_ops.py"],
                            "context_files_job": ["src/math_ops.py"],
                            "context_files_test": ["src/math_ops.py"],
                        },
                        "plans": {
                            "job_one_plan": "markdown/templates/implement.md",
                            "job_two_plan": "templates/validate_custom.md",
                            "validate_strategy_file": ".aider_factory/markdown/oracle_pre_plan/strategy_template.md",
                            "job_three_plan": "markdown/templates/testing.md",
                            "iterate_plan": "markdown/templates/testing_unit_iterate.md",
                        },
                    },
                ],
            }

            config_file = proj / "live_pipeline.yml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f)

            env = self._get_subprocess_env()

            # Execute real workflow subprocess
            res_workflow = subprocess.run(
                [
                    sys.executable,
                    self.workflow_runner,
                    "live_master_session",
                    str(config_file),
                ],
                cwd=str(proj),
                env=env,
                capture_output=True,
                text=True,
                timeout=240,
            )

            self.assertEqual(
                res_workflow.returncode,
                0,
                f"Live E2E execution failed with stderr:\n{res_workflow.stderr}\nStdout:\n{res_workflow.stdout}",
            )

            # 1. Assert paired session configuration
            session_dir = proj / ".aider_factory" / "sessions" / "live_master_session"
            self.assertTrue(session_dir.exists(), "Session directory was not created")
            self.assertTrue((session_dir / "session.yml").exists(), "session.yml was not paired")

            # 2. Assert strategy injection into rendered validation template
            val_rendered = session_dir / "templates" / "math_ops_validate_rendered.md"
            self.assertTrue(val_rendered.exists(), "Rendered validate template was not generated")
            val_text = val_rendered.read_text(encoding="utf-8")
            self.assertIn("# Phase 0 Mathematical Specification", val_text)
            self.assertIn("Implement function `def square(n: int) -> int:`", val_text)
            self.assertNotIn("PLACEHOLDER", val_text)

            # 3. Assert on-disk debate verdicts generated by live Oracle consultation
            debates_dir = proj / ".aider_factory" / "logs" / "debates"
            self.assertTrue((debates_dir / "math_ops.job1_verdict.md").exists(), "Job 1 verdict missing")
            self.assertTrue((debates_dir / "math_ops.job2_verdict.md").exists(), "Job 2 verdict missing")
            self.assertTrue((debates_dir / "math_ops.job3_verdict.md").exists(), "Job 3 verdict missing")

            # 4. Assert physical code transformations performed by live models
            final_math_ops = target_py.read_text(encoding="utf-8")
            self.assertIn("def square", final_math_ops, "Job 1 model edit was not applied to math_ops.py")

            final_tests = test_py.read_text(encoding="utf-8")
            self.assertIn("square", final_tests, "Job 3 model edit was not applied to test_math_ops.py")

            # 5. Assert physical test execution passes cleanly
            test_run = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_py)],
                cwd=str(proj),
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                test_run.returncode,
                0,
                f"Generated unit tests failed:\nStdout:\n{test_run.stdout}\nStderr:\n{test_run.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
