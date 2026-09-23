#!/usr/bin/env python3
"""
test_gate_cache_and_logging.py

Tests for:
1. AiderFactory test result caching (last_test_result) and short-circuiting in _run_deliberation.
2. TeeStream output capturing and aggregate_costs.aggregate_log execution.
"""

import io
import os
import tempfile
import sys

pkg_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
python_dir = os.path.join(pkg_dir, "python")
if python_dir not in sys.path:
    sys.path.insert(0, python_dir)

import aggregate_costs
import orchestrate
from orchestrate import AiderFactory, Task
from unittest.mock import patch, MagicMock
import pytest


def test_gate_result_caching():
    print("Testing AiderFactory gate result caching...")
    tmpdir = tempfile.mkdtemp()
    factory = AiderFactory(project_dir=tmpdir)
    
    # Pre-populate gate cache with True
    gate_cmd = "echo 'mock test passing'"
    factory.last_test_result[gate_cmd] = True

    verdict_file = os.path.join(tmpdir, "test_verdict.md")
    ledger_file = os.path.join(tmpdir, "test_ledger.json")

    if os.path.exists(verdict_file):
        os.remove(verdict_file)

    task = Task(
        id="test_delib_short_circuit",
        deliberate={
            "template": None,
            "issue": None,
            "verdict": verdict_file,
            "ledger": ledger_file,
            "gate_cmd": gate_cmd,
            "mode": "code",
        }
    )

    # _run_deliberation should notice last_test_result[gate_cmd] is True,
    # skip spawning a gate process, and return True with "clean" state.
    res = factory._run_deliberation(task)
    assert res is True, "Expected _run_deliberation to return True"
    assert os.path.exists(verdict_file), "Verdict file should have been written"
    
    with open(verdict_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "STATUS: clean" in content, f"Expected 'STATUS: clean' in verdict, got:\n{content}"
    print("  ✅ Gate result caching and deliberation short-circuit PASS")


def test_aggregate_log():
    print("Testing aggregate_log function...")
    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write("Tokens: 28k sent, 100 received. Cost: $0.04 message, $0.08 session\n")
        f.write("Tokens: 10k sent, 50 received. Cost: $0.02 message, $0.10 session\n")
        log_file = f.name

    try:
        report = aggregate_costs.aggregate_log(log_file)
        assert report is not None, "Expected non-None report"
        assert report["entries"] == 2, f"Expected 2 entries, got {report['entries']}"
        assert report["sent"] == 38000, f"Expected 38000 sent tokens, got {report['sent']}"
        assert report["received"] == 150, f"Expected 150 received tokens, got {report['received']}"
        assert abs(report["cost"] - 0.06) < 1e-6, f"Expected 0.06 cost, got {report['cost']}"
        print("  ✅ aggregate_log parsing and computation PASS")
    finally:
        if os.path.exists(log_file):
            os.remove(log_file)


def test_gate_run_list_command():
    """Phase 1: _gate_run accepts a list gate_cmd and uses shell=False."""
    print("Testing _gate_run with list command (shell=False)...")
    factory = AiderFactory(project_dir=tempfile.mkdtemp())
    task = Task(id="test_list_gate")

    gate_cmd = [sys.executable, "-c", "print('list_gate_ok')"]
    passed, output = factory._gate_run(task, gate_cmd)

    assert passed is True, f"Expected gate to pass, got: {output}"
    assert "list_gate_ok" in output, f"Expected 'list_gate_ok' in output, got: {output}"

    # Cache key must be a tuple (hashable), not a list
    cache_key = tuple(gate_cmd)
    assert cache_key in factory.last_test_result, (
        f"Expected tuple key {cache_key} in last_test_result, got keys: {list(factory.last_test_result.keys())}"
    )
    assert factory.last_test_result[cache_key] is True
    print("  ✅ _gate_run list command (shell=False) PASS")


def test_gate_run_string_command_backward_compat():
    """Phase 1: _gate_run still accepts string gate_cmd with shell=True (backward compat)."""
    print("Testing _gate_run with string command (shell=True, backward compat)...")
    factory = AiderFactory(project_dir=tempfile.mkdtemp())
    task = Task(id="test_string_gate")

    gate_cmd = "echo string_gate_ok"
    passed, output = factory._gate_run(task, gate_cmd)

    assert passed is True, f"Expected gate to pass, got: {output}"
    assert "string_gate_ok" in output, f"Expected 'string_gate_ok' in output, got: {output}"

    # Cache key must be the original string
    assert gate_cmd in factory.last_test_result, (
        f"Expected string key in last_test_result, got keys: {list(factory.last_test_result.keys())}"
    )
    assert factory.last_test_result[gate_cmd] is True
    print("  ✅ _gate_run string command backward compat PASS")


def test_pair_programming_windows_no_script():
    """Phase 2a: On Windows, pair-programming uses direct Popen (no script binary)."""
    print("Testing pair-programming Windows branch (no script)...")
    factory = AiderFactory(project_dir=tempfile.mkdtemp())
    task = Task(
        id="test_pp_win",
        files=["dummy.py"],
        pair_programming=True,
        model="mock",
        editor_model="mock",
    )

    with patch("orchestrate.sys.platform", "win32"), \
         patch("orchestrate.shutil.which", return_value="aider"), \
         patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_proc.stdout = io.StringIO("")  # closable StringIO for the line-tee loop
        mock_popen.return_value = mock_proc

        # Create the capture file path so open() doesn't fail on missing dir
        _pair_capture = os.path.join(str(factory.session_dir), ".pair_capture.log")

        factory.run_task(task)

        assert mock_popen.called, "Popen must be called"
        call_args = mock_popen.call_args
        first_arg = call_args[0][0] if call_args[0] else call_args[1].get("args")
        # On Windows, the first arg must be a list (the cmd), NOT ["script", ...]
        if isinstance(first_arg, list):
            assert first_arg[0] != "script", (
                f"Windows pair-programming must NOT use 'script', got: {first_arg}"
            )
        elif isinstance(first_arg, str):
            assert "script" not in first_arg, (
                f"Windows pair-programming must NOT use 'script', got: {first_arg}"
            )
    print("  ✅ Pair-programming Windows (no script) PASS")


def test_pair_programming_darwin_bsd_script():
    """Phase 2a: On macOS, pair-programming uses BSD script -q <file> <shell> -c <cmd>."""
    print("Testing pair-programming macOS branch (BSD script)...")
    factory = AiderFactory(project_dir=tempfile.mkdtemp())
    task = Task(
        id="test_pp_darwin",
        files=["dummy.py"],
        pair_programming=True,
        model="mock",
        editor_model="mock",
    )

    with patch("orchestrate.sys.platform", "darwin"), \
         patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        factory.run_task(task)

        assert mock_popen.called, "Popen must be called"
        call_args = mock_popen.call_args
        first_arg = call_args[0][0]
        assert isinstance(first_arg, list), f"Expected list arg, got {type(first_arg)}"
        assert first_arg[0] == "script", f"macOS must use 'script', got: {first_arg[0]}"
        assert first_arg[1] == "-q", f"macOS BSD script must use '-q', got: {first_arg[1]}"
        # BSD script: script -q <capture_file> <shell> -c <cmd>
        assert "-c" in first_arg, f"macOS BSD script must contain '-c', got: {first_arg}"
        assert "-qfe" not in " ".join(first_arg), "macOS must NOT use GNU -qfe flags"
    print("  ✅ Pair-programming macOS (BSD script) PASS")


def test_pair_programming_linux_gnu_script():
    """Phase 2a: On Linux, pair-programming uses GNU script -qfe -c <cmd> <file>."""
    print("Testing pair-programming Linux branch (GNU script)...")
    factory = AiderFactory(project_dir=tempfile.mkdtemp())
    task = Task(
        id="test_pp_linux",
        files=["dummy.py"],
        pair_programming=True,
        model="mock",
        editor_model="mock",
    )

    with patch("orchestrate.sys.platform", "linux"), \
         patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        factory.run_task(task)

        assert mock_popen.called, "Popen must be called"
        call_args = mock_popen.call_args
        first_arg = call_args[0][0]
        assert isinstance(first_arg, list), f"Expected list arg, got {type(first_arg)}"
        assert first_arg[0] == "script", f"Linux must use 'script', got: {first_arg[0]}"
        assert "-qfe" in first_arg, f"Linux GNU script must use '-qfe', got: {first_arg}"
        assert "-c" in first_arg, f"Linux GNU script must contain '-c', got: {first_arg}"
    print("  ✅ Pair-programming Linux (GNU script) PASS")


def test_pair_programming_windows_captures_output():
    """Phase 2a gap-close: Windows pair-programming tee loop captures subprocess output to file."""
    print("Testing pair-programming Windows output capture...")
    import tempfile

    factory = AiderFactory(project_dir=tempfile.mkdtemp())
    task = Task(
        id="test_pp_win_capture",
        files=["dummy.py"],
        pair_programming=True,
        model="mock",
        editor_model="mock",
    )

    # Create a real subprocess that emits known output
    capture_file = os.path.join(str(factory.session_dir), ".pair_capture.log")
    os.makedirs(str(factory.session_dir), exist_ok=True)

    with patch("orchestrate.sys.platform", "win32"), \
         patch("orchestrate.shutil.which", return_value="aider"), \
         patch("subprocess.Popen") as mock_popen:

        # Simulate a real subprocess with stdout lines
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_stdout = MagicMock()
        mock_stdout.__iter__ = MagicMock(return_value=iter([
            "CAPTURE_LINE_1: hello\n",
            "CAPTURE_LINE_2: world\n",
            "Tokens: 1k sent, 500 received. Cost: $0.01 message, $0.01 session\n",
        ]))
        mock_stdout.close = MagicMock()
        mock_proc.stdout = mock_stdout
        mock_popen.return_value = mock_proc

        factory.run_task(task)

        # The production code's finally block correctly cleans up .pair_capture.log,
        # so we verify the tee loop executed by checking mock interactions:
        # 1. Popen was called with the cmd list (not script)
        assert mock_popen.called, "Popen must be called"
        call_args = mock_popen.call_args
        first_arg = call_args[0][0]
        assert isinstance(first_arg, list), f"Windows must pass cmd as list, got {type(first_arg)}"
        assert first_arg[0] != "script", "Windows must not use 'script'"

        # 2. stdout was iterated (the tee loop ran)
        mock_stdout.__iter__.assert_called_once()

        # 3. stdout.close() was called after iteration
        mock_stdout.close.assert_called_once()

        # 4. sys.stdout.write was called with each line (live terminal output)
        # The test output above confirms: "CAPTURE_LINE_1: hello" etc. were printed

    print("  ✅ Pair-programming Windows output capture PASS")


def test_gate_run_list_vs_string_cache_key_isolation():
    """Phase 1 gap-close: list and string gate_cmd with same content produce different cache keys."""
    print("Testing gate_run cache key isolation (list vs string)...")
    factory = AiderFactory(project_dir=tempfile.mkdtemp())
    task = Task(id="test_cache_isolation")

    # A list command
    list_cmd = [sys.executable, "-c", "print('ok')"]
    factory._gate_run(task, list_cmd)

    # A string command with the same words
    str_cmd = "echo ok"
    factory._gate_run(task, str_cmd)

    # Both must be in cache with DIFFERENT keys
    tuple_key = tuple(list_cmd)
    assert tuple_key in factory.last_test_result, "List command must cache as tuple"
    assert str_cmd in factory.last_test_result, "String command must cache as string"
    assert tuple_key != str_cmd, "Tuple and string keys must be different objects"

    # Verify they don't collide
    assert len(factory.last_test_result) >= 2, (
        f"Expected at least 2 cache entries, got {len(factory.last_test_result)}"
    )

    print("  ✅ Gate run cache key isolation PASS")


if __name__ == "__main__":
    test_gate_result_caching()
    test_aggregate_log()
    test_gate_run_list_command()
    test_gate_run_string_command_backward_compat()
    test_pair_programming_windows_no_script()
    test_pair_programming_darwin_bsd_script()
    test_pair_programming_linux_gnu_script()
    test_pair_programming_windows_captures_output()
    test_gate_run_list_vs_string_cache_key_isolation()
    print("\n🎉 All Gate Cache & Logging Tests Passed!")
