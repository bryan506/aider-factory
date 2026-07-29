#!/usr/bin/env python3
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "../../python"))

from oracle_agent import _extract_overrides

print("Starting Oracle Clear CLI Tests...\n")


def test_clear_standalone():
    args = ["--clear"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)
    assert out == []
    assert did_clear is True
    assert do_list is False
    print("  ✅ standalone --clear parses and drops cleanly.")


def test_clear_consumes_oracle():
    args = ["--clear", "oracle", "My Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)
    assert out == ["My Query"], f"Expected ['My Query'], got {out}"
    assert did_clear is True
    print("  ✅ --clear oracle consumes the token and leaves the query.")


def test_clear_with_files():
    args = ["--file", "test.txt", "--clear", "oracle", "My Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)
    assert out == ["--file", "test.txt", "My Query"]
    assert did_clear is True
    print("  ✅ --clear works transparently with positional and file args.")


if __name__ == "__main__":
    test_clear_standalone()
    test_clear_consumes_oracle()
    test_clear_with_files()
    print("\n🎉 All CLI Oracle Clear Tests Passed!")
