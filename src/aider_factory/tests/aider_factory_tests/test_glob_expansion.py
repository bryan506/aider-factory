#!/usr/bin/env python3
import os
import glob
import shutil
import ast
import sys

# 1. Import _expand_file_list from run_workflow.py
script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
if python_module_dir not in sys.path:
    sys.path.insert(0, python_module_dir)

from run_workflow import _expand_file_list

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

import unittest

class TestGlobExpansion(unittest.TestCase):
    def test_glob_expansion(self):
        print("Starting _expand_file_list Unit Tests...\n")

        try:
            # Test 1: Glob expansion and alphabetical sorting
            res1 = _expand_file_list(["R/*.R"], base_dir)
            self.assertEqual(res1, ["R/a_file.R", "R/b_file.R", "R/c_file.R"])
            print("✅ Test 1 Passed: Globs are expanded and alphabetically sorted.")

            # Test 2: Literal paths preserved (even if they don't exist)
            res2 = _expand_file_list(["R/literal.R", "R/another.R"], base_dir)
            self.assertEqual(res2, ["R/literal.R", "R/another.R"])
            print("✅ Test 2 Passed: Literal paths (no glob magic) are preserved verbatim.")

            # Test 3: Deduplication
            res3 = _expand_file_list(["R/*.R", "R/a_file.R", "R/c_file.R"], base_dir)
            self.assertEqual(res3, ["R/a_file.R", "R/b_file.R", "R/c_file.R"])
            print("✅ Test 3 Passed: Duplicate files are cleanly filtered out.")

            # Test 4: Empty/None
            self.assertEqual(_expand_file_list(None, base_dir), [])
            self.assertEqual(_expand_file_list([], base_dir), [])
            print("✅ Test 4 Passed: Empty and None inputs are handled safely.")

            # Test 5: The Symmetry Alignment Scenario
            res_target = _expand_file_list(["R/*.R"], base_dir)
            res_test = _expand_file_list(["tests/test_*.R"], base_dir)
            self.assertEqual(res_target[0], "R/a_file.R")
            self.assertEqual(res_test[0], "tests/test_a_file.R")
            self.assertEqual(res_target[1], "R/b_file.R")
            self.assertEqual(res_test[1], "tests/test_b_file.R")
            self.assertEqual(res_target[2], "R/c_file.R")
            self.assertEqual(res_test[2], "tests/test_c_file.R")
            print("✅ Test 5 Passed: Alphabetical symmetry guarantees 1:1 index mapping.")

            print("\n🎉 All _expand_file_list tests passed successfully!\n")

        finally:
            # Cleanup
            shutil.rmtree(base_dir)

if __name__ == "__main__":
    unittest.main()
