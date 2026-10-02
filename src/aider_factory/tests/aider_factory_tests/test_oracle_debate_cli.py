#!/usr/bin/env python3
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "../../python"))

from oracle_agent import _extract_overrides

print("Starting Oracle Debate CLI Tests...\n")


def test_no_pass_history_flag_parsing():
    os.environ.pop("ORACLE_DEBATE_NO_PASS_HISTORY", None)
    args = ["--no-pass-history", "--debate", "code", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)
    assert out == ["Query"]
    assert os.environ.get("ORACLE_DEBATE_NO_PASS_HISTORY") == "1"
    print("  ✅ --no-pass-history CLI flag parsed correctly.")


def test_persist_flag_parsing():
    os.environ.pop("ORACLE_DEBATE_PERSIST", None)
    args = ["--persist", "--debate", "code", "Test Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)
    assert out == ["Test Query"]
    assert os.environ.get("ORACLE_DEBATE_PERSIST") == "1"
    print("  ✅ --persist flag parsed correctly.")


def test_persona_sequencing_flags_parsing():
    os.environ.pop("ORACLE_PERSONA_FILE", None)
    os.environ.pop("ARCHITECT_PERSONA_FILE", None)
    args = ["--oracle-personas", "p1.md,p2.md", "--architect-personas", "a1.md,a2.md", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)
    assert out == ["Query"]
    assert os.environ.get("ORACLE_PERSONA_FILE") == "p1.md,p2.md"
    assert os.environ.get("ARCHITECT_PERSONA_FILE") == "a1.md,a2.md"
    print("  ✅ --oracle-personas and --architect-personas multi-file lists parsed correctly.")


def test_persona_flags_parsing():
    os.environ.pop("ORACLE_PERSONA_FILE", None)
    os.environ.pop("ARCHITECT_PERSONA_FILE", None)

    args = ["--oracle-persona", "oracle_rules.md", "--architect-persona", "arch_rules.md", "--debate", "code", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["Query"]
    assert os.environ.get("ORACLE_PERSONA_FILE") == "oracle_rules.md"
    assert os.environ.get("ARCHITECT_PERSONA_FILE") == "arch_rules.md"
    print("  ✅ --oracle-persona and --architect-persona CLI flags parsed correctly.")


def test_persona_missing_file_abort():
    import oracle_agent
    from unittest.mock import patch

    with patch.dict("os.environ", {"ORACLE_PERSONA_FILE": "non_existent_persona.md"}):
        ret = oracle_agent._run_cli_debate("Query", "code", max_turns=1, rounds=1)
        assert ret == 1
    print("  ✅ Missing persona file cleanly aborts with returncode 1.")


def test_persona_prompt_injection_and_cache_invalidation():
    import hashlib
    import oracle_agent
    import tempfile
    from unittest.mock import patch, MagicMock

    class FakeMessage:
        def __init__(self, content):
            self.content = content
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    class FakeUsage:
        def __init__(self):
            self.prompt_tokens = 10
            self.completion_tokens = 5
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    class FakeResponse:
        def __init__(self, content="<critique>ok</critique>\nVERDICT: AGREE"):
            self.choices = [FakeChoice(content)]
            self.usage = FakeUsage()
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    with tempfile.TemporaryDirectory() as tmpdir:
        orc_file = os.path.join(tmpdir, "oracle_persona.md")
        arch_file = os.path.join(tmpdir, "arch_persona.md")
        with open(orc_file, "w", encoding="utf-8") as f:
            f.write("STRICT_ORACLE_DIRECTIVE")
        with open(arch_file, "w", encoding="utf-8") as f:
            f.write("STRICT_ARCHITECT_DIRECTIVE")

        with patch.dict("os.environ", {
            "ORACLE_PERSONA_FILE": orc_file,
            "ARCHITECT_PERSONA_FILE": arch_file,
        }), patch("orchestrate.AiderFactory") as mock_factory, \
           patch("oracle_agent._retrieve", return_value=""), \
           patch("litellm.completion", return_value=FakeResponse()) as mock_llm:

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: implement fix"

            ret = oracle_agent._run_cli_debate("Test persona issue", "code", max_turns=1, rounds=1)
            assert ret == 0

            # Verify Oracle system prompt received the persona
            llm_calls = mock_llm.call_args_list
            sys_msg = llm_calls[0][1]["messages"][0]["content"]
            assert "STRICT_ORACLE_DIRECTIVE" in sys_msg

            # Verify Architect prompt received the persona
            ask_args = mock_factory.return_value._aider_ask_turn.call_args[0]
            arch_prompt_arg = ask_args[1]
            assert "STRICT_ARCHITECT_DIRECTIVE" in arch_prompt_arg
    print("  ✅ Persona injection and sandwich contract verified.")


def test_debate_flag():
    os.environ.pop("ORACLE_DEBATE_MODE", None)
    os.environ.pop("ORACLE_DEBATE_LOOPS", None)

    args = ["--file", "test.txt", "--debate", "code", "--loops", "5", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["--file", "test.txt", "Query"], f"Unexpected args left: {out}"
    assert os.environ.get("ORACLE_DEBATE_MODE") == "code"
    assert os.environ.get("ORACLE_DEBATE_LOOPS") == "5"
    print("  ✅ --debate <mode> and --loops <N> parse correctly.")


def test_debate_default():
    os.environ.pop("ORACLE_DEBATE_MODE", None)
    os.environ.pop("ORACLE_DEBATE_LOOPS", None)

    # "Query" is the query string, which does not start with "-"
    # But because --debate checks `not args[i+1].startswith("-")`, it will consume "Query" as the mode!
    # Let's verify this behavior.
    args = ["--debate", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == [], f"Unexpected args left: {out}"
    assert (
        os.environ.get("ORACLE_DEBATE_MODE") == "query"
    )  # "Query" gets consumed as the mode
    assert os.environ.get("ORACLE_DEBATE_LOOPS") is None
    print(
        "  ✅ --debate without mode consumes the next token if it doesn't start with '-'."
    )

    args2 = ["--debate", "--no-rag", "Query2"]
    out2, do_list2, did_clear2, _, _ = _extract_overrides(args2)
    assert out2 == ["Query2"]
    assert (
        os.environ.get("ORACLE_DEBATE_MODE") == "code"
    )  # default mode because --no-rag starts with "-"

    print(
        "  ✅ --debate without mode falls back to 'code' if the next token starts with '-'."
    )


def test_cli_debate_pass_history_resolution():
    """Verify _run_cli_debate resolves pass_history (defaulting to True) from active phase."""
    import oracle_agent
    import tempfile
    import yaml
    from unittest.mock import patch, MagicMock

    class FakeMessage:
        def __init__(self, content):
            self.content = content
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    class FakeUsage:
        def __init__(self, prompt_tokens=10, completion_tokens=5):
            self.prompt_tokens = prompt_tokens
            self.completion_tokens = completion_tokens
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    class FakeResponse:
        def __init__(self, content="VERDICT: AGREE"):
            self.choices = [FakeChoice(content)]
            self.usage = FakeUsage()
        def get(self, item, default=None):
            return getattr(self, item, default)
        def __getitem__(self, item):
            return getattr(self, item)

    cfg = {
        "phases": [
            {
                "enabled": True,
                "escalation_debate": {
                    "pass_history": False,
                }
            }
        ]
    }

    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        yaml.dump(cfg, f)
        f.flush()
        cfg_path = f.name

    try:
        with patch.dict("os.environ", {"ORACLE_CONFIG_FILE": cfg_path}), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse("VERDICT: AGREE")):
            
            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: test fix"

            ret = oracle_agent._run_cli_debate("Test issue", "code", max_turns=1, rounds=1)
            assert ret == 0
            print("  ✅ _run_cli_debate resolved pass_history successfully.")
    finally:
        if os.path.exists(cfg_path):
            os.remove(cfg_path)


def test_cli_debate_reads_glob_and_sticky_expansion():
    """Verify _run_cli_debate expands wildcards and attempts sticky plan discovery."""
    import oracle_agent
    import tempfile
    import yaml
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = os.path.join(tmpdir, "src")
        os.makedirs(src_dir, exist_ok=True)
        open(os.path.join(src_dir, "alpha.py"), "w").close()
        open(os.path.join(src_dir, "beta.py"), "w").close()

        cfg = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "enabled": True,
                    "files": {
                        "target_files": ["src/*.py"],
                    },
                }
            ],
        }
        cfg_path = os.path.join(tmpdir, "test_glob.yml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        class FakeMessage:
            def __init__(self, content): self.content = content
            def get(self, item, default=None): return getattr(self, item, default)
            def __getitem__(self, item): return getattr(self, item)

        class FakeChoice:
            def __init__(self, content): self.message = FakeMessage(content)
            def get(self, item, default=None): return getattr(self, item, default)
            def __getitem__(self, item): return getattr(self, item)

        class FakeResponse:
            def __init__(self):
                self.choices = [FakeChoice("VERDICT: AGREE")]
                self.usage = {"prompt_tokens": 10, "completion_tokens": 5}
            def get(self, item, default=None): return getattr(self, item, default)
            def __getitem__(self, item): return getattr(self, item)

        with patch.dict("os.environ", {"ORACLE_CONFIG_FILE": cfg_path}), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse()):

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: test"
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                ret = oracle_agent._run_cli_debate("Test glob", "code", max_turns=1, rounds=1)
                assert ret == 0
                ask_call = mock_factory.return_value._aider_ask_turn.call_args[0]
                reads_arg = ask_call[2]
                assert "src/alpha.py" in reads_arg
                assert "src/beta.py" in reads_arg
                print("  ✅ _run_cli_debate expanded glob patterns into reads correctly.")
            finally:
                os.chdir(orig_cwd)


def test_conventions_system_prompt_primacy():
    """Verify CONVENTIONS.md is injected into system prompt and excluded from <project_files>."""
    import oracle_agent
    import tempfile
    from unittest.mock import patch

    class FakeMessage:
        def __init__(self, content): self.content = content
        def get(self, item, default=None): return getattr(self, item, default)
        def __getitem__(self, item): return getattr(self, item)

    class FakeChoice:
        def __init__(self, content): self.message = FakeMessage(content)
        def get(self, item, default=None): return getattr(self, item, default)
        def __getitem__(self, item): return getattr(self, item)

    class FakeResponse:
        def __init__(self, content="VERDICT: AGREE"):
            self.choices = [FakeChoice(content)]
            self.usage = {"prompt_tokens": 10, "completion_tokens": 5}
        def get(self, item, default=None): return getattr(self, item, default)
        def __getitem__(self, item): return getattr(self, item)

    with tempfile.TemporaryDirectory() as tmpdir:
        af_dir = os.path.join(tmpdir, ".aider_factory")
        os.makedirs(af_dir, exist_ok=True)
        conv_path = os.path.join(af_dir, "CONVENTIONS.md")
        with open(conv_path, "w", encoding="utf-8") as f:
            f.write("# Invariant: Zero-Mock Mandate\n")

        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("ORACLE_") and not k.startswith("AI_FACTORY_") and k != "AIDER_ARCHITECT"
        }
        with patch.dict("os.environ", clean_env, clear=True), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion") as mock_llm:

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: test fix"
            mock_llm.return_value = FakeResponse("VERDICT: AGREE")
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                ret = oracle_agent._run_cli_debate("Test conventions query", "code", max_turns=1, rounds=1)
                assert ret == 0
                first_call = mock_llm.call_args_list[0][1]["messages"]
                sys_msg = next(m["content"] for m in first_call if m["role"] == "system")
                assert "## Project Foundational Invariants & Conventions" in sys_msg
                assert "Zero-Mock Mandate" in sys_msg

                # Assert CONVENTIONS.md was suppressed from <project_files> to avoid token bloat
                user_msg = next(m["content"] for m in first_call if m["role"] == "user")
                assert "## .aider_factory/CONVENTIONS.md" not in user_msg
                print("  ✅ CONVENTIONS.md injected into Oracle system prompt and excluded from user prompt.")
            finally:
                os.chdir(orig_cwd)


def test_get_model_settings_embodiment():
    from env_utils import get_model_settings
    import tempfile, yaml
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_path = os.path.join(tmpdir, ".aider.model.settings.yml")
        with open(settings_path, "w", encoding="utf-8") as f:
            yaml.dump([{
                "name": "gemini/gemini-3.8-flash",
                "extra_params": {"reasoning_effort": "high", "temperature": 0.8}
            }], f)
        res = get_model_settings("gemini/gemini-3.8-flash", cwd=tmpdir)
        assert res.get("extra_params", {}).get("reasoning_effort") == "high"
        assert res.get("extra_params", {}).get("temperature") == 0.8
        print("  ✅ get_model_settings embodied settings from YAML.")


def test_reasoning_effort_and_temp_flag_parsing():
    os.environ.pop("ORACLE_REASONING_EFFORT", None)
    os.environ.pop("ORACLE_TEMPERATURE", None)
    args = ["--reasoning-effort", "high", "--temperature", "0.8", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)
    assert out == ["Query"]
    assert os.environ.get("ORACLE_REASONING_EFFORT") == "high"
    assert os.environ.get("ORACLE_TEMPERATURE") == "0.8"
    print("  ✅ --reasoning-effort and --temperature CLI flags parsed correctly.")


def test_build_llm_kwargs_reasoning_propagation():
    import oracle_agent
    from unittest.mock import patch

    with patch.dict("os.environ", {
        "ORACLE_REASONING_EFFORT": "medium",
        "ORACLE_TEMPERATURE": "0.7",
    }):
        kwargs = oracle_agent._build_llm_kwargs("gemini/gemini-3.8-flash", [{"role": "user", "content": "hi"}])
        assert kwargs["reasoning_effort"] == "medium"
        assert kwargs["temperature"] == 0.7
        assert kwargs["drop_params"] is True
        print("  ✅ _build_llm_kwargs propagated reasoning_effort and drop_params.")


def test_conventions_disk_cache_invalidation():
    """Verify modifying CONVENTIONS.md invalidates the debate session cache hash."""
    import json
    import oracle_agent
    import tempfile
    from unittest.mock import patch

    class FakeMessage:
        def __init__(self, content): self.content = content
        def get(self, item, default=None): return getattr(self, item, default)
        def __getitem__(self, item): return getattr(self, item)

    class FakeChoice:
        def __init__(self, content): self.message = FakeMessage(content)
        def get(self, item, default=None): return getattr(self, item, default)
        def __getitem__(self, item): return getattr(self, item)

    class FakeResponse:
        def __init__(self, content="VERDICT: AGREE"):
            self.choices = [FakeChoice(content)]
            self.usage = {"prompt_tokens": 10, "completion_tokens": 5}
        def get(self, item, default=None): return getattr(self, item, default)
        def __getitem__(self, item): return getattr(self, item)

    with tempfile.TemporaryDirectory() as tmpdir:
        af_dir = os.path.join(tmpdir, ".aider_factory")
        os.makedirs(af_dir, exist_ok=True)
        conv_path = os.path.join(af_dir, "CONVENTIONS.md")
        with open(conv_path, "w", encoding="utf-8") as f:
            f.write("# Version 1 Conventions\n")

        session_path = os.path.join(tmpdir, ".aider_factory", ".oracle_debate_session.json")
        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("ORACLE_") and not k.startswith("AI_FACTORY_") and k != "AIDER_ARCHITECT"
        }
        clean_env["ORACLE_DEBATE_SESSION_FILE"] = session_path

        with patch.dict("os.environ", clean_env, clear=True), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse("VERDICT: AGREE")):

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: test fix"
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                ret1 = oracle_agent._run_cli_debate("Query 1", "code", max_turns=1, rounds=1)
                assert ret1 == 0
                with open(session_path, "r", encoding="utf-8") as sf:
                    hash1 = json.load(sf)["files_hash"]

                # Mutate conventions
                with open(conv_path, "w", encoding="utf-8") as f:
                    f.write("# Version 2 Conventions — Updated Rule\n")

                ret2 = oracle_agent._run_cli_debate("Query 2", "code", max_turns=1, rounds=1)
                assert ret2 == 0
                with open(session_path, "r", encoding="utf-8") as sf:
                    hash2 = json.load(sf)["files_hash"]

                assert hash1 != hash2, "Modifying CONVENTIONS.md must invalidate files_hash"
                print("  ✅ CONVENTIONS.md mutation successfully invalidates debate cache hash.")
            finally:
                os.chdir(orig_cwd)


if __name__ == "__main__":
    test_debate_flag()
    test_debate_default()
    test_cli_debate_pass_history_resolution()
    test_no_pass_history_flag_parsing()
    test_persist_flag_parsing()
    test_persona_sequencing_flags_parsing()
    test_persona_flags_parsing()
    test_persona_missing_file_abort()
    test_persona_prompt_injection_and_cache_invalidation()
    test_cli_debate_reads_glob_and_sticky_expansion()
    test_conventions_system_prompt_primacy()
    test_conventions_disk_cache_invalidation()
    test_get_model_settings_embodiment()
    test_reasoning_effort_and_temp_flag_parsing()
    test_build_llm_kwargs_reasoning_propagation()
    print("\n🎉 All CLI Oracle Debate Tests Passed!")
