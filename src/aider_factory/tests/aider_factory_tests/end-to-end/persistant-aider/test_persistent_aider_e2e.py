#!/usr/bin/env python3
import os
import sys
from unittest.mock import MagicMock, patch

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(script_dir, "../../../../.."))
python_module_dir = os.path.join(project_dir, ".aider_factory", "python")

sys.path.insert(0, python_module_dir)

print("==================================================")
print("Starting E2E Persistent Aider Smoke Test...")
print("==================================================")

# Set the YAML configuration path in argv so run_workflow loads our test config
config_path = os.path.join(script_dir, "env_e2e_persistent.yml")
sys.argv = [sys.argv[0], config_path]


# Helper class to simulate a real character-by-character stream
class MockStream:
    def __init__(self, text):
        self.text = text
        self.index = 0

    def read(self, size=1):
        if self.index >= len(self.text):
            return ""
        res = self.text[self.index : self.index + size]
        self.index += size
        return res

    def close(self):
        pass


# We mock Popen and run to intercept Aider and Oracle subprocesses
with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
    # 1. Setup Aider Popen mock with side effect
    def mock_popen_side_effect(*args, **kwargs):
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.stdout = MockStream("Thinking...\nPROPOSAL: Fix the leverage logic.\n")
        return proc

    mock_popen.side_effect = mock_popen_side_effect

    # 2. Setup Oracle/Gate run mock with side effect
    def mock_run_side_effect(*args, **kwargs):
        cmd = args[0]
        res = MagicMock()
        # If running validate or checking the gate, return failure to trigger debate
        if any(x in str(cmd) for x in ["validate", "apply_evidence", "test_dummy.sh"]):
            res.returncode = 1
            res.stdout = "Validation failed: tripped quotes detected."
            res.stderr = ""
        else:
            # Oracle run succeeds with an objection to trigger Turn 2
            res.returncode = 0
            res.stdout = "VERDICT: OBJECT - I object to this!"
            res.stderr = "[oracle] 1 source chunk(s) · mode=top_k"
        return res

    mock_run.side_effect = mock_run_side_effect

    # Import and run the workflow
    import run_workflow

    # Execute the pipeline
    run_workflow.factory.execute_pipeline()

    # Verify Aider Popen was called
    assert mock_popen.called, "Aider subprocess.Popen was never called"
    assert mock_popen.call_count >= 1, (
        f"Expected Aider to be called, got {mock_popen.call_count} calls"
    )

    # Verify Oracle run was called
    assert mock_run.called, "Oracle subprocess.run was never called"

    # Check Aider arguments
    all_popen_calls = mock_popen.call_args_list

    # First turn of the debate
    turn1_args = all_popen_calls[0].args[0]
    turn1_env = all_popen_calls[0].kwargs.get("env", {})
    assert "aider" in turn1_args[0]
    assert "--restore-chat-history" in turn1_args, (
        "Turn 1 must specify restore history to write to custom file"
    )
    assert "--chat-history-file" in turn1_args, "Turn 1 must specify chat history file"
    assert turn1_env.get("PYTHONHASHSEED") == "0", "Missing PYTHONHASHSEED=0 on Turn 1"

    # Second turn of the debate (if we simulated multiple turns)
    if len(all_popen_calls) > 1:
        turn2_args = all_popen_calls[1].args[0]
        turn2_env = all_popen_calls[1].kwargs.get("env", {})
        assert "--restore-chat-history" in turn2_args, (
            "Turn 2 must restore chat history"
        )
        assert "--chat-history-file" in turn2_args, (
            "Turn 2 must specify chat history file"
        )
        assert turn2_env.get("PYTHONHASHSEED") == "0", (
            "Missing PYTHONHASHSEED=0 on Turn 2"
        )

print("\n✅ E2E Persistent Aider Smoke Test PASS")
