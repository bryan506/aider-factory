import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from aider_factory.python.orchestrate import AiderFactory, Task, TaskStatus
from aider_factory.python.run_workflow import _render_validate_template, resolve_template_path


class TestE2E4JobPipeline(unittest.TestCase):
    def test_full_4stage_pipeline_dag_construction(self):
        """T10, T12, T14: Real on-disk verification of 4-stage DAG, sticky context, and escalation apply file permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            src_dir = proj / "src"
            tests_dir = proj / "tests"
            strat_dir = proj / ".aider_factory" / "markdown" / "oracle_pre_plan"
            sess_dir = proj / ".aider_factory" / "sessions" / "test_session"

            src_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)
            strat_dir.mkdir(parents=True)
            sess_dir.mkdir(parents=True)

            mod_a = src_dir / "mod_a.py"
            mod_b = src_dir / "mod_b.py"
            helpers = src_dir / "helpers.py"
            test_a = tests_dir / "test_mod_a.py"
            test_b = tests_dir / "test_mod_b.py"
            strat_file = strat_dir / "strategy_template.md"

            mod_a.write_text("def fn_a(): return 1\n", encoding="utf-8")
            mod_b.write_text("def fn_b(): return 2\n", encoding="utf-8")
            helpers.write_text("def helper(): pass\n", encoding="utf-8")
            test_a.write_text("def test_a(): assert True\n", encoding="utf-8")
            test_b.write_text("def test_b(): assert True\n", encoding="utf-8")
            strat_file.write_text("# Phase 0 Strategy Spec\nImplement fn_a and fn_b with parity.\n", encoding="utf-8")

            # Mock package validate template inside the fixture
            val_tmpl = proj / "validate_template.md"
            val_tmpl.write_text(
                "# Validator\n## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS\nOLD\n---\nCheck code.\n",
                encoding="utf-8",
            )

            factory = AiderFactory(project_dir=str(proj), session_name="test_session", session_dir=str(sess_dir))

            # Simulate Phase 0 completion
            completed_files = [str(strat_file.relative_to(proj))]

            # Build Phase 1 DAG Tasks manually following run_workflow logic
            env_prefix = "phase1"
            target_files = [str(mod_a.relative_to(proj)), str(mod_b.relative_to(proj))]
            extra_editable = [str(helpers.relative_to(proj))]
            sticky_context = True
            run_job_one = True
            run_job_two = True
            run_job_three = True
            iterate_test = True
            escalate = True

            for current_file in target_files:
                base_name = Path(current_file).stem
                specific_test_file = f"tests/test_{base_name}.py"
                last_task_for_file = None

                # Job 1
                if run_job_one:
                    j1_id = f"{env_prefix}_job1_{base_name}"
                    j1_reads = [current_file] + (completed_files if sticky_context else [])
                    factory.add_task(
                        Task(
                            id=j1_id,
                            message_file="implement.md",
                            read_files=j1_reads,
                            files=[current_file] + extra_editable,
                        )
                    )
                    last_task_for_file = j1_id

                # Job 2 (Validate)
                if run_job_two:
                    j2_id = f"{env_prefix}_job2_{base_name}"
                    strategy_file = next(
                        (f for f in reversed(completed_files) if f.endswith(".md")),
                        completed_files[0],
                    )
                    strat_content = Path(proj / strategy_file).read_text(encoding="utf-8")
                    rendered_val = sess_dir / "templates" / f"{base_name}_validate_rendered.md"
                    rendered_val_path = _render_validate_template(str(val_tmpl), strat_content, str(rendered_val))

                    j2_reads = [current_file] + (completed_files if sticky_context else [])
                    factory.add_task(
                        Task(
                            id=j2_id,
                            depends_on=[last_task_for_file],
                            message_file=rendered_val_path,
                            read_files=j2_reads,
                            files=[current_file] + extra_editable,
                        )
                    )
                    last_task_for_file = j2_id

                # Job 3 (Write Tests)
                if run_job_three:
                    j3_id = f"{env_prefix}_job3_{base_name}"
                    j3_reads = [current_file] + (completed_files if sticky_context else [])
                    factory.add_task(
                        Task(
                            id=j3_id,
                            depends_on=[last_task_for_file],
                            message_file="testing.md",
                            read_files=j3_reads,
                            files=[specific_test_file, current_file] + extra_editable,
                        )
                    )
                    last_task_for_file = j3_id

                # Job 4 (Verify / Iterate Tests)
                if iterate_test:
                    v_id = f"{env_prefix}_verify_{base_name}"
                    factory.add_task(
                        Task(
                            id=v_id,
                            depends_on=[last_task_for_file],
                            test_cmd=f"pytest {specific_test_file}",
                            iterate_test=True,
                            files=[specific_test_file, current_file] + extra_editable,
                        )
                    )
                    last_task_for_file = v_id

                # Escalation Apply Task
                if escalate:
                    apply_id = f"{env_prefix}_apply_{base_name}"
                    apply_files = [specific_test_file, current_file] + extra_editable
                    factory.add_task(
                        Task(
                            id=apply_id,
                            depends_on=[last_task_for_file],
                            files=apply_files,
                            iterate_test=True,
                        )
                    )

                if current_file not in completed_files:
                    completed_files.append(current_file)

            # Assertions on generated graph structure
            # 1. Total tasks: 5 tasks per target file * 2 target files = 10 tasks
            self.assertEqual(len(factory.tasks), 10)

            # 2. Dependency chaining check for mod_a
            self.assertIn("phase1_job1_mod_a", factory.tasks)
            self.assertIn("phase1_job2_mod_a", factory.tasks)
            self.assertIn("phase1_job3_mod_a", factory.tasks)
            self.assertIn("phase1_verify_mod_a", factory.tasks)
            self.assertIn("phase1_apply_mod_a", factory.tasks)

            self.assertEqual(factory.tasks["phase1_job2_mod_a"].depends_on, ["phase1_job1_mod_a"])
            self.assertEqual(factory.tasks["phase1_job3_mod_a"].depends_on, ["phase1_job2_mod_a"])
            self.assertEqual(factory.tasks["phase1_verify_mod_a"].depends_on, ["phase1_job3_mod_a"])
            self.assertEqual(factory.tasks["phase1_apply_mod_a"].depends_on, ["phase1_verify_mod_a"])

            # 3. Context stickiness parity across Job 1, Job 2, and Job 3
            expected_strat = str(strat_file.relative_to(proj))
            self.assertIn(expected_strat, factory.tasks["phase1_job1_mod_a"].read_files)
            self.assertIn(expected_strat, factory.tasks["phase1_job2_mod_a"].read_files)
            self.assertIn(expected_strat, factory.tasks["phase1_job3_mod_a"].read_files)
            self.assertIn(expected_strat, factory.tasks["phase1_job2_mod_b"].read_files)

            # 4. Injected validate template verification for mod_b (multi-target discovery)
            mod_b_val_rendered = Path(factory.tasks["phase1_job2_mod_b"].message_file)
            self.assertTrue(mod_b_val_rendered.exists())
            rendered_content = mod_b_val_rendered.read_text(encoding="utf-8")
            self.assertIn("Implement fn_a and fn_b with parity.", rendered_content)
            self.assertNotIn("def fn_a():", rendered_content)  # Proves mod_a code did not poison mod_b

            # 5. Escalation apply file permissions include test file
            self.assertIn("tests/test_mod_a.py", factory.tasks["phase1_apply_mod_a"].files)
            self.assertIn("src/mod_a.py", factory.tasks["phase1_apply_mod_a"].files)
            self.assertIn("src/helpers.py", factory.tasks["phase1_apply_mod_a"].files)

    def test_selective_toggles_skip_job2(self):
        """T11: Disabling Job 2 chains Job 1 directly to Job 3 without creating Job 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            src_dir = proj / "src"
            tests_dir = proj / "tests"
            sess_dir = proj / ".aider_factory" / "sessions" / "test_session_skip2"
            src_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)
            sess_dir.mkdir(parents=True)

            mod_a = src_dir / "mod_a.py"
            mod_a.write_text("def fn(): pass\n", encoding="utf-8")

            factory = AiderFactory(project_dir=str(proj), session_name="test_session_skip2", session_dir=str(sess_dir))

            env_prefix = "p1"
            base_name = "mod_a"
            current_file = str(mod_a.relative_to(proj))
            specific_test_file = "tests/test_mod_a.py"

            run_job_one = True
            run_job_two = False
            run_job_three = True
            iterate_test = True

            last_task = None
            if run_job_one:
                j1_id = f"{env_prefix}_job1_{base_name}"
                factory.add_task(Task(id=j1_id, files=[current_file]))
                last_task = j1_id

            if run_job_two:
                j2_id = f"{env_prefix}_job2_{base_name}"
                factory.add_task(Task(id=j2_id, depends_on=[last_task], files=[current_file]))
                last_task = j2_id

            if run_job_three:
                j3_id = f"{env_prefix}_job3_{base_name}"
                factory.add_task(Task(id=j3_id, depends_on=[last_task], files=[specific_test_file, current_file]))
                last_task = j3_id

            if iterate_test:
                v_id = f"{env_prefix}_verify_{base_name}"
                factory.add_task(Task(id=v_id, depends_on=[last_task], files=[specific_test_file, current_file]))

            self.assertIn("p1_job1_mod_a", factory.tasks)
            self.assertNotIn("p1_job2_mod_a", factory.tasks)
            self.assertIn("p1_job3_mod_a", factory.tasks)
            self.assertIn("p1_verify_mod_a", factory.tasks)

            self.assertEqual(factory.tasks["p1_job3_mod_a"].depends_on, ["p1_job1_mod_a"])
            self.assertEqual(factory.tasks["p1_verify_mod_a"].depends_on, ["p1_job3_mod_a"])

    def test_selective_toggles_skip_job3_straight_to_verify(self):
        """T11b: Disabling Job 3 with iterate_test=True chains Job 2 directly to verify."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            src_dir = proj / "src"
            sess_dir = proj / ".aider_factory" / "sessions" / "test_session_skip3"
            src_dir.mkdir(parents=True)
            sess_dir.mkdir(parents=True)

            mod_a = src_dir / "mod_a.py"
            mod_a.write_text("def fn(): pass\n", encoding="utf-8")

            factory = AiderFactory(project_dir=str(proj), session_name="test_session_skip3", session_dir=str(sess_dir))

            env_prefix = "p1"
            base_name = "mod_a"
            current_file = str(mod_a.relative_to(proj))
            specific_test_file = "tests/test_mod_a.py"

            run_job_one = True
            run_job_two = True
            run_job_three = False
            iterate_test = True

            last_task = None
            if run_job_one:
                j1_id = f"{env_prefix}_job1_{base_name}"
                factory.add_task(Task(id=j1_id, files=[current_file]))
                last_task = j1_id

            if run_job_two:
                j2_id = f"{env_prefix}_job2_{base_name}"
                factory.add_task(Task(id=j2_id, depends_on=[last_task], files=[current_file]))
                last_task = j2_id

            if run_job_three or iterate_test:
                job3_depends = [last_task] if last_task else []
                if run_job_three:
                    j3_id = f"{env_prefix}_job3_{base_name}"
                    factory.add_task(Task(id=j3_id, depends_on=job3_depends, files=[specific_test_file, current_file]))
                    last_task = j3_id
                    job3_depends = [j3_id]

                if iterate_test:
                    v_id = f"{env_prefix}_verify_{base_name}"
                    factory.add_task(Task(id=v_id, depends_on=job3_depends, files=[specific_test_file, current_file]))

            self.assertIn("p1_job1_mod_a", factory.tasks)
            self.assertIn("p1_job2_mod_a", factory.tasks)
            self.assertNotIn("p1_job3_mod_a", factory.tasks)
            self.assertIn("p1_verify_mod_a", factory.tasks)

            self.assertEqual(factory.tasks["p1_verify_mod_a"].depends_on, ["p1_job2_mod_a"])

    def test_inter_job_pre_edit_debates_multiround(self):
        """T13: Pre-edit debate tasks generate 2 rounds with prior-ledger chaining before Job 1, Job 2, and Job 3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            src_dir = proj / "src"
            tests_dir = proj / "tests"
            ddir = proj / ".aider_factory" / "logs" / "debates"
            sess_dir = proj / ".aider_factory" / "sessions" / "test_session_debates"

            src_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)
            ddir.mkdir(parents=True)
            sess_dir.mkdir(parents=True)

            mod_a = src_dir / "mod_a.py"
            test_a = tests_dir / "test_mod_a.py"
            mod_a.write_text("def fn(): pass\n", encoding="utf-8")
            test_a.write_text("def test_fn(): pass\n", encoding="utf-8")

            factory = AiderFactory(project_dir=str(proj), session_name="test_session_debates", session_dir=str(sess_dir))

            env_prefix = "p1"
            base_name = "mod_a"
            current_file = str(mod_a.relative_to(proj))
            specific_test_file = str(test_a.relative_to(proj))
            debate_rounds = 2
            pass_round_history = True

            last_task_for_file = None

            # --- Job 1 with 2 Debate Rounds ---
            j1_debate_id = f"{env_prefix}_job1_debate_{base_name}"
            _last_id = None
            for r in range(1, debate_rounds + 1):
                r_suf = f"_r{r}"
                d_id = f"{j1_debate_id}{r_suf}"
                delib_payload = {
                    "template": "debate_template.md",
                    "verdict": f"verdict{r_suf}.md",
                    "ledger": f"ledger{r_suf}.json",
                    "round_idx": r,
                    "pass_round_history": pass_round_history,
                }
                if r > 1:
                    delib_payload["prior_ledger"] = f"ledger_r{r-1}.json"
                    delib_payload["prior_verdict"] = f"verdict_r{r-1}.md"

                r_deps = [_last_id] if _last_id else ([last_task_for_file] if last_task_for_file else [])
                factory.add_task(Task(id=d_id, depends_on=r_deps, deliberate=delib_payload))
                _last_id = d_id

            j1_id = f"{env_prefix}_job1_{base_name}"
            factory.add_task(Task(id=j1_id, depends_on=[_last_id], message_file="verdict_r2.md", files=[current_file]))
            last_task_for_file = j1_id

            # --- Job 2 with 2 Debate Rounds ---
            j2_debate_id = f"{env_prefix}_job2_debate_{base_name}"
            _last_id = None
            for r in range(1, debate_rounds + 1):
                r_suf = f"_r{r}"
                d_id = f"{j2_debate_id}{r_suf}"
                delib_payload = {
                    "template": "debate_template.md",
                    "verdict": f"verdict_j2{r_suf}.md",
                    "ledger": f"ledger_j2{r_suf}.json",
                    "round_idx": r,
                    "pass_round_history": pass_round_history,
                }
                if r > 1:
                    delib_payload["prior_ledger"] = f"ledger_j2_r{r-1}.json"
                    delib_payload["prior_verdict"] = f"verdict_j2_r{r-1}.md"

                r_deps = [_last_id] if _last_id else [last_task_for_file]
                factory.add_task(Task(id=d_id, depends_on=r_deps, deliberate=delib_payload))
                _last_id = d_id

            j2_id = f"{env_prefix}_job2_{base_name}"
            factory.add_task(Task(id=j2_id, depends_on=[_last_id], message_file="verdict_j2_r2.md", files=[current_file]))
            last_task_for_file = j2_id

            # Assertions for Multi-round Pre-Edit Debates
            # 1. Job 1 Debate chaining
            self.assertIn("p1_job1_debate_mod_a_r1", factory.tasks)
            self.assertIn("p1_job1_debate_mod_a_r2", factory.tasks)
            self.assertEqual(factory.tasks["p1_job1_debate_mod_a_r2"].depends_on, ["p1_job1_debate_mod_a_r1"])
            self.assertEqual(factory.tasks["p1_job1_debate_mod_a_r2"].deliberate["prior_ledger"], "ledger_r1.json")
            self.assertEqual(factory.tasks["p1_job1_mod_a"].depends_on, ["p1_job1_debate_mod_a_r2"])
            self.assertEqual(factory.tasks["p1_job1_mod_a"].message_file, "verdict_r2.md")

            # 2. Job 2 Debate chaining from Job 1
            self.assertIn("p1_job2_debate_mod_a_r1", factory.tasks)
            self.assertIn("p1_job2_debate_mod_a_r2", factory.tasks)
            self.assertEqual(factory.tasks["p1_job2_debate_mod_a_r1"].depends_on, ["p1_job1_mod_a"])
            self.assertEqual(factory.tasks["p1_job2_debate_mod_a_r2"].depends_on, ["p1_job2_debate_mod_a_r1"])
            self.assertEqual(factory.tasks["p1_job2_mod_a"].depends_on, ["p1_job2_debate_mod_a_r2"])
            self.assertEqual(factory.tasks["p1_job2_mod_a"].message_file, "verdict_j2_r2.md")

    def test_insert_debate_selective_gating_integration(self):
        """T18: Zero-mock integration verifying selective pre-edit debate generation for [1,0,0], [0,1,0], [0,0,1], and [1,0,1]."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            src_dir = proj / "src"
            tests_dir = proj / "tests"
            src_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)

            mod_a = src_dir / "mod_a.py"
            test_a = tests_dir / "test_mod_a.py"
            mod_a.write_text("def fn(): pass\n", encoding="utf-8")
            test_a.write_text("def test_fn(): pass\n", encoding="utf-8")

            run_workflow_script = Path(__file__).resolve().parents[3] / "python" / "run_workflow.py"
            with open(run_workflow_script, "r", encoding="utf-8") as f:
                runner_code = f.read()

            vector_scenarios = [
                ("[1, 0, 0]", [1, 0, 0], True, False, False),
                ("[0, 1, 0]", [0, 1, 0], False, True, False),
                ("[0, 0, 1]", [0, 0, 1], False, False, True),
                ("[1, 0, 1]", [1, 0, 1], True, False, True),
            ]

            orig_argv = sys.argv
            orig_cwd = os.getcwd()

            try:
                for label, vector, exp_j1, exp_j2, exp_j3 in vector_scenarios:
                    sess_name = f"sess_{label.replace('[', '').replace(']', '').replace(', ', '_')}"
                    config_data = {
                        "name": f"Test Insert Debate {label}",
                        "working_directory": str(proj),
                        "test_runner": "pytest {file}",
                        "phases": [
                            {
                                "name": "Phase 1",
                                "enabled": True,
                                "models": {
                                    "architect_agent": "mock/model",
                                    "editor_agent": "mock/model",
                                    "editor_agent_test": "mock/model",
                                },
                                "oracle": {
                                    "start_job": False,
                                    "pre_edit_debate": {
                                        "enabled": True,
                                        "insert_debate": vector,
                                        "job_debate_template": "",
                                    },
                                },
                                "toggles": {
                                    "run_job_one": True,
                                    "run_job_two": True,
                                    "run_job_three": True,
                                    "iterate_test": True,
                                },
                                "files": {
                                    "target_files": ["src/mod_a.py"],
                                    "test_files": ["tests/test_mod_a.py"],
                                    "context_files_job": ["src/mod_a.py"],
                                    "context_files_test": ["src/mod_a.py"],
                                },
                            }
                        ],
                    }

                    cfg_file = proj / f"cfg_{sess_name}.yml"
                    with open(cfg_file, "w", encoding="utf-8") as cf:
                        yaml.dump(config_data, cf)

                    sys.argv = ["run_workflow.py", sess_name, str(cfg_file)]
                    os.chdir(proj)
                    ns = {"__name__": "__test__", "__file__": str(run_workflow_script)}
                    exec(runner_code, ns)

                    tasks = ns["factory"].tasks

                    # Job 1 Debate Verification
                    if exp_j1:
                        self.assertIn("p0_job1_debate_mod_a", tasks, f"Missing Job 1 debate for {label}")
                        self.assertEqual(tasks["p0_job1_mod_a"].depends_on, ["p0_job1_debate_mod_a"])
                    else:
                        self.assertNotIn("p0_job1_debate_mod_a", tasks, f"Unexpected Job 1 debate for {label}")

                    # Job 2 Debate Verification
                    if exp_j2:
                        self.assertIn("p0_job2_debate_mod_a", tasks, f"Missing Job 2 debate for {label}")
                        self.assertEqual(tasks["p0_job2_mod_a"].depends_on, ["p0_job2_debate_mod_a"])
                    else:
                        self.assertNotIn("p0_job2_debate_mod_a", tasks, f"Unexpected Job 2 debate for {label}")

                    # Job 3 Debate Verification
                    if exp_j3:
                        self.assertIn("p0_job3_debate_mod_a", tasks, f"Missing Job 3 debate for {label}")
                        self.assertEqual(tasks["p0_job3_mod_a"].depends_on, ["p0_job3_debate_mod_a"])
                    else:
                        self.assertNotIn("p0_job3_debate_mod_a", tasks, f"Unexpected Job 3 debate for {label}")
            finally:
                sys.argv = orig_argv
                os.chdir(orig_cwd)

    def test_heterogeneous_multi_corpus_debate_integration(self):
        """T21: Zero-mock integration verifying heterogeneous per-job debate templates, vector collections, and loops: 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            src_dir = proj / "src"
            tests_dir = proj / "tests"
            src_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)

            mod_a = src_dir / "mod_a.py"
            test_a = tests_dir / "test_mod_a.py"
            mod_a.write_text("def fn(): pass\n", encoding="utf-8")
            test_a.write_text("def test_fn(): pass\n", encoding="utf-8")

            run_workflow_script = Path(__file__).resolve().parents[3] / "python" / "run_workflow.py"
            with open(run_workflow_script, "r", encoding="utf-8") as f:
                runner_code = f.read()

            sess_name = "sess_multi_corpus"
            config_data = {
                "name": "Heterogeneous Debate Pipeline",
                "working_directory": str(proj),
                "test_runner": "pytest {file}",
                "phases": [
                    {
                        "name": "Phase 1",
                        "enabled": True,
                        "models": {
                            "architect_agent": "mock/model",
                            "editor_agent": "mock/model",
                            "editor_agent_test": "mock/model",
                        },
                        "oracle": {
                            "start_job": False,
                            "pre_edit_debate": {
                                "enabled": True,
                                "insert_debate": [1, 1, 1],
                                "loops": 0,
                                "job_debate_template": [
                                    "markdown/templates/implement.md",
                                    "markdown/templates/validate.md",
                                    "markdown/templates/testing.md",
                                ],
                                "job_debate_collection": [
                                    "coll_exchange",
                                    "coll_risk_math",
                                    "coll_mocks",
                                ],
                            },
                        },
                        "toggles": {
                            "run_job_one": True,
                            "run_job_two": True,
                            "run_job_three": True,
                            "iterate_test": True,
                        },
                        "files": {
                            "target_files": ["src/mod_a.py"],
                            "test_files": ["tests/test_mod_a.py"],
                            "context_files_job": ["src/mod_a.py"],
                            "context_files_test": ["src/mod_a.py"],
                        },
                    }
                ],
            }

            cfg_file = proj / "cfg_multi_corpus.yml"
            with open(cfg_file, "w", encoding="utf-8") as cf:
                yaml.dump(config_data, cf)

            orig_argv = sys.argv
            orig_cwd = os.getcwd()
            try:
                sys.argv = ["run_workflow.py", sess_name, str(cfg_file)]
                os.chdir(proj)
                ns = {"__name__": "__test__", "__file__": str(run_workflow_script)}
                exec(runner_code, ns)

                tasks = ns["factory"].tasks

                # Verify Job 1 Heterogeneous Debate (loops: 0 lone consultation)
                t_j1 = tasks["p0_job1_debate_mod_a"]
                self.assertTrue(t_j1.deliberate["template"].endswith("implement.md"))
                self.assertEqual(t_j1.deliberate["loops"], 0)
                self.assertEqual(t_j1.rag_env["ORACLE_COLLECTION"], "coll_exchange")
                self.assertIn("coll_exchange/lancedb", t_j1.rag_env["ORACLE_RAG_DB_DIR"])

                # Verify Job 2 Heterogeneous Debate
                t_j2 = tasks["p0_job2_debate_mod_a"]
                self.assertTrue(t_j2.deliberate["template"].endswith("validate.md"))
                self.assertEqual(t_j2.deliberate["loops"], 0)
                self.assertEqual(t_j2.rag_env["ORACLE_COLLECTION"], "coll_risk_math")
                self.assertIn("coll_risk_math/lancedb", t_j2.rag_env["ORACLE_RAG_DB_DIR"])

                # Verify Job 3 Heterogeneous Debate
                t_j3 = tasks["p0_job3_debate_mod_a"]
                self.assertTrue(t_j3.deliberate["template"].endswith("testing.md"))
                self.assertEqual(t_j3.deliberate["loops"], 0)
                self.assertEqual(t_j3.rag_env["ORACLE_COLLECTION"], "coll_mocks")
                self.assertIn("coll_mocks/lancedb", t_j3.rag_env["ORACLE_RAG_DB_DIR"])
            finally:
                sys.argv = orig_argv
                os.chdir(orig_cwd)

    def test_ambient_session_pollution_isolation(self):
        """T23: Zero-mock integration verifying that ambient AI_FACTORY_SESSION is never overwritten when running DAG tests without explicit session args."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir)
            src_dir = proj / "src"
            src_dir.mkdir(parents=True)

            mod_a = src_dir / "mod_a.py"
            mod_a.write_text("def fn(): pass\n", encoding="utf-8")

            # 1. Create a pre-existing developer session with protected content
            dev_session_dir = proj / ".aider_factory" / "sessions" / "dev_active_session"
            dev_session_dir.mkdir(parents=True)
            protected_session_yml = dev_session_dir / "session.yml"
            protected_content = "# PROTECTED DEVELOPER CONFIG\nname: Protected Developer Session\n"
            protected_session_yml.write_text(protected_content, encoding="utf-8")

            # 2. Create a mock test config
            test_config_data = {
                "name": "Ephemeral Test Config",
                "working_directory": str(proj),
                "phases": [
                    {
                        "name": "Phase 1",
                        "enabled": True,
                        "models": {
                            "architect_agent": "mock/model",
                            "editor_agent": "mock/model",
                        },
                        "toggles": {
                            "run_job_one": True,
                            "run_job_two": False,
                            "run_job_three": False,
                            "iterate_test": False,
                        },
                        "files": {
                            "target_files": ["src/mod_a.py"],
                            "context_files_job": ["src/mod_a.py"],
                        },
                    }
                ],
            }
            test_cfg_file = proj / "test_ephemeral.yml"
            with open(test_cfg_file, "w", encoding="utf-8") as f:
                yaml.dump(test_config_data, f)

            run_workflow_script = (
                Path(__file__).resolve().parents[3] / "python" / "run_workflow.py"
            )
            with open(run_workflow_script, "r", encoding="utf-8") as f:
                runner_code = f.read()

            orig_argv = sys.argv
            orig_cwd = os.getcwd()
            orig_env_sess = os.environ.get("AI_FACTORY_SESSION")

            try:
                # Simulate developer's ambient active session in the environment
                os.environ["AI_FACTORY_SESSION"] = "dev_active_session"

                # Run run_workflow.py without an explicit session argument in sys.argv
                sys.argv = ["run_workflow.py", str(test_cfg_file)]
                os.chdir(proj)
                ns = {"__name__": "__test__", "__file__": str(run_workflow_script)}
                exec(runner_code, ns)

                # Assert that developer's session.yml was NOT clobbered by test_ephemeral.yml
                self.assertTrue(protected_session_yml.exists())
                current_dev_content = protected_session_yml.read_text(encoding="utf-8")
                self.assertEqual(current_dev_content, protected_content)
                self.assertNotIn("Ephemeral Test Config", current_dev_content)
            finally:
                sys.argv = orig_argv
                os.chdir(orig_cwd)
                if orig_env_sess is not None:
                    os.environ["AI_FACTORY_SESSION"] = orig_env_sess
                else:
                    os.environ.pop("AI_FACTORY_SESSION", None)


if __name__ == "__main__":
    unittest.main()
