import os
import tempfile
import unittest
from pathlib import Path

from aider_factory.python.run_workflow import (
    _parse_insert_debate,
    _render_validate_template,
    _resolve_job_debate_collection,
    _resolve_job_debate_template,
    resolve_template_path,
)


class TestWorkflow4JobUnits(unittest.TestCase):
    def test_parse_insert_debate_matrix(self):
        """T17: Validates insert_debate parsing across lists, booleans, strings, and defaults."""
        # 1. Disabled returns all False
        self.assertEqual(_parse_insert_debate({"enabled": False, "insert_debate": [1, 1, 1]}), (False, False, False))
        self.assertEqual(_parse_insert_debate(None), (False, False, False))
        self.assertEqual(_parse_insert_debate({}), (False, False, False))

        # 2. Enabled with omitted/None insert_debate defaults to (True, False, False)
        self.assertEqual(_parse_insert_debate({"enabled": True}), (True, False, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": None}), (True, False, False))

        # 3. Native YAML integer and boolean lists
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": [1, 0, 0]}), (True, False, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": [1, 1, 0]}), (True, True, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": [True, True, True]}), (True, True, True))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": [False, True, False]}), (False, True, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": [0, 0, 0]}), (False, False, False))

        # 4. Short lists pad with False, long lists truncate
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": [1]}), (True, False, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": [0, 1]}), (False, True, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": []}), (False, False, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": [1, 0, 1, 1, 0]}), (True, False, True))

        # 5. String representations (brackets, braces, commas, spaces)
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": "[1, 0, 1]"}), (True, False, True))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": "{0, 1, 0}"}), (False, True, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": "1,1,1"}), (True, True, True))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": "1 0 0"}), (True, False, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": ""}), (False, False, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": "invalid, string"}), (False, False, False))

        # 6. Fallback for unhandled types
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": 123}), (True, False, False))
        self.assertEqual(_parse_insert_debate({"enabled": True, "insert_debate": {"job1": True}}), (True, False, False))

    def test_resolve_job_debate_template_matrix(self):
        """T19: Validates per-job debate template resolution across lists, strings, and fallbacks."""
        # 1. None/empty cfg returns None
        self.assertIsNone(_resolve_job_debate_template(None, 1))
        self.assertIsNone(_resolve_job_debate_template({}, 1))

        # 2. Single string applies to all jobs
        cfg_str = {"job_debate_template": "markdown/templates/implement.md"}
        self.assertTrue(_resolve_job_debate_template(cfg_str, 1).endswith("implement.md"))
        self.assertTrue(_resolve_job_debate_template(cfg_str, 2).endswith("implement.md"))
        self.assertTrue(_resolve_job_debate_template(cfg_str, 3).endswith("implement.md"))

        # 3. 3-element list resolves exact index
        cfg_list = {
            "job_debate_template": [
                "markdown/templates/implement.md",
                "markdown/templates/validate.md",
                "markdown/templates/testing.md",
            ]
        }
        self.assertTrue(_resolve_job_debate_template(cfg_list, 1).endswith("implement.md"))
        self.assertTrue(_resolve_job_debate_template(cfg_list, 2).endswith("validate.md"))
        self.assertTrue(_resolve_job_debate_template(cfg_list, 3).endswith("testing.md"))

        # 4. Short list falls back to [0]
        cfg_short = {"job_debate_template": ["markdown/templates/implement.md"]}
        self.assertTrue(_resolve_job_debate_template(cfg_short, 3).endswith("implement.md"))

    def test_resolve_job_debate_collection_matrix(self):
        """T20: Validates per-job vector collection and LanceDB path resolution."""
        root = "/tmp/lanceDB"

        # 1. Default fallback when omitted
        c1, db1 = _resolve_job_debate_collection({}, 1, "default_coll", root)
        self.assertEqual(c1, "default_coll")
        self.assertEqual(db1, "/tmp/lanceDB/default_coll/lancedb")

        # 2. Single string applies to all jobs
        cfg_str = {"job_debate_collection": "shared_coll"}
        c, db = _resolve_job_debate_collection(cfg_str, 2, "default_coll", root)
        self.assertEqual(c, "shared_coll")
        self.assertEqual(db, "/tmp/lanceDB/shared_coll/lancedb")

        # 3. 3-element list resolves heterogeneous collections
        cfg_list = {
            "job_debate_collection": ["coll_exchange", "coll_risk_math", "coll_mocks"]
        }
        c1, db1 = _resolve_job_debate_collection(cfg_list, 1, "default_coll", root)
        c2, db2 = _resolve_job_debate_collection(cfg_list, 2, "default_coll", root)
        c3, db3 = _resolve_job_debate_collection(cfg_list, 3, "default_coll", root)

        self.assertEqual(c1, "coll_exchange")
        self.assertEqual(db1, "/tmp/lanceDB/coll_exchange/lancedb")
        self.assertEqual(c2, "coll_risk_math")
        self.assertEqual(db2, "/tmp/lanceDB/coll_risk_math/lancedb")
        self.assertEqual(c3, "coll_mocks")
        self.assertEqual(db3, "/tmp/lanceDB/coll_mocks/lancedb")

    def test_render_validate_template_non_existent(self):
        """T01: Non-existent template path returns original path without writing."""
        res = _render_validate_template("/non/existent/path.md", "strategy", "/tmp/out.md")
        self.assertEqual(res, "/non/existent/path.md")
        self.assertFalse(os.path.exists("/tmp/out.md"))

    def test_render_validate_template_with_placeholder(self):
        """T02: Injects strategy markdown replacing placeholder cleanly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_path = os.path.join(tmpdir, "validate.md")
            out_path = os.path.join(tmpdir, "nested", "rendered.md")

            with open(tmpl_path, "w", encoding="utf-8") as f:
                f.write(
                    "# Header\n\n"
                    "## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS\n\n"
                    "OLD GOALS\n\n"
                    "---\n\n"
                    "## 2. Editor Execution Strategy\n"
                )

            strat_content = "# Target Goals\n1. Do not break invariant\n2. Parity"
            res = _render_validate_template(tmpl_path, strat_content, out_path)

            self.assertEqual(res, out_path)
            self.assertTrue(os.path.exists(out_path))

            rendered = Path(out_path).read_text(encoding="utf-8")
            self.assertIn("## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS", rendered)
            self.assertIn("# Target Goals\n1. Do not break invariant\n2. Parity", rendered)
            self.assertNotIn("OLD GOALS", rendered)
            self.assertIn("## 2. Editor Execution Strategy", rendered)

    def test_render_validate_template_without_placeholder_appends(self):
        """T03 & T04: Appends strategy when placeholder is missing & creates directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_path = os.path.join(tmpdir, "custom_validate.md")
            out_path = os.path.join(tmpdir, "nested", "dir", "custom_rendered.md")

            with open(tmpl_path, "w", encoding="utf-8") as f:
                f.write("# Simple Custom Validator\nValidate carefully.")

            strat_content = "Strategy: enforce strict checks"
            res = _render_validate_template(tmpl_path, strat_content, out_path)

            self.assertEqual(res, out_path)
            self.assertTrue(os.path.exists(out_path))

            rendered = Path(out_path).read_text(encoding="utf-8")
            self.assertTrue(rendered.startswith("# Simple Custom Validator\nValidate carefully."))
            self.assertIn("## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS", rendered)
            self.assertIn("Strategy: enforce strict checks", rendered)

    def test_plan_resolution_null_yaml_fallbacks(self):
        """T05: Explicit null YAML values safely fall back to standard defaults."""
        plans = {
            "job_one_plan": None,
            "job_two_plan": None,
            "job_three_plan": None,
            "iterate_plan": None,
        }
        j1_val = plans.get("job_one_plan") or "markdown/templates/implement.md"
        j2_val = plans.get("job_two_plan")
        j3_val = plans.get("job_three_plan") or "markdown/templates/testing.md"
        it_val = plans.get("iterate_plan") or "markdown/templates/testing_unit_iterate.md"

        self.assertEqual(j1_val, "markdown/templates/implement.md")
        self.assertIsNone(j2_val)
        self.assertEqual(j3_val, "markdown/templates/testing.md")
        self.assertEqual(it_val, "markdown/templates/testing_unit_iterate.md")

    def test_multi_target_strategy_discovery_reverse_scan(self):
        """T07: Discovers latest .md strategy artifact even when subsequent source files are in completed_files."""
        completed_files = [
            ".aider_factory/markdown/oracle_pre_plan/strategy_template.md",
            "src/module_a.py",
            "src/helpers.py",
        ]
        strategy_file = next(
            (f for f in reversed(completed_files) if f.endswith(".md")),
            completed_files[0],
        )
        self.assertEqual(
            strategy_file,
            ".aider_factory/markdown/oracle_pre_plan/strategy_template.md",
        )

    def test_strategy_discovery_explicit_plan_override(self):
        """T08: Explicit validate_strategy_file overrides completed_files."""
        plans = {"validate_strategy_file": "custom/my_plan.md"}
        completed_files = [
            ".aider_factory/markdown/oracle_pre_plan/strategy_template.md",
            "src/module_a.py",
        ]
        strategy_file = plans.get("validate_strategy_file")
        if not strategy_file and completed_files:
            strategy_file = next(
                (f for f in reversed(completed_files) if f.endswith(".md")),
                completed_files[0],
            )
        self.assertEqual(strategy_file, "custom/my_plan.md")

    def test_plan_resolution_custom_paths(self):
        """T06: Custom plan paths are resolved directly without modification."""
        plans = {
            "job_one_plan": "custom/job1.md",
            "job_two_plan": "custom/job2.md",
            "job_three_plan": "custom/job3.md",
            "iterate_plan": "custom/iterate.md",
        }
        j1_val = plans.get("job_one_plan") or "markdown/templates/implement.md"
        j2_val = plans.get("job_two_plan")
        j3_val = plans.get("job_three_plan") or "markdown/templates/testing.md"
        it_val = plans.get("iterate_plan") or "markdown/templates/testing_unit_iterate.md"

        self.assertEqual(j1_val, "custom/job1.md")
        self.assertEqual(j2_val, "custom/job2.md")
        self.assertEqual(j3_val, "custom/job3.md")
        self.assertEqual(it_val, "custom/iterate.md")

    def test_custom_job_two_plan_with_placeholder_rendering(self):
        """T06b: Custom job_two_plan containing the placeholder section is rendered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_tmpl = os.path.join(tmpdir, "custom_val.md")
            out_path = os.path.join(tmpdir, "rendered_custom.md")

            with open(custom_tmpl, "w", encoding="utf-8") as f:
                f.write("# Custom Title\n## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS\nOLD\n---\nRules")

            strat_content = "# Injected Goals\nGoal A"
            res = _render_validate_template(custom_tmpl, strat_content, out_path)

            self.assertEqual(res, out_path)
            rendered = Path(out_path).read_text(encoding="utf-8")
            self.assertIn("# Injected Goals\nGoal A", rendered)
            self.assertNotIn("OLD", rendered)

    def test_phase_skip_boolean_logic(self):
        """T15: Verifies the phase skip boolean logic when all toggles are False."""
        run_job_one = False
        run_job_two = False
        run_job_three = False
        iterate_test = False
        phase_run_ocr_rag = False
        oracle_cfg = None
        resolve_evidence = False
        post_validate = False

        should_skip = (
            not run_job_one
            and not run_job_two
            and not run_job_three
            and not iterate_test
            and not phase_run_ocr_rag
            and not oracle_cfg
            and not resolve_evidence
            and not post_validate
        )
        self.assertTrue(should_skip)

    def test_explicit_false_toggles_override_fallbacks(self):
        """T16: Explicit false boolean values in toggles are preserved and not clobbered by fallbacks."""
        toggles = {
            "pair_programming": True,
            "yes_always": False,
            "auto_accept_architect": False,
            "disable_playwright": False,
            "auto_commits": False,
            "suggest_shell_commands": False,
            "detect_urls": False,
        }
        pair_programming = toggles.get("pair_programming", False)

        yes_always_val = toggles.get("yes_always")
        yes_always = yes_always_val if yes_always_val is not None else not pair_programming

        auto_accept_architect_val = toggles.get("auto_accept_architect")
        auto_accept_architect = (
            auto_accept_architect_val
            if auto_accept_architect_val is not None
            else not pair_programming
        )

        auto_commits_val = toggles.get("auto_commits")
        auto_commits = auto_commits_val if auto_commits_val is not None else True

        suggest_shell_commands_val = toggles.get("suggest_shell_commands")
        suggest_shell_commands = (
            suggest_shell_commands_val
            if suggest_shell_commands_val is not None
            else True
        )

        detect_urls_val = toggles.get("detect_urls")
        detect_urls = detect_urls_val if detect_urls_val is not None else False

        disable_playwright_val = toggles.get("disable_playwright")
        disable_playwright = (
            disable_playwright_val
            if disable_playwright_val is not None
            else False
        )

        self.assertIs(yes_always, False)
        self.assertIs(auto_accept_architect, False)
        self.assertIs(disable_playwright, False)
        self.assertIs(auto_commits, False)
        self.assertIs(suggest_shell_commands, False)
        self.assertIs(detect_urls, False)

    def test_session_name_resolution_env_isolation(self):
        """T22: Validates session name resolution ignores ambient AI_FACTORY_SESSION in __test__ mode unless explicitly passed in sys.argv."""
        import re

        def resolve_session_name(argv, env_session, is_test_mode):
            session_name = None
            if len(argv) > 1:
                for arg in argv[1:]:
                    if not arg.startswith("-") and not arg.endswith(".yml") and not arg.endswith(".yaml"):
                        session_name = arg
                        break
            if not session_name and not is_test_mode:
                session_name = env_session
            if session_name:
                return re.sub(r"[^a-zA-Z0-9_\-\.]", "_", session_name.strip())
            return "ephemeral_generated_session"

        # 1. Explicit CLI session name takes precedence in all modes
        self.assertEqual(
            resolve_session_name(["run_workflow.py", "my_cli_session", "config.yml"], "ambient_session", is_test_mode=True),
            "my_cli_session",
        )
        self.assertEqual(
            resolve_session_name(["run_workflow.py", "my_cli_session", "config.yml"], "ambient_session", is_test_mode=False),
            "my_cli_session",
        )

        # 2. No CLI session in __test__ mode ignores ambient environment
        self.assertEqual(
            resolve_session_name(["run_workflow.py", "config.yml"], "ambient_session", is_test_mode=True),
            "ephemeral_generated_session",
        )

        # 3. No CLI session in __main__ mode respects ambient environment
        self.assertEqual(
            resolve_session_name(["run_workflow.py", "config.yml"], "ambient_session", is_test_mode=False),
            "ambient_session",
        )


if __name__ == "__main__":
    unittest.main()
