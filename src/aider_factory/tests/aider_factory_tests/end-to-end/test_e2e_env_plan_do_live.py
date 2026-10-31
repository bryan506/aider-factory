#!/usr/bin/env python3
"""test_e2e_env_plan_do_live.py — True Zero-Mock 3-Phase Live E2E Test Suite for .env_plan_do.yml.

Executes the real `aider` binary, real `run_bootstrap()`, real `run_workflow.py`,
real `oracle_agent.py`, and real `pytest` across all 3 phases:
  Phase 1 (Architect Planning)
    -> Phase 2 (Code, 2-Round Pre-Edit Debates, <stem> Unit Test Authoring, Pytest Verify)
    -> Phase 3 (Post-Test Validation & Review)

Not included in GitHub CI (`uv_run.py`) so CI remains offline-safe.
Run directly via:
  uv run pytest src/aider_factory/tests/aider_factory_tests/end-to-end/test_e2e_env_plan_do_live.py -s
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

import yaml

test_file_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(test_file_dir, "../../../../.."))
src_dir = os.path.join(repo_root, "src")
pkg_dir = os.path.join(src_dir, "aider_factory")
python_dir = os.path.join(pkg_dir, "python")

for p in (repo_root, src_dir, pkg_dir, python_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

from bootstrap import run_bootstrap
from env_utils import is_dummy_key, load_env_files
from run_workflow import _extract_files_from_plan

RUN_WORKFLOW_PATH = os.path.join(python_dir, "run_workflow.py")


def _probe_openai_endpoint(
    base_url: str, api_key: str = "sk-dummy", timeout: float = 2.5
) -> list[str]:
    """Return list of model IDs from an OpenAI-compatible /v1/models endpoint, or [] if unreachable."""
    if not base_url:
        return []
    url = f"{base_url.rstrip('/')}/models"
    headers = {"User-Agent": "AI-Factory-LiveTest/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                models = [
                    m["id"] if "/" in m["id"] else f"openai/{m['id']}"
                    for m in data.get("data", [])
                    if isinstance(m, dict) and m.get("id")
                ]
                return models
    except Exception:
        pass
    return []


def _resolve_live_endpoints_and_models() -> dict | None:
    """Resolve cloud Gemini model (gemini/gemini-3.8-flash) for live E2E execution."""
    load_env_files(repo_root)

    for k in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "AIDER_GEMINI_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_VERTEX_PROJECT",
        "VERTEXAI_PROJECT",
    ):
        val = os.environ.get(k)
        if val and not is_dummy_key(val):
            m = "gemini/gemini-3.8-flash"
            return {
                "mode": "cloud_gemini",
                "architect_api_base": "",
                "editor_api": "",
                "rag_agent_api": "",
                "weak_model_api_base": "",
                "architect_agent": m,
                "editor_agent": m,
                "rag_agent": m,
                "weak_model": m,
            }

    return None


class TestE2EEnvPlanDoLive(unittest.TestCase):
    """Zero-mock live 3-phase E2E test for .env_plan_do.yml."""

    def setUp(self):
        self.live_cfg = _resolve_live_endpoints_and_models()
        if not self.live_cfg:
            self.skipTest("No live LLM endpoint or cloud API key detected.")
        if not shutil.which("aider"):
            self.skipTest("Real 'aider' binary not found in PATH.")

        self.tmp_dir = tempfile.mkdtemp(prefix="e2e_plan_do_live_")
        self.project_dir = Path(self.tmp_dir)
        self.old_cwd = os.getcwd()
        os.chdir(self.project_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_live_3phase_env_plan_do_end_to_end(self):
        """Run Phase 1 (Plan) -> Phase 2 (Code + 2-Round Pre-Edit Debates + <stem> Unit Tests + Pytest Verify) -> Phase 3 (Post-Test Validation) live."""
        print(
            f"\n[Live E2E] Using mode={self.live_cfg['mode']} | "
            f"Architect={self.live_cfg['architect_agent']} | "
            f"Editor={self.live_cfg['editor_agent']}"
        )

        # 1. Initialize real git repo and project files
        subprocess.run(
            ["git", "init"], cwd=self.tmp_dir, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Live E2E Tester"],
            cwd=self.tmp_dir,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "live@aider.local"],
            cwd=self.tmp_dir,
            check=True,
        )

        (self.project_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "docs").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "src" / "__init__.py").write_text("", encoding="utf-8")
        (self.project_dir / "src" / "validators.py").write_text(
            "def ensure_int(val: int) -> int:\n"
            '    """Placeholder: raise TypeError(\'not_int\') if isinstance(val, bool) or not isinstance(val, int), else return val."""\n'
            "    return val\n",
            encoding="utf-8",
        )
        (self.project_dir / "src" / "bounds.py").write_text(
            "from src.validators import ensure_int\n\n"
            "def validate_bounds(low: int, high: int) -> None:\n"
            '    """Placeholder: call ensure_int(low) and ensure_int(high); raise ValueError(\'low_gt_high\') if low > high."""\n'
            "    pass\n",
            encoding="utf-8",
        )
        (self.project_dir / "src" / "formatter.py").write_text(
            "def format_clamped(val: int) -> str:\n"
            '    """Placeholder: return f\'CLAMPED:{val}\'."""\n'
            "    return ''\n",
            encoding="utf-8",
        )
        (self.project_dir / "src" / "clamp.py").write_text(
            "from src.bounds import validate_bounds\n"
            "from src.validators import ensure_int\n"
            "from src.formatter import format_clamped\n\n"
            "def clamp_int(val: int, low: int, high: int) -> int:\n"
            '    """Placeholder: validate ints & bounds and clamp val to [low, high]."""\n'
            "    return 0\n\n"
            "def clamp_and_format(val: int, low: int, high: int) -> str:\n"
            '    """Placeholder: return format_clamped(clamp_int(val, low, high))."""\n'
            "    return ''\n",
            encoding="utf-8",
        )
        (self.project_dir / "docs" / "spec.md").write_text(
            "# Bounded Integer Clamp Specification\n\n"
            "## Required Scope Analysis YAML Manifest for `strategy_template.md`\n"
            "- `target_files`: `[\"src/clamp.py\"]`\n"
            "- `extra_editable_files`: `[\"src/bounds.py\", \"src/validators.py\", \"src/formatter.py\"]`\n"
            "- `test_files`: `[]`\n"
            "- `context_files_job`: `[\"docs/spec.md\", \"docs/architecture.md\", \"docs/formulas.md\"]`\n"
            "- `context_files_test`: `[\"docs/test_matrix.md\", \"docs/edge_cases.md\"]`\n\n"
            "## Module Specifications\n"
            "1. `src/validators.py` -> `ensure_int(val: int) -> int`:\n"
            "   - If `isinstance(val, bool)` or `not isinstance(val, int)`, raise `TypeError('not_int')`.\n"
            "   - Return `val`.\n"
            "2. `src/bounds.py` -> `validate_bounds(low: int, high: int) -> None`:\n"
            "   - Call `ensure_int(low)` and `ensure_int(high)`.\n"
            "   - If `low > high`, raise `ValueError('low_gt_high')`.\n"
            "3. `src/formatter.py` -> `format_clamped(val: int) -> str`:\n"
            "   - Return `f\"CLAMPED:{val}\"`.\n"
            "4. `src/clamp.py` -> `clamp_int(val: int, low: int, high: int) -> int` and `clamp_and_format(val: int, low: int, high: int) -> str`:\n"
            "   - `clamp_int`: call `ensure_int(val)` and `validate_bounds(low, high)`; clamp `val` to `[low, high]`.\n"
            "   - `clamp_and_format`: return `format_clamped(clamp_int(val, low, high))`.\n",
            encoding="utf-8",
        )
        (self.project_dir / "docs" / "architecture.md").write_text(
            "# Architecture Overview\n"
            "- Primary Anchor: `src/clamp.py`\n"
            "- Supporting Editable Modules: `src/bounds.py`, `src/validators.py`, `src/formatter.py`\n",
            encoding="utf-8",
        )
        (self.project_dir / "docs" / "formulas.md").write_text(
            "# Clamping Formula\n"
            "- `clamp(val, low, high) = max(low, min(val, high))` for `low <= high`.\n",
            encoding="utf-8",
        )
        (self.project_dir / "docs" / "test_matrix.md").write_text(
            "# Unit Test Matrix\n"
            "- Interior value: `clamp_int(5, 0, 10) == 5`\n"
            "- Lower bound: `clamp_int(-5, 0, 10) == 0`\n"
            "- Upper bound: `clamp_int(25, 0, 10) == 10`\n"
            "- Formatted output: `clamp_and_format(25, 0, 10) == 'CLAMPED:10'`\n",
            encoding="utf-8",
        )
        (self.project_dir / "docs" / "edge_cases.md").write_text(
            "# Edge Cases\n"
            "- `low > high`: `clamp_int(5, 10, 0)` raises `ValueError('low_gt_high')`.\n"
            "- Non-integer input: `clamp_int(True, 0, 10)` raises `TypeError('not_int')`.\n",
            encoding="utf-8",
        )
        (self.project_dir / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n',
            encoding="utf-8",
        )
        (self.project_dir / ".gitignore").write_text(
            ".aider_factory/\n.DS_Store\n.aider*\n",
            encoding="utf-8",
        )

        subprocess.run(["git", "add", "."], cwd=self.tmp_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial skeleton"], cwd=self.tmp_dir, check=True
        )

        # 2. Run real run_bootstrap() and verify .env_plan_do.yml + tests/ directory provisioning
        run_bootstrap(self.tmp_dir)

        chk_ignore = subprocess.run(
            ["git", "check-ignore", "-q", ".aider_factory/markdown/oracle_pre_plan/strategy_template.md"],
            cwd=self.tmp_dir,
        )
        self.assertEqual(
            chk_ignore.returncode,
            1,
            "strategy_template.md must NOT be git-ignored after run_bootstrap",
        )

        plan_do_path = self.project_dir / ".aider_factory" / ".env_plan_do.yml"
        self.assertTrue(
            plan_do_path.is_file(),
            ".aider_factory/.env_plan_do.yml must be provisioned by run_bootstrap",
        )
        self.assertTrue(
            (self.project_dir / "tests").is_dir(),
            "tests/ directory must be created by run_bootstrap",
        )

        # 3. Verify strategy_template.md starts unpopulated (`target_files: []`, `test_files: []`)
        strat_template_path = (
            self.project_dir
            / ".aider_factory"
            / "markdown"
            / "oracle_pre_plan"
            / "strategy_template.md"
        )
        self.assertTrue(strat_template_path.is_file())
        initial_extracted = _extract_files_from_plan(
            str(strat_template_path), self.tmp_dir
        )
        self.assertEqual(
            initial_extracted["target_files"],
            [],
            "strategy_template.md must start with empty target_files",
        )

        aiderignore_txt = (self.project_dir / ".aiderignore").read_text(encoding="utf-8")
        self.assertIn(
            "!.aider_factory/markdown/oracle_pre_plan/strategy_template.md",
            aiderignore_txt,
            ".aiderignore must un-ignore strategy_template.md",
        )

        # 4. Seed draft notes directly inside strategy_template.md while keeping YAML lists empty ([])
        #    so strategy_instruct_template.md remains untouched and Phase 1 edits strategy_template.md directly
        fence = "`" * 3
        strat_template_path.write_text(
            "# Strategy Template (Source of Truth)\n\n"
            "<!-- MANDATORY PHASE 1 PLANNING NOTE:\n"
            "In this Phase 1 planning session, the ONLY editable file in chat is `.aider_factory/markdown/oracle_pre_plan/strategy_template.md`.\n"
            "Do NOT output Task IDs targeting `src/clamp.py`, `src/bounds.py`, `src/validators.py`, or `src/formatter.py`.\n"
            "Output a single `[Task ID: 001]` with `- **Target File**: \".aider_factory/markdown/oracle_pre_plan/strategy_template.md\"` "
            "whose Syntax Example replaces the empty `files:` lists below with:\n"
            "  target_files: [\"src/clamp.py\"]\n"
            "  extra_editable_files: [\"src/bounds.py\", \"src/validators.py\", \"src/formatter.py\"]\n"
            "  test_files: []\n"
            "  context_files_job: [\"docs/spec.md\", \"docs/architecture.md\", \"docs/formulas.md\"]\n"
            "  context_files_test: [\"docs/test_matrix.md\", \"docs/edge_cases.md\"]\n"
            "and fills in Sections 1-5 from `docs/spec.md`, `docs/architecture.md`, and `docs/formulas.md`. -->\n\n"
            "## Scope Analysis\n"
            f"{fence}yaml\n"
            "files:\n"
            "  target_files: []          # Specify EXACTLY ONE existing primary anchor file (drives <stem> naming)\n"
            "  extra_editable_files: []  # Additional existing files to edit alongside the anchor file in this pass\n"
            "  test_files: []            # Leave empty ([]) to auto-assign unit test file via <stem>, or specify 1 test file\n"
            "  context_files_job: []     # Read-only reference files for implementation (Job 1 & Job 2)\n"
            "  context_files_test: []    # Read-only reference files for unit testing (Job 3 & Verify)\n"
            f"{fence}\n\n"
            "## 1. Scope\n"
            "- [Define implementation/refactoring scope and objectives]\n\n"
            "## 2. Definitions & Formulas\n"
            "- [Exact definitions, formulas, and domain rules with source citations]\n\n"
            "## 3. Inputs & Outputs\n"
            "- [Names, types, units, and valid ranges]\n\n"
            "## 4. Edge Cases & Constraints\n"
            "- [Boundary behavior and error handling expectations]\n\n"
            "## 5. Acceptance Criteria\n"
            "- [Concise, testable statements]\n",
            encoding="utf-8",
        )
        self.assertEqual(
            _extract_files_from_plan(str(strat_template_path), self.tmp_dir)["target_files"],
            [],
        )

        # Ensure live Oracle debate instructions converge to VERDICT: AGREE once tasks are specified
        for r_file in (
            "oracle_contract_audit_r1.md",
            "oracle_adversarial_hardening_r2.md",
        ):
            r_path = (
                self.project_dir
                / ".aider_factory"
                / "markdown"
                / "templates"
                / "debate_instruct"
                / r_file
            )
            if r_path.is_file():
                with open(r_path, "a", encoding="utf-8") as rf:
                    rf.write(
                        "\n\n## CONVERGENCE RULE\n"
                        "If the Architect's specification or the existing code already satisfies `docs/spec.md`, "
                        "you MUST conclude your response with `VERDICT: AGREE`.\n"
                    )

        # Make post_test_validation.md non-blocking for headless Phase 3 completion
        post_val_path = (
            self.project_dir
            / ".aider_factory"
            / "markdown"
            / "templates"
            / "post_test_validation.md"
        )
        with open(post_val_path, "w", encoding="utf-8") as f:
            f.write(
                "# Post-Test Validation & Review\n\n"
                "Review `src/clamp.py`, `src/bounds.py`, `src/validators.py`, `src/formatter.py`, `tests/test_clamp.py`, and `docs/spec.md`.\n"
                "If the implementation and unit tests already satisfy `docs/spec.md`, make no destructive changes and reply briefly confirming validation passed.\n"
            )

        # Track .gitignore in git (leave strategy_template.md untracked to prove Phase 1 Aider can add/edit it directly)
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=self.tmp_dir,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Track .gitignore"], cwd=self.tmp_dir, check=True
        )

        # 5. Configure .env_plan_do.yml with live models/endpoints and headless execution across all 3 phases
        with open(plan_do_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        cfg["working_directory"] = self.tmp_dir
        cfg["auto_lint"] = False
        py_exec = sys.executable.replace("\\", "/")
        cfg["test_runner"] = f'"{py_exec}" -m pytest {{file}}'
        cfg["test_naming_and_path"] = "tests/test_{stem}.py"
        cfg["phases"][1]["test_naming_and_path"] = "tests/test_{stem}.py"

        if self.live_cfg["architect_api_base"]:
            cfg["endpoints"]["architect_api_base"] = self.live_cfg["architect_api_base"]
            cfg["endpoints"]["editor_api"] = self.live_cfg["editor_api"]
            cfg["endpoints"]["editor_api_fallback"] = self.live_cfg["editor_api"]
            cfg["endpoints"]["rag_agent_api"] = self.live_cfg["rag_agent_api"]
            cfg["endpoints"]["weak_model_api_base"] = self.live_cfg[
                "weak_model_api_base"
            ]

        # Give Phase 1 the doc and source files so the Planning Architect can read them directly
        # without Aider interrupting Turn 1 to auto-add mentioned repo files
        cfg["phases"][0]["files"]["context_files_job"] = [
            "docs/spec.md",
            "docs/architecture.md",
            "docs/formulas.md",
            "docs/test_matrix.md",
            "docs/edge_cases.md",
            "src/clamp.py",
            "src/bounds.py",
            "src/validators.py",
            "src/formatter.py",
        ]
        cfg["phases"][0]["toggles"]["pair_programming"] = False
        cfg["phases"][0]["toggles"]["yes_always"] = True
        cfg["phases"][0]["toggles"]["auto_accept_architect"] = True
        cfg["phases"][0]["toggles"]["suggest_shell_commands"] = False

        # Keep 2 rounds of pre-edit debate before Job 2 and Job 3
        cfg["phases"][1]["oracle"]["pre_edit_debate"]["loops"] = 3
        cfg["phases"][1]["oracle"]["pre_edit_debate"]["rounds"] = 2
        cfg["phases"][1]["toggles"]["suggest_shell_commands"] = False
        cfg["phases"][1]["escalation_debate"]["loops"] = 0

        cfg["phases"][2]["toggles"]["pair_programming"] = False
        cfg["phases"][2]["toggles"]["yes_always"] = True
        cfg["phases"][2]["toggles"]["auto_accept_architect"] = True
        cfg["phases"][2]["toggles"]["suggest_shell_commands"] = False

        for p in cfg["phases"]:
            p["models"]["architect_agent"] = self.live_cfg["architect_agent"]
            p["models"]["editor_agent"] = self.live_cfg["editor_agent"]
            p["models"]["editor_agent_test"] = self.live_cfg["editor_agent"]
            p["models"]["editor_agent_test_fallback"] = self.live_cfg["editor_agent"]
            p["models"]["rag_agent"] = self.live_cfg["rag_agent"]
            p["models"]["weak_model"] = self.live_cfg["weak_model"]

        with open(plan_do_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        # 6. Execute the full 3-phase workflow via run_workflow.py
        env = os.environ.copy()
        for k in list(env.keys()):
            if k.startswith("AI_FACTORY_") or k.startswith("ORACLE_"):
                env.pop(k, None)
        env["PYTHONPATH"] = os.pathsep.join(
            [self.tmp_dir, repo_root, src_dir, pkg_dir, python_dir]
        )
        if self.live_cfg["architect_api_base"] and "OPENAI_API_KEY" not in env:
            env["OPENAI_API_KEY"] = os.environ.get("LITELLM_API_KEY", "sk-dummy")

        proc = subprocess.Popen(
            [sys.executable, RUN_WORKFLOW_PATH, "live_plan_do_sess", str(plan_do_path)],
            cwd=self.tmp_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output_lines = []
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            output_lines.append(line)
        proc.wait(timeout=1200)
        full_output = "".join(output_lines)

        self.assertEqual(
            proc.returncode,
            0,
            f"Live 3-phase workflow failed with rc={proc.returncode}.\nLast 80 lines of output:\n"
            + "".join(output_lines[-80:]),
        )

        # 7. Assert Phase 1 genuinely populated all 9 files across the 5 fields of strategy_template.md
        post_p1_extracted = _extract_files_from_plan(
            str(strat_template_path), self.tmp_dir
        )
        self.assertEqual(post_p1_extracted["target_files"], ["src/clamp.py"])
        self.assertEqual(
            set(post_p1_extracted["extra_editable_files"]),
            {"src/bounds.py", "src/validators.py", "src/formatter.py"},
        )
        self.assertEqual(post_p1_extracted["test_files"], [])
        self.assertTrue(
            {"docs/spec.md", "docs/architecture.md", "docs/formulas.md"}.issubset(
                set(post_p1_extracted["context_files_job"])
            )
        )
        self.assertTrue(
            {"docs/test_matrix.md", "docs/edge_cases.md"}.issubset(
                set(post_p1_extracted["context_files_test"])
            )
        )

        # 8. Assert rendered validate.md and testing templates were created with Phase 1's strategy content and net git diff injected
        rendered_val = (
            self.project_dir
            / ".aider_factory"
            / "sessions"
            / "live_plan_do_sess"
            / "templates"
            / "clamp_validate_rendered.md"
        )
        self.assertTrue(rendered_val.is_file(), "clamp_validate_rendered.md must exist")
        self.assertIn(
            "## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS",
            rendered_val.read_text(encoding="utf-8"),
        )

        rendered_test_exec = (
            self.project_dir
            / ".aider_factory"
            / "sessions"
            / "live_plan_do_sess"
            / "templates"
            / "clamp_testing_exec_rendered.md"
        )
        self.assertTrue(
            rendered_test_exec.is_file(), "clamp_testing_exec_rendered.md must exist"
        )
        test_exec_txt = rendered_test_exec.read_text(encoding="utf-8")
        self.assertIn(
            "## COMPLETED IMPLEMENTATION CONTEXT (READ-ONLY REFERENCE FOR TESTING)",
            test_exec_txt,
        )
        self.assertIn("<completed_strategy_specification>", test_exec_txt)
        self.assertIn("<implementation_git_diff>", test_exec_txt)
        self.assertIn("a/src/clamp.py", test_exec_txt)

        rendered_test_iter = (
            self.project_dir
            / ".aider_factory"
            / "sessions"
            / "live_plan_do_sess"
            / "templates"
            / "clamp_testing_iterate_rendered.md"
        )
        self.assertTrue(
            rendered_test_iter.is_file(), "clamp_testing_iterate_rendered.md must exist"
        )
        test_iter_txt = rendered_test_iter.read_text(encoding="utf-8")
        self.assertIn("<completed_strategy_specification>", test_iter_txt)
        self.assertNotIn("<implementation_git_diff>", test_iter_txt)

        # 9. Assert all 4 Pre-Edit Debate verdicts and ledgers exist (Job 2 R1/R2 & Job 3 R1/R2)
        debates_dir = self.project_dir / ".aider_factory" / "logs" / "debates"
        for v_file in (
            "clamp.job2_verdict_r1.md",
            "clamp.job2_verdict_r2.md",
            "clamp.job3_verdict_r1.md",
            "clamp.job3_verdict_r2.md",
        ):
            vp = debates_dir / v_file
            self.assertTrue(vp.is_file(), f"Missing debate verdict: {v_file}")
            v_text = vp.read_text(encoding="utf-8")
            self.assertIn("GATE: draft", v_text)
            self.assertIn("# Resolution", v_text)

        # 10. Assert <stem> unit test file tests/test_clamp.py was auto-assigned, created, and passes real pytest
        stem_test_file = self.project_dir / "tests" / "test_clamp.py"
        self.assertTrue(
            stem_test_file.is_file(),
            "Job 3 must create auto-named tests/test_clamp.py on disk",
        )

        pytest_res = subprocess.run(
            [sys.executable, "-m", "pytest", str(stem_test_file)],
            cwd=self.tmp_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            pytest_res.returncode,
            0,
            f"Standalone pytest on generated tests/test_clamp.py failed:\n{pytest_res.stdout}\n{pytest_res.stderr}",
        )

        # 11. Independently import and verify src/validators.py, src/bounds.py, src/formatter.py, and src/clamp.py
        for mod_name, rel_file in (
            ("src.validators", "src/validators.py"),
            ("src.bounds", "src/bounds.py"),
            ("src.formatter", "src/formatter.py"),
            ("src.clamp", "src/clamp.py"),
        ):
            spec_obj = importlib.util.spec_from_file_location(
                mod_name, str(self.project_dir / rel_file)
            )
            mod_obj = importlib.util.module_from_spec(spec_obj)
            sys.modules[mod_name] = mod_obj
            spec_obj.loader.exec_module(mod_obj)

        mod_clamp = sys.modules["src.clamp"]
        self.assertEqual(mod_clamp.clamp_int(5, 0, 10), 5)
        self.assertEqual(mod_clamp.clamp_int(-5, 0, 10), 0)
        self.assertEqual(mod_clamp.clamp_int(25, 0, 10), 10)
        self.assertEqual(mod_clamp.clamp_and_format(25, 0, 10), "CLAMPED:10")
        with self.assertRaises(ValueError):
            mod_clamp.clamp_int(5, 10, 0)
        with self.assertRaises(TypeError):
            mod_clamp.clamp_int(True, 0, 10)

        # 12. Verify Phase 3 ran and logged its task execution
        self.assertIn(
            "p2_job1_clamp",
            full_output,
            "Phase 3 post-test review task p2_job1_clamp must execute",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
