#!/usr/bin/env python3
import os
import sys
from unittest.mock import patch

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from orchestrate import AiderFactory, Task

print("Starting Orchestrate Subprocess Env Tests...\n")

factory = AiderFactory(script_dir)
test_task = Task(
    id="test_oracle_task",
    oracle={"template": "my_template.md", "out": "out.md", "full_document": True},
    skip_aider=True
)

# We patch subprocess.run to just capture the 'env' kwargs instead of running bash
with patch('subprocess.run') as mock_run:
    mock_run.return_value.returncode = 0
    factory._run_oracle_job(test_task)
    
    # Assert subprocess was called
    assert mock_run.called
    
    # Extract the env dictionary passed to subprocess
    called_env = mock_run.call_args.kwargs.get("env", {})
    
    assert called_env.get("ORACLE_JOB") == "1", "Missing ORACLE_JOB flag"
    assert called_env.get("ORACLE_JOB_TEMPLATE") == "my_template.md"
    assert called_env.get("ORACLE_JOB_OUT") == "out.md"
    assert called_env.get("ORACLE_JOB_FULLDOC") == "1"

print("✅ Subprocess Environment Injection PASS")
