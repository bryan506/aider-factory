#!/usr/bin/env python3
import sys
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from rag_manager import _maybe_create_index, IVF_PQ_MIN_ROWS

class MockTable:
    def __init__(self, count, should_fail=False):
        self.count = count
        self.should_fail = should_fail
        self.called_with = None

    def count_rows(self):
        return self.count

    def create_index(self, metric):
        if self.should_fail:
            raise RuntimeError("mock failure")
        self.called_with = metric

print("Starting IVF Index Tests...")

# Test 1: Below threshold -> no-op
t1 = MockTable(IVF_PQ_MIN_ROWS - 1)
_maybe_create_index(t1, "test_table")
assert t1.called_with is None, "Failed: create_index called below threshold"
print("  ✅ Below threshold check PASS")

# Test 2: Above threshold -> triggers with metric="cosine"
t2 = MockTable(IVF_PQ_MIN_ROWS + 1)
_maybe_create_index(t2, "test_table")
assert t2.called_with == "cosine", f"Failed: create_index called with {t2.called_with}"
print("  ✅ Above threshold check PASS")

# Test 3: Failure during creation is caught
t3 = MockTable(IVF_PQ_MIN_ROWS + 1, should_fail=True)
try:
    _maybe_create_index(t3, "test_table")
    print("  ✅ Exception correctly caught PASS")
except Exception as e:
    print(f"  ❌ Failed: Exception propagated: {e}")
    sys.exit(1)

print("\n🎉 All IVF Index tests passed!")
