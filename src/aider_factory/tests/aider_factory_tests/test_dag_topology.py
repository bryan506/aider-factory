#!/usr/bin/env python3
import os
import sys
import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

print("Starting DAG Topology Tests...\n")

def check_topology(test_name, config, required_substrings, forbidden_substrings):
    yaml_path = os.path.join(script_dir, "mock_topo.yml")
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)
    
    old_argv = sys.argv
    sys.argv = ["run_workflow.py", yaml_path]
    namespace = {"__name__": "__test__", "__file__": os.path.join(python_module_dir, "run_workflow.py")}
    
    with open(os.path.join(python_module_dir, "run_workflow.py"), "r") as f:
        code = f.read()
    
    try:
        exec(code, namespace)
        tasks = namespace["factory"].tasks
        task_ids = " ".join(tasks.keys())
        
        success = True
        for req in required_substrings:
            if req not in task_ids:
                print(f"  ❌ Missing expected node type: {req}")
                success = False
        for forb in forbidden_substrings:
            if forb in task_ids:
                print(f"  ❌ Found forbidden node type: {forb}")
                success = False
                
        if success:
            print(f"✅ {test_name} PASS")
        else:
            print(f"💥 {test_name} FAIL")
            print(f"   Generated Tasks: {task_ids}")
            sys.exit(1)
    finally:
        sys.argv = old_argv
        if os.path.exists(yaml_path):
            os.remove(yaml_path)

# Test 1: Code Mode (job1 -> job2 -> iterate -> debate -> apply)
code_config = {
    "working_directory": script_dir,
    "phases": [{
        "name": "Code", "enabled": True, "batch": True,
        "oracle": {"start_job": False, "architect_oracle_chat": True},
        "toggles": {"run_job_one": True, "run_job_two": True, "iterate_test": True},
        "oracle_toggles": {"debate_loops": 2, "debate_rounds": 1},
        "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
        "files": {"target_files": ["mock.R"]}
    }]
}
check_topology("Code Mode Topology", code_config, 
               ["job1", "job2", "verify", "deliberate", "apply"], 
               ["oracle_mock.R", "autofix", "finalize"])

# Test 2: Review Mode (oracle -> autofix -> heal -> debate -> apply -> finalize)
review_config = {
    "working_directory": script_dir,
    "phases": [{
        "name": "Review", "enabled": True, "batch": False,
        "oracle": {"start_job": True},
        "toggles": {"run_job_one": False, "run_job_two": False, "iterate_test": False},
        "oracle_toggles": {"post_validate": True, "debate_loops": 2, "debate_rounds": 1},
        "models": {"architect_agent": "mock", "editor_agent": "mock", "editor_agent_test": "mock"},
        "files": {"target_files": ["mock.md"], "test_files": ["heal.sh"]}
    }]
}
check_topology("Review Mode Topology", review_config, 
               ["oracle", "autofix", "heal", "deliberate", "apply", "finalize"], 
               ["job1", "job2", "verify"])
