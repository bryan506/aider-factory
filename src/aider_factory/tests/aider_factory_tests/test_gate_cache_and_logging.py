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


def test_gate_result_caching():
    print("Testing AiderFactory gate result caching...")
    factory = AiderFactory(project_dir=tempfile.gettempdir())
    
    # Pre-populate gate cache with True
    gate_cmd = "echo 'mock test passing'"
    factory.last_test_result[gate_cmd] = True

    verdict_file = os.path.join(tempfile.gettempdir(), "test_verdict.md")
    ledger_file = os.path.join(tempfile.gettempdir(), "test_ledger.json")

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


if __name__ == "__main__":
    test_gate_result_caching()
    test_aggregate_log()
    print("\n🎉 All Gate Cache & Logging Tests Passed!")
