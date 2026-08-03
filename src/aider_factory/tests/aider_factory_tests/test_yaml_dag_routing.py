#!/usr/bin/env python3
import os
import sys
import shutil
import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
base_dir = os.path.join(script_dir, "mock_proj_dag")
run_workflow_path = os.path.join(script_dir, "../../python/run_workflow.py")
python_module_dir = os.path.join(script_dir, "../../python")

# Setup Mock Filesystem
os.makedirs(os.path.join(base_dir, "R"), exist_ok=True)
os.makedirs(os.path.join(base_dir, "tests"), exist_ok=True)
open(os.path.join(base_dir, "R", "a.R"), "w").close()
open(os.path.join(base_dir, "R", "b.R"), "w").close()
open(os.path.join(base_dir, "tests", "test_a.R"), "w").close()
open(os.path.join(base_dir, "tests", "test_b.R"), "w").close()
open(os.path.join(base_dir, "tests", "global.R"), "w").close()

print("Starting YAML DAG Routing Tests...\n")

def run_test(test_name, yaml_content, expected_mapping):
    yaml_path = os.path.join(base_dir, "test.yml")
    with open(yaml_path, "w") as f:
        yaml.dump(yaml_content, f)
    
    old_argv = sys.argv
    sys.argv = ["run_workflow.py", yaml_path]
    
    namespace = {
        "__name__": "__test__", # prevents execute_pipeline from running
        "__file__": run_workflow_path
    }
    
    sys.path.insert(0, python_module_dir)
    with open(run_workflow_path, "r") as f:
        code = f.read()
    
    try:
        exec(code, namespace)
        tasks = namespace["factory"].tasks
        
        # Verify
        actual_mapping = {}
        for t_id, task in tasks.items():
            if "job2" in t_id:
                if len(task.files) >= 2:
                    test_file = task.files[0]
                    target_file = task.files[1]
                    actual_mapping[target_file] = test_file
        
        print(f"Test {test_name}:")
        success = True
        for tgt, expected_test in expected_mapping.items():
            if tgt not in actual_mapping:
                print(f"  ❌ Missing target {tgt} in tasks")
                success = False
            elif actual_mapping[tgt] != expected_test:
                print(f"  ❌ Mismatch for {tgt}: Expected {expected_test}, got {actual_mapping[tgt]}")
                success = False
            else:
                print(f"  ✅ {tgt} -> {expected_test}")
        
        if success:
            print("  🎉 PASS\n")
        else:
            print("  💥 FAIL\n")
            sys.exit(1)
            
    finally:
        sys.argv = old_argv
        sys.path.pop(0)

try:
    # Scenarios
    # 1. Alphabetical Symmetry
    config_1 = {
        "working_directory": base_dir,
        "phases": [{
            "name": "Phase1",
            "enabled": True,
            "rag": {
                "collection_name": "",
                "batch": True,
                "run_ocr_rag": False
            },
            "toggles": {"run_job_one": False, "run_job_two": True},
            "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
            "files": {
                "target_files": ["R/*.R"],
                "test_files": ["tests/test_*.R"]
            }
        }]
    }
    expected_1 = {"R/a.R": "tests/test_a.R", "R/b.R": "tests/test_b.R"}
    run_test("1: Alphabetical Symmetry", config_1, expected_1)

    # 2. Broadcast
    config_2 = {
        "working_directory": base_dir,
        "phases": [{
            "name": "Phase2",
            "enabled": True,
            "rag": {
                "collection_name": "",
                "batch": True,
                "run_ocr_rag": False
            },
            "toggles": {"run_job_one": False, "run_job_two": True},
            "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
            "files": {
                "target_files": ["R/*.R"],
                "test_files": ["tests/global.R"]
            }
        }]
    }
    expected_2 = {"R/a.R": "tests/global.R", "R/b.R": "tests/global.R"}
    run_test("2: Broadcast Test Script", config_2, expected_2)

    # 3. Fallback
    config_3 = {
        "working_directory": base_dir,
        "test_naming_and_path": "tests/auto_{stem}.R",
        "phases": [{
            "name": "Phase3",
            "enabled": True,
            "rag": {
                "collection_name": "",
                "batch": True,
                "run_ocr_rag": False
            },
            "toggles": {"run_job_one": False, "run_job_two": True},
            "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
            "files": {
                "target_files": ["R/*.R"]
            }
        }]
    }
    expected_3 = {"R/a.R": "tests/auto_a.R", "R/b.R": "tests/auto_b.R"}
    run_test("3: Fallback Convention", config_3, expected_3)

    # 4. Out of bounds fallback (3 targets, 2 tests)
    open(os.path.join(base_dir, "R", "c.R"), "w").close()
    config_4 = {
        "working_directory": base_dir,
        "test_naming_and_path": "tests/out_{stem}.R",
        "phases": [{
            "name": "Phase4",
            "enabled": True,
            "rag": {
                "collection_name": "",
                "batch": True,
                "run_ocr_rag": False
            },
            "toggles": {"run_job_one": False, "run_job_two": True},
            "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
            "files": {
                "target_files": ["R/*.R"],
                "test_files": ["tests/test_a.R", "tests/test_b.R"]
            }
        }]
    }
    expected_4 = {
        "R/a.R": "tests/test_a.R", 
        "R/b.R": "tests/test_b.R",
        "R/c.R": "tests/out_c.R" # Fallback triggered!
    }
    run_test("4: Out-of-bounds Fallback", config_4, expected_4)

finally:
    shutil.rmtree(base_dir)

