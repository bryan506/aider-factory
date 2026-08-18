#!/usr/bin/env python3
import os
import sys
import shutil
import yaml

script_dir = os.path.dirname(os.path.abspath(__file__))
orig_cwd = os.getcwd()
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
        os.chdir(orig_cwd)
        sys.argv = old_argv
        if python_module_dir in sys.path:
            sys.path.remove(python_module_dir)

try:
    config_1 = {
        "working_directory": base_dir,
        "phases": [{
            "name": "Phase1",
            "enabled": True,
            "rag": {
                "collection_name": "",
                "batch": True,
                "run_ocr_rag": True
            },
            "toggles": {"run_job_one": False, "run_job_two": False, "iterate_test": False},
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
            "rag": {
                "collection_name": "",
                "batch": True,
                "run_ocr_rag": False
            },
            "oracle": {
                "start_job": False,
                "pre_edit_debate": {
                    "enabled": True,
                    "job_debate_template": []
                }
            },
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
    os.chdir(orig_cwd)
    if os.path.exists(base_dir):
        shutil.rmtree(base_dir)
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

script_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
if python_dir not in sys.path:
    sys.path.insert(0, python_dir)

import oracle_agent


class FakeMessage:
    def __init__(self, content):
        self.content = content

    def __getitem__(self, item):
        return self.content if item == "content" else None

    def get(self, item, default=None):
        return self.content if item == "content" else default


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)

    def __getitem__(self, item):
        return self.message if item == "message" else None

    def get(self, item, default=None):
        return self.message if item == "message" else default


class FakeResponse:
    def __init__(self, content="Direct LLM response without RAG."):
        self.choices = [FakeChoice(content)]

    def __getitem__(self, item):
        return self.choices if item == "choices" else None

    def get(self, item, default=None):
        return self.choices if item == "choices" else default


class TestZeroRagOracle(unittest.TestCase):
    def setUp(self):
        self.old_env = dict(os.environ)
        os.environ.pop("ORACLE_NO_RAG_INGEST", None)
        os.environ.pop("ORACLE_RETRIEVE_MODE", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)

    def test_extract_overrides_no_rag_flag(self):
        args = ["--no-rag", "What is the summary?"]
        out, do_list, did_clear, action, target = oracle_agent._extract_overrides(args)

        self.assertEqual(out, ["What is the summary?"])
        self.assertEqual(os.environ.get("ORACLE_NO_RAG_INGEST"), "1")
        self.assertEqual(os.environ.get("ORACLE_RETRIEVE_MODE"), "no_retrieve")

    @patch("litellm.completion")
    def test_oracle_agent_no_retrieve_mode_skips_vector_search(self, mock_completion):
        os.environ["ORACLE_AGENT_MODEL"] = "gemini/gemini-2.5-flash"
        os.environ["ORACLE_RETRIEVE_MODE"] = "no_retrieve"

        mock_completion.return_value = FakeResponse("Direct LLM response without RAG.")

        with patch("oracle_agent._retrieve") as mock_retrieve:
            args = ["oracle_agent.py", "Explain the concept directly."]
            with patch.object(sys, "argv", args):
                oracle_agent.main()

            mock_retrieve.assert_not_called()
            mock_completion.assert_called_once()


if __name__ == "__main__":
    unittest.main()
