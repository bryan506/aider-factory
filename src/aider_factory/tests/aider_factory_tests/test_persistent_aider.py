#!/usr/bin/env python3
import os
import sys
from unittest.mock import MagicMock, patch

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

from orchestrate import AiderFactory, Task

def test_persistent_aider_cli_and_env():
    factory = AiderFactory(script_dir)
    test_task = Task(
        id="test_persistent_aider_task",
        model="openai/minimax-229b-ud-iq4nl:LATEST",
        architect_api_base="http://localhost:11435/v1",
    )

    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.stdout.read.side_effect = ["a", "b", "c", ""]
        mock_process.poll.return_value = 0
        mock_popen.return_value = mock_process

        history_file_path = "temp/test_history.md"
        factory._aider_ask_turn(
            test_task,
            message="Hello",
            read_files=[__file__],
            label="turn 1/3",
            history_file=history_file_path,
        )

        assert mock_popen.called, "subprocess.Popen was not called"

        called_args = mock_popen.call_args.args[0]
        called_env = mock_popen.call_args.kwargs.get("env", {})

        assert "--restore-chat-history" in called_args, (
            "Missing --restore-chat-history flag"
        )
        assert "--chat-history-file" in called_args, "Missing --chat-history-file flag"
        assert history_file_path in called_args, "Missing history file path in args"
        assert "--read" in called_args, "Missing --read flag"
        assert __file__ in called_args, "Missing read file in args"

        assert called_env.get("PYTHONHASHSEED") == "0", (
            "Missing or incorrect PYTHONHASHSEED"
        )
        assert called_env.get("AIDER_ARCHITECT") == "false", (
            "AIDER_ARCHITECT should be false"
        )


if __name__ == "__main__":
    test_persistent_aider_cli_and_env()
    print("✅ Persistent Aider CLI & Env Injection PASS")
