#!/usr/bin/env python3
import os
import shutil
import sys
import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(script_dir, "../../.."))
base_dir = os.path.join(script_dir, "mock_proj_dag")
run_workflow_path = os.path.join(script_dir, "../../python/run_workflow.py")
python_module_dir = os.path.join(script_dir, "../../python")

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
if python_module_dir not in sys.path:
    sys.path.insert(0, python_module_dir)


def setup_mock_fs():
    os.makedirs(os.path.join(base_dir, "R"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "tests"), exist_ok=True)
    open(os.path.join(base_dir, "R", "a.R"), "w").close()
    open(os.path.join(base_dir, "R", "b.R"), "w").close()
    open(os.path.join(base_dir, "tests", "test_a.R"), "w").close()
    open(os.path.join(base_dir, "tests", "test_b.R"), "w").close()
    open(os.path.join(base_dir, "tests", "global.R"), "w").close()


def run_test(test_name, yaml_content, expected_mapping):
    orig_cwd = os.getcwd()
    yaml_path = os.path.join(base_dir, "test.yml")
    with open(yaml_path, "w") as f:
        yaml.dump(yaml_content, f)

    old_argv = sys.argv
    os.chdir(base_dir)
    sys.argv = ["run_workflow.py", "mock_routing_session", yaml_path]

    namespace = {
        "__name__": "__test__",  # prevents execute_pipeline from running
        "__file__": run_workflow_path,
    }

    with open(run_workflow_path, "r") as f:
        code = f.read()

    try:
        exec(code, namespace)
        tasks = namespace["factory"].tasks

        # Verify: In 4-job architecture, Job 3 is the test-writing task that binds target + test file
        actual_mapping = {}
        for t_id, task in tasks.items():
            if "job3" in t_id:
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
                print(
                    f"  ❌ Mismatch for {tgt}: Expected {expected_test}, got {actual_mapping[tgt]}"
                )
                success = False
            else:
                print(f"  ✅ {tgt} -> {expected_test}")

        assert success, f"Test {test_name} failed mapping assertions"
        print("  🎉 PASS\n")
    finally:
        sys.argv = old_argv
        os.chdir(orig_cwd)


def test_yaml_dag_routing():
    setup_mock_fs()
    orig_cwd = os.getcwd()
    try:
        # 1. Alphabetical Symmetry
        config_1 = {
            "working_directory": base_dir,
            "phases": [
                {
                    "name": "Phase1",
                    "enabled": True,
                    "rag": {
                        "collection_name": "",
                        "batch": True,
                        "run_ocr_rag": False,
                    },
                    "toggles": {"run_job_one": False, "run_job_three": True},
                    "models": {
                        "architect_agent": "mock",
                        "editor_agent": "mock",
                        "editor_agent_test": "mock",
                    },
                    "files": {
                        "target_files": ["R/*.R"],
                        "test_files": ["tests/test_*.R"],
                    },
                }
            ],
        }
        expected_1 = {"R/a.R": "tests/test_a.R", "R/b.R": "tests/test_b.R"}
        run_test("1: Alphabetical Symmetry", config_1, expected_1)

        # 2. Broadcast
        config_2 = {
            "working_directory": base_dir,
            "phases": [
                {
                    "name": "Phase2",
                    "enabled": True,
                    "rag": {
                        "collection_name": "",
                        "batch": True,
                        "run_ocr_rag": False,
                    },
                    "toggles": {"run_job_one": False, "run_job_three": True},
                    "models": {
                        "architect_agent": "mock",
                        "editor_agent": "mock",
                        "editor_agent_test": "mock",
                    },
                    "files": {
                        "target_files": ["R/*.R"],
                        "test_files": ["tests/global.R"],
                    },
                }
            ],
        }
        expected_2 = {"R/a.R": "tests/global.R", "R/b.R": "tests/global.R"}
        run_test("2: Broadcast Test Script", config_2, expected_2)

        # 3. Fallback
        config_3 = {
            "working_directory": base_dir,
            "test_naming_and_path": "tests/auto_{stem}.R",
            "phases": [
                {
                    "name": "Phase3",
                    "enabled": True,
                    "rag": {
                        "collection_name": "",
                        "batch": True,
                        "run_ocr_rag": False,
                    },
                    "toggles": {"run_job_one": False, "run_job_three": True},
                    "models": {
                        "architect_agent": "mock",
                        "editor_agent": "mock",
                        "editor_agent_test": "mock",
                    },
                    "files": {"target_files": ["R/*.R"]},
                }
            ],
        }
        expected_3 = {"R/a.R": "tests/auto_a.R", "R/b.R": "tests/auto_b.R"}
        run_test("3: Fallback Convention", config_3, expected_3)

        # 4. Out of bounds fallback (3 targets, 2 tests)
        open(os.path.join(base_dir, "R", "c.R"), "w").close()
        config_4 = {
            "working_directory": base_dir,
            "test_naming_and_path": "tests/out_{stem}.R",
            "phases": [
                {
                    "name": "Phase4",
                    "enabled": True,
                    "rag": {
                        "collection_name": "",
                        "batch": True,
                        "run_ocr_rag": False,
                    },
                    "toggles": {"run_job_one": False, "run_job_three": True},
                    "models": {
                        "architect_agent": "mock",
                        "editor_agent": "mock",
                        "editor_agent_test": "mock",
                    },
                    "files": {
                        "target_files": ["R/*.R"],
                        "test_files": ["tests/test_a.R", "tests/test_b.R"],
                    },
                }
            ],
        }
        expected_4 = {
            "R/a.R": "tests/test_a.R",
            "R/b.R": "tests/test_b.R",
            "R/c.R": "tests/out_c.R",
        }
        run_test("4: Out-of-bounds Fallback", config_4, expected_4)

        # 5. Explicit Toggles DAG Propagation
        config_5 = {
            "working_directory": base_dir,
            "phases": [
                {
                    "name": "Phase5",
                    "enabled": True,
                    "rag": {
                        "collection_name": "",
                        "batch": True,
                        "run_ocr_rag": False,
                    },
                    "toggles": {
                        "run_job_one": True,
                        "run_job_two": False,
                        "pair_programming": True,
                        "yes_always": False,
                        "auto_accept_architect": False,
                        "disable_playwright": False,
                        "auto_commits": False,
                        "suggest_shell_commands": False,
                        "detect_urls": False,
                    },
                    "models": {"architect_agent": "mock", "editor_agent": "mock"},
                    "files": {
                        "target_files": ["R/a.R"],
                        "context_files_job": ["R/b.R"],
                    },
                }
            ],
        }

        yaml_path_5 = os.path.join(base_dir, "test5.yml")
        with open(yaml_path_5, "w") as f:
            yaml.dump(config_5, f)

        old_argv = sys.argv
        os.chdir(base_dir)
        sys.argv = ["run_workflow.py", "mock_routing_session_5", yaml_path_5]
        namespace_5 = {
            "__name__": "__test__",
            "__file__": run_workflow_path,
        }
        with open(run_workflow_path, "r") as f:
            code_5 = f.read()
        try:
            exec(code_5, namespace_5)
            tasks_5 = namespace_5["factory"].tasks
            job1_task = next(t for t_id, t in tasks_5.items() if "job1" in t_id)
            assert job1_task.pair_programming is True
            assert job1_task.yes_always is False
            assert job1_task.auto_accept_architect is False
            assert job1_task.disable_playwright is False
            assert job1_task.auto_commits is False
            assert job1_task.suggest_shell_commands is False
            assert job1_task.detect_urls is False
            print(
                "Test 5: Explicit Toggles DAG Propagation:\n  ✅ All task flags matched explicit False values\n  🎉 PASS\n"
            )
        finally:
            sys.argv = old_argv
            os.chdir(orig_cwd)

    finally:
        os.chdir(orig_cwd)
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)


if __name__ == "__main__":
    print("Starting YAML DAG Routing Tests...\n")
    test_yaml_dag_routing()

