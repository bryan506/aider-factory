#!/usr/bin/env python3
import os
import sys
import shutil
import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
base_dir = os.path.join(script_dir, "mock_proj_rag")
run_workflow_path = os.path.join(script_dir, "../../python/run_workflow.py")
python_module_dir = os.path.join(script_dir, "../../python")

os.makedirs(os.path.join(base_dir, "src"), exist_ok=True)
open(os.path.join(base_dir, "src", "code.py"), "w").close()
open(os.path.join(base_dir, "src", "context.py"), "w").close()

print("Starting Zero-RAG Oracle Tests...\n")

def run_test(test_name, yaml_content, expected_checks):
    yaml_path = os.path.join(base_dir, "test.yml")
    with open(yaml_path, "w") as f:
        yaml.dump(yaml_content, f)

    old_argv = sys.argv
    sys.argv = ["run_workflow.py", yaml_path]

    namespace = {
        "__name__": "__test__",
        "__file__": run_workflow_path
    }

    sys.path.insert(0, python_module_dir)
    with open(run_workflow_path, "r") as f:
        code = f.read()

    try:
        exec(code, namespace)
        tasks = namespace["factory"].tasks

        print(f"Test {test_name}:")
        success = True
        
        for expected in expected_checks:
            task = next((t for t_id, t in tasks.items() if expected["id_substring"] in t_id), None)
            if not task:
                print(f"  ❌ Missing task with '{expected['id_substring']}' in ID")
                success = False
                continue
                
            coll = task.rag_env.get("ORACLE_COLLECTION")
            if coll != expected["collection"]:
                print(f"  ❌ Mismatch collection: Expected {expected['collection']}, got {coll}")
                success = False
                
            if "oracle" in expected:
                rf = task.oracle.get("read_files", [])
                for ef in expected["read_files"]:
                    if ef not in rf:
                        print(f"  ❌ Missing '{ef}' in oracle read_files: {rf}")
                        success = False
            
            if "deliberate" in expected:
                rf = task.deliberate.get("read_files", [])
                for ef in expected["read_files"]:
                    if ef not in rf:
                        print(f"  ❌ Missing '{ef}' in deliberate read_files: {rf}")
                        success = False

        if success:
            print("  🎉 PASS\n")
        else:
            print("  💥 FAIL\n")
            sys.exit(1)

    finally:
        sys.argv = old_argv
        sys.path.pop(0)

try:
    config_1 = {
        "working_directory": base_dir,
        "phases": [{
            "name": "Phase1",
            "enabled": True,
            "vector_store": {"collection_name": []},
            "toggles": {"run_ocr_rag": True, "run_job_one": False, "run_job_two": False, "iterate_test": False},
            "oracle": {"start_job": True},
            "models": {"architect_agent": "mock", "editor_agent": "mock"},
            "files": {
                "target_files": ["src/code.py"],
                "context_files_job": ["src/context.py"]
            }
        }]
    }
    
    expected_1 = [
        {
            "id_substring": "_oracle_", 
            "collection": "*",
            "oracle": True,
            "read_files": ["src/code.py", "src/context.py"]
        }
    ]
    run_test("1: Zero-RAG in REVIEW mode", config_1, expected_1)

    config_2 = {
        "working_directory": base_dir,
        "phases": [{
            "name": "Phase2",
            "enabled": True,
            "vector_store": {"collection_name": []},
            "oracle": {"start_job": False, "architect_oracle_chat": True},
            "toggles": {"run_job_one": True},
            "models": {"architect_agent": "mock", "editor_agent": "mock"},
            "files": {
                "target_files": ["src/code.py"],
                "context_files_job": ["src/context.py"]
            }
        }]
    }
    
    expected_2 = [
        {
            "id_substring": "job1_debate", 
            "collection": "*",
            "deliberate": True,
            "read_files": ["src/code.py", "src/context.py"]
        }
    ]
    run_test("2: Zero-RAG in CODE mode", config_2, expected_2)

finally:
    shutil.rmtree(base_dir)
