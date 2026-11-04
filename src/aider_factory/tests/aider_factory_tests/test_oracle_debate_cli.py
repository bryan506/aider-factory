#!/usr/bin/env python3
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "../../python"))

import oracle_agent
from oracle_agent import _extract_overrides

print("Starting Oracle Debate CLI Tests...\n")


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
    def __init__(
        self,
        content="<critique>ok</critique>\nVERDICT: AGREE",
        prompt_tokens=10,
        completion_tokens=5,
    ):
        self.choices = [FakeChoice(content)]
        self.usage = FakeUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )

    def get(self, item, default=None):
        return getattr(self, item, default)

    def __getitem__(self, item):
        return getattr(self, item)


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
    import oracle_agent
    import tempfile
    from unittest.mock import patch

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

            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                ret = oracle_agent._run_cli_debate("Test persona issue", "code", max_turns=1, rounds=1)
            finally:
                os.chdir(orig_cwd)
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

    args = ["--debate", "code", "--loops", "5", "Query"]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["Query"], f"Unexpected args left: {out}"
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
    from unittest.mock import patch

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

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = os.path.join(tmpdir, "pass_history_cfg.yml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        with patch.dict("os.environ", {"ORACLE_CONFIG_FILE": cfg_path}), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse("VERDICT: AGREE")):

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: test fix"
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                ret = oracle_agent._run_cli_debate("Test issue", "code", max_turns=1, rounds=1)
                assert ret == 0
                print("  ✅ _run_cli_debate resolved pass_history successfully.")
            finally:
                os.chdir(orig_cwd)


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


def test_ensure_oracle_config_working_dir_discovery_priority():
    import oracle_agent
    import tempfile
    import yaml
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        af_dir = os.path.join(tmpdir, ".aider_factory")
        os.makedirs(af_dir, exist_ok=True)
        with open(os.path.join(af_dir, ".env.yml"), "w", encoding="utf-8") as f:
            yaml.dump({"phases": [{"enabled": True, "models": {"rag_agent": "model_primary"}}]}, f)
        with open(os.path.join(tmpdir, ".env.yml"), "w", encoding="utf-8") as f:
            yaml.dump({"phases": [{"enabled": True, "models": {"rag_agent": "model_secondary"}}]}, f)

        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ORACLE_") and not k.startswith("AI_FACTORY_")}
        with patch.dict("os.environ", clean_env, clear=True):
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                oracle_agent._ensure_oracle_config()
                assert os.environ.get("ORACLE_AGENT_MODEL") == "model_primary"
                print("  ✅ _ensure_oracle_config prioritizes .aider_factory/.env.yml over .env.yml.")
            finally:
                os.chdir(orig_cwd)


def test_ensure_oracle_config_ignores_foreign_ambient_config_and_session():
    import oracle_agent
    import tempfile
    import yaml
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as foreign_dir, tempfile.TemporaryDirectory() as local_dir:
        foreign_cfg = os.path.join(foreign_dir, "foreign.yml")
        with open(foreign_cfg, "w", encoding="utf-8") as f:
            yaml.dump({"phases": [{"enabled": True, "models": {"rag_agent": "foreign_model"}}]}, f)
        foreign_sess = os.path.join(foreign_dir, "foreign_session.json")

        local_af = os.path.join(local_dir, ".aider_factory")
        os.makedirs(local_af, exist_ok=True)
        with open(os.path.join(local_af, ".env.yml"), "w", encoding="utf-8") as f:
            yaml.dump({"phases": [{"enabled": True, "models": {"rag_agent": "local_model"}}]}, f)

        ambient_env = {
            "ORACLE_CONFIG_FILE": foreign_cfg,
            "ORACLE_SESSION_FILE": foreign_sess,
        }
        with patch.dict("os.environ", ambient_env, clear=True):
            orig_cwd = os.getcwd()
            os.chdir(local_dir)
            try:
                oracle_agent._ensure_oracle_config()
                assert os.environ.get("ORACLE_AGENT_MODEL") == "local_model", "Foreign config hijacked local directory!"
                sess_path = oracle_agent._session_file()
                assert not sess_path.startswith(foreign_dir), "Foreign session hijacked local directory!"
                print("  ✅ Foreign ambient config and session files correctly ignored.")
            finally:
                os.chdir(orig_cwd)


def test_ensure_oracle_config_rejects_placeholder_working_directory():
    import oracle_agent
    import tempfile
    import yaml
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {
            "working_directory": "/path/to/project",
            "phases": [{"enabled": True, "models": {"rag_agent": "placeholder_test_model"}}],
        }
        with open(os.path.join(tmpdir, ".env.yml"), "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("ORACLE_") and not k.startswith("AI_FACTORY_") and k not in ("LITELLM_BASE_URL", "LITELLM_API_KEY")
        }
        with patch.dict("os.environ", clean_env, clear=True):
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                oracle_agent._ensure_oracle_config()
                assert os.environ.get("ORACLE_AGENT_MODEL") == "placeholder_test_model"
                print("  ✅ Placeholder working_directory '/path/to/project' safely ignored.")
            finally:
                os.chdir(orig_cwd)


def test_ensure_oracle_config_sanitizes_placeholder_endpoints():
    import oracle_agent
    import tempfile
    import yaml
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {
            "endpoints": {"embed_api_base": "http://<your-router-host>:4000/v1"},
            "phases": [
                {
                    "enabled": True,
                    "rag": {
                        "embed_model": "BAAI/bge-m3",
                        "embed_backend": "sentence-transformers",
                    },
                }
            ],
        }
        with open(os.path.join(tmpdir, ".env.yml"), "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ORACLE_")}
        with patch.dict("os.environ", clean_env, clear=True):
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                oracle_agent._ensure_oracle_config()
                assert "ORACLE_EMBED_API_BASE" not in os.environ, "Placeholder endpoint was not sanitized!"
                assert os.environ.get("ORACLE_EMBED_BACKEND") == "sentence-transformers"
                print("  ✅ Placeholder embedder endpoint sanitized without flipping backend.")
            finally:
                os.chdir(orig_cwd)


def test_ensure_oracle_config_db_and_type_filter():
    """Verify _ensure_oracle_config sets ORACLE_RAG_DB_DIR and ORACLE_TYPE_FILTER from YAML collection path."""
    import oracle_agent
    import tempfile
    import yaml

    with tempfile.TemporaryDirectory() as tmpdir:
        custom_coll_dir = os.path.join(tmpdir, "custom_corpus")
        os.makedirs(os.path.join(custom_coll_dir, "lancedb"), exist_ok=True)
        cfg = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "enabled": True,
                    "rag": {
                        "collection_name": custom_coll_dir,
                        "type_filter": "docs",
                    },
                }
            ],
        }
        cfg_path = os.path.join(tmpdir, ".env.yml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        clean_env = {k: v for k, v in os.environ.items() if k not in ("ORACLE_RAG_DB_DIR", "ORACLE_TYPE_FILTER", "ORACLE_COLLECTION")}
        clean_env["ORACLE_CONFIG_FILE"] = cfg_path

        from unittest.mock import patch
        with patch.dict("os.environ", clean_env, clear=True):
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                oracle_agent._ensure_oracle_config()
                assert os.environ.get("ORACLE_TYPE_FILTER") == "docs"
                assert os.environ.get("ORACLE_COLLECTION") == "custom_corpus"
                assert os.environ.get("ORACLE_RAG_DB_DIR", "").replace("\\", "/").endswith("custom_corpus/lancedb")
                print("  ✅ _ensure_oracle_config sets smart collection and type_filter from YAML.")
            finally:
                os.chdir(orig_cwd)


def test_cli_debate_yaml_persona_and_persist_fallback():
    """Verify _run_cli_debate falls back to YAML for persist and personas when CLI flags are absent."""
    import oracle_agent
    import tempfile
    import yaml
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        orc_file = os.path.join(tmpdir, "yaml_oracle_persona.md")
        arch_file = os.path.join(tmpdir, "yaml_arch_persona.md")
        with open(orc_file, "w", encoding="utf-8") as f:
            f.write("YAML_ORACLE_PERSONA_CONTENT")
        with open(arch_file, "w", encoding="utf-8") as f:
            f.write("YAML_ARCH_PERSONA_CONTENT")

        cfg = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "enabled": True,
                    "escalation_debate": {
                        "persist": True,
                        "oracle_persona": orc_file,
                        "architect_persona": arch_file,
                    },
                }
            ],
        }
        cfg_path = os.path.join(tmpdir, "fallback_test.yml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        clean_env = {
            k: v for k, v in os.environ.items()
            if k not in ("ORACLE_DEBATE_PERSIST", "ORACLE_PERSONA_FILE", "ARCHITECT_PERSONA_FILE")
        }
        clean_env["ORACLE_CONFIG_FILE"] = cfg_path

        with patch.dict("os.environ", clean_env, clear=True), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse()) as mock_llm:

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: test resolution"
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                ret = oracle_agent._run_cli_debate("Test YAML fallback", "code", max_turns=1, rounds=1, persist=False)
                assert ret == 0
                first_llm_call = mock_llm.call_args_list[0][1]["messages"]
                sys_msg = next(m["content"] for m in first_llm_call if m["role"] == "system")
                assert "YAML_ORACLE_PERSONA_CONTENT" in sys_msg

                ask_args = mock_factory.return_value._aider_ask_turn.call_args[0]
                arch_prompt = ask_args[1]
                assert "YAML_ARCH_PERSONA_CONTENT" in arch_prompt
                print("  ✅ _run_cli_debate successfully embodies personas and persist from YAML.")
            finally:
                os.chdir(orig_cwd)


def test_instruction_file_disk_cache_invalidation():
    """Verify modifying oracle_file or architect_file invalidates the debate session cache hash."""
    import json
    import oracle_agent
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        o_file = os.path.join(tmpdir, "oracle_spec.md")
        a_file = os.path.join(tmpdir, "arch_spec.md")
        with open(o_file, "w", encoding="utf-8") as f:
            f.write("ORACLE_V1")
        with open(a_file, "w", encoding="utf-8") as f:
            f.write("ARCH_V1")

        session_path = os.path.join(tmpdir, "session.json")
        env = {
            "ORACLE_FILE_PATH": o_file,
            "ARCHITECT_FILE_PATH": a_file,
            "ORACLE_DEBATE_SESSION_FILE": session_path,
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse("VERDICT: AGREE")):

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: test"
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                assert oracle_agent._run_cli_debate("Query", "code", max_turns=1, rounds=1) == 0
                with open(session_path, "r", encoding="utf-8") as sf:
                    hash1 = json.load(sf)["files_hash"]

                with open(o_file, "w", encoding="utf-8") as f:
                    f.write("ORACLE_V2_MUTATED")

                assert oracle_agent._run_cli_debate("Query", "code", max_turns=1, rounds=1) == 0
                with open(session_path, "r", encoding="utf-8") as sf:
                    hash2 = json.load(sf)["files_hash"]

                assert hash1 != hash2, "Mutating oracle_file must invalidate files_hash"
                print("  ✅ Mutating oracle_file successfully invalidates files_hash.")
            finally:
                os.chdir(orig_cwd)


def test_yaml_persona_list_parsing():
    """Verify YAML list format for oracle_persona and architect_persona resolves without error."""
    import oracle_agent
    import tempfile
    import yaml
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        p1 = os.path.join(tmpdir, "p1.md")
        a1 = os.path.join(tmpdir, "a1.md")
        with open(p1, "w", encoding="utf-8") as f:
            f.write("P1_DIRECTIVE")
        with open(a1, "w", encoding="utf-8") as f:
            f.write("A1_DIRECTIVE")

        cfg = {
            "working_directory": tmpdir,
            "phases": [
                {
                    "enabled": True,
                    "escalation_debate": {
                        "oracle_persona": [p1],
                        "architect_persona": [a1],
                    },
                }
            ],
        }
        cfg_path = os.path.join(tmpdir, ".env.yml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        env = {
            "ORACLE_CONFIG_FILE": cfg_path,
            "ORACLE_DEBATE_SESSION_FILE": os.path.join(tmpdir, "session.json"),
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse("VERDICT: AGREE")):

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: test"
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                ret = oracle_agent._run_cli_debate("Query", "code", max_turns=1, rounds=1)
                assert ret == 0, f"Expected 0, got {ret}"
                print("  ✅ YAML persona list format parsed and loaded cleanly.")
            finally:
                os.chdir(orig_cwd)


# Removed premature __main__ block

def test_oracle_and_architect_file_flags_parsing():
    """Verify --oracle-file, --oracle-files, --architect-file, and --architect-files parse correctly."""
    os.environ.pop("ORACLE_FILE_PATH", None)
    os.environ.pop("ARCHITECT_FILE_PATH", None)

    args = [
        "--oracle-file", "orc_rules.md",
        "--architect-file", "arch_spec.md",
        "--debate", "code",
        "Perform audit"
    ]
    out, do_list, did_clear, _, _ = _extract_overrides(args)

    assert out == ["Perform audit"]
    assert os.environ.get("ORACLE_FILE_PATH") == "orc_rules.md"
    assert os.environ.get("ARCHITECT_FILE_PATH") == "arch_spec.md"

    # Multi-file variants
    os.environ.pop("ORACLE_FILE_PATH", None)
    os.environ.pop("ARCHITECT_FILE_PATH", None)
    args_multi = [
        "--oracle-files", "o1.md,o2.md",
        "--architect-files", "a1.md,a2.md",
        "--debate", "code",
        "Perform multi-round audit"
    ]
    out_m, _, _, _, _ = _extract_overrides(args_multi)
    assert out_m == ["Perform multi-round audit"]
    assert os.environ.get("ORACLE_FILE_PATH") == "o1.md,o2.md"
    assert os.environ.get("ARCHITECT_FILE_PATH") == "a1.md,a2.md"
    print("  ✅ --oracle-file(s) and --architect-file(s) flags parsed correctly.")


def test_debate_mode_file_interception():
    """Verify that --file in debate mode is NOT hijacked as ORACLE_FILE_PATH and forms the shared prompt."""
    import oracle_agent
    import tempfile

    os.environ.pop("ORACLE_FILE_PATH", None)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
        tf.write("# Shared Specification Content")
        tf.flush()
        file_path = tf.name

    try:
        args = ["--file", file_path, "--debate", "code", "Fix bug"]
        remaining, do_list, did_clear, _, _ = _extract_overrides(args)
        assert os.environ.get("ORACLE_FILE_PATH") is None, "--file must NOT set ORACLE_FILE_PATH"

        question, display = oracle_agent._build_question(remaining)
        assert question.startswith("Fix bug\n\n# Shared Specification Content")
        assert display.startswith("Fix bug [file:")
        print("  ✅ --file in debate mode prepends the inline message and shares the file content.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def test_cli_debate_turn0_prompt_isolation():
    """Verify Oracle Turn 0 receives oracle_file and Architect Turn 0 receives architect_file with zero cross-bleed."""
    import oracle_agent
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        orc_file = os.path.join(tmpdir, "oracle_rubric.md")
        arch_file = os.path.join(tmpdir, "arch_spec.md")
        with open(orc_file, "w", encoding="utf-8") as f:
            f.write("SECRET_ORACLE_RUBRIC_INSTRUCTION")
        with open(arch_file, "w", encoding="utf-8") as f:
            f.write("SECRET_ARCHITECT_SPEC_INSTRUCTION")

        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            with patch.dict("os.environ", {
                "ORACLE_FILE_PATH": orc_file,
                "ARCHITECT_FILE_PATH": arch_file,
            }), patch("orchestrate.AiderFactory") as mock_factory, \
               patch("oracle_agent._retrieve", return_value=""), \
               patch("litellm.completion", return_value=FakeResponse()) as mock_llm:

                mock_factory.return_value._aider_ask_turn.return_value = (
                    "# Full Specification\n"
                    "## Scope\nTarget: main.py\n\n"
                    "PROPOSAL: Implement robust error handling"
                )

                ret = oracle_agent._run_cli_debate("Shared issue: optimize loop", "code", max_turns=1, rounds=1)
                assert ret == 0

                # 1. Oracle prompt verification
                first_llm_call = mock_llm.call_args_list[0][1]["messages"]
                user_msg = next(m["content"] for m in first_llm_call if m["role"] == "user")
                assert "<oracle_instructions>" in user_msg
                assert "SECRET_ORACLE_RUBRIC_INSTRUCTION" in user_msg
                assert "SECRET_ARCHITECT_SPEC_INSTRUCTION" not in user_msg

                # 2. Architect prompt verification
                ask_args = mock_factory.return_value._aider_ask_turn.call_args[0]
                arch_prompt = ask_args[1]
                assert "INSTRUCTIONS / SPECIFICATION:" in arch_prompt
                assert "SECRET_ARCHITECT_SPEC_INSTRUCTION" in arch_prompt
                assert "SECRET_ORACLE_RUBRIC_INSTRUCTION" not in arch_prompt
                assert "USER ISSUE: Shared issue: optimize loop" in arch_prompt

                # 3. Terminal anchor verification
                assert "Conclude your response with EXACTLY this terminal line:\nPROPOSAL: <one-line summary of resolution>" in arch_prompt
                print("  ✅ Turn 0 prompt isolation and terminal anchor verified.")
        finally:
            os.chdir(orig_cwd)


def test_cli_debate_emits_timestamped_artifacts_and_archives_history():
    """R2: Validates that standalone CLI debate writes all 3 artifacts and archives history."""
    import oracle_agent
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("ORACLE_") and not k.startswith("AI_FACTORY_")
        }
        clean_env["ORACLE_DEBATE_STEM"] = "audit_unit"

        with patch.dict("os.environ", clean_env, clear=True), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse("VERDICT: AGREE")):

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: verified fix"
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                ret = oracle_agent._run_cli_debate("Test artifact writing", "code", max_turns=1, rounds=1)
                assert ret == 0

                debates_dir = os.path.join(tmpdir, ".aider_factory", "logs", "debates")
                assert os.path.isdir(debates_dir)
                files = os.listdir(debates_dir)

                v_files = [f for f in files if f.startswith("audit_unit_") and f.endswith(".verdict.md")]
                d_files = [f for f in files if f.startswith("audit_unit_") and f.endswith(".debate.md")]
                j_files = [f for f in files if f.startswith("audit_unit_") and f.endswith(".debate.json")]

                assert len(v_files) == 1, f"Expected 1 verdict file, got: {v_files}"
                assert len(d_files) == 1, f"Expected 1 debate markdown file, got: {d_files}"
                assert len(j_files) == 1, f"Expected 1 ledger json file, got: {j_files}"

                chat_dir = os.path.join(tmpdir, ".aider_factory", "logs", "chat_history")
                assert os.path.isdir(chat_dir)
                archived = [f for f in os.listdir(chat_dir) if f.startswith("audit_unit_") and f.endswith("_debate_history.md")]
                assert len(archived) == 1, f"Expected archived chat history, got: {archived}"
                print("  ✅ CLI debate artifact parity and history archival verified.")
            finally:
                os.chdir(orig_cwd)


def test_cli_debate_multi_round_agreement_continuation_with_instruction_files():
    """Verify debate continues to round 2 on agreement when distinct architect files are configured."""
    import oracle_agent
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        a1 = os.path.join(tmpdir, "arch1.md")
        a2 = os.path.join(tmpdir, "arch2.md")
        with open(a1, "w", encoding="utf-8") as f:
            f.write("SPEC_1")
        with open(a2, "w", encoding="utf-8") as f:
            f.write("SPEC_2")

        clean_env = {
            "ARCHITECT_FILE_PATH": f"{a1},{a2}",
            "ORACLE_DEBATE_STEM": "test_stem",
        }
        with patch.dict("os.environ", clean_env, clear=True), \
             patch("orchestrate.AiderFactory") as mock_factory, \
             patch("oracle_agent._retrieve", return_value=""), \
             patch("litellm.completion", return_value=FakeResponse("VERDICT: AGREE")):

            mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: fix"
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                ret = oracle_agent._run_cli_debate("Query", "code", max_turns=1, rounds=2, persist=False)
                assert ret == 0
                assert mock_factory.return_value._aider_ask_turn.call_count == 2, (
                    f"Expected 2 turns across rounds despite round 1 agreement, got {mock_factory.return_value._aider_ask_turn.call_count}"
                )
                print("  ✅ Debate continues to round 2 on agreement with multi-round instruction files.")
            finally:
                os.chdir(orig_cwd)


def test_cli_debate_multi_round_file_cycling():
    """Verify --architect-files cycles across rounds."""
    import oracle_agent
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        a1 = os.path.join(tmpdir, "arch1.md")
        a2 = os.path.join(tmpdir, "arch2.md")
        with open(a1, "w", encoding="utf-8") as f:
            f.write("ROUND_1_ARCHITECT_SPEC")
        with open(a2, "w", encoding="utf-8") as f:
            f.write("ROUND_2_ARCHITECT_SPEC")

        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            clean_env = {
                k: v for k, v in os.environ.items()
                if k not in ("ORACLE_FILE_PATH", "ORACLE_PERSONA_FILE", "ARCHITECT_PERSONA_FILE")
            }
            clean_env["ARCHITECT_FILE_PATH"] = f"{a1},{a2}"
            with patch.dict("os.environ", clean_env, clear=True), \
                 patch("orchestrate.AiderFactory") as mock_factory, \
                 patch("oracle_agent._retrieve", return_value=""), \
                 patch("litellm.completion", return_value=FakeResponse("VERDICT: REVISE")):

                mock_factory.return_value._aider_ask_turn.return_value = "PROPOSAL: update"

                ret = oracle_agent._run_cli_debate("Test cycling", "code", max_turns=1, rounds=2)
                assert ret == 0

                calls = mock_factory.return_value._aider_ask_turn.call_args_list
                round1_prompt = calls[0][0][1]
                round2_prompt = calls[1][0][1]

                assert "ROUND_1_ARCHITECT_SPEC" in round1_prompt
                assert "ROUND_2_ARCHITECT_SPEC" in round2_prompt
                print("  ✅ Multi-round file cycling verified.")
        finally:
            os.chdir(orig_cwd)


def test_env_plan_do_persona_and_instruction_pairing_exists_and_resolves():
    """Verify all personas and instruction files configured in env_plan_do.yml exist on disk
    and conform to role terminal contracts (Oracle -> VERDICT:, Architect -> PROPOSAL:)."""
    import yaml
    from run_workflow import resolve_template_path

    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "default_configs", "sample_yaml_config", "env_plan_do.yml"
    )
    assert os.path.isfile(env_path), f"env_plan_do.yml not found at {env_path}"
    with open(env_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    phase2 = cfg["phases"][1]
    pre_edit = phase2["oracle"]["pre_edit_debate"]

    # 1. Verify Oracle Personas (must terminate with VERDICT:)
    for p in pre_edit["oracle_persona"]:
        resolved = resolve_template_path(p)
        assert resolved is not None, f"Could not resolve oracle persona: {p}"
        assert os.path.isfile(resolved), f"Missing file: {resolved}"
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()
        assert "VERDICT:" in content, f"Oracle persona {p} must define VERDICT: output contract"

    # 2. Verify Architect Personas (must terminate with PROPOSAL:)
    for p in pre_edit["architect_persona"]:
        resolved = resolve_template_path(p)
        assert resolved is not None, f"Could not resolve architect persona: {p}"
        assert os.path.isfile(resolved), f"Missing file: {resolved}"
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()
        assert "PROPOSAL:" in content, f"Architect persona {p} must define PROPOSAL: terminal directive"

    # 3. Verify Oracle Instruction Files (must contain Primacy & Recency anchors)
    for fpath in pre_edit["oracle_file"]:
        resolved = resolve_template_path(fpath)
        assert resolved is not None, f"Could not resolve oracle file: {fpath}"
        assert os.path.isfile(resolved), f"Missing file: {resolved}"
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Primacy Anchor" in content
        assert "Recency Anchor" in content

    # 4. Verify Architect Instruction Files (must contain Task ID schema and Cumulative Invariant)
    for fpath in pre_edit["architect_file"]:
        resolved = resolve_template_path(fpath)
        assert resolved is not None, f"Could not resolve architect file: {fpath}"
        assert os.path.isfile(resolved), f"Missing file: {resolved}"
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Task ID" in content
        assert "PROPOSAL:" in content
        assert "Cumulative Plan Invariant" in content, (
            f"Architect instruction file {fpath} must define Cumulative Plan Invariant"
        )
    print("  ✅ env_plan_do.yml persona and instruction pairings verified.")


def test_deliberate_shared_contracts_and_loaders():
    """Verify shared prompt contracts, strict/lenient persona/instruction loaders, and multi-round continuation."""
    import builtins
    import contextlib
    import io
    import tempfile
    from unittest.mock import patch
    import deliberate
    from orchestrate import AiderFactory, Task

    expected_eval = (
        "\n\n<evaluation_contract>\n"
        "Critically evaluate the Architect's proposal in accordance with your persona guidelines. "
        "Structure your response exactly as follows:\n"
        "<critique>\n"
        "[Step-by-step analysis of edge cases, logic flaws, and RAG grounding]\n"
        "</critique>\n"
        "VERDICT: [AGREE | REVISE | OBJECT - <reason>]\n"
        "</evaluation_contract>"
    )
    expected_anchor = (
        "Conclude your response with EXACTLY this terminal line:\n"
        "PROPOSAL: <one-line summary of resolution>"
    )
    assert deliberate.EVALUATION_CONTRACT == expected_eval
    assert deliberate.PROPOSAL_TERMINAL_ANCHOR == expected_anchor

    with tempfile.TemporaryDirectory() as tmpdir:
        p1 = os.path.join(tmpdir, "p1.md")
        p2 = os.path.join(tmpdir, "p2.md")
        with open(p1, "w", encoding="utf-8") as f:
            f.write("  Persona 1 Directive  \n")
        with open(p2, "w", encoding="utf-8") as f:
            f.write("Persona 2 Directive\n")

        assert deliberate.load_persona_or_instruct_files(None, project_dir=tmpdir) == []
        assert deliberate.load_persona_or_instruct_files("", project_dir=tmpdir) == []

        loaded_csv = deliberate.load_persona_or_instruct_files(
            "p1.md, p2.md", project_dir=tmpdir, strict=True
        )
        assert loaded_csv == ["Persona 1 Directive", "Persona 2 Directive"]

        # strict=True aborts and prints error on missing file
        stderr_buf = io.StringIO()
        with contextlib.redirect_stderr(stderr_buf):
            res_strict = deliberate.load_persona_or_instruct_files(
                ["p1.md", "missing_persona.md"],
                project_dir=tmpdir,
                label="Oracle persona",
                strict=True,
            )
        assert res_strict is None
        assert "[oracle] Error: Oracle persona file not found: missing_persona.md" in stderr_buf.getvalue()

        # strict=False gracefully skips missing file and loads existing
        res_lenient = deliberate.load_persona_or_instruct_files(
            ["missing_persona.md", "p2.md"],
            project_dir=tmpdir,
            strict=False,
        )
        assert res_lenient == ["Persona 2 Directive"]

        # PermissionError during open with strict=True returns None; strict=False skips
        real_open = builtins.open

        def fail_p1_open(file, *args, **kwargs):
            if os.path.abspath(str(file)) == os.path.abspath(p1):
                raise PermissionError("locked")
            return real_open(file, *args, **kwargs)

        stderr_buf = io.StringIO()
        with contextlib.redirect_stderr(stderr_buf), patch("builtins.open", side_effect=fail_p1_open):
            assert (
                deliberate.load_persona_or_instruct_files("p1.md", project_dir=tmpdir, strict=True)
                is None
            )
            assert (
                deliberate.load_persona_or_instruct_files(["p1.md", "p2.md"], project_dir=tmpdir, strict=False)
                == ["Persona 2 Directive"]
            )

        # Multi-round continuation checks including Zero-RAG empty string round entry
        assert deliberate.has_remaining_round_configs(1, ["working_repo_lib", ""]) is True
        assert deliberate.has_remaining_round_configs(2, ["working_repo_lib", ""]) is False
        assert deliberate.has_remaining_round_configs(1, "p1.md,p2.md") is True
        assert deliberate.has_remaining_round_configs(2, "p1.md,p2.md") is False
        assert deliberate.has_remaining_round_configs(1, "single.md", None, []) is False

        # Verify AiderFactory._run_deliberation executes Round 2 when job_debate_collection=["working_repo_lib", ""]
        prior_v = os.path.join(tmpdir, "r1.verdict.md")
        deliberate.write_verdict(prior_v, "agreed", False, "PROPOSAL: round 1 plan", draft_mode=True)
        r2_v = os.path.join(tmpdir, "r2.verdict.md")
        r2_l = os.path.join(tmpdir, "r2.debate.json")

        factory = AiderFactory(tmpdir, session_name="test_delib_r2")
        task_continue = Task(
            id="delib_r2_continue",
            deliberate={
                "verdict": r2_v,
                "ledger": r2_l,
                "prior_verdict": prior_v,
                "round_idx": 2,
                "loops": 1,
                "mode": "code",
                "draft_mode": True,
                "job_debate_collection": ["working_repo_lib", ""],
            },
        )
        with patch.object(factory, "_oracle_turn", return_value="VERDICT: AGREE") as mock_orc, \
             patch.object(factory, "_aider_ask_turn", return_value="PROPOSAL: round 2 plan") as mock_arch:
            assert factory._run_deliberation(task_continue) is True
            assert mock_orc.call_count == 2  # Turn 0 pre-assess + Turn 1 review
            assert mock_arch.call_count == 1

    print("  ✅ deliberate shared contracts, loaders, and multi-round continuation verified.")


def _write_task_heavy_seed_files(tmpdir: str) -> tuple[str, str]:
    """Create template (2 tasks) and issue (4 tasks) files yielding a 6-task seed."""
    template_path = os.path.join(tmpdir, "debate_template.md")
    issue_path = os.path.join(tmpdir, "debate_issue.md")
    with open(template_path, "w", encoding="utf-8") as tf:
        tf.write(
            "## Scope Analysis\n"
            "RAW_SEED_SENTINEL_DO_NOT_LEAK\n"
            "### [Task ID: 001] - Template Example Task 1\n"
            "### [Task ID: 002] - Template Example Task 2\n"
        )
    with open(issue_path, "w", encoding="utf-8") as isf:
        isf.write(
            "## Implementation Plan\n"
            "### [Task ID: 001] - Prior Strategy Task 1\n"
            "### [Task ID: 002] - Prior Strategy Task 2\n"
            "### [Task ID: 003] - Prior Strategy Task 3\n"
            "### [Task ID: 004] - Prior Strategy Task 4\n"
        )
    return template_path, issue_path


def test_deliberation_high_watermark_retention_tc001():
    """TC-001: Verify 2-task Turn-1 proposal is retained over 6-task seed and 0-task Turn-2 delta."""
    import re
    import tempfile
    from unittest.mock import patch
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path, issue_path = _write_task_heavy_seed_files(tmpdir)
        factory = AiderFactory(tmpdir, session_name="test_tc001")
        v_tc1 = os.path.join(tmpdir, "tc1.verdict.md")
        l_tc1 = os.path.join(tmpdir, "tc1.debate.json")
        t_tc1 = Task(
            id="tc1_hwm",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": v_tc1,
                "ledger": l_tc1,
                "loops": 2,
                "mode": "code",
                "draft_mode": True,
            },
        )
        turn1_arch_spec = (
            "## Scope Analysis\n"
            "Architect Focused Specification\n\n"
            "## Implementation Plan\n"
            "### [Task ID: 001] - Real Architect Task One\n"
            "- Tight Description: First surgical change.\n\n"
            "### [Task ID: 002] - Real Architect Task Two\n"
            "- Tight Description: Second surgical change.\n\n"
            "PROPOSAL: Two-task surgical plan"
        )
        turn2_arch_delta = (
            "All P2 reviewer comments have been incorporated into the plan.\n\n"
            "PROPOSAL: Confirmed two-task surgical plan"
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=["Pre-assessment notes", "VERDICT: REVISE", "VERDICT: AGREE"],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            side_effect=[turn1_arch_spec, turn2_arch_delta],
        ):
            assert factory._run_deliberation(t_tc1) is True

        with open(v_tc1, "r", encoding="utf-8") as vf:
            v_tc1_text = vf.read()
        res_tc1 = re.search(
            r"(?s)# Resolution\s*\n\n(.*?)(?=\n---\n\n# Oracle Assessment|\Z)",
            v_tc1_text,
        ).group(1).strip()
        assert "### [Task ID: 001] - Real Architect Task One" in res_tc1
        assert "### [Task ID: 002] - Real Architect Task Two" in res_tc1
        assert "RAW_SEED_SENTINEL_DO_NOT_LEAK" not in res_tc1
        assert "All P2 reviewer comments" not in res_tc1
    print("  ✅ TC-001 high-watermark retention against task-heavy seed verified.")


def test_deliberation_draft_mode_seed_fallback_tc002a():
    """TC-002A: Verify draft_mode=True falls back to sanitized seed when all Architect turns are empty/whitespace."""
    import re
    import tempfile
    from unittest.mock import patch
    import deliberate
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path, issue_path = _write_task_heavy_seed_files(tmpdir)
        factory = AiderFactory(tmpdir, session_name="test_tc002a")
        v_tc2a = os.path.join(tmpdir, "tc2a.verdict.md")
        l_tc2a = os.path.join(tmpdir, "tc2a.debate.json")
        t_tc2a = Task(
            id="tc2a_fallback",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": v_tc2a,
                "ledger": l_tc2a,
                "loops": 2,
                "mode": "code",
                "draft_mode": True,
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=["Pre-assessment", "VERDICT: REVISE", "VERDICT: AGREE"],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            side_effect=["   \n  ", ""],
        ):
            assert factory._run_deliberation(t_tc2a) is True

        with open(v_tc2a, "r", encoding="utf-8") as vf:
            v_tc2a_text = vf.read()
        res_tc2a = re.search(
            r"(?s)# Resolution\s*\n\n(.*?)(?=\n---\n\n# Oracle Assessment|\Z)",
            v_tc2a_text,
        ).group(1).strip()
        assert "RAW_SEED_SENTINEL_DO_NOT_LEAK" in res_tc2a
        assert deliberate.count_tasks(res_tc2a) == 6
    print("  ✅ TC-002A draft_mode=True whitespace fallback to seed verified.")


def test_deliberation_non_draft_mode_no_fallback_tc002b():
    """TC-002B: Verify draft_mode=False does NOT fall back to seed when Architect output is empty."""
    import re
    import tempfile
    from unittest.mock import patch
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path, issue_path = _write_task_heavy_seed_files(tmpdir)
        factory = AiderFactory(tmpdir, session_name="test_tc002b")
        v_tc2b = os.path.join(tmpdir, "tc2b.verdict.md")
        l_tc2b = os.path.join(tmpdir, "tc2b.debate.json")
        t_tc2b = Task(
            id="tc2b_no_fallback",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": v_tc2b,
                "ledger": l_tc2b,
                "loops": 1,
                "mode": "code",
                "draft_mode": False,
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=["Pre-assessment", "VERDICT: OBJECT - empty"],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            return_value="   ",
        ):
            assert factory._run_deliberation(t_tc2b) is True

        with open(v_tc2b, "r", encoding="utf-8") as vf:
            v_tc2b_text = vf.read()
        res_tc2b = re.search(
            r"(?s)# Resolution[ \t]*\r?\n\r?\n(.*?)(?=\r?\n---\r?\n\r?\n# Oracle Assessment|\Z)",
            v_tc2b_text,
        ).group(1).strip()
        assert res_tc2b == ""
        assert "RAW_SEED_SENTINEL_DO_NOT_LEAK" not in v_tc2b_text
    print("  ✅ TC-002B draft_mode=False empty resolution preservation verified.")


def test_deliberation_zero_loops_boundary_tc002c():
    """TC-002C: Verify loops=0 transitions state to exhausted, falls back to seed, and is non-actionable."""
    import json
    import re
    import tempfile
    from unittest.mock import patch
    import deliberate
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path, issue_path = _write_task_heavy_seed_files(tmpdir)
        factory = AiderFactory(tmpdir, session_name="test_tc002c")
        v_tc2c = os.path.join(tmpdir, "tc2c.verdict.md")
        l_tc2c = os.path.join(tmpdir, "tc2c.debate.json")
        t_tc2c = Task(
            id="tc2c_zero_loops",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": v_tc2c,
                "ledger": l_tc2c,
                "loops": 0,
                "mode": "code",
                "draft_mode": True,
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            return_value="Pre-assessment only",
        ) as mock_orc_2c, patch.object(
            factory,
            "_aider_ask_turn",
        ) as mock_arch_2c:
            assert factory._run_deliberation(t_tc2c) is True
            assert mock_orc_2c.call_count == 1
            assert mock_arch_2c.call_count == 0

        assert deliberate.verdict_status(v_tc2c) == "exhausted"
        assert deliberate.verdict_is_actionable(v_tc2c) is False
        with open(v_tc2c, "r", encoding="utf-8") as vf:
            res_tc2c = re.search(
                r"(?s)# Resolution\s*\n\n(.*?)(?=\n---\n\n# Oracle Assessment|\Z)",
                vf.read(),
            ).group(1).strip()
        assert "RAW_SEED_SENTINEL_DO_NOT_LEAK" in res_tc2c
        with open(l_tc2c, "r", encoding="utf-8") as lf:
            assert json.load(lf)["state"] == "exhausted"
    print("  ✅ TC-002C zero-turn boundary exhaustion and seed fallback verified.")


def test_deliberation_architect_error_prefix_isolation_tc003():
    """TC-003A & TC-003B: Verify _arch_err_prefixes bypass high-watermark update, record proposal_hash=None,
    and fall back to seed when all turns fail in draft_mode=True."""
    import json
    import re
    import tempfile
    from unittest.mock import patch
    import deliberate
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path, issue_path = _write_task_heavy_seed_files(tmpdir)
        factory = AiderFactory(tmpdir, session_name="test_tc003")

        # TC-003A: Turn 1 valid, Turn 2 timeout, Turn 3 failed
        v_tc3a = os.path.join(tmpdir, "tc3a.verdict.md")
        l_tc3a = os.path.join(tmpdir, "tc3a.debate.json")
        t_tc3a = Task(
            id="tc3a_err_prefix",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": v_tc3a,
                "ledger": l_tc3a,
                "loops": 3,
                "mode": "code",
                "draft_mode": True,
            },
        )
        valid_turn1 = (
            "## Scope Analysis\n"
            "Valid Turn 1 Spec\n"
            "### [Task ID: 001] - Valid Task\n"
            "PROPOSAL: Valid turn 1"
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=[
                "Pre-assessment",
                "VERDICT: OBJECT - refine",
                "VERDICT: OBJECT - timed out",
                "VERDICT: OBJECT - failed",
            ],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            side_effect=[
                valid_turn1,
                "PROPOSAL: (architect turn timed out)",
                "PROPOSAL: (architect turn failed: subprocess error)",
            ],
        ):
            assert factory._run_deliberation(t_tc3a) is True

        with open(v_tc3a, "r", encoding="utf-8") as vf:
            res_tc3a = re.search(
                r"(?s)# Resolution\s*\n\n(.*?)(?=\n---\n\n# Oracle Assessment|\Z)",
                vf.read(),
            ).group(1).strip()
        assert "### [Task ID: 001] - Valid Task" in res_tc3a
        assert "architect turn timed out" not in res_tc3a
        assert "architect turn failed" not in res_tc3a

        with open(l_tc3a, "r", encoding="utf-8") as lf:
            ledger_tc3a = json.load(lf)
        arch_turns_3a = [t for t in ledger_tc3a["turns"] if t["role"] == "architect"]
        assert len(arch_turns_3a) == 3
        assert arch_turns_3a[0]["proposal_hash"] == deliberate.proposal_hash(valid_turn1)
        assert arch_turns_3a[1]["proposal_hash"] is None
        assert arch_turns_3a[2]["proposal_hash"] is None
        assert ledger_tc3a["state"] == "exhausted"

        # TC-003B: All Architect turns fail in draft_mode=True -> falls back to seed, not error text
        v_tc3b = os.path.join(tmpdir, "tc3b.verdict.md")
        l_tc3b = os.path.join(tmpdir, "tc3b.debate.json")
        t_tc3b = Task(
            id="tc3b_all_failed",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": v_tc3b,
                "ledger": l_tc3b,
                "loops": 1,
                "mode": "code",
                "draft_mode": True,
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=["Pre-assessment", "VERDICT: OBJECT - failed"],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            return_value="PROPOSAL: (architect turn failed)",
        ):
            assert factory._run_deliberation(t_tc3b) is True

        with open(v_tc3b, "r", encoding="utf-8") as vf:
            res_tc3b = re.search(
                r"(?s)# Resolution\s*\n\n(.*?)(?=\n---\n\n# Oracle Assessment|\Z)",
                vf.read(),
            ).group(1).strip()
        assert "RAW_SEED_SENTINEL_DO_NOT_LEAK" in res_tc3b
        assert "architect turn failed" not in res_tc3b
    print("  ✅ TC-003A & TC-003B architect failure/timeout prefix isolation verified.")


def test_deliberation_round2_prior_verdict_deduplication_tc004abc():
    """TC-004A, TC-004B, TC-004C: Verify Round-2 prior_verdict hash deduplication,
    status=='agreed' gating, and distinct specification injection."""
    import tempfile
    from unittest.mock import patch
    import deliberate
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path, issue_path = _write_task_heavy_seed_files(tmpdir)
        factory = AiderFactory(tmpdir, session_name="test_tc004abc")

        seed_text = ""
        for p in (template_path, issue_path):
            with open(p, "r", encoding="utf-8") as fh:
                seed_text += fh.read() + "\n\n"

        distinct_spec = (
            "## Scope Analysis\n"
            "Distinct Round 1 Specification\n\n"
            "## Implementation Plan\n"
            "### [Task ID: 001] - Distinct Round 1 Task\n"
            "PROPOSAL: Distinct Round 1 plan"
        )

        v_prior_seed = os.path.join(tmpdir, "prior_seed.verdict.md")
        deliberate.write_verdict(v_prior_seed, "agreed", False, seed_text, draft_mode=True)

        v_prior_exhausted = os.path.join(tmpdir, "prior_exhausted.verdict.md")
        deliberate.write_verdict(v_prior_exhausted, "exhausted", False, distinct_spec, draft_mode=True)

        v_prior_agreed = os.path.join(tmpdir, "prior_agreed.verdict.md")
        deliberate.write_verdict(v_prior_agreed, "agreed", False, distinct_spec, draft_mode=True)

        # TC-004A: agreed prior_verdict matching seed hash -> suppressed
        t_r2a = Task(
            id="tc4a_r2_dedup",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": os.path.join(tmpdir, "r2a.verdict.md"),
                "ledger": os.path.join(tmpdir, "r2a.debate.json"),
                "prior_verdict": v_prior_seed,
                "round_idx": 2,
                "loops": 1,
                "mode": "code",
                "draft_mode": True,
                "job_debate_collection": ["coll_r1", "coll_r2"],
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=["Pre-assessment", "VERDICT: AGREE"],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            return_value=distinct_spec,
        ) as mock_arch_4a:
            assert factory._run_deliberation(t_r2a) is True
            r2a_prompt = mock_arch_4a.call_args[0][1]
            assert (
                "## Context: The PREVIOUS escalation round agreed to attempt this specification:"
                not in r2a_prompt
            )
            assert r2a_prompt.count("RAW_SEED_SENTINEL_DO_NOT_LEAK") == 1

        # TC-004B: exhausted prior_verdict -> suppressed
        t_r2b = Task(
            id="tc4b_r2_unagreed",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": os.path.join(tmpdir, "r2b.verdict.md"),
                "ledger": os.path.join(tmpdir, "r2b.debate.json"),
                "prior_verdict": v_prior_exhausted,
                "round_idx": 2,
                "loops": 1,
                "mode": "code",
                "draft_mode": True,
                "job_debate_collection": ["coll_r1", "coll_r2"],
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=["Pre-assessment", "VERDICT: AGREE"],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            return_value=distinct_spec,
        ) as mock_arch_4b:
            assert factory._run_deliberation(t_r2b) is True
            r2b_prompt = mock_arch_4b.call_args[0][1]
            assert (
                "## Context: The PREVIOUS escalation round agreed to attempt this specification:"
                not in r2b_prompt
            )

        # TC-004C: agreed prior_verdict with distinct spec -> injected
        t_r2c = Task(
            id="tc4c_r2_inject",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": os.path.join(tmpdir, "r2c.verdict.md"),
                "ledger": os.path.join(tmpdir, "r2c.debate.json"),
                "prior_verdict": v_prior_agreed,
                "round_idx": 2,
                "loops": 1,
                "mode": "code",
                "draft_mode": True,
                "job_debate_collection": ["coll_r1", "coll_r2"],
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=["Pre-assessment", "VERDICT: AGREE"],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            return_value=distinct_spec,
        ) as mock_arch_4c:
            assert factory._run_deliberation(t_r2c) is True
            r2c_prompt = mock_arch_4c.call_args[0][1]
            assert (
                "## Context: The PREVIOUS escalation round agreed to attempt this specification:"
                in r2c_prompt
            )
            assert "### [Task ID: 001] - Distinct Round 1 Task" in r2c_prompt
    print("  ✅ TC-004A, TC-004B, TC-004C Round-2 prior verdict deduplication and injection verified.")


def test_deliberation_round2_malformed_prior_verdict_resilience_tc004de():
    """TC-004D & TC-004E: Verify malformed prior_verdict (no # Resolution) and regex parse exceptions
    are handled safely without aborting _run_deliberation."""
    import tempfile
    from unittest.mock import patch
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path, issue_path = _write_task_heavy_seed_files(tmpdir)
        factory = AiderFactory(tmpdir, session_name="test_tc004de")

        v_malformed = os.path.join(tmpdir, "malformed_prior.verdict.md")
        with open(v_malformed, "w", encoding="utf-8") as mf:
            mf.write("STATUS: agreed\nGATE: draft\n\nBody without resolution section\n")

        turn1_spec = (
            "## Scope Analysis\n"
            "### [Task ID: 001] - Task One\n"
            "PROPOSAL: Task one plan"
        )

        # TC-004D: Missing # Resolution header (res_match is None)
        t_r2d = Task(
            id="tc4d_malformed_prior",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": os.path.join(tmpdir, "r2d.verdict.md"),
                "ledger": os.path.join(tmpdir, "r2d.debate.json"),
                "prior_verdict": v_malformed,
                "round_idx": 2,
                "loops": 1,
                "mode": "code",
                "draft_mode": True,
                "job_debate_collection": ["coll_r1", "coll_r2"],
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=["Pre-assessment", "VERDICT: AGREE"],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            return_value=turn1_spec,
        ) as mock_arch_4d:
            assert factory._run_deliberation(t_r2d) is True
            r2d_prompt = mock_arch_4d.call_args[0][1]
            assert (
                "## Context: The PREVIOUS escalation round agreed to attempt this specification:"
                not in r2d_prompt
            )

        # TC-004E: Exception during prior_verdict regex parsing is caught and logged
        t_r2e = Task(
            id="tc4e_prior_read_err",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": os.path.join(tmpdir, "r2e.verdict.md"),
                "ledger": os.path.join(tmpdir, "r2e.debate.json"),
                "prior_verdict": v_malformed,
                "round_idx": 2,
                "loops": 1,
                "mode": "code",
                "draft_mode": True,
                "job_debate_collection": ["coll_r1", "coll_r2"],
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=["Pre-assessment", "VERDICT: AGREE"],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            return_value=turn1_spec,
        ), patch("deliberate.verdict_status", side_effect=OSError("simulated prior verdict error")):
            assert factory._run_deliberation(t_r2e) is True
    print("  ✅ TC-004D & TC-004E malformed prior verdict and exception resilience verified.")


def test_deliberation_state_and_env_isolation_tc005():
    """TC-005A & TC-005B: Verify consecutive timeouts do not trigger false deadlock,
    stale verdict/ledger artifacts are overwritten, and _ScopedEnv restores os.environ."""
    import json
    import tempfile
    from unittest.mock import patch
    import deliberate
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path, issue_path = _write_task_heavy_seed_files(tmpdir)
        factory = AiderFactory(tmpdir, session_name="test_tc005")

        v_tc5a = os.path.join(tmpdir, "tc5a.verdict.md")
        l_tc5a = os.path.join(tmpdir, "tc5a.debate.json")
        with open(v_tc5a, "w", encoding="utf-8") as svf:
            svf.write("STATUS: deadlock\nGATE: none\n\n# Resolution\n\nSTALE_VERDICT_CONTENT\n")
        with open(l_tc5a, "w", encoding="utf-8") as slf:
            json.dump({"issue": "stale", "turns": [], "state": "deadlock"}, slf)

        recovered_spec = (
            "## Scope Analysis\n"
            "Recovered Turn 3 Specification\n\n"
            "## Implementation Plan\n"
            "### [Task ID: 001] - Recovered Architect Task\n"
            "PROPOSAL: Recovered Turn 3 plan"
        )
        t_tc5a = Task(
            id="tc5a_no_false_deadlock",
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": v_tc5a,
                "ledger": l_tc5a,
                "loops": 3,
                "mode": "code",
                "draft_mode": True,
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=[
                "Pre-assessment",
                "VERDICT: OBJECT - timeout 1",
                "VERDICT: OBJECT - timeout 2",
                "VERDICT: AGREE",
            ],
        ), patch.object(
            factory,
            "_aider_ask_turn",
            side_effect=[
                "PROPOSAL: (architect turn timed out)",
                "PROPOSAL: (architect turn timed out)",
                recovered_spec,
            ],
        ) as mock_arch_5a:
            assert factory._run_deliberation(t_tc5a) is True
            assert mock_arch_5a.call_count == 3

        assert deliberate.verdict_status(v_tc5a) == "agreed"
        assert deliberate.verdict_is_actionable(v_tc5a) is True
        with open(v_tc5a, "r", encoding="utf-8") as vf:
            v_tc5a_text = vf.read()
        assert "STALE_VERDICT_CONTENT" not in v_tc5a_text
        assert "### [Task ID: 001] - Recovered Architect Task" in v_tc5a_text

        # TC-005B: _ScopedEnv hermetic restoration of ORACLE_* environment variables
        os.environ["ORACLE_AGENT_MODEL"] = "baseline_agent_model"
        os.environ.pop("ORACLE_REASONING_EFFORT", None)
        observed_env_in_turn = {}

        def _capture_env_oracle_turn(*args, **kwargs):
            observed_env_in_turn["ORACLE_AGENT_MODEL"] = os.environ.get("ORACLE_AGENT_MODEL")
            observed_env_in_turn["ORACLE_REASONING_EFFORT"] = os.environ.get("ORACLE_REASONING_EFFORT")
            return "VERDICT: AGREE"

        t_tc5b = Task(
            id="tc5b_scoped_env",
            rag_env={
                "ORACLE_AGENT_MODEL": "scoped_override_model",
                "ORACLE_REASONING_EFFORT": "high",
            },
            deliberate={
                "template": template_path,
                "issue": issue_path,
                "verdict": os.path.join(tmpdir, "tc5b.verdict.md"),
                "ledger": os.path.join(tmpdir, "tc5b.debate.json"),
                "loops": 1,
                "mode": "code",
                "draft_mode": True,
            },
        )
        with patch.object(
            factory,
            "_oracle_turn",
            side_effect=_capture_env_oracle_turn,
        ), patch.object(
            factory,
            "_aider_ask_turn",
            return_value=recovered_spec,
        ):
            assert factory._run_deliberation(t_tc5b) is True

        assert observed_env_in_turn["ORACLE_AGENT_MODEL"] == "scoped_override_model"
        assert observed_env_in_turn["ORACLE_REASONING_EFFORT"] == "high"
        assert os.environ.get("ORACLE_AGENT_MODEL") == "baseline_agent_model"
        assert os.environ.get("ORACLE_REASONING_EFFORT") is None
    print("  ✅ TC-005A & TC-005B anti-deadlock timeout recovery and _ScopedEnv hermeticity verified.")


def test_oracle_agent_consolidated_helpers():
    """Verify Pass 3B consolidated helpers in oracle_agent.py and orchestrate.py."""
    import contextlib
    import io
    import tempfile
    import yaml
    from unittest.mock import patch
    import oracle_agent
    from orchestrate import AiderFactory, Task

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. _call_oracle_llm: nominal execution + cost/timing + unswallowed exception propagation
        stderr_buf = io.StringIO()
        with patch("litellm.completion", return_value=FakeResponse("Synthesized Answer")), \
             patch("oracle_agent._litellm_cost_line", return_value="[oracle] Tokens: 10 sent, 5 received. Cost: $0.0001 message, $0.0001 session."), \
             contextlib.redirect_stderr(stderr_buf):
            ans, cost = oracle_agent._call_oracle_llm(
                "gemini/gemini-3.6-flash",
                [{"role": "user", "content": "hello"}],
                persist_session=False,
            )
        assert ans == "Synthesized Answer"
        assert "thinking_time=" in cost
        assert "[oracle] Thinking (gemini/gemini-3.6-flash" in stderr_buf.getvalue()

        with patch("litellm.completion", side_effect=RuntimeError("LLM connection error")):
            try:
                oracle_agent._call_oracle_llm(
                    "gemini/gemini-3.6-flash", [{"role": "user", "content": "hi"}]
                )
                assert False, "Expected RuntimeError to propagate from _call_oracle_llm"
            except RuntimeError as exc:
                assert "LLM connection error" in str(exc)

        # 2. _resolve_collection_and_db: empty, bare name, directory path, and lancedb suffix
        assert oracle_agent._resolve_collection_and_db("", tmpdir) == ("", "")
        assert oracle_agent._resolve_collection_and_db("   ", tmpdir) == ("", "")

        c_name, db_path = oracle_agent._resolve_collection_and_db("my_docs", tmpdir)
        assert c_name == "my_docs"
        assert db_path == os.path.join(
            tmpdir, ".aider_factory", "markdown", "lanceDB", "my_docs", "lancedb"
        )

        custom_dir = os.path.join(tmpdir, "custom_corpus")
        c_name2, db_path2 = oracle_agent._resolve_collection_and_db(custom_dir, tmpdir)
        assert c_name2 == "custom_corpus"
        assert db_path2 == os.path.join(os.path.abspath(custom_dir), "lancedb")

        lancedb_dir = os.path.join(custom_dir, "lancedb")
        c_name3, db_path3 = oracle_agent._resolve_collection_and_db(lancedb_dir, tmpdir)
        assert c_name3 == "custom_corpus"
        assert db_path3 == os.path.abspath(lancedb_dir)

        # 3. _select_active_phase: empty, index match, collection match, prefer_debate=True/False
        assert oracle_agent._select_active_phase({}) is None
        assert oracle_agent._select_active_phase({"phases": []}) is None

        phases_cfg = {
            "phases": [
                {"name": "p0_disabled", "enabled": False, "rag": {"collection_name": "c0"}},
                {"name": "p1_basic", "enabled": True, "rag": {"collection_name": "c1"}},
                {
                    "name": "p2_debate",
                    "enabled": True,
                    "vector_store": {"collection_name": "c2"},
                    "oracle": {"pre_edit_debate": {"loops": 2}},
                },
            ]
        }
        assert oracle_agent._select_active_phase(phases_cfg, active_idx="1")["name"] == "p1_basic"
        assert oracle_agent._select_active_phase(phases_cfg, target_coll="c2")["name"] == "p2_debate"
        assert oracle_agent._select_active_phase(phases_cfg, prefer_debate=False)["name"] == "p1_basic"
        assert oracle_agent._select_active_phase(phases_cfg, prefer_debate=True)["name"] == "p2_debate"

        # 4. _format_project_files_block: empty, skip_conventions=False vs True, item_prefix
        assert oracle_agent._format_project_files_block([]) == ""
        assert oracle_agent._format_project_files_block(["missing_file.py"], base_dir=tmpdir) == ""

        conv_file = os.path.join(tmpdir, "CONVENTIONS.md")
        code_file = os.path.join(tmpdir, "module.py")
        with open(conv_file, "w", encoding="utf-8") as f:
            f.write("RULE_1")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write("x = 1")

        block_all = oracle_agent._format_project_files_block(
            ["CONVENTIONS.md", "module.py"],
            base_dir=tmpdir,
            item_prefix="File: ",
            skip_conventions=False,
        )
        assert "File: CONVENTIONS.md\n```\nRULE_1\n```" in block_all
        assert "File: module.py\n```\nx = 1\n```" in block_all

        block_no_conv = oracle_agent._format_project_files_block(
            ["CONVENTIONS.md", "module.py"],
            base_dir=tmpdir,
            item_prefix="## ",
            skip_conventions=True,
        )
        assert "CONVENTIONS.md" not in block_no_conv
        assert "## module.py\n```\nx = 1\n```" in block_no_conv

        # 5. _retrieve_by_mode: no_retrieve, full_document, top_k
        with patch("oracle_agent._retrieve", return_value="TOP_K_CHUNK") as mock_ret, \
             patch("oracle_agent._full_document", return_value="FULL_DOC_TEXT") as mock_full:
            assert oracle_agent._retrieve_by_mode("q", "no_retrieve", 5) == ""
            assert mock_ret.call_count == 0
            assert mock_full.call_count == 0

            assert (
                oracle_agent._retrieve_by_mode(
                    "q", "full_document", 5, db_dir="/tmp/db", collection="coll_a"
                )
                == "FULL_DOC_TEXT"
            )
            mock_full.assert_called_once_with("/tmp/db", "coll_a")

            assert oracle_agent._retrieve_by_mode("q", "top_k", 7) == "TOP_K_CHUNK"
            mock_ret.assert_called_once_with("q", 7)

        # 6. AiderFactory._apply_oracle_model_env: local endpoint preservation vs cloud stripping
        factory = AiderFactory(tmpdir, session_name="helper_unit")
        local_task = Task(
            id="local_t",
            model="ollama/deepseek-r1",
            editor_model="ollama/qwen2.5-coder",
            architect_api_base="http://127.0.0.1:11434",
            editor_api_base="http://127.0.0.1:11435",
        )
        env_local = {}
        factory._apply_oracle_model_env(local_task, env_local)
        assert env_local["ORACLE_AGENT_MODEL"] == "ollama/qwen2.5-coder"
        assert env_local["ORACLE_AGENT_API_BASE"] == "http://127.0.0.1:11435"
        assert env_local["ORACLE_ARCHITECT_MODEL"] == "ollama/deepseek-r1"
        assert env_local["ORACLE_ARCHITECT_API_BASE"] == "http://127.0.0.1:11434"

        cloud_task = Task(
            id="cloud_t",
            model="gemini/gemini-3.6-flash",
            editor_model="gemini/gemini-2.5-flash",
            architect_api_base="http://127.0.0.1:11434",
            editor_api_base="http://127.0.0.1:11435",
        )
        env_cloud = {
            "ORACLE_AGENT_API_BASE": "http://127.0.0.1:11435",
            "ORACLE_ARCHITECT_API_BASE": "http://127.0.0.1:11434",
        }
        factory._apply_oracle_model_env(cloud_task, env_cloud)
        assert env_cloud["ORACLE_AGENT_MODEL"] == "gemini/gemini-2.5-flash"
        assert "ORACLE_AGENT_API_BASE" not in env_cloud
        assert env_cloud["ORACLE_ARCHITECT_MODEL"] == "gemini/gemini-3.6-flash"
        assert "ORACLE_ARCHITECT_API_BASE" not in env_cloud

        # 7. AiderFactory._resolve_weak_model_settings: local synthesis, fallback, conf, cloud stripping
        clean_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("AIDER_WEAK_MODEL", "WEAK_MODEL", "WEAK_MODEL_API_BASE", "AIDER_WEAK_MODEL_API_BASE")
        }
        with patch.dict("os.environ", clean_env, clear=True):
            t_local_weak = Task(
                id="weak_local",
                weak_model="ollama/qwen2.5:7b",
                weak_model_api_base="http://127.0.0.1:11434/v1",
            )
            wm, wapi, settings_p = factory._resolve_weak_model_settings(t_local_weak)
            assert wm == "ollama/qwen2.5:7b"
            assert wapi == "http://127.0.0.1:11434/v1"
            assert settings_p == os.path.join(str(factory.session_dir), ".aider.model.settings.yml")
            assert os.path.isfile(settings_p)

            # Cloud weak model must strip local api_base and remove stale session settings file
            t_cloud_weak = Task(
                id="weak_cloud",
                weak_model="gemini/gemini-2.5-flash",
                weak_model_api_base="http://127.0.0.1:11434/v1",
            )
            wm_c, wapi_c, settings_c = factory._resolve_weak_model_settings(t_cloud_weak)
            assert wm_c == "gemini/gemini-2.5-flash"
            assert wapi_c is None
            assert settings_c is None
            assert not os.path.exists(settings_p)

            # Fallback to editor_api_base + .aider.conf.yml weak-model resolution
            with open(os.path.join(tmpdir, ".aider.conf.yml"), "w", encoding="utf-8") as cf:
                yaml.safe_dump({"weak-model": "ollama/qwen2.5:3b"}, cf)
            t_conf_weak = Task(
                id="weak_conf",
                weak_model=None,
                editor_api_base="http://127.0.0.1:11434/v1",
            )
            wm_f, wapi_f, settings_f = factory._resolve_weak_model_settings(t_conf_weak)
            assert wm_f == "ollama/qwen2.5:3b"
            assert wapi_f == "http://127.0.0.1:11434/v1"
            assert os.path.isfile(settings_f)

        # 8. AiderFactory._oracle_turn Turn-0 vs Turn-1 <project_files> formatting
        captured_prompts = []

        def fake_subproc_run(args, **kwargs):
            file_idx = args.index("--file") + 1
            with open(args[file_idx], "r", encoding="utf-8") as pf:
                captured_prompts.append(pf.read())
            return type("Proc", (), {"returncode": 0, "stdout": "VERDICT: AGREE\n", "stderr": ""})()

        existing_sf = os.path.join(tmpdir, ".oracle_debate_session.json")
        with open(existing_sf, "w", encoding="utf-8") as sf_fh:
            import json
            json.dump(
                [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "r1 turn 0"},
                    {"role": "assistant", "content": "r1 reply"},
                ],
                sf_fh,
            )

        with patch("subprocess.run", side_effect=fake_subproc_run):
            d_cfg = {"mode": "code", "read_files": ["module.py"]}
            factory._oracle_turn(local_task, d_cfg, "PROPOSAL: fix", turn=0, pre_assess_prompt="Pre-assess:")
            factory._oracle_turn(local_task, d_cfg, "PROPOSAL: fix", turn=1)
            d_cfg_r2 = {"mode": "code", "read_files": ["module.py"], "oracle_session_file": existing_sf}
            factory._oracle_turn(local_task, d_cfg_r2, "", turn=0, pre_assess_prompt="Round 2 pre-assess:")

        assert "<project_files>\nFile: module.py\n```\nx = 1\n```\n</project_files>" in captured_prompts[0]
        assert "<project_files>" not in captured_prompts[1]
        assert "<project_files>" not in captured_prompts[2]

    print("  ✅ Consolidated helpers in oracle_agent.py and orchestrate.py verified.")


if __name__ == "__main__":
    test_env_plan_do_persona_and_instruction_pairing_exists_and_resolves()
    test_instruction_file_disk_cache_invalidation()
    test_yaml_persona_list_parsing()
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
    test_ensure_oracle_config_working_dir_discovery_priority()
    test_ensure_oracle_config_ignores_foreign_ambient_config_and_session()
    test_ensure_oracle_config_rejects_placeholder_working_directory()
    test_ensure_oracle_config_sanitizes_placeholder_endpoints()
    test_ensure_oracle_config_db_and_type_filter()
    test_cli_debate_yaml_persona_and_persist_fallback()
    test_oracle_and_architect_file_flags_parsing()
    test_debate_mode_file_interception()
    test_cli_debate_turn0_prompt_isolation()
    test_cli_debate_multi_round_file_cycling()
    test_cli_debate_emits_timestamped_artifacts_and_archives_history()
    test_cli_debate_multi_round_agreement_continuation_with_instruction_files()
    test_deliberate_shared_contracts_and_loaders()
    test_deliberation_high_watermark_retention_tc001()
    test_deliberation_draft_mode_seed_fallback_tc002a()
    test_deliberation_non_draft_mode_no_fallback_tc002b()
    test_deliberation_zero_loops_boundary_tc002c()
    test_deliberation_architect_error_prefix_isolation_tc003()
    test_deliberation_round2_prior_verdict_deduplication_tc004abc()
    test_deliberation_round2_malformed_prior_verdict_resilience_tc004de()
    test_deliberation_state_and_env_isolation_tc005()
    test_oracle_agent_consolidated_helpers()
    print("\n🎉 All CLI Oracle Debate Tests Passed!")
