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


def test_walk_repo_ignore_and_dedup():
    import tempfile

    for expected_ign in (".aider_factory", "ai-agent-config", "skeleton", "tempfiles", "secrets"):
        assert expected_ign in IGNORE_DEFAULT, f"Missing {expected_ign} in IGNORE_DEFAULT"

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "arch_repo")
        os.makedirs(os.path.join(repo, "skeleton"), exist_ok=True)
        with open(os.path.join(repo, "skeleton", "skip.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
        with open(os.path.join(repo, "AGENTS.md"), "w", encoding="utf-8") as fh:
            fh.write("harness\n")
        with open(os.path.join(repo, "guide.rmd"), "w", encoding="utf-8") as fh:
            fh.write("# Guide\n")
        with open(os.path.join(repo, "guide.html"), "w", encoding="utf-8") as fh:
            fh.write("<html></html>\n")

        found = list(_walk_repo(repo, IGNORE_DEFAULT, CODE_EXTS_DEFAULT, TEXT_DOC_EXTS_DEFAULT))
        assert len(found) == 1
        assert found[0][1] == "text_doc"
        assert found[0][2] == "arch_repo/guide.rmd"
    print("  ✅ _walk_repo enforces IGNORE_DEFAULT, AGENT_HARNESS_FILES, and .rmd/.html priority.")


if __name__ == "__main__":
    test_classify()
    test_fenced_chunking()
    test_type_flag_parser()
    test_walk_repo_ignore_and_dedup()
    print("\n🎉 All Phase 3+4 Architecture Tests Passed!")
