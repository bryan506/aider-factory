#!/usr/bin/env python3
import os
import sys
import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(script_dir, "../../.."))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
if python_module_dir not in sys.path:
    sys.path.insert(0, python_module_dir)


def check_topology(test_name, config, required_substrings, forbidden_substrings):
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "mock_topo.yml")
        config = dict(config)
        config["working_directory"] = tmpdir
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)

        # Ensure mock files exist in the project directory
        mock_r = os.path.join(tmpdir, "mock.R")
        mock_md = os.path.join(tmpdir, "mock.md")
        heal_sh = os.path.join(tmpdir, "heal.sh")
        open(mock_r, "a").close()
        open(mock_md, "a").close()
        open(heal_sh, "a").close()

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_topo_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }

        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()

        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            # Force development source to front of sys.path so exec'd run_workflow.py
            # imports the development orchestrate.py (with auto_lint) not the installed one.
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks
            task_ids = " ".join(tasks.keys())

            success = True
            for req in required_substrings:
                if req not in task_ids:
                    print(f"  ❌ Missing expected node type: {req}")
                    success = False
            for forb in forbidden_substrings:
                if forb in task_ids:
                    print(f"  ❌ Found forbidden node type: {forb}")
                    success = False

            assert success, f"{test_name} FAILED: Generated Tasks: {task_ids}"
            print(f"✅ {test_name} PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_code_mode_topology():
    """Test 1: Code Mode (job1 -> job2 -> job3 -> verify -> deliberate -> apply)"""
    code_config = {
        "working_directory": script_dir,
        "phases": [
            {
                "name": "Code",
                "enabled": True,
                "rag": {
                    "collection_name": "",
                    "batch": True,
                    "run_ocr_rag": False,
                },
                "oracle": {
                    "start_job": False,
                    "pre_edit_debate": {
                        "enabled": True,
                        "job_debate_template": "",
                    },
                },
                "toggles": {
                    "run_job_one": True,
                    "run_job_two": True,
                    "run_job_three": True,
                    "iterate_test": True,
                },
                "validation": {"enabled": False},
                "escalation_debate": {"loops": 2, "rounds": 1},
                "models": {
                    "architect_agent": "mock",
                    "editor_agent": "mock",
                    "editor_agent_test": "mock",
                },
                "files": {"target_files": ["mock.R"]},
            }
        ],
    }
    check_topology(
        "Code Mode Topology",
        code_config,
        ["job1", "job2", "job3", "verify", "deliberate", "apply"],
        ["oracle_mock.R", "autofix", "finalize"],
    )


def test_review_mode_topology():
    """Test 2: Review Mode (oracle -> autofix -> heal -> deliberate -> apply -> finalize)"""
    review_config = {
        "working_directory": script_dir,
        "phases": [
            {
                "name": "Review",
                "enabled": True,
                "rag": {
                    "collection_name": "",
                    "batch": False,
                    "run_ocr_rag": False,
                },
                "oracle": {"start_job": True},
                "toggles": {
                    "run_job_one": False,
                    "run_job_two": False,
                    "run_job_three": False,
                    "iterate_test": False,
                },
                "validation": {
                    "enabled": True,
                    "post_validate": True,
                    "validation_loops": 2,
                },
                "escalation_debate": {"loops": 2, "rounds": 1},
                "models": {
                    "architect_agent": "mock",
                    "editor_agent": "mock",
                    "editor_agent_test": "mock",
                },
                "files": {"target_files": ["mock.md"], "test_files": ["heal.sh"]},
            }
        ],
    }
    check_topology(
        "Review Mode Topology",
        review_config,
        ["oracle", "autofix", "heal", "deliberate", "apply", "finalize"],
        ["job1", "job2", "job3", "verify"],
    )


def test_grounding_gate_is_list():
    """Phase 1: Grounding gate command in review mode is a list, not a shell string."""
    import tempfile
    review_config = {
        "working_directory": "",
        "phases": [{
            "name": "Review",
            "enabled": True,
            "rag": {"collection_name": "", "batch": False, "run_ocr_rag": False},
            "oracle": {"start_job": True},
            "toggles": {
                "run_job_one": False, "run_job_two": False,
                "run_job_three": False, "iterate_test": False,
            },
            "validation": {"enabled": True, "post_validate": True, "validation_loops": 2},
            "escalation_debate": {"loops": 2, "rounds": 1},
            "models": {
                "architect_agent": "mock", "editor_agent": "mock",
                "editor_agent_test": "mock",
            },
            "files": {"target_files": ["mock.md"], "test_files": ["heal.sh"]},
        }],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        review_config["working_directory"] = tmpdir
        yaml_path = os.path.join(tmpdir, "test_gate_type.yml")
        open(os.path.join(tmpdir, "mock.md"), "a").close()
        open(os.path.join(tmpdir, "heal.sh"), "a").close()

        with open(yaml_path, "w") as f:
            yaml.dump(review_config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "test_gate_type_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            delib_tasks = [t for tid, t in tasks.items() if "deliberate" in tid]
            assert len(delib_tasks) > 0, "Expected at least one deliberation task"

            for dt in delib_tasks:
                gate = dt.deliberate.get("gate_cmd")
                assert isinstance(gate, list), (
                    f"Expected gate_cmd to be a list, got {type(gate).__name__}: {gate}"
                )
                assert gate[0] == sys.executable, (
                    f"Expected gate_cmd[0] to be sys.executable ({sys.executable}), got {gate[0]}"
                )
                assert "validator.py" in gate[1], (
                    f"Expected 'validator.py' in gate_cmd[1], got {gate[1]}"
                )
            print("✅ Grounding gate is list (not shell string) PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_tee_writer_dual_output():
    """Phase 2b: _TeeWriter writes to both original stream and log file."""
    import io
    print("Testing _TeeWriter dual output...")

    sys.path.insert(0, python_module_dir)
    from run_workflow import _TeeWriter

    original = io.StringIO()
    log = io.StringIO()
    tee = _TeeWriter(original, log)

    tee.write("hello world\n")
    tee.flush()

    assert original.getvalue() == "hello world\n", (
        f"Original stream must receive write, got: {original.getvalue()!r}"
    )
    assert log.getvalue() == "hello world\n", (
        f"Log file must receive write, got: {log.getvalue()!r}"
    )

    # Test __getattr__ proxy
    assert hasattr(tee, "getvalue"), "_TeeWriter must proxy unknown attrs to original"
    print("  ✅ _TeeWriter dual output PASS")


def test_ostee_windows_branch_sets_tee_writer():
    """Phase 2b: OSTee on Windows sets sys.stdout/stderr to _TeeWriter instances."""
    import io
    import tempfile
    from unittest.mock import patch
    print("Testing OSTee Windows branch...")

    sys.path.insert(0, python_module_dir)
    from run_workflow import OSTee, _TeeWriter

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    try:
        with patch("run_workflow.sys.platform", "win32"):
            tee = OSTee(log_path)

            assert isinstance(sys.stdout, _TeeWriter), (
                f"sys.stdout must be _TeeWriter on Windows, got {type(sys.stdout)}"
            )
            assert isinstance(sys.stderr, _TeeWriter), (
                f"sys.stderr must be _TeeWriter on Windows, got {type(sys.stderr)}"
            )
            assert tee.orig_stdout_fd is None, "orig_stdout_fd must be None on Windows"
            assert tee.thread is None, "thread must be None on Windows"

            tee.stop()

            assert sys.stdout is orig_stdout or sys.stdout is tee._orig_stdout, (
                "sys.stdout must be restored after stop()"
            )
    finally:
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr
        if os.path.exists(log_path):
            os.remove(log_path)
    print("  ✅ OSTee Windows branch PASS")


def test_ostee_posix_branch_uses_fd_dup():
    """Phase 2b: OSTee on POSIX uses os.dup/dup2 (regression test)."""
    import tempfile
    print("Testing OSTee POSIX branch (regression)...")

    sys.path.insert(0, python_module_dir)
    from run_workflow import OSTee

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    try:
        # On actual Linux, this exercises the real POSIX path
        if sys.platform != "win32":
            tee = OSTee(log_path)
            assert tee.orig_stdout_fd is not None, "orig_stdout_fd must be set on POSIX"
            assert tee.thread is not None, "pump thread must be started on POSIX"
            assert tee.thread.is_alive(), "pump thread must be alive"
            tee.stop()
            assert not tee.thread.is_alive(), "pump thread must be stopped"
        else:
            print("    (skipped on Windows)")
    finally:
        if os.path.exists(log_path):
            os.remove(log_path)
    print("  ✅ OSTee POSIX branch PASS")


def test_ostee_windows_branch_real_io():
    """Phase 2b gap-close: OSTee on Windows actually captures print() output to log file."""
    import tempfile
    from unittest.mock import patch
    print("Testing OSTee Windows branch real I/O...")

    sys.path.insert(0, python_module_dir)
    from run_workflow import OSTee, _TeeWriter

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    try:
        with patch("run_workflow.sys.platform", "win32"):
            tee = OSTee(log_path)

            # Real I/O: print through the _TeeWriter and verify it reaches the log
            sys.stdout.write("OSTEE_WIN_IO_TEST_MARKER\n")
            sys.stdout.flush()

            tee.stop()

        # Read the log file and verify the marker was captured
        with open(log_path, "r", encoding="utf-8") as lf:
            log_content = lf.read()
        assert "OSTEE_WIN_IO_TEST_MARKER" in log_content, (
            f"Expected 'OSTEE_WIN_IO_TEST_MARKER' in log file, got: {log_content!r}"
        )
    finally:
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr
        if os.path.exists(log_path):
            os.remove(log_path)
    print("  ✅ OSTee Windows branch real I/O PASS")


def test_tee_writer_flush_and_fileno_proxy():
    """Phase 2b gap-close: _TeeWriter proxies flush(), fileno(), and unknown attrs correctly."""
    import io
    print("Testing _TeeWriter flush/fileno/proxy...")

    sys.path.insert(0, python_module_dir)
    from run_workflow import _TeeWriter

    original = io.StringIO()
    log = io.StringIO()
    tee = _TeeWriter(original, log)

    # Test write + flush
    tee.write("line1\n")
    tee.write("line2\n")
    tee.flush()
    assert original.getvalue() == "line1\nline2\n"
    assert log.getvalue() == "line1\nline2\n"

    # Test __getattr__ proxy: StringIO has getvalue, readable, etc.
    assert tee.getvalue() == "line1\nline2\n", "getvalue must proxy to original"

    # Test fileno proxy: StringIO doesn't have a real fd, so fileno() should
    # call original.fileno() which raises UnsupportedOperation — proving the proxy works
    try:
        tee.fileno()
        # If we get here, original somehow has a fileno (unlikely for StringIO)
    except io.UnsupportedOperation:
        pass  # Expected: StringIO has no fd, proxy correctly delegates

    print("  ✅ _TeeWriter flush/fileno/proxy PASS")


def test_tee_writer_multiple_writes_interleaved():
    """Phase 2b gap-close: Multiple writes to _TeeWriter produce identical content in both streams."""
    import io
    print("Testing _TeeWriter interleaved writes...")

    sys.path.insert(0, python_module_dir)
    from run_workflow import _TeeWriter

    original = io.StringIO()
    log = io.StringIO()
    tee = _TeeWriter(original, log)

    for i in range(50):
        tee.write(f"line_{i:04d}\n")

    tee.flush()

    orig_lines = original.getvalue().splitlines()
    log_lines = log.getvalue().splitlines()

    assert len(orig_lines) == 50, f"Expected 50 lines in original, got {len(orig_lines)}"
    assert len(log_lines) == 50, f"Expected 50 lines in log, got {len(log_lines)}"
    assert orig_lines == log_lines, "Original and log must have identical content"
    assert orig_lines[0] == "line_0000"
    assert orig_lines[49] == "line_0049"

    print("  ✅ _TeeWriter interleaved writes PASS")


def test_env_plan_do_workflow_topology():
    """Verify that env_plan_do.yml compiles into the exact 3-phase DAG:
    Phase 1 (Planning): pair-programming strategy specification.
    Phase 2 (Code): Job 1 (implement) -> Job 2 (validate) -> Pre-Test Debate (Job 3 debate)
                    -> Job 3 (author tests with testing_exec.md) -> Verify (test loop)
                    -> Escalation Debate (rounds 1 & 2).
    Phase 3 (Post-Implementation): pair-programming review with post_test_validation.md.
    """
    import tempfile

    sample_yaml = os.path.abspath(
        os.path.join(
            src_dir,
            "aider_factory/default_configs/sample_yaml_config/env_plan_do.yml",
        )
    )
    assert os.path.isfile(sample_yaml), f"Missing sample config: {sample_yaml}"

    with open(sample_yaml, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    with tempfile.TemporaryDirectory() as tmpdir:
        config["working_directory"] = tmpdir

        # Scaffold physical files in the temporary project directory
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "tests", "unit"), exist_ok=True)
        os.makedirs(
            os.path.join(tmpdir, ".aider_factory", "markdown", "oracle_pre_plan"),
            exist_ok=True,
        )

        open(os.path.join(tmpdir, "src", "feature.py"), "a").close()
        strat_md_path = os.path.join(
            tmpdir,
            ".aider_factory",
            "markdown",
            "oracle_pre_plan",
            "strategy_template.md",
        )
        with open(strat_md_path, "w", encoding="utf-8") as sf:
            sf.write("""# Strategy
## Scope Analysis
```yaml
files:
  target_files:
    - "src/feature.py"
  extra_editable_files: []
  test_files: []
  context_files_job: []
  context_files_test: []
```
""")

        yaml_path = os.path.join(tmpdir, "env_plan_do_test.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "test_plan_do_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()

        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)

            exec(code, namespace)
            tasks = namespace["factory"].tasks

            # 1. Expected Task Nodes
            expected_nodes = [
                "p0_job1_strategy_template",
                "p1_job1_feature",
                "p1_job2_feature",
                "p1_job3_debate_feature",
                "p1_job3_feature",
                "p1_verify_feature",
                "p1_deliberate_feature_r1",
                "p1_apply_feature_r1",
                "p1_deliberate_feature_r2",
                "p1_apply_feature_r2",
                "p2_job1_feature",
            ]
            for node_id in expected_nodes:
                assert node_id in tasks, f"Expected node '{node_id}' not found in tasks: {list(tasks.keys())}"

            # 2. Negative Scope: verify no debates before Job 1 or Job 2
            assert "p1_job1_debate_feature" not in tasks, "Found forbidden p1_job1_debate_feature node"
            assert "p1_job2_debate_feature" not in tasks, "Found forbidden p1_job2_debate_feature node"

            # 3. Phase 1 (Planning) Configuration
            p0_job1 = tasks["p0_job1_strategy_template"]
            assert p0_job1.pair_programming is True
            assert p0_job1.yes_always is False
            assert p0_job1.message_file is not None and os.path.isfile(p0_job1.message_file)
            assert p0_job1.message_file.endswith("strategy_instruct_template.md")

            # Verify Phase barrier linking: Phase 1 Job 1 depends on Phase 0 Job 1
            p1_j1 = tasks["p1_job1_feature"]
            assert p1_j1.depends_on == ["p0_job1_strategy_template"], (
                f"Expected p1_job1_feature to depend on p0_job1_strategy_template, got: {p1_j1.depends_on}"
            )

            # 4. Phase 2 (Code) Pre-Test Debate Node Invariants
            j3_debate = tasks["p1_job3_debate_feature"]
            assert j3_debate.deliberate is not None
            assert j3_debate.deliberate["mode"] == "code"
            assert j3_debate.deliberate["draft_mode"] is True
            assert j3_debate.deliberate["loops"] == 3
            assert j3_debate.deliberate["template"] is not None and os.path.isfile(j3_debate.deliberate["template"])
            assert j3_debate.deliberate["template"].endswith("testing_debate.md")
            assert j3_debate.deliberate["issue"] is not None and os.path.isfile(j3_debate.deliberate["issue"])
            assert j3_debate.deliberate["issue"].endswith("testing_exec.md")
            assert j3_debate.depends_on == ["p1_job2_feature"]

            # 5. Phase 2 Job 3 (Test Authoring) Invariants
            j3 = tasks["p1_job3_feature"]
            assert j3.depends_on == ["p1_job3_debate_feature"]
            assert j3.message_file is not None and j3.message_file.endswith("feature.job3_verdict.md")
            assert any(f.endswith("test_feature.py") for f in j3.files)
            assert any(f.endswith("feature.py") for f in j3.files)

            # 6. Phase 2 Verification & Escalation Chain
            verify = tasks["p1_verify_feature"]
            assert verify.depends_on == ["p1_job3_feature"]
            assert "pytest tests/unit/test_feature.py" in verify.test_cmd
            assert verify.iterate_test is True
            assert verify.soft_fail is True

            delib_r1 = tasks["p1_deliberate_feature_r1"]
            apply_r1 = tasks["p1_apply_feature_r1"]
            delib_r2 = tasks["p1_deliberate_feature_r2"]
            apply_r2 = tasks["p1_apply_feature_r2"]

            assert delib_r1.depends_on == ["p1_verify_feature"]
            assert apply_r1.depends_on == ["p1_deliberate_feature_r1"]
            assert delib_r2.depends_on == ["p1_apply_feature_r1"]
            assert apply_r2.depends_on == ["p1_deliberate_feature_r2"]
            assert delib_r1.deliberate["loops"] == 4
            assert delib_r1.deliberate["pass_history"] is True

            # 7. Phase 3 (Review & Follow-up) Invariants
            p2_job1 = tasks["p2_job1_feature"]
            assert p2_job1.depends_on == ["p1_apply_feature_r2"]
            assert p2_job1.pair_programming is True
            assert p2_job1.yes_always is False
            assert p2_job1.message_file is not None and os.path.isfile(p2_job1.message_file)
            assert p2_job1.message_file.endswith("post_test_validation.md")

            print("  ✅ env_plan_do 3-phase DAG topology PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_sticky_phases_5_field_extraction():
    """Verify sticky_phases extracts 5 fields, separates tests from targets, and links barriers."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "docs"), exist_ok=True)
        open(os.path.join(tmpdir, "src", "engine.py"), "w").close()
        open(os.path.join(tmpdir, "tests", "test_engine.py"), "w").close()
        open(os.path.join(tmpdir, "docs", "spec.md"), "w").close()

        plan_dir = os.path.join(tmpdir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("""# Strategy Plan
## Frontmatter Metadata
```yaml
metadata:
  version: "1.0.0"
  author: "architect"
```

## Scope Analysis
```yaml
files:
  target_files:
    - "src/engine.py"
    - "tests/test_engine.py"
    - "src/phantom_nonexistent.py"
  extra_editable_files: []
  test_files: []
  context_files_job:
    - "docs/spec.md"
  context_files_test: []
```
""")

        config = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "name": "Phase0",
                    "enabled": True,
                    "toggles": {"run_job_one": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": [plan_path]},
                },
                {
                    "name": "Phase1",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {"run_job_one": True, "run_job_three": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": plan_path},
                },
            ],
        }

        yaml_path = os.path.join(tmpdir, "test_sticky_5field.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_sticky_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }

        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()

        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            # 1. Target files: engine.py compiled, phantom_nonexistent.py dropped, test_engine.py diverted
            assert "p1_job1_engine" in tasks, "Expected p1_job1_engine to be compiled"
            assert "p1_job1_phantom_nonexistent" not in tasks, "Phantom file must not be compiled"
            assert "p1_job1_test_engine" not in tasks, "Test file must not be compiled as target_file"

            # 2. Barrier linking: Phase 1 entry task depends on Phase 0 exit task
            p0_task = next(t for tid, t in tasks.items() if tid.startswith("p0_"))
            assert tasks["p1_job1_engine"].depends_on == [p0_task.id], (
                f"Expected entry task to depend on {p0_task.id}, got {tasks['p1_job1_engine'].depends_on}"
            )

            # 3. Test separation: test_engine.py was diverted to test_files
            assert tasks["p1_job3_engine"].files[0] == "tests/test_engine.py"

            # 4. Context propagation: docs/spec.md was inherited in read_files
            assert any(f.endswith("docs/spec.md") for f in tasks["p1_job1_engine"].read_files)
            # Verify context_files_test defaulted to context_files_job
            assert any(f.endswith("docs/spec.md") for f in tasks["p1_job3_engine"].read_files)

            print("  ✅ sticky_phases 5-field extraction and barrier linking PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_review_mode_autofix_dependency():
    """Verify autofix node strictly depends on oracle generation node in review mode."""
    import tempfile
    review_config = {
        "working_directory": "",
        "phases": [{
            "name": "Review",
            "enabled": True,
            "rag": {"collection_name": "", "batch": False, "run_ocr_rag": False},
            "oracle": {"start_job": True},
            "toggles": {
                "run_job_one": False, "run_job_two": False,
                "run_job_three": False, "iterate_test": False,
            },
            "validation": {"enabled": True, "post_validate": True, "validation_loops": 2},
            "models": {
                "architect_agent": "mock", "editor_agent": "mock",
                "editor_agent_test": "mock",
            },
            "files": {"target_files": ["mock.md"], "test_files": ["heal.sh"]},
        }],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        review_config["working_directory"] = tmpdir
        yaml_path = os.path.join(tmpdir, "review_dep.yml")
        open(os.path.join(tmpdir, "mock.md"), "a").close()
        open(os.path.join(tmpdir, "heal.sh"), "a").close()

        with open(yaml_path, "w") as f:
            yaml.dump(review_config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "review_dep_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks
            assert "p0_oracle_mock" in tasks
            assert "p0_autofix_mock" in tasks
            assert tasks["p0_autofix_mock"].depends_on == ["p0_oracle_mock"], (
                f"Expected autofix to depend on p0_oracle_mock, got: {tasks['p0_autofix_mock'].depends_on}"
            )
            print("  ✅ Grounding mode autofix depends_on oracle task PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_sticky_phases_multi_block_and_readonly():
    """Verify multi-block YAML parsing skips empty blocks and sticky_readonly extracts context files."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "docs"), exist_ok=True)
        open(os.path.join(tmpdir, "src", "manual_target.py"), "w").close()
        open(os.path.join(tmpdir, "src", "plan_target.py"), "w").close()
        open(os.path.join(tmpdir, "docs", "spec.md"), "w").close()

        plan_dir = os.path.join(tmpdir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("""# Plan With Multi-Block YAML
## Template Documentation
```yaml
files: {}
```

## Actual Scope Manifest
```yaml
files:
  target_files:
    - "src/plan_target.py"
  extra_editable_files: []
  test_files: []
  context_files_job:
    - "docs/spec.md"
  context_files_test: []
```
""")

        config = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "name": "Phase0",
                    "enabled": True,
                    "sticky_phases": {"editable": False, "readonly": True},
                    "toggles": {"run_job_one": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/manual_target.py"]},
                    "plans": {"job_one_plan": plan_path},
                }
            ],
        }

        yaml_path = os.path.join(tmpdir, "test_multi_block.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_multi_block_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            # 1. Target file must remain manual_target.py because editable is False
            assert "p0_job1_manual_target" in tasks
            assert "p0_job1_plan_target" not in tasks

            # 2. Context file docs/spec.md must be discovered and inherited in read_files
            j1 = tasks["p0_job1_manual_target"]
            assert any(f.endswith("docs/spec.md") for f in j1.read_files), (
                f"Expected docs/spec.md in read_files, got: {j1.read_files}"
            )
            print("  ✅ Multi-block YAML resilience and standalone sticky_readonly PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_skipped_or_disabled_phase_barrier_propagation():
    """ADV-03: Phase 0 -> Phase 1 (disabled) -> Phase 2 (all toggles off/skipped) -> Phase 3 (active).
    Verify Phase 3 entry task directly inherits Phase 0 exit task as dependency barrier."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        open(os.path.join(tmpdir, "src", "p0.py"), "w").close()
        open(os.path.join(tmpdir, "src", "p1.py"), "w").close()
        open(os.path.join(tmpdir, "src", "p2.py"), "w").close()
        open(os.path.join(tmpdir, "src", "p3.py"), "w").close()

        config = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "name": "Phase0",
                    "enabled": True,
                    "toggles": {"run_job_one": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/p0.py"]},
                },
                {
                    "name": "Phase1_Disabled",
                    "enabled": False,
                    "toggles": {"run_job_one": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/p1.py"]},
                },
                {
                    "name": "Phase2_Skipped",
                    "enabled": True,
                    "toggles": {
                        "run_job_one": False,
                        "run_job_two": False,
                        "run_job_three": False,
                        "iterate_test": False,
                    },
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/p2.py"]},
                },
                {
                    "name": "Phase3_Active",
                    "enabled": True,
                    "toggles": {"run_job_one": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/p3.py"]},
                },
            ],
        }

        yaml_path = os.path.join(tmpdir, "skipped_phase_barrier.yml")
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_skipped_barrier_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            # Phase 0 ran
            assert "p0_job1_p0" in tasks
            # Phase 1 & 2 generated no tasks
            assert "p1_job1_p1" not in tasks
            assert "p2_job1_p2" not in tasks
            # Phase 3 ran and directly depends on Phase 0's exit task
            assert "p3_job1_p3" in tasks
            assert tasks["p3_job1_p3"].depends_on == ["p0_job1_p0"], (
                f"Expected p3_job1_p3 to depend on p0_job1_p0 across skipped phases, got: {tasks['p3_job1_p3'].depends_on}"
            )
            print("  ✅ Skipped and disabled phase barrier propagation PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_multi_target_fan_in_fan_out_matrix():
    """ADV-04: Multi-target fan-out and fan-in matrix across phases.
    Phase 0 processes [a.py, b.py] -> Phase 1 processes [a.py, c.py].
    Verify a.py preserves single-file task affinity, while new file c.py fans in across all Phase 0 terminal tasks."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        open(os.path.join(tmpdir, "src", "a.py"), "w").close()
        open(os.path.join(tmpdir, "src", "b.py"), "w").close()
        open(os.path.join(tmpdir, "src", "c.py"), "w").close()

        config = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "name": "Phase0_MultiTarget",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "run_job_two": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/a.py", "src/b.py"]},
                },
                {
                    "name": "Phase1_FanInFanOut",
                    "enabled": True,
                    "toggles": {"run_job_one": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["src/a.py", "src/c.py"]},
                },
            ],
        }

        yaml_path = os.path.join(tmpdir, "fan_in_out.yml")
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_fan_in_out_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            # Phase 0 tasks
            assert "p0_job2_a" in tasks
            assert "p0_job2_b" in tasks

            # Phase 1 a.py preserves direct single-file affinity
            assert "p1_job1_a" in tasks
            assert tasks["p1_job1_a"].depends_on == ["p0_job2_a"], (
                f"Expected p1_job1_a to depend strictly on p0_job2_a, got: {tasks['p1_job1_a'].depends_on}"
            )

            # Phase 1 c.py (brand new target) fans in across ALL Phase 0 terminal tasks as barrier
            assert "p1_job1_c" in tasks
            assert set(tasks["p1_job1_c"].depends_on) == {"p0_job2_a", "p0_job2_b"}, (
                f"Expected p1_job1_c to fan-in depend on all prior phase terminal tasks, got: {tasks['p1_job1_c'].depends_on}"
            )
            print("  ✅ Multi-target fan-in/fan-out barrier matrix PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_pre_edit_debate_triad_full_chain():
    """ADV-06: Pre-edit debate triad [1, 1, 1] full sequential DAG chain:
    job1_debate -> job1 -> job2_debate -> job2 -> job3_debate -> job3 -> verify.
    Verify unique verdicts, ledgers, and exact dependency links."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
        open(os.path.join(tmpdir, "src", "triad.py"), "w").close()
        open(os.path.join(tmpdir, "tests", "test_triad.py"), "w").close()
        open(os.path.join(tmpdir, "plan.md"), "w").close()

        config = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "name": "PhaseTriad",
                    "enabled": True,
                    "oracle": {
                        "start_job": False,
                        "pre_edit_debate": {
                            "enabled": True,
                            "insert_debate": [1, 1, 1],
                            "loops": 2,
                        },
                    },
                    "toggles": {
                        "run_job_one": True,
                        "run_job_two": True,
                        "run_job_three": True,
                        "iterate_test": True,
                    },
                    "models": {
                        "architect_agent": "mock",
                        "editor_agent": "mock",
                        "editor_agent_test": "mock",
                    },
                    "files": {
                        "target_files": ["src/triad.py"],
                        "test_files": ["tests/test_triad.py"],
                    },
                    "plans": {
                        "job_one_plan": "plan.md",
                        "job_two_plan": "plan.md",
                        "job_three_plan": "plan.md",
                        "iterate_plan": "plan.md",
                    },
                }
            ],
        }

        yaml_path = os.path.join(tmpdir, "triad.yml")
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_triad_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            # 1. Existence of all 3 debates and all 3 jobs + verify
            for expected_id in [
                "p0_job1_debate_triad", "p0_job1_triad",
                "p0_job2_debate_triad", "p0_job2_triad",
                "p0_job3_debate_triad", "p0_job3_triad",
                "p0_verify_triad",
            ]:
                assert expected_id in tasks, f"Missing node: {expected_id}"

            # 2. Strict sequential dependencies
            assert tasks["p0_job1_triad"].depends_on == ["p0_job1_debate_triad"]
            assert tasks["p0_job2_debate_triad"].depends_on == ["p0_job1_triad"]
            assert tasks["p0_job2_triad"].depends_on == ["p0_job2_debate_triad"]
            assert tasks["p0_job3_debate_triad"].depends_on == ["p0_job2_triad"]
            assert tasks["p0_job3_triad"].depends_on == ["p0_job3_debate_triad"]
            assert tasks["p0_verify_triad"].depends_on == ["p0_job3_triad"]

            # 3. Segregated verdict filenames
            assert tasks["p0_job1_triad"].message_file.endswith("triad.job1_verdict.md")
            assert tasks["p0_job2_triad"].message_file.endswith("triad.job2_verdict.md")
            assert tasks["p0_job3_triad"].message_file.endswith("triad.job3_verdict.md")
            print("  ✅ Pre-edit debate triad [1, 1, 1] full sequential DAG PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_hybrid_multi_mode_phase_cascade():
    """ADV-07: Hybrid cross-mode cascade: Phase 0 (Code) -> Phase 1 (Grounding) -> Phase 2 (Code).
    Verify Phase 1 entry waits for Phase 0 exit, and Phase 2 entry waits for Phase 1 finalize."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "doc"), exist_ok=True)
        open(os.path.join(tmpdir, "doc", "spec.md"), "w").close()
        open(os.path.join(tmpdir, "heal.sh"), "w").close()

        config = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "name": "Phase0_Code",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "run_job_two": False, "run_job_three": False, "iterate_test": False},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["doc/spec.md"]},
                },
                {
                    "name": "Phase1_Grounding",
                    "enabled": True,
                    "oracle": {"start_job": True},
                    "toggles": {
                        "run_job_one": False,
                        "run_job_two": False,
                        "run_job_three": False,
                        "iterate_test": False,
                    },
                    "validation": {"enabled": True, "post_validate": True, "validation_loops": 2},
                    "escalation_debate": {"loops": 2, "rounds": 1},
                    "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
                    "files": {"target_files": ["doc/spec.md"], "test_files": ["heal.sh"]},
                },
                {
                    "name": "Phase2_CodeFollowUp",
                    "enabled": True,
                    "toggles": {"run_job_one": True, "run_job_two": False, "run_job_three": False, "iterate_test": False},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": ["doc/spec.md"]},
                },
            ],
        }

        yaml_path = os.path.join(tmpdir, "hybrid_cascade.yml")
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_hybrid_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            # Phase 0 exit task
            assert "p0_job1_spec" in tasks
            # Phase 1 links to Phase 0 exit
            assert tasks["p1_oracle_spec"].depends_on == ["p0_job1_spec"]
            assert tasks["p1_autofix_spec"].depends_on == ["p1_oracle_spec"]
            assert tasks["p1_heal_spec"].depends_on == ["p1_autofix_spec"]
            assert tasks["p1_deliberate_spec"].depends_on == ["p1_heal_spec"]
            assert tasks["p1_apply_spec"].depends_on == ["p1_deliberate_spec"]
            assert tasks["p1_finalize_spec"].depends_on == ["p1_apply_spec"]

            # Phase 2 entry task waits for Phase 1 finalize
            assert "p2_job1_spec" in tasks
            assert tasks["p2_job1_spec"].depends_on == ["p1_finalize_spec"], (
                f"Expected p2_job1_spec to depend on p1_finalize_spec, got: {tasks['p2_job1_spec'].depends_on}"
            )
            print("  ✅ Hybrid multi-mode phase cascade barrier PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_glob_expansion_in_strategy_plan():
    """ADV-10: Glob/wildcard pattern expansion inside strategy_template.md manifest.
    Verify target_files glob, test_files glob, and context_files glob resolve correctly without pruning."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "docs"), exist_ok=True)
        open(os.path.join(tmpdir, "src", "mod_alpha.py"), "w").close()
        open(os.path.join(tmpdir, "src", "mod_beta.py"), "w").close()
        open(os.path.join(tmpdir, "tests", "test_mod_alpha.py"), "w").close()
        open(os.path.join(tmpdir, "tests", "test_mod_beta.py"), "w").close()
        open(os.path.join(tmpdir, "docs", "guide.md"), "w").close()

        plan_dir = os.path.join(tmpdir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("""# Strategy
## Scope Analysis
```yaml
files:
  target_files:
    - "src/mod_*.py"
  test_files:
    - "tests/test_mod_*.py"
  context_files_job:
    - "docs/*.md"
  context_files_test: []
```
""")

        config = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "name": "PhaseGlob",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {"run_job_one": True, "run_job_three": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": plan_path},
                }
            ],
        }

        yaml_path = os.path.join(tmpdir, "glob_plan.yml")
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_glob_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            # Both alpha and beta targets expanded
            assert "p0_job1_mod_alpha" in tasks
            assert "p0_job1_mod_beta" in tasks

            # Test files matched
            assert "tests/test_mod_alpha.py" in tasks["p0_job3_mod_alpha"].files
            assert "tests/test_mod_beta.py" in tasks["p0_job3_mod_beta"].files

            # Context file docs/guide.md inherited in read_files
            assert any(f.endswith("docs/guide.md") for f in tasks["p0_job1_mod_alpha"].read_files)
            print("  ✅ Glob pattern expansion in strategy plans PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_asymmetric_sticky_phases_discovery():
    """Verify Phase 0 readonly -> Phase 1 editable extracts targets without deadlock."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "docs"), exist_ok=True)
        open(os.path.join(tmpdir, "src", "target.py"), "w").close()
        open(os.path.join(tmpdir, "docs", "spec.md"), "w").close()

        plan_dir = os.path.join(tmpdir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("""# Strategy Plan
## Scope Analysis
```yaml
files:
  target_files:
    - "src/target.py"
  extra_editable_files: []
  test_files: []
  context_files_job:
    - "docs/spec.md"
  context_files_test: []
```
""")

        config = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "name": "Phase0_Readonly",
                    "enabled": True,
                    "sticky_phases": {"editable": False, "readonly": True},
                    "toggles": {"run_job_one": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": [plan_path]},
                    "plans": {"job_one_plan": plan_path},
                },
                {
                    "name": "Phase1_Editable",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": False},
                    "toggles": {"run_job_one": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": plan_path},
                },
            ],
        }

        yaml_path = os.path.join(tmpdir, "asym_sticky.yml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_asym_sticky_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            assert "p1_job1_target" in tasks, f"Expected p1_job1_target in tasks: {list(tasks.keys())}"
            print("  ✅ Asymmetric sticky phases discovery PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_sticky_phases_h2_markdown_header_fallback():
    """Verify that _parse_section extracts targets when plan uses H2 markdown headers."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
        open(os.path.join(tmpdir, "src", "h2_target.py"), "w").close()
        open(os.path.join(tmpdir, "tests", "test_h2.py"), "w").close()

        plan_dir = os.path.join(tmpdir, ".aider_factory", "markdown", "oracle_pre_plan")
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, "strategy_template.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("""# H2 Strategy Plan

## Target Files:
- `src/h2_target.py`

## Test Files:
- `tests/test_h2.py`
""")

        config = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "name": "PhaseH2",
                    "enabled": True,
                    "sticky_phases": {"editable": True, "readonly": True},
                    "toggles": {"run_job_one": True, "run_job_three": True},
                    "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
                    "files": {"target_files": []},
                    "plans": {"job_one_plan": plan_path},
                }
            ],
        }

        yaml_path = os.path.join(tmpdir, "test_h2.yml")
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_h2_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }
        with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
            code = f.read()
        try:
            for k in list(sys.modules.keys()):
                if "orchestrate" in k or "run_workflow" in k or k.startswith("aider_factory"):
                    del sys.modules[k]
            if python_module_dir in sys.path:
                sys.path.remove(python_module_dir)
            sys.path.insert(0, python_module_dir)
            exec(code, namespace)
            tasks = namespace["factory"].tasks

            assert "p0_job1_h2_target" in tasks, "Expected p0_job1_h2_target from H2 header parsing"
            assert tasks["p0_job3_h2_target"].files[0] == "tests/test_h2.py"
            print("  ✅ H2 markdown header manifest parsing PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


if __name__ == "__main__":
    print("Starting DAG Topology Tests...\n")
    test_code_mode_topology()
    test_review_mode_topology()
    test_grounding_gate_is_list()
    test_tee_writer_dual_output()
    test_ostee_windows_branch_sets_tee_writer()
    test_ostee_posix_branch_uses_fd_dup()
    test_ostee_windows_branch_real_io()
    test_tee_writer_flush_and_fileno_proxy()
    test_tee_writer_multiple_writes_interleaved()
    test_env_plan_do_workflow_topology()
    test_sticky_phases_5_field_extraction()
    test_review_mode_autofix_dependency()
    test_sticky_phases_multi_block_and_readonly()
    test_skipped_or_disabled_phase_barrier_propagation()
    test_multi_target_fan_in_fan_out_matrix()
    test_pre_edit_debate_triad_full_chain()
    test_hybrid_multi_mode_phase_cascade()
    test_glob_expansion_in_strategy_plan()
    test_sticky_phases_h2_markdown_header_fallback()
    test_asymmetric_sticky_phases_discovery()
    print("\nAll DAG Topology tests passed.")
