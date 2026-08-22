#!/usr/bin/env python3
import os
import sys
import yaml
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
    rag_env={
        "ORACLE_COLLECTION": "my_collection",
        "ORACLE_RAG_DB_DIR": "my_db_dir"
    },
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

from unittest.mock import MagicMock

# --- Aider Toggle CLI Flag and Environment Variable Override Tests ---

def test_aider_toggle_overrides_when_false():
    factory = AiderFactory(script_dir, session_name="test_flag_override_false")
    task = Task(
        id="test_toggles_false",
        files=["dummy.py"],
        pair_programming=False,
        yes_always=False,
        auto_accept_architect=False,
        disable_playwright=False,
        auto_commits=False,
        suggest_shell_commands=False,
        detect_urls=False,
        map_tokens=0,
        map_refresh="manual",
        map_multiplier_no_files=0.0,
        max_chat_history_tokens=50000,
    )

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        factory.run_task(task)

        assert mock_popen.called, "subprocess.Popen was not called"
        args, kwargs = mock_popen.call_args
        cmd_str = args[0] if isinstance(args[0], str) else " ".join(args[0])
        env = kwargs.get("env", {})

        # 1. Verify AIDER_* env overrides
        assert env.get("AIDER_YES_ALWAYS") == "false"
        assert env.get("AIDER_AUTO_ACCEPT_ARCHITECT") == "false"
        assert env.get("AIDER_DISABLE_PLAYWRIGHT") == "false"
        assert env.get("AIDER_AUTO_COMMITS") == "false"
        assert env.get("AIDER_SUGGEST_SHELL_COMMANDS") == "false"
        assert env.get("AIDER_DETECT_URLS") == "false"

        # 2. Verify negative CLI flags for symmetric options
        assert "--no-auto-accept-architect" in cmd_str
        assert "--no-auto-commits" in cmd_str
        assert "--no-suggest-shell-commands" in cmd_str
        assert "--no-detect-urls" in cmd_str

        # 3. Verify asymmetric store_true flags are NOT passed as --no-*
        assert "--yes-always" not in cmd_str
        assert "--no-yes-always" not in cmd_str
        assert "--disable-playwright" not in cmd_str
        assert "--no-disable-playwright" not in cmd_str

        # 4. Verify numeric and string options
        assert "--map-tokens 0" in cmd_str
        assert "--map-refresh manual" in cmd_str
        assert "--max-chat-history-tokens 50000" in cmd_str

        # 5. Verify compiled session config file
        session_conf_path = os.path.join(str(factory.session_dir), ".aider.conf.yml")
        assert os.path.exists(session_conf_path), "Session-scoped .aider.conf.yml must be written"
        with open(session_conf_path, "r", encoding="utf-8") as cf:
            conf_data = yaml.safe_load(cf)
        assert conf_data.get("yes-always") is False
        assert conf_data.get("auto-accept-architect") is False
        assert conf_data.get("auto-commits") is False
        assert conf_data.get("disable-playwright") is False
        assert conf_data.get("suggest-shell-commands") is False
        assert conf_data.get("detect-urls") is False
        assert conf_data.get("map-tokens") == 0
        assert conf_data.get("map-refresh") == "manual"
        assert conf_data.get("max-chat-history-tokens") == "50000"

    print("✅ Aider Toggle Overrides (False) PASS")


def test_aider_toggle_overrides_when_true():
    factory = AiderFactory(script_dir, session_name="test_flag_override_true")
    task = Task(
        id="test_toggles_true",
        files=["dummy.py"],
        pair_programming=False,
        yes_always=True,
        auto_accept_architect=True,
        disable_playwright=True,
        auto_commits=True,
        suggest_shell_commands=True,
        detect_urls=True,
    )

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        factory.run_task(task)

        assert mock_popen.called, "subprocess.Popen was not called"
        args, kwargs = mock_popen.call_args
        cmd_str = args[0] if isinstance(args[0], str) else " ".join(args[0])
        env = kwargs.get("env", {})

        assert env.get("AIDER_YES_ALWAYS") == "true"
        assert env.get("AIDER_AUTO_ACCEPT_ARCHITECT") == "true"
        assert env.get("AIDER_DISABLE_PLAYWRIGHT") == "true"
        assert env.get("AIDER_AUTO_COMMITS") == "true"
        assert env.get("AIDER_SUGGEST_SHELL_COMMANDS") == "true"
        assert env.get("AIDER_DETECT_URLS") == "true"

        assert "--yes-always" in cmd_str
        assert "--auto-accept-architect" in cmd_str
        assert "--disable-playwright" in cmd_str
        assert "--auto-commits" in cmd_str
        assert "--suggest-shell-commands" in cmd_str
        assert "--detect-urls" in cmd_str

        # Verify compiled session config file
        session_conf_path = os.path.join(str(factory.session_dir), ".aider.conf.yml")
        assert os.path.exists(session_conf_path), "Session-scoped .aider.conf.yml must be written"
        with open(session_conf_path, "r", encoding="utf-8") as cf:
            conf_data = yaml.safe_load(cf)
        assert conf_data.get("yes-always") is True
        assert conf_data.get("auto-accept-architect") is True
        assert conf_data.get("auto-commits") is True
        assert conf_data.get("disable-playwright") is True
        assert conf_data.get("suggest-shell-commands") is True
        assert conf_data.get("detect-urls") is True

    print("✅ Aider Toggle Overrides (True) PASS")


def test_aider_multi_phase_toggle_transition():
    """Verify that sequential tasks across different phases dynamically recompile session .aider.conf.yml."""
    factory = AiderFactory(script_dir, session_name="test_multi_phase_transition")

    task_phase1 = Task(
        id="phase1_paired_job",
        files=["dummy.py"],
        pair_programming=True,
        yes_always=False,
        auto_accept_architect=False,
        auto_commits=False,
        map_tokens=0,
        max_chat_history_tokens=100000,
    )

    task_phase2 = Task(
        id="phase2_autonomous_job",
        files=["dummy.py"],
        pair_programming=False,
        yes_always=True,
        auto_accept_architect=True,
        auto_commits=True,
        map_tokens=2048,
        max_chat_history_tokens=50000,
    )

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        # Execute Phase 1 Task
        factory.run_task(task_phase1)
        session_conf = os.path.join(str(factory.session_dir), ".aider.conf.yml")
        with open(session_conf, "r", encoding="utf-8") as f:
            p1_conf = yaml.safe_load(f)
        assert p1_conf.get("yes-always") is False
        assert p1_conf.get("auto-accept-architect") is False
        assert p1_conf.get("auto-commits") is False
        assert p1_conf.get("map-tokens") == 0
        assert p1_conf.get("max-chat-history-tokens") == "100000"

        # Execute Phase 2 Task (transitions toggles in same session)
        factory.run_task(task_phase2)
        with open(session_conf, "r", encoding="utf-8") as f:
            p2_conf = yaml.safe_load(f)
        assert p2_conf.get("yes-always") is True
        assert p2_conf.get("auto-accept-architect") is True
        assert p2_conf.get("auto-commits") is True
        assert p2_conf.get("map-tokens") == 2048
        assert p2_conf.get("max-chat-history-tokens") == "50000"

    print("✅ Aider Multi-Phase Toggle Transition PASS")


if __name__ == "__main__":
    test_aider_toggle_overrides_when_false()
    test_aider_toggle_overrides_when_true()
    test_aider_multi_phase_toggle_transition()
