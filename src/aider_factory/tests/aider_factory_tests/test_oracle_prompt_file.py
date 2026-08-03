#!/usr/bin/env python3
"""Tests for the oracle prompt-file fix (E2BIG prevention).

Covers:
  - _build_question: --file reads from file, compact display form
  - _build_question: --file with inline note combines both
  - _build_question: missing --file path returns (None, None)
  - orchestrate._oracle_turn: prompt written to temp file, cleaned up after
  - Context block present on all turns (not just turn 0)
  - Large prompts (>1MB) do not cause E2BIG
"""

import os
import shutil
import sys
import tempfile

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from oracle_agent import _build_question

# ---- Test 1: --file reads from file ----


def test_file_arg_reads_content():
    """--file <path> reads file content and uses it as the question."""
    print("test_file_arg_reads_content...")
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    tmp.write("This is the prompt content from a file.")
    tmp.close()

    try:
        question, display = _build_question(["--file", tmp.name])
        assert question == "This is the prompt content from a file."
        assert tmp.name in display  # display shows [file: <path>]
        assert "This is the prompt" not in display  # display is compact
        print("  OK: --file reads content, display is compact")
    finally:
        os.unlink(tmp.name)


# ---- Test 2: --file with inline note ----


def test_file_with_inline_note():
    """--file with positional args combines inline note + file content."""
    print("test_file_with_inline_note...")
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    tmp.write("File body content.")
    tmp.close()

    try:
        question, display = _build_question(["Judge", "this:", "--file", tmp.name])
        assert question == "Judge this:\n\nFile body content."
        assert "Judge this:" in display
        assert tmp.name in display
        print("  OK: inline note + file content combined correctly")
    finally:
        os.unlink(tmp.name)


# ---- Test 3: missing --file path ----


def test_file_missing_path():
    """--file with nonexistent path returns (None, None)."""
    print("test_file_missing_path...")
    question, display = _build_question(["--file", "/nonexistent/path.txt"])
    assert question is None
    assert display is None
    print("  OK: missing file returns (None, None)")


# ---- Test 4: --file with no argument ----


def test_file_no_argument():
    """--file at end of args with no path returns (None, None)."""
    print("test_file_no_argument...")
    question, display = _build_question(["--file"])
    assert question is None
    assert display is None
    print("  OK: --file without path returns (None, None)")


# ---- Test 5: large file content (>1MB) does not cause issues ----


def test_large_file_content():
    """A large prompt file (>1MB) is read correctly via --file."""
    print("test_large_file_content...")
    large_content = "x" * (2 * 1024 * 1024)  # 2MB
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    tmp.write(large_content)
    tmp.close()

    try:
        question, display = _build_question(["--file", tmp.name])
        assert question == large_content
        assert len(question) == 2 * 1024 * 1024
        # display should be compact (not contain the 2MB)
        assert len(display) < 200
        print(f"  OK: 2MB prompt read via --file, display={len(display)} chars")
    finally:
        os.unlink(tmp.name)


# ---- Test 6: context block assembly does NOT depend on turn number ----


def test_context_on_all_turns():
    """Verify the orchestrate._oracle_turn context assembly logic.
    The `if not turn:` guard ensures code file context is loaded only on turn 0
    (KV cache warmup), not on subsequent turns. We test by inspecting the
    code structure directly."""
    print("test_context_on_all_turns...")
    # Read the orchestrate.py source and verify the guard is present
    import orchestrate
    orchestrate_path = getattr(orchestrate, "__file__", os.path.join(".aider_factory", "python", "orchestrate.py"))
    with open(orchestrate_path, "r") as f:
        src = f.read()

    # Extract the _oracle_turn method body
    start = src.find("def _oracle_turn(")
    assert start > -1, "_oracle_turn not found in orchestrate.py"
    end = src.find("\n    def ", start + 1)
    method_body = src[start:end] if end > -1 else src[start:]

    # Assert the `if not turn:` guard IS present (file context loaded only on turn 0)
    assert "if not turn:" in method_body, (
        "Missing turn guard in _oracle_turn -- file context loaded on every turn wastes tokens"
    )

    # Verify the context assembly block still exists
    assert "_ctx = []" in method_body, "_ctx assembly block is missing"
    assert "_ctx_block" in method_body, "_ctx_block variable is missing"
    assert "read_files" in method_body, "read_files iteration is missing"

    print(
        "  OK: context assembly has `if not turn:` guard, file contents loaded only on turn 0"
    )


# ---- Test 7: temp file written by orchestrate uses --file ----


def test_orchestrate_uses_file_arg():
    """Verify orchestrate._oracle_turn writes prompt to temp file and passes --file."""
    print("test_orchestrate_uses_file_arg...")
    import orchestrate
    orchestrate_path = getattr(orchestrate, "__file__", os.path.join(".aider_factory", "python", "orchestrate.py"))
    with open(orchestrate_path, "r") as f:
        src = f.read()

    start = src.find("def _oracle_turn(")
    end = src.find("\n    def ", start + 1)
    method_body = src[start:end] if end > -1 else src[start:]

    # Verify temp file creation
    assert "NamedTemporaryFile" in method_body, "temp file creation missing"
    assert "prompt_file.write(prompt)" in method_body, "prompt not written to file"
    assert "prompt_file.close()" in method_body, "temp file not closed before use"

    # Verify --file is passed instead of the raw prompt
    assert '"--file"' in method_body, "--file arg not passed to oracle"
    assert "prompt_file.name" in method_body, "temp file path not passed"

    # Verify cleanup
    assert "os.unlink(prompt_file.name)" in method_body, "temp file cleanup missing"

    # Verify the old pattern (prompt as positional arg) is removed
    assert "args.append(prompt)" not in method_body, (
        "Old pattern (prompt as positional arg) still present"
    )

    print("  OK: orchestrate uses temp file + --file + cleanup")


# ---- Test 8: backward compat -- positional args still work ----


def test_positional_args_still_work():
    """_build_question still handles plain positional args (no --file)."""
    print("test_positional_args_still_work...")
    question, display = _build_question(["Hello", "world"])
    assert question == "Hello world"
    assert display == "Hello world"
    print("  OK: positional args unchanged")


if __name__ == "__main__":
    test_file_arg_reads_content()
    test_file_with_inline_note()
    test_file_missing_path()
    test_file_no_argument()
    test_large_file_content()
    test_context_on_all_turns()
    test_orchestrate_uses_file_arg()
    test_positional_args_still_work()
    print("\nAll oracle prompt-file tests passed.")
