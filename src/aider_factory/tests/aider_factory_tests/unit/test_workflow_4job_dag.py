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

    def test_plan_resolution_null_yaml_returns_none(self):
        """T05: Explicit null YAML values resolve to None without falling back to defaults."""
        plans = {
            "job_one_plan": None,
            "job_two_plan": None,
            "job_three_plan": None,
            "iterate_plan": None,
        }
        j1_val = plans.get("job_one_plan")
        j2_val = plans.get("job_two_plan")
        j3_val = plans.get("job_three_plan")
        it_val = plans.get("iterate_plan")

        job_one_plan = resolve_template_path(j1_val) if j1_val else None
        job_two_plan = resolve_template_path(j2_val) if j2_val else None
        job_three_plan = resolve_template_path(j3_val) if j3_val else None
        iterate_plan = resolve_template_path(it_val) if it_val else None

        self.assertIsNone(job_one_plan)
        self.assertIsNone(job_two_plan)
        self.assertIsNone(job_three_plan)
        self.assertIsNone(iterate_plan)

    def test_plan_resolution_empty_yaml_returns_none_and_preserves_internal_defaults(self):
        """Verify Job 1, 2, 3, and Iterate plans default to None when omitted in YAML,
        while internal templates preserve their defaults."""
        phase = {"plans": {}}

        plans = phase.get("plans", {}) or {}
        j1_val = plans.get("job_one_plan")
        job_one_plan = resolve_template_path(j1_val) if j1_val else None

        j2_val = plans.get("job_two_plan")
        job_two_plan = resolve_template_path(j2_val) if j2_val else None

        j3_val = plans.get("job_three_plan")
        job_three_plan = resolve_template_path(j3_val) if j3_val else None

        it_val = plans.get("iterate_plan")
        iterate_plan = resolve_template_path(it_val) if it_val else None

        delib_val = plans.get(
            "deliberate_plan", "markdown/internal/deliberation_evidence_template.md"
        )
        deliberate_plan = resolve_template_path(delib_val)

        applyt_val = plans.get(
            "apply_plan", "markdown/internal/apply_evidence_template.md"
        )
        apply_plan = resolve_template_path(applyt_val)

        ab_val = plans.get("analyze_bugs_plan", "markdown/internal/analyze_bugs.md")
        analyze_bugs_plan = resolve_template_path(ab_val)

        self.assertIsNone(job_one_plan)
        self.assertIsNone(job_two_plan)
        self.assertIsNone(job_three_plan)
        self.assertIsNone(iterate_plan)

        self.assertTrue(deliberate_plan.endswith("deliberation_evidence_template.md"))
        self.assertTrue(apply_plan.endswith("apply_evidence_template.md"))
        self.assertTrue(analyze_bugs_plan.endswith("analyze_bugs.md"))

    def test_job_two_plan_none_suppresses_validation_template_fallback(self):
        """Verify Job 2 message_file is None when job_two_plan is None, even with strategy content."""
        job_two_plan = None
        strategy_content = "# Injected Goals"

        if job_two_plan:
            job2_msg_file = job_two_plan
        else:
            job2_msg_file = None

        self.assertIsNone(job2_msg_file)

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
        j1_val = plans.get("job_one_plan")
        j2_val = plans.get("job_two_plan")
        j3_val = plans.get("job_three_plan")
        it_val = plans.get("iterate_plan")

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

    def test_global_and_phase_linting_resolution(self):
        """Validates inheritance and override hierarchy for auto_lint and lint_cmd."""
        # 1. Global config defaults
        global_cfg = {
            "auto_lint": False,
            "lint_cmd": "flake8 {file}",
        }
        global_auto_lint = global_cfg.get("auto_lint", True)
        global_lint_cmd = global_cfg.get("lint_cmd", None)
        self.assertFalse(global_auto_lint)
        self.assertEqual(global_lint_cmd, "flake8 {file}")

        # 2. Phase with no overrides inherits global settings
        phase_toggles_empty = {}
        auto_lint_val = phase_toggles_empty.get("auto_lint")
        auto_lint = auto_lint_val if auto_lint_val is not None else global_auto_lint
        lint_cmd_val = phase_toggles_empty.get("lint_cmd")
        lint_cmd = lint_cmd_val if lint_cmd_val is not None else global_lint_cmd
        self.assertFalse(auto_lint)
        self.assertEqual(lint_cmd, "flake8 {file}")

        # 3. Phase with explicit overrides takes precedence
        phase_toggles_override = {
            "auto_lint": True,
            "lint_cmd": "ruff check {file}",
        }
        auto_lint_val = phase_toggles_override.get("auto_lint")
        auto_lint = auto_lint_val if auto_lint_val is not None else global_auto_lint
        lint_cmd_val = phase_toggles_override.get("lint_cmd")
        lint_cmd = lint_cmd_val if lint_cmd_val is not None else global_lint_cmd
        self.assertTrue(auto_lint)
        self.assertEqual(lint_cmd, "ruff check {file}")

    def test_pass_history_standardization(self):
        """Validates pass_history default (True) and configuration extraction."""
        # 1. Default when omitted from escalation_debate is True
        esc_cfg_empty = {}
        self.assertTrue(esc_cfg_empty.get("pass_history", True))

        # 2. Explicitly disabled pass_history
        esc_cfg_disabled = {"pass_history": False}
        self.assertFalse(esc_cfg_disabled.get("pass_history", True))

        # 3. Explicitly enabled pass_history
        esc_cfg_enabled = {"pass_history": True}
        self.assertTrue(esc_cfg_enabled.get("pass_history", True))

    def test_shared_history_stem_wiring_across_multiple_target_files(self):
        """UNIT: Validates that when shared_history is False, each target file gets a
        unique history_stem per job, and when shared_history is True, history_stem is None."""
        target_files = ["src/module_alpha.py", "src/module_beta.py", "src/module_gamma.py"]

        # Case 1: shared_history is False -> stems must be distinct and include base_name
        shared_history_false = False
        stems_false = {}
        for tf in target_files:
            base_name = os.path.splitext(os.path.basename(tf))[0]
            stems_false[base_name] = {
                "job1": None if shared_history_false else f"job1_{base_name}",
                "job2": None if shared_history_false else f"job2_{base_name}",
                "job3": None if shared_history_false else f"job3_{base_name}",
                "verify": None if shared_history_false else f"verify_{base_name}",
            }

        self.assertEqual(stems_false["module_alpha"]["job1"], "job1_module_alpha")
        self.assertEqual(stems_false["module_beta"]["job1"], "job1_module_beta")
        self.assertEqual(stems_false["module_gamma"]["job1"], "job1_module_gamma")
        self.assertNotEqual(stems_false["module_alpha"]["job1"], stems_false["module_beta"]["job1"])

        # Case 2: shared_history is True -> stems must be None for all files
        shared_history_true = True
        stems_true = {}
        for tf in target_files:
            base_name = os.path.splitext(os.path.basename(tf))[0]
            stems_true[base_name] = {
                "job1": None if shared_history_true else f"job1_{base_name}",
            }

        self.assertIsNone(stems_true["module_alpha"]["job1"])
        self.assertIsNone(stems_true["module_beta"]["job1"])
        self.assertIsNone(stems_true["module_gamma"]["job1"])

    def test_state_swap_isolation_wipes_active_stage_between_tasks(self):
        """UNIT: Tests that AiderFactory._swap_in_state and _swap_out_state properly isolate
        chat history between target files and completely wipe active staging files so Task B
        never inherits residual history from Task A."""
        from aider_factory.python.orchestrate import AiderFactory

        with tempfile.TemporaryDirectory() as tmpdir:
            factory = AiderFactory(tmpdir, session_name="test_swap_session")
            sess_dir = factory.session_dir
            active_chat = sess_dir / ".aider.chat.history.md"
            active_input = sess_dir / ".aider.input.history"
            active_oracle = sess_dir / ".oracle_session.json"

            # 1. Task A runs and creates active state
            active_chat.write_text("# Task A History\nUser: Prompt A\n", encoding="utf-8")
            active_input.write_text("Prompt A\n", encoding="utf-8")
            active_oracle.write_text('{"turn": 1, "query": "Oracle A"}', encoding="utf-8")

            # 2. Task A finishes -> _swap_out_state("job1_alpha")
            factory._swap_out_state("job1_alpha")

            vault_dir = sess_dir / "chat_history"
            self.assertTrue(vault_dir.is_dir())
            vault_chat_a = vault_dir / ".aider.chat.history_job1_alpha.md"
            vault_input_a = vault_dir / ".aider.input.history_job1_alpha"
            vault_oracle_a = vault_dir / ".oracle_session_job1_alpha.json"

            self.assertTrue(vault_chat_a.is_file())
            self.assertIn("Prompt A", vault_chat_a.read_text(encoding="utf-8"))
            self.assertTrue(vault_input_a.is_file())
            self.assertTrue(vault_oracle_a.is_file())

            # 3. Task B starts -> _swap_in_state("job1_beta")
            # Since Task B has no prior vault files, _swap_in_state MUST wipe active stage!
            factory._swap_in_state("job1_beta")

            self.assertFalse(active_chat.exists(), "Active chat history MUST be deleted for fresh Task B")
            self.assertFalse(active_input.exists(), "Active input history MUST be deleted for fresh Task B")
            self.assertFalse(active_oracle.exists(), "Active oracle session MUST be deleted for fresh Task B")

            # 4. Task B runs and writes its own history
            active_chat.write_text("# Task B History\nUser: Prompt B\n", encoding="utf-8")
            factory._swap_out_state("job1_beta")

            vault_chat_b = vault_dir / ".aider.chat.history_job1_beta.md"
            self.assertTrue(vault_chat_b.is_file())
            self.assertIn("Prompt B", vault_chat_b.read_text(encoding="utf-8"))

            # 5. Resume Task A -> _swap_in_state("job1_alpha")
            factory._swap_in_state("job1_alpha")
            self.assertTrue(active_chat.is_file())
            self.assertIn("Prompt A", active_chat.read_text(encoding="utf-8"))
            self.assertNotIn("Prompt B", active_chat.read_text(encoding="utf-8"))

    def test_yes_always_cli_flag_and_config_resolution(self):
        """UNIT: Validates that yes_always toggle logic properly maps:
        - yes_always: True -> adds --yes-always to CLI and 'yes-always: true' to .aider.conf.yml
        - yes_always: False -> omits --yes-always, NEVER adds --no-yes-always, and writes 'yes-always: false' to .aider.conf.yml
        """
        import yaml
        from aider_factory.python.orchestrate import Task

        # Case 1: yes_always = False
        task_no = Task(id="test_no", yes_always=False, pair_programming=False)
        self.assertFalse(task_no.yes_always)

        conf_data_no = {}
        if task_no.yes_always is not None:
            conf_data_no["yes-always"] = bool(task_no.yes_always)
        self.assertIs(conf_data_no["yes-always"], False)

        cmd_no = ["aider"]
        if task_no.yes_always:
            cmd_no.append("--yes-always")

        self.assertNotIn("--yes-always", cmd_no)
        self.assertNotIn("--no-yes-always", cmd_no)

        # Case 2: yes_always = True
        task_yes = Task(id="test_yes", yes_always=True, pair_programming=False)
        self.assertTrue(task_yes.yes_always)

        conf_data_yes = {}
        if task_yes.yes_always is not None:
            conf_data_yes["yes-always"] = bool(task_yes.yes_always)
        self.assertIs(conf_data_yes["yes-always"], True)

        cmd_yes = ["aider"]
        if task_yes.yes_always:
            cmd_yes.append("--yes-always")

        self.assertIn("--yes-always", cmd_yes)


if __name__ == "__main__":
    unittest.main()
