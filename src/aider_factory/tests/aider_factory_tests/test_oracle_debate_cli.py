#!/usr/bin/env python3
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "../../python"))

from oracle_agent import _extract_overrides

print("Starting Oracle Debate CLI Tests...\n")


def test_debate_flag():
    os.environ.pop("ORACLE_DEBATE_MODE", None)
    os.environ.pop("ORACLE_DEBATE_LOOPS", None)

    args = ["--file", "test.txt", "--debate", "code", "--loops", "5", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["--file", "test.txt", "Query"], f"Unexpected args left: {out}"
    assert os.environ.get("ORACLE_DEBATE_MODE") == "code"
    assert os.environ.get("ORACLE_DEBATE_LOOPS") == "5"
    print("  ✅ --debate <mode> and --loops <N> parse correctly.")


def test_debate_default():
    os.environ.pop("ORACLE_DEBATE_MODE", None)
    os.environ.pop("ORACLE_DEBATE_LOOPS", None)

    # "Query" is the query string, which does not start with "-"
    # But because --debate checks `not args[i+1].startswith("-")`, it will consume "Query" as the mode!
    # Let's verify this behavior.
    args = ["--debate", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == [], f"Unexpected args left: {out}"
    assert (
        os.environ.get("ORACLE_DEBATE_MODE") == "query"
    )  # "Query" gets consumed as the mode
    assert os.environ.get("ORACLE_DEBATE_LOOPS") is None
    print(
        "  ✅ --debate without mode consumes the next token if it doesn't start with '-'."
    )

    args2 = ["--debate", "--no-rag", "Query2"]
    out2, do_list2, did_clear2, _, _ = _extract_overrides(args2)
    assert out2 == ["Query2"]
    assert (
        os.environ.get("ORACLE_DEBATE_MODE") == "code"
    )  # default mode because --no-rag starts with "-"

    print(
        "  ✅ --debate without mode falls back to 'code' if the next token starts with '-'."
    )


if __name__ == "__main__":
    test_debate_flag()
    test_debate_default()
    print("\n🎉 All CLI Oracle Debate Tests Passed!")
