import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../python"))
from oracle_agent import _extract_overrides
from rag_manager import (
    CODE_EXTS_DEFAULT,
    IGNORE_DEFAULT,
    TEXT_DOC_EXTS_DEFAULT,
    _chunk,
    _classify,
    _walk_repo,
)

print("Starting Phase 3+4 Comprehensive Tests...\n")


def test_classify():
    assert _classify("test.py", CODE_EXTS_DEFAULT, TEXT_DOC_EXTS_DEFAULT) == "code"
    assert _classify("test.R", CODE_EXTS_DEFAULT, TEXT_DOC_EXTS_DEFAULT) == "code"
    assert _classify("test.txt", CODE_EXTS_DEFAULT, TEXT_DOC_EXTS_DEFAULT) == "text_doc"
    assert _classify("test.md", CODE_EXTS_DEFAULT, TEXT_DOC_EXTS_DEFAULT) == "text_doc"
    assert _classify("test.pdf", CODE_EXTS_DEFAULT, TEXT_DOC_EXTS_DEFAULT) == "ocr_doc"
    assert _classify("test.unknown", CODE_EXTS_DEFAULT, TEXT_DOC_EXTS_DEFAULT) is None
    print("  ✅ _classify accurately routes code, text_docs, and ocr_docs.")


def test_fenced_chunking():
    # Construct an oversized fenced block
    oversized = "```python\n" + ("print('hello')\n" * 100) + "```"
    chunks = _chunk(oversized, chunk_size_chars=400, chunk_overlap_chars=50)

    assert len(chunks) > 1, "Failed to split oversized block"
    for c in chunks:
        assert c.startswith("```python\n"), "Chunk lost its opening fence"
        assert c.endswith("```\n"), "Chunk lost its closing fence"
    print("  ✅ _chunk perfectly preserves markdown fences across oversized splits.")


def test_type_flag_parser():
    args = ["--type", "docs", "My Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)
    assert out == ["My Query"]
    assert os.environ.get("ORACLE_TYPE_FILTER") == "docs"

    args = ["--type", "code", "My Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)
    assert os.environ.get("ORACLE_TYPE_FILTER") == "code"
    print("  ✅ --type [code|docs] CLI parser works correctly.")


if __name__ == "__main__":
    test_classify()
    test_fenced_chunking()
    test_type_flag_parser()
    print("\n🎉 All Phase 3+4 Architecture Tests Passed!")
