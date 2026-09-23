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
    print("\nAll DAG Topology tests passed.")
