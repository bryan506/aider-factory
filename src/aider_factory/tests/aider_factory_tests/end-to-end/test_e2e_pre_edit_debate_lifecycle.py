#!/usr/bin/env python3
# test_e2e_pre_edit_debate_lifecycle.py — E2E tests for pre-edit debate lifecycle,
# proposal sanitization, and downstream editor task gating.

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../../python"))
for _p in (python_module_dir,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import deliberate
from orchestrate import AiderFactory, Task


class TestE2EPreEditDebateLifecycle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)

        self._orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin_dir}{os.pathsep}{self._orig_path}"
        self._orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        os.environ["PATH"] = self._orig_path
        self._tmp.cleanup()

    @staticmethod
    def _write_fake_binary(path: Path, content: str):
        if sys.platform == "win32":
            py_path = str(path) + ".py"
            with open(py_path, "w", encoding="utf-8") as f:
                f.write(content)
            cmd_path = str(path) + ".cmd"
            with open(cmd_path, "w", encoding="utf-8") as f:
                f.write(f'@"{sys.executable}" "%~dp0{os.path.basename(py_path)}" %*\n@exit /b %errorlevel%\n')
        else:
            with open(str(path), "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(str(path), os.stat(str(path)).st_mode | stat.S_IEXEC)

    def test_e2e_pre_edit_debate_consensus_and_clean_verdict_handoff(self):
        """E2E: Validates agreed pre-edit debate writes clean verdict and hands off to editor."""
        mock_aider = self.bin_dir / "aider"
        fake_aider = (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "from pathlib import Path\n"
            "for arg in sys.argv:\n"
            "    if arg.endswith('.py') and not arg.startswith('-'):\n"
            "        Path(arg).write_text('# edited by editor task\\n', encoding='utf-8')\n"
            "sys.exit(0)\n"
        )
        self._write_fake_binary(mock_aider, fake_aider)

        factory = AiderFactory(str(self.root), session_name="e2e_pre_edit")
        debates_dir = self.root / ".aider_factory" / "logs" / "debates"
        debates_dir.mkdir(parents=True, exist_ok=True)

        target_file = self.root / "calc.py"
        target_file.write_text("# original calc\n", encoding="utf-8")

        verdict_file = debates_dir / "calc_e2e_pre_edit.job2_verdict_r1.md"

        noisy_proposal = (
            "Added src/calc.py to the chat (read-only).\n"
            "Restored previous conversation history.\n"
            "► THINKING\n"
            "Analyzing math bugs...\n"
            "## Scope Analysis\n\n"
            "### Target Files:\n1. `calc.py`\n\n"
            "## Implementation Plan\n\n"
            "### [Task ID: 001] - Fix Addition\n"
            "- Pattern: return a + b\n"
        )

        deliberate.write_verdict(
            str(verdict_file),
            state="agreed",
            gate_present=False,
            proposal=noisy_proposal,
            draft_mode=True,
            oracle_response="VERDICT: AGREE",
        )

        self.assertTrue(verdict_file.exists())
        content = verdict_file.read_text(encoding="utf-8")
        self.assertIn("STATUS: agreed", content)
        self.assertIn("GATE: draft", content)
        self.assertNotIn("chat (read-only)", content)
        self.assertNotIn("THINKING", content)
        self.assertIn("## Scope Analysis", content)

        job2_task = Task(
            id="job2_calc_apply",
            files=[str(target_file)],
            message_file=str(verdict_file),
            verdict_gate=str(verdict_file),
            skip_aider=False,
        )

        success = factory.run_task(job2_task)
        self.assertTrue(success)
        self.assertEqual(target_file.read_text(encoding="utf-8"), "# edited by editor task\n")

    def test_e2e_pre_edit_debate_deadlock_halts_downstream_task(self):
        """E2E: Validates deadlock pre-edit debate halts downstream editor and leaves target untouched."""
        factory = AiderFactory(str(self.root), session_name="e2e_deadlock")
        debates_dir = self.root / ".aider_factory" / "logs" / "debates"
        debates_dir.mkdir(parents=True, exist_ok=True)

        target_file = self.root / "calc_untouched.py"
        target_file.write_text("# pristine source\n", encoding="utf-8")

        verdict_file = debates_dir / "calc_deadlock.job2_verdict_r1.md"
        deliberate.write_verdict(
            str(verdict_file),
            state="deadlock",
            gate_present=False,
            proposal="Contested proposal",
            draft_mode=True,
            oracle_response="VERDICT: OBJECT - logic flawed",
        )

        job2_task = Task(
            id="job2_calc_deadlock",
            files=[str(target_file)],
            message_file=str(verdict_file),
            verdict_gate=str(verdict_file),
            skip_aider=False,
        )

        success = factory.run_task(job2_task)
        self.assertTrue(success)
        # Target file must remain completely untouched!
        self.assertEqual(target_file.read_text(encoding="utf-8"), "# pristine source\n")


if __name__ == "__main__":
    unittest.main()
