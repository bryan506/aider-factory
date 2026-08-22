#!/usr/bin/env python3
import os
import sys
import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(script_dir, "../../.."))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
if python_module_dir not in sys.path:
    sys.path.insert(0, python_module_dir)


def check_topology(test_name, config, required_substrings, forbidden_substrings):
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "mock_topo.yml")
        config = dict(config)
        config["working_directory"] = tmpdir
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)

        # Ensure mock files exist in the project directory
        mock_r = os.path.join(tmpdir, "mock.R")
        mock_md = os.path.join(tmpdir, "mock.md")
        heal_sh = os.path.join(tmpdir, "heal.sh")
        open(mock_r, "a").close()
        open(mock_md, "a").close()
        open(heal_sh, "a").close()

        old_argv = sys.argv
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        sys.argv = ["run_workflow.py", "mock_topo_session", yaml_path]
        namespace = {
            "__name__": "__test__",
            "__file__": os.path.join(python_module_dir, "run_workflow.py"),
        }

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

            assert success, f"{test_name} FAILED: Generated Tasks: {task_ids}"
            print(f"✅ {test_name} PASS")
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)


def test_code_mode_topology():
    """Test 1: Code Mode (job1 -> job2 -> job3 -> verify -> deliberate -> apply)"""
    code_config = {
        "working_directory": script_dir,
        "phases": [
            {
                "name": "Code",
                "enabled": True,
                "rag": {
                    "collection_name": "",
                    "batch": True,
                    "run_ocr_rag": False,
                },
                "oracle": {
                    "start_job": False,
                    "pre_edit_debate": {
                        "enabled": True,
                        "job_debate_template": "",
                    },
                },
                "toggles": {
                    "run_job_one": True,
                    "run_job_two": True,
                    "run_job_three": True,
                    "iterate_test": True,
                },
                "validation": {"enabled": False},
                "escalation_debate": {"loops": 2, "rounds": 1},
                "models": {
                    "architect_agent": "mock",
                    "editor_agent": "mock",
                    "editor_agent_test": "mock",
                },
                "files": {"target_files": ["mock.R"]},
            }
        ],
    }
    check_topology(
        "Code Mode Topology",
        code_config,
        ["job1", "job2", "job3", "verify", "deliberate", "apply"],
        ["oracle_mock.R", "autofix", "finalize"],
    )


def test_review_mode_topology():
    """Test 2: Review Mode (oracle -> autofix -> heal -> deliberate -> apply -> finalize)"""
    review_config = {
        "working_directory": script_dir,
        "phases": [
            {
                "name": "Review",
                "enabled": True,
                "rag": {
                    "collection_name": "",
                    "batch": False,
                    "run_ocr_rag": False,
                },
                "oracle": {"start_job": True},
                "toggles": {
                    "run_job_one": False,
                    "run_job_two": False,
                    "run_job_three": False,
                    "iterate_test": False,
                },
                "validation": {
                    "enabled": True,
                    "post_validate": True,
                    "validation_loops": 2,
                },
                "escalation_debate": {"loops": 2, "rounds": 1},
                "models": {
                    "architect_agent": "mock",
                    "editor_agent": "mock",
                    "editor_agent_test": "mock",
                },
                "files": {"target_files": ["mock.md"], "test_files": ["heal.sh"]},
            }
        ],
    }
    check_topology(
        "Review Mode Topology",
        review_config,
        ["oracle", "autofix", "heal", "deliberate", "apply", "finalize"],
        ["job1", "job2", "job3", "verify"],
    )


if __name__ == "__main__":
    print("Starting DAG Topology Tests...\n")
    test_code_mode_topology()
    test_review_mode_topology()
    print("\nAll DAG Topology tests passed.")
