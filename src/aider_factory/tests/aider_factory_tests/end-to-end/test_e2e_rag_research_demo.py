import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestE2ERagResearchDemo(unittest.TestCase):
    """Zero-Mock Live E2E test executing the self-contained rag_research example suite."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).resolve().parent
        # Locate src/aider_factory/tests/examples/rag_research
        cls.demo_source = cls.test_dir.parents[1] / "examples" / "rag_research"
        if not cls.demo_source.is_dir():
            raise unittest.SkipTest(f"rag_research directory not found at {cls.demo_source}")

    def _ensure_binaries_on_path(self, bin_dir: Path, env: dict):
        """Ensure aider-* CLI commands resolve deterministically in the test subprocess."""
        bin_dir.mkdir(parents=True, exist_ok=True)
        py_exec = sys.executable
        python_pkg_dir = self.test_dir.parents[2] / "src"

        shims = {
            "aider-helper": "from aider_factory.python.cli import main_helper; main_helper()",
            "aider-oracle": "import sys; from aider_factory.python.oracle_agent import main; sys.exit(main())",
            "aider-validate": "import sys; from aider_factory.python.validator import main; sys.exit(main())",
            "aider-research": "import sys; from aider_factory.python.research_agent import main; sys.exit(main())",
        }

        for bin_name, py_code in shims.items():
            script_path = bin_dir / bin_name
            existing = shutil.which(bin_name, path=env.get("PATH", ""))
            if not existing:
                script_path.write_text(
                    f"#!/usr/bin/env bash\n"
                    f'PYTHONPATH="{python_pkg_dir}:${{PYTHONPATH:-}}" exec "{py_exec}" -c "{py_code}" "$@"\n',
                    encoding="utf-8",
                )
                script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)

        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        env["PYTHONPATH"] = f"{python_pkg_dir}:{env.get('PYTHONPATH', '')}"

    def test_e2e_rag_research_workflow(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = Path(tmp_dir) / "workspace"
            shutil.copytree(self.demo_source, ws)

            env = os.environ.copy()
            shim_bin = Path(tmp_dir) / "bin"
            self._ensure_binaries_on_path(shim_bin, env)

            # Scrub lingering session variables
            for k in list(env.keys()):
                if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_"):
                    env.pop(k, None)

            env["ORACLE_EMBED_MODEL"] = "BAAI/bge-m3"
            env["ORACLE_EMBED_BACKEND"] = "sentence-transformers"
            env["ORACLE_EMBED_API_BASE"] = ""
            if "OPENAI_API_KEY" not in env and "GEMINI_API_KEY" not in env:
                env["OPENAI_API_KEY"] = "sk-dummy"

            # 1. Run 01_setup_workspace.sh
            res1 = subprocess.run(
                ["bash", "01_setup_workspace.sh"],
                cwd=str(ws),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res1.returncode,
                0,
                f"01_setup_workspace.sh failed with exit code {res1.returncode}\nStderr: {res1.stderr}\nStdout: {res1.stdout}",
            )
            self.assertTrue((ws / ".aider_factory" / ".env.yml").is_file())

            # 2. Run 02_research_and_rag.sh
            res2 = subprocess.run(
                ["bash", "02_research_and_rag.sh"],
                cwd=str(ws),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res2.returncode,
                0,
                f"02_research_and_rag.sh failed with exit code {res2.returncode}\nStderr: {res2.stderr}\nStdout: {res2.stdout}",
            )
            lancedb_dir = ws / ".aider_factory" / "markdown" / "lanceDB" / "microstructure" / "lancedb"
            self.assertTrue(lancedb_dir.is_dir(), "LanceDB database was not created")

            # 3. Run 03_draft_and_validate.sh all
            res3 = subprocess.run(
                ["bash", "03_draft_and_validate.sh", "all"],
                cwd=str(ws),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res3.returncode,
                0,
                f"03_draft_and_validate.sh failed with exit code {res3.returncode}\nStderr: {res3.stderr}\nStdout: {res3.stdout}",
            )

            # Assert generated reports and baseline reset
            # On positive pass, validator cleans up heal reports
            self.assertFalse((ws / "reports" / "quote_audit_positive.md").is_file())
            # On negative rejection, validator retains audit reports
            self.assertTrue((ws / "reports" / "quote_audit_negative.md").is_file())
            self.assertTrue((ws / "reports" / "claims_audit_negative.md").is_file())
            self.assertIn("POSITIVE TEST RESULT: PASS", res3.stdout)
            self.assertIn("NEGATIVE TEST RESULT: PASS", res3.stdout)
