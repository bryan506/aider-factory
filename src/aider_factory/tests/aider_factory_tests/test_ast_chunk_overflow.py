#!/usr/bin/env python3
"""Tests for the _ast_chunk oversized-leaf fallback and _text_split_fallback helper.

Covers:
  - _text_split_fallback: line-boundary splitting, overlap, edge cases
  - _ast_chunk: oversized leaf nodes split instead of emitted as-is
  - Regression: normal code unchanged by the fix
"""
import sys
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from rag_manager import _ast_chunk, _text_split_fallback


# --- _text_split_fallback tests ---

def test_text_split_fallback_basic():
    """Chunks are <= max_chars and cover all input (no overlap)."""
    print("test_text_split_fallback_basic...")
    text = "\n".join(f"line {i}: {'x' * 50}" for i in range(100))
    chunks = _text_split_fallback(text, max_chars=500, overlap_lines=0)
    for i, c in enumerate(chunks):
        # Each chunk should be roughly <= max_chars.  The last line appended
        # before the flush can push slightly over because we check *before*
        # appending, so allow one extra line of headroom.
        assert len(c) <= 560, f"Chunk {i} too large: {len(c)}"
    reassembled = "".join(chunks)
    assert reassembled == text, "Chunks do not cover all input (no overlap mode)"
    print(f"  OK: {len(chunks)} chunks, all <= max_chars")


def test_text_split_fallback_overlap():
    """overlap_lines causes shared lines between consecutive chunks."""
    print("test_text_split_fallback_overlap...")
    lines = [f"line-{i}\n" for i in range(20)]
    text = "".join(lines)
    chunks = _text_split_fallback(text, max_chars=80, overlap_lines=2)
    assert len(chunks) > 1, "Should produce multiple chunks"
    # Check that the last 2 lines of chunk N appear at the start of chunk N+1
    for i in range(len(chunks) - 1):
        tail = chunks[i].splitlines()[-2:]
        head = chunks[i + 1].splitlines()[:2]
        assert tail == head, f"Overlap missing between chunks {i} and {i+1}: tail={tail}, head={head}"
    print(f"  OK: {len(chunks)} chunks with 2-line overlap verified")


def test_text_split_fallback_single_long_line():
    """A single line exceeding max_chars is split at character boundaries."""
    print("test_text_split_fallback_single_long_line...")
    text = "x" * 5000
    chunks = _text_split_fallback(text, max_chars=500)
    assert len(chunks) > 1, f"Expected multiple chunks, got {len(chunks)}"
    for i, c in enumerate(chunks):
        assert len(c) <= 500, f"Chunk {i} exceeds max_chars: {len(c)}"
    # All content should be recoverable (with overlap, total chars > original)
    assert chunks[0][:100] == text[:100], "First chunk should start with original content"
    assert chunks[-1][-100:] == text[-100:], "Last chunk should end with original content"
    print(f"  OK: {len(chunks)} chunks from single long line, all <= max_chars")


def test_text_split_fallback_empty():
    """Empty string produces no chunks (no content to embed)."""
    print("test_text_split_fallback_empty...")
    chunks = _text_split_fallback("", max_chars=500)
    assert len(chunks) == 0, f"Expected [], got {chunks}"
    print("  OK: empty input returns []")


# --- _ast_chunk tests ---

def test_ast_chunk_oversized_leaf_python():
    """A Python file with a giant string literal should split into multiple chunks <= max_chars."""
    print("test_ast_chunk_oversized_leaf_python...")
    big_string = "x" * 10000
    code = f'SCHEMA = """{big_string}"""\n'
    chunks = _ast_chunk(code, "python", max_chars=2000)
    assert len(chunks) > 1, f"Expected >1 chunks from 10K string, got {len(chunks)}"
    for i, (text, ls, le, sym) in enumerate(chunks):
        assert len(text) <= 2100, f"Chunk {i} exceeds max_chars: {len(text)}"
    total_text = "".join(t for t, *_ in chunks)
    assert big_string[:100] in total_text, "Content lost during splitting"
    print(f"  OK: {len(chunks)} chunks, all <= max_chars")


def test_ast_chunk_oversized_leaf_r():
    """An R file with a huge character assignment should split."""
    print("test_ast_chunk_oversized_leaf_r...")
    big_val = "x" * 8000
    code = f'my_var <- "{big_val}"\n'
    chunks = _ast_chunk(code, "r", max_chars=2000)
    assert len(chunks) >= 1, "Should produce at least 1 chunk"
    for i, (text, ls, le, sym) in enumerate(chunks):
        assert len(text) <= 2100, f"Chunk {i} exceeds max_chars: {len(text)}"
    print(f"  OK: {len(chunks)} chunks from oversized R assignment")


def test_ast_chunk_normal_unaffected():
    """Normal small functions should produce the same results as before the fix."""
    print("test_ast_chunk_normal_unaffected...")
    code = """
def foo():
    return 1

def bar():
    return 2

class Baz:
    def method(self):
        pass
"""
    chunks = _ast_chunk(code, "python", max_chars=2000)
    assert len(chunks) > 0, "Should parse normal code"
    # All chunks should be small (well under max_chars)
    for i, (text, ls, le, sym) in enumerate(chunks):
        assert len(text) < 500, f"Normal chunk unexpectedly large: {len(text)}"
    print(f"  OK: {len(chunks)} normal chunks, unchanged by fix")


def test_ast_chunk_symbol_preserved():
    """Symbol metadata should still be extracted after the fix."""
    print("test_ast_chunk_symbol_preserved...")
    code = """
def my_function():
    x = 1
    return x
"""
    chunks = _ast_chunk(code, "python", max_chars=2000)
    assert len(chunks) > 0
    texts = [t for t, *_ in chunks]
    found = any("my_function" in t for t in texts)
    assert found, "Function name not found in any chunk"
    print("  OK: symbol content preserved")


def test_ast_chunk_mixed():
    """File with normal functions + one oversized leaf: both types coexist."""
    print("test_ast_chunk_mixed...")
    big_string = "y" * 6000
    code = f'''
def small_func():
    return 42

BIG_DATA = """{big_string}"""

def another_func():
    return 99
'''
    chunks = _ast_chunk(code, "python", max_chars=2000)
    texts = [t for t, *_ in chunks]
    # Should have chunks for small_func, split chunks for BIG_DATA, and another_func
    has_small = any("small_func" in t for t in texts)
    has_another = any("another_func" in t for t in texts)
    has_big_content = any("yyy" in t for t in texts)
    assert has_small, "small_func missing"
    assert has_another, "another_func missing"
    assert has_big_content, "BIG_DATA content missing"
    # No chunk should exceed max_chars (with small tolerance for the append-then-check pattern)
    for i, (text, *_) in enumerate(chunks):
        assert len(text) <= 2100, f"Chunk {i} exceeds limit: {len(text)}"
    print(f"  OK: {len(chunks)} chunks, mixed normal + oversized leaf")


def test_no_chunk_exceeds_model_context():
    """Integration: simulate MARKET_mock.py scale (146K single string) -> no chunk > 2000 chars."""
    print("test_no_chunk_exceeds_model_context...")
    giant = "z" * 146000
    code = f'SCHEMA = r"""{giant}"""\n'
    chunks = _ast_chunk(code, "python", max_chars=2000)
    assert len(chunks) > 50, f"Expected many chunks from 146K, got {len(chunks)}"
    max_len = max(len(t) for t, *_ in chunks)
    assert max_len <= 2100, f"Largest chunk is {max_len} chars, exceeds limit"
    print(f"  OK: {len(chunks)} chunks from 146K input, largest = {max_len} chars")


if __name__ == "__main__":
    test_text_split_fallback_basic()
    test_text_split_fallback_overlap()
    test_text_split_fallback_single_long_line()
    test_text_split_fallback_empty()
    test_ast_chunk_oversized_leaf_python()
    test_ast_chunk_oversized_leaf_r()
    test_ast_chunk_normal_unaffected()
    test_ast_chunk_symbol_preserved()
    test_ast_chunk_mixed()
    test_no_chunk_exceeds_model_context()
    print("\nAll _ast_chunk overflow tests passed.")
