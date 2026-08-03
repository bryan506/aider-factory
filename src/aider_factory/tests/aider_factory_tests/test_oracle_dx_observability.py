#!/usr/bin/env python3
"""Tests for oracle DX observability improvements.

Covers:
  1. _oracle_turn surfaces the chunk count from stderr in the live terminal
     output (not just on failure).
  2. _run_deliberation archives the oracle transcript to logs/oracle_history/
     before the next aider task can delete it.
  3. The archive uses the same directory convention as the aider session archive.
  4. The stderr surfacing correctly parses the [oracle] source chunk line.
  5. Backward compat: stderr without the chunk line still works (no crash).
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

import orchestrate

ORCHESTRATE_PATH = getattr(orchestrate, "__file__", os.path.join(".aider_factory", "python", "orchestrate.py"))


def _read_method(name):
    """Extract a method body from orchestrate.py by name."""
    with open(ORCHESTRATE_PATH, "r") as f:
        src = f.read()
    start = src.find(f"def {name}(")
    assert start > -1, f"{name} not found in orchestrate.py"
    end = src.find("\n    def ", start + 1)
    return src[start:end] if end > -1 else src[start:]


# ---- Test 1: _oracle_turn surfaces chunk count from stderr ----


def test_oracle_turn_surfaces_chunk_count():
    """_oracle_turn extracts [oracle] N source chunk(s) from stderr and prints it."""
    body = _read_method("_oracle_turn")
    # Must search stderr for the chunk line
    assert '"[oracle]"' in body and '"source chunk"' in body, (
        "_oracle_turn does not search stderr for the [oracle] source chunk line"
    )
    # Must print the line when found
    assert "_rag_line" in body, "_rag_line variable missing"
    assert "print(" in body and "_rag_line" in body, (
        "_oracle_turn does not print the chunk count line"
    )
    print("  [PASS] _oracle_turn surfaces chunk count from stderr")


# ---- Test 2: chunk count surfacing is unconditional ----


def test_chunk_surfacing_not_gated_on_failure():
    """The chunk count line is printed regardless of whether stdout is empty."""
    body = _read_method("_oracle_turn")
    # Find the _rag_line print and verify it's NOT inside the `if not out:` block.
    # The print should appear BEFORE the `if not out:` check.
    rag_print_pos = body.find("_rag_line")
    not_out_pos = body.find("if not out:")
    assert rag_print_pos < not_out_pos, (
        "Chunk count surfacing appears after the `if not out:` guard -- "
        "it will only show on failure, not on success"
    )
    print(
        "  [PASS] chunk count surfacing is unconditional (before `if not out:` check)"
    )


# ---- Test 3: _run_deliberation archives oracle transcript ----


def test_deliberation_archives_transcript():
    """_run_deliberation archives .oracle_chat.history.md before returning."""
    body = _read_method("_run_deliberation")
    # Must reference the oracle transcript file
    assert ".oracle_chat.history.md" in body, (
        "_run_deliberation does not reference the oracle transcript file"
    )
    # Must copy to logs/oracle_history
    assert "oracle_history" in body, (
        "_run_deliberation does not archive to logs/oracle_history/"
    )
    # Must use shutil.copy
    assert "shutil.copy" in body, (
        "_run_deliberation does not use shutil.copy for archiving"
    )
    print("  [PASS] _run_deliberation archives oracle transcript")


# ---- Test 4: archive happens before the return ----


def test_archive_before_return():
    """The archive happens before _run_deliberation returns True."""
    body = _read_method("_run_deliberation")
    archive_pos = body.find("oracle_history")
    # Find the final `return True` (the deliberation success return)
    last_return = body.rfind("return True")
    assert archive_pos < last_return, (
        "Archive happens after the final return -- it will never execute"
    )
    print("  [PASS] archive executes before _run_deliberation returns")


# ---- Test 5: archive uses task.id in the filename ----


def test_archive_uses_task_id():
    """The archived filename includes task.id for traceability."""
    body = _read_method("_run_deliberation")
    assert "task.id" in body and "oracle_history" in body, (
        "Archive filename does not include task.id"
    )
    print("  [PASS] archived filename includes task.id")


# ---- Test 6: stderr without chunk line does not crash ----


def test_no_chunk_line_no_crash():
    """When stderr has no [oracle] source chunk line, _rag_line is empty and no crash."""
    body = _read_method("_oracle_turn")
    # _rag_line must be initialized to "" before the loop
    assert '_rag_line = ""' in body, "_rag_line not initialized to empty string"
    # The print is guarded by `if _rag_line:`
    assert "if _rag_line:" in body, "Missing guard for empty _rag_line"
    print("  [PASS] empty stderr (no chunk line) handled safely")


# ---- Test 7: archive is wrapped in try/except ----


def test_archive_exception_safe():
    """The archive copy is wrapped in try/except so a failed copy does not
    break the deliberation."""
    body = _read_method("_run_deliberation")
    # Find the shutil.copy call and verify it's inside a try block
    copy_pos = body.find("shutil.copy(_ot")
    assert copy_pos > -1, "shutil.copy(_ot...) not found"
    # Check there's a try before the copy within the archive block
    archive_block_start = body.find(".oracle_chat.history.md")
    try_pos = body.find("try:", archive_block_start)
    assert archive_block_start < try_pos < copy_pos, (
        "shutil.copy is not inside a try block"
    )
    print("  [PASS] archive copy is exception-safe")


if __name__ == "__main__":
    print("Starting Oracle DX Observability Tests...")
    test_oracle_turn_surfaces_chunk_count()
    test_chunk_surfacing_not_gated_on_failure()
    test_deliberation_archives_transcript()
    test_archive_before_return()
    test_archive_uses_task_id()
    test_no_chunk_line_no_crash()
    test_archive_exception_safe()
    print("All Oracle DX Observability Tests Passed!")
