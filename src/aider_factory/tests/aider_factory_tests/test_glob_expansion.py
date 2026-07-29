#!/usr/bin/env python3
import os
import glob
import shutil
import ast
import sys

# 1. Extract the function from run_workflow.py so we can test it directly
script_dir = os.path.dirname(os.path.abspath(__file__))
run_workflow_path = os.path.join(script_dir, "../../python/run_workflow.py")

with open(run_workflow_path, "r", encoding="utf-8") as f:
    code = f.read()

module = ast.parse(code)
func_code = ""
for node in module.body:
    if isinstance(node, ast.FunctionDef) and node.name == "_expand_file_list":
        func_code = ast.unparse(node)
        break

if not func_code:
    print("Error: Could not find _expand_file_list in run_workflow.py")
    sys.exit(1)

# Compile and define the function in this script's local scope
exec(func_code)

# 2. Setup mock filesystem
base_dir = os.path.join(script_dir, "mock_project_unit")
os.makedirs(os.path.join(base_dir, "R"), exist_ok=True)
os.makedirs(os.path.join(base_dir, "tests"), exist_ok=True)

# Create files out of order to ensure the function sorts them properly
open(os.path.join(base_dir, "R", "c_file.R"), "w").close()
open(os.path.join(base_dir, "R", "a_file.R"), "w").close()
open(os.path.join(base_dir, "R", "b_file.R"), "w").close()

open(os.path.join(base_dir, "tests", "test_c_file.R"), "w").close()
open(os.path.join(base_dir, "tests", "test_a_file.R"), "w").close()
open(os.path.join(base_dir, "tests", "test_b_file.R"), "w").close()

# 3. Run Tests
print("Starting _expand_file_list Unit Tests...\n")

try:
    # Test 1: Glob expansion and alphabetical sorting
    res1 = _expand_file_list(["R/*.R"], base_dir)
    assert res1 == ["R/a_file.R", "R/b_file.R", "R/c_file.R"], f"Test 1 failed: {res1}"
    print("✅ Test 1 Passed: Globs are expanded and alphabetically sorted.")

    # Test 2: Literal paths preserved (even if they don't exist)
    res2 = _expand_file_list(["R/literal.R", "R/another.R"], base_dir)
    assert res2 == ["R/literal.R", "R/another.R"], f"Test 2 failed: {res2}"
    print("✅ Test 2 Passed: Literal paths (no glob magic) are preserved verbatim.")

    # Test 3: Deduplication
    res3 = _expand_file_list(["R/*.R", "R/a_file.R", "R/c_file.R"], base_dir)
    assert res3 == ["R/a_file.R", "R/b_file.R", "R/c_file.R"], f"Test 3 failed: {res3}"
    print("✅ Test 3 Passed: Duplicate files are cleanly filtered out.")

    # Test 4: Empty/None
    assert _expand_file_list(None, base_dir) == []
    assert _expand_file_list([], base_dir) == []
    print("✅ Test 4 Passed: Empty and None inputs are handled safely.")

    # Test 5: The Symmetry Alignment Scenario
    res_target = _expand_file_list(["R/*.R"], base_dir)
    res_test = _expand_file_list(["tests/test_*.R"], base_dir)
    assert res_target[0] == "R/a_file.R" and res_test[0] == "tests/test_a_file.R"
    assert res_target[1] == "R/b_file.R" and res_test[1] == "tests/test_b_file.R"
    assert res_target[2] == "R/c_file.R" and res_test[2] == "tests/test_c_file.R"
    print("✅ Test 5 Passed: Alphabetical symmetry guarantees 1:1 index mapping.")

    print("\n🎉 All _expand_file_list tests passed successfully!\n")

finally:
    # Cleanup
    shutil.rmtree(base_dir)
