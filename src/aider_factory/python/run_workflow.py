#!/usr/bin/env python3
# run_workflow.py

import datetime
import glob
import os
import re
import shlex
import shutil
import sys
import threading
from typing import Optional

_python_dir = os.path.dirname(os.path.abspath(__file__))
if _python_dir not in sys.path:
    sys.path.insert(0, _python_dir)

try:
    from aider_factory.python.env_utils import (
        load_env_files,
        is_dummy_key,
        is_valid_endpoint,
        is_local_model,
        is_test_path,
        get_model_settings,
    )
except ImportError:
    from env_utils import (
        load_env_files,
        is_dummy_key,
        is_valid_endpoint,
        is_local_model,
        is_test_path,
        get_model_settings,
    )

load_env_files()

try:
    import rag_manager  # for table_name_for(): shared per-document table-name sanitizer
except ImportError:
    from aider_factory.python import rag_manager

import yaml  # type: ignore

try:
    from orchestrate import AiderFactory, Task, TaskStatus
except ImportError:
    from aider_factory.python.orchestrate import AiderFactory, Task, TaskStatus

try:
    import aggregate_costs
except ImportError:
    from aider_factory.python import aggregate_costs


try:
    from aider_factory.python.run_workflow_utils import (
        OSTee,
        _TeeWriter,
        _expand_file_list,
        _extract_files_from_plan,
        _hex_to_ansi,
        _parse_insert_debate,
        _render_testing_template,
        _render_validate_template,
        _resolve_job_debate_collection,
        _resolve_job_debate_template,
        resolve_template_path,
    )
except ImportError:
    from run_workflow_utils import (
        OSTee,
        _TeeWriter,
        _expand_file_list,
        _extract_files_from_plan,
        _hex_to_ansi,
        _parse_insert_debate,
        _render_testing_template,
        _render_validate_template,
        _resolve_job_debate_collection,
        _resolve_job_debate_template,
        resolve_template_path,
    )

script_dir = os.path.dirname(os.path.abspath(__file__))  # Verified


if __name__ in ("__main__", "__test__"):
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print("""aider-factory: Multi-agent orchestration and workflow runner.

Usage:
  aider-factory [options] [session_name] [config_file.yml]
  .aider_factory/bash/factory [options] [session_name] [config_file.yml]

Options:
  -h, --help            Show this help message and exit.
  -s, --session <name>  Explicit session identifier.
""")
        sys.exit(0)

    # Ensure user project space and bash wrappers are initialized and up-to-date
    try:
        try:
            from cli import init_user_project
        except ImportError:
            from aider_factory.cli import init_user_project
        init_user_project()
    except Exception as e:
        pass

    # Determine session name (CLI argument takes precedence over environment variable)
    session_name = None
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if (
                not arg.startswith("-")
                and not arg.endswith(".yml")
                and not arg.endswith(".yaml")
            ):
                session_name = arg
                break

    if not session_name and __name__ != "__test__":
        session_name = os.environ.get("AI_FACTORY_SESSION")

    if session_name:
        session_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", session_name.strip())
    else:
        session_name = datetime.datetime.now().strftime("session_%Y%m%d_%H%M%S_%f")

    # Determine project dir and session dir
    base_cwd = os.getcwd()
    session_dir = os.path.join(base_cwd, ".aider_factory", "sessions", session_name)
    os.makedirs(session_dir, exist_ok=True)

    hist_dir = os.path.join(session_dir, "chat_history")
    if os.path.exists(hist_dir):
        hist_files = [
            f for f in os.listdir(hist_dir) if f.startswith(".aider.chat.history_")
        ]
        if len(hist_files) > 1:
            print(
                f"⚠️  Resuming a multi-file isolated session. Found {len(hist_files)} history files in {hist_dir}.",
                file=sys.stderr,
            )

    # Resolve config YAML path (CLI argument takes precedence over environment variable)
    session_yaml = os.path.join(session_dir, "session.yml")
    yaml_path = session_yaml
    explicit_config = None
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if (
                arg.endswith(".yml")
                or arg.endswith(".yaml")
                or os.path.isfile(os.path.join(base_cwd, arg))
            ):
                if not arg.startswith("-") and arg != session_name:
                    explicit_config = arg
                    break

    if not explicit_config:
        explicit_config = os.environ.get("AI_FACTORY_CONFIG")

    if explicit_config and os.path.exists(explicit_config):
        shutil.copy2(explicit_config, session_yaml)
    elif not os.path.exists(session_yaml):
        default_config = None
        repo_stem = os.path.basename(base_cwd.rstrip("/\\")).strip().replace(" ", "_")
        candidates = [
            os.path.join(base_cwd, ".aider_factory", ".env.yml"),
            os.path.join(base_cwd, ".aider_factory", f".env_{repo_stem}.yml"),
            os.path.join(base_cwd, ".aider_factory", ".env_plan_do.yml"),
        ]
        for cand in candidates:
            if os.path.exists(cand):
                default_config = cand
                break
        if not default_config:
            aider_factory_dir = os.path.join(base_cwd, ".aider_factory")
            if os.path.exists(aider_factory_dir):
                for f in sorted(os.listdir(aider_factory_dir)):
                    if f.endswith(".yml") and not f.startswith(".aider"):
                        default_config = os.path.join(aider_factory_dir, f)
                        break
        if default_config and os.path.exists(default_config):
            shutil.copy2(default_config, session_yaml)
        else:
            print(
                "❌ Error: No pipeline configuration file found. Run 'aider-helper bootstrap' or initialize '.aider_factory/.env.yml'.",
                file=sys.stderr,
            )
            sys.exit(1)

    with open(session_yaml, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    project_directory = config.get("working_directory", base_cwd)
    if not os.path.isdir(str(project_directory)):
        project_directory = base_cwd
    os.chdir(project_directory)

    # Export session environment variables for sub-processes
    os.environ["AI_FACTORY_SESSION"] = session_name
    os.environ["ORACLE_SESSION_FILE"] = os.path.join(
        session_dir, ".oracle_session.json"
    )
    os.environ["ORACLE_DEBATE_SESSION_FILE"] = os.path.join(
        session_dir, ".oracle_debate_session.json"
    )

    test_command_prefix = config.get("test_command_prefix", "").strip()
    global_max_aider_loops = int(config.get("loop_aider_test", 1))
    global_auto_lint = config.get("auto_lint", True)
    global_lint_cmd = config.get("lint_cmd", None)

    test_runner = config.get(
        "test_runner", "Rscript .aider_factory/tests/run_tests.R {file}"
    )
    test_file_convention = config.get(
        "test_naming_and_path", "tests/testthat/test-{stem}.R"
    )

    factory: AiderFactory = AiderFactory(
        project_dir=str(project_directory),
        session_name=session_name,
        session_dir=session_dir,
    )
    file_last_tasks = {}
    file_test_files = {}
    completed_files = []
    prior_phase_terminal_tasks = []
    pipeline_discovered_targets = []
    pipeline_discovered_extra = []
    pipeline_discovered_tests = []
    pipeline_discovered_contexts = []
    pipeline_discovered_test_contexts = []

    config_base = os.path.basename(yaml_path)
    config_stem = os.path.splitext(config_base)[0].lstrip(".")
    logs_dir = os.path.join(str(project_directory), ".aider_factory", "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = os.path.join(logs_dir, f"{config_stem}_run_{timestamp}.log")
    os_tee = None
    if __name__ == "__main__":
        os_tee = OSTee(log_file_path)
        print(
            f"Starting AI Factory Pipeline\n   Config: {yaml_path}\n   Log:    {log_file_path}",
            file=sys.stderr,
        )

    try:
        # Parse Endpoints and Models
        endpoints = config.get("endpoints", {})

        global_architect_api_base = endpoints.get("architect_api_base")
        global_editor_api = endpoints.get("editor_api")
        global_editor_test_api = endpoints.get("editor_api_fallback")
        raw_weak_api_base = (
            endpoints.get("weak_model_api_base")
            or endpoints.get("weak_model_api")
            or endpoints.get("weak_api_base")
            or os.environ.get("WEAK_MODEL_API_BASE")
            or os.environ.get("AIDER_WEAK_MODEL_API_BASE")
        )
        global_weak_model_api_base = raw_weak_api_base if is_valid_endpoint(raw_weak_api_base) else None
        if global_weak_model_api_base:
            os.environ["WEAK_MODEL_API_BASE"] = str(global_weak_model_api_base)
        global_rag_agent_api = endpoints.get("rag_agent_api")
        global_grounding_api = endpoints.get("grounding_agent_api")
        raw_ranking_api = endpoints.get("ranking_api_base")
        global_ranking_api = raw_ranking_api if is_valid_endpoint(raw_ranking_api) else None

        # Find the first enabled phase to extract default RAG models if present
        global_models = config.get("models", {}) or {}
        global_weak_model = (
            global_models.get("weak_model")
            or global_models.get("weak_agent")
            or os.environ.get("AIDER_WEAK_MODEL")
            or os.environ.get("WEAK_MODEL")
        )
        first_enabled_phase = next(
            (p for p in config.get("phases", []) if p.get("enabled", True)), {}
        )
        phase_models = {**global_models, **(first_enabled_phase.get("models", {}) or {})}

        # --- RAG / Oracle globals: infrastructure + DEFAULTS ---
        DEFAULT_OCR_PROMPT = (
            "Extract the text, tables, and mathematical formulas from this page into "
            "clean Markdown. Preserve all structural integrity."
        )
        ocr_api_base = endpoints.get("ocr_api_base")
        rag_context_root = os.path.join(
            str(project_directory), ".aider_factory", "markdown", "lanceDB"
        )
        phase_rag = first_enabled_phase.get("rag", {}) or {}
        global_rag = config.get("rag", {}) or {}
        rag_embed_model = (
            phase_models.get("embed_model")
            or phase_rag.get("embed_model")
            or global_rag.get("embed_model")
            or "gemini/text-embedding-004"
        )
        rag_embed_backend = (
            phase_rag.get("embed_backend")
            or global_rag.get("embed_backend")
            or (
                "openai"
                if (
                    "embedding" in rag_embed_model.lower()
                    or "gemini" in rag_embed_model.lower()
                    or "qwen" in rag_embed_model.lower()
                )
                else "sentence-transformers"
            )
        )
        rag_embed_api_base = (
            endpoints.get("embed_api_base")
            or phase_rag.get("embed_api_base")
            or global_rag.get("embed_api_base")
        )
        rag_query_prefix = "Query: "
        rag_chunk_size = 800
        rag_chunk_overlap = 100
        rag_top_k = "5"
        rag_default_collection = ""
        rag_default_overwrite = False
        rag_default_ocr_agent = phase_models.get("ocr_agent", "")
        rag_default_ocr_prompt = DEFAULT_OCR_PROMPT
        rag_cer_threshold = 0.05
        rag_ocr_max_retries = 2
        rag_ocr_parallel = 1
        rag_ocr_max_tokens = 4096

        os.environ["ORACLE_EMBED_MODEL"] = rag_embed_model
        os.environ["ORACLE_EMBED_BACKEND"] = rag_embed_backend
        if rag_embed_api_base:
            os.environ["ORACLE_EMBED_API_BASE"] = rag_embed_api_base
        rag_default_retrieval = "top_k"

        _colors_cfg = config.get("colors", {}) or {}
        os.environ["PIPELINE_COLOR_ARCHITECT"] = _hex_to_ansi(
            _colors_cfg.get("architect_debate"), "\033[38;2;56;189;248m"
        )
        os.environ["PIPELINE_COLOR_ORACLE"] = _hex_to_ansi(
            _colors_cfg.get("oracle_debate"), "\033[38;2;211;134;155m"
        )

        conventions_path = resolve_template_path(
            "CONVENTIONS.md", project_directory=project_directory
        )

        for phase_idx, phase in enumerate(config.get("phases", [])):
            if not phase.get("enabled", True):
                continue

            phase_name = phase.get("name", f"Phase_{phase_idx}")
            env_prefix = f"p{phase_idx}"
            phase_task_ids = []

            oracle_cfg = phase.get("oracle")
            val_cfg = phase.get("validation", {}) or {}
            resolve_evidence = val_cfg.get("enabled", False)
            post_validate = val_cfg.get("post_validate", False)

            _oa_early = oracle_cfg or {}
            _start_job_early = bool(_oa_early.get("start_job", True))
            _grounding_signal_early = bool(
                (oracle_cfg is not None and _start_job_early)
                or post_validate
                or resolve_evidence
            )
            run_job_one_default = False if _grounding_signal_early else True

            # Per-phase toggles
            toggles = phase.get("toggles", {}) or {}
            run_job_one = toggles.get("run_job_one", run_job_one_default)
            run_job_two = toggles.get("run_job_two", False)
            run_job_three = toggles.get("run_job_three", False)
            iterate_test = toggles.get("iterate_test", False)
            auto_test = toggles.get("auto_test", False)
            sticky_context = toggles.get("sticky_context", False)
            pair_programming = toggles.get("pair_programming", False)

            shared_history_val = toggles.get("shared_history")
            shared_history = shared_history_val if shared_history_val is not None else False

            rag_phase_cfg = phase.get("rag", {}) or {}
            phase_run_ocr_rag = rag_phase_cfg.get("run_ocr_rag", False)

            should_skip = (
                not run_job_one
                and not run_job_two
                and not run_job_three
                and not iterate_test
                and not phase_run_ocr_rag
                and not oracle_cfg
                and not resolve_evidence
                and not post_validate
            )
            if should_skip:
                print(
                    f"ℹ️  Skipping phase '{phase_name}': all job and execution toggles are disabled.",
                    flush=True,
                )
                continue

            yes_always_val = toggles.get("yes_always")
            yes_always = (
                yes_always_val if yes_always_val is not None else not pair_programming
            )

            auto_accept_architect_val = toggles.get("auto_accept_architect")
            auto_accept_architect = (
                auto_accept_architect_val
                if auto_accept_architect_val is not None
                else not pair_programming
            )

            auto_commits_val = toggles.get("auto_commits")
            auto_commits = auto_commits_val if auto_commits_val is not None else True

            auto_lint_val = toggles.get("auto_lint")
            auto_lint = auto_lint_val if auto_lint_val is not None else global_auto_lint

            lint_cmd_val = toggles.get("lint_cmd")
            lint_cmd = lint_cmd_val if lint_cmd_val is not None else global_lint_cmd

            suggest_shell_commands_val = toggles.get("suggest_shell_commands")
            suggest_shell_commands = (
                suggest_shell_commands_val
                if suggest_shell_commands_val is not None
                else True
            )

            detect_urls_val = toggles.get("detect_urls")
            detect_urls = detect_urls_val if detect_urls_val is not None else False

            disable_playwright_val = toggles.get("disable_playwright")
            disable_playwright = (
                disable_playwright_val if disable_playwright_val is not None else False
            )

            weak_model = (
                phase.get("models", {}).get("weak_model")
                or phase.get("models", {}).get("weak_agent")
                or global_weak_model
            )
            raw_phase_weak_api = (
                phase.get("endpoints", {}).get("weak_model_api_base")
                or phase.get("endpoints", {}).get("weak_model_api")
                or phase.get("endpoints", {}).get("weak_api_base")
                or global_weak_model_api_base
            )
            if weak_model and not is_local_model(weak_model):
                weak_model_api_base = None
            elif is_valid_endpoint(raw_phase_weak_api):
                weak_model_api_base = raw_phase_weak_api
            else:
                weak_model_api_base = None

            task_aider_flags = {
                "map_tokens": toggles.get("map_tokens"),
                "map_refresh": toggles.get("map_refresh"),
                "map_multiplier_no_files": toggles.get("map_multiplier_no_files"),
                "max_chat_history_tokens": toggles.get("max_chat_history_tokens"),
                "yes_always": yes_always,
                "auto_accept_architect": auto_accept_architect,
                "auto_commits": auto_commits,
                "auto_lint": auto_lint,
                "lint_cmd": lint_cmd,
                "suggest_shell_commands": suggest_shell_commands,
                "detect_urls": detect_urls,
                "disable_playwright": disable_playwright,
                "weak_model": weak_model,
                "weak_model_api_base": weak_model_api_base,
            }

            oracle_cfg = phase.get("oracle")
            val_cfg = phase.get("validation", {}) or {}
            resolve_evidence = val_cfg.get("enabled", False)
            post_validate = val_cfg.get("post_validate", False)
            validation_tag = val_cfg.get("validation_tag", "evidence")
            region_threshold = val_cfg.get("region_threshold", 0.60)
            region_margin = val_cfg.get("region_margin", 2)
            region_paragraphs = val_cfg.get("region_paragraphs", 0)
            region_top_k = val_cfg.get("region_top_k", 5)
            validation_loops = val_cfg.get("validation_loops", 3)
            redo_oracle_job = val_cfg.get("redo_oracle_job", False)
            verify_all_claims = val_cfg.get("verify_all_claims", False)
            entail_threshold = val_cfg.get("entail_threshold", 0.5)

            esc_cfg = phase.get("escalation_debate", {}) or {}
            debate_loops = esc_cfg.get("loops", 0)
            debate_rounds = esc_cfg.get("rounds", 1)
            pass_history = esc_cfg.get("pass_history", True)

            rag_phase_cfg = phase.get("rag", {}) or {}
            phase_run_ocr_rag = rag_phase_cfg.get("run_ocr_rag", False)
            phase_overwrite = rag_phase_cfg.get("vectordb_overwrite", rag_default_overwrite)
            phase_batch = rag_phase_cfg.get("batch", True)

            global_models = config.get("models", {}) or {}
            phase_models = phase.get("models", {}) or {}
            models = {**global_models, **phase_models}
            ARCHITECT_AGENT = models.get("architect_agent", "")
            EDITOR_AGENT = models.get("editor_agent", "")
            # RAG-only phases need not define a test editor; fall back to the main editor.
            EDITOR_AGENT_TEST = models.get("editor_agent_test", EDITOR_AGENT)
            EDITOR_AGENT_TEST_FALLBACK = models.get("editor_agent_test_fallback", None)

            if not all([ARCHITECT_AGENT, EDITOR_AGENT]):
                print(
                    f"Error: Missing agent configurations in phase '{phase_name}'. Exiting."
                )
                sys.exit(1)

            ARCHITECT_API_BASE = (
                None if not is_local_model(ARCHITECT_AGENT) else global_architect_api_base
            )
            EDITOR_API = None if not is_local_model(EDITOR_AGENT) else global_editor_api
            EDITOR_API_FALLBACK = (
                None if not is_local_model(EDITOR_AGENT_TEST) else global_editor_test_api
            )

            # Per-phase RAG collection
            phase_collection = rag_phase_cfg.get("collection_name", rag_default_collection)

            # Zero-RAG mode bypass: if collection_name is explicitly [], "", or None
            if not phase_collection or phase_collection == []:
                phase_collection = ""
                phase_run_ocr_rag = False

            # Resolve collection and DB directory via smart path detection
            phase_custom_db = rag_phase_cfg.get("db") or global_rag.get("db")
            if phase_custom_db:
                raw_db = str(phase_custom_db).strip()
                if not (raw_db.startswith("/") or raw_db.startswith("\\") or (len(raw_db) > 1 and raw_db[1] == ":")):
                    phase_db_dir = os.path.join(str(project_directory), raw_db).replace("\\", "/")
                else:
                    phase_db_dir = os.path.abspath(os.path.expanduser(raw_db)).replace("\\", "/")
            elif phase_collection and phase_collection != "*":
                expanded = os.path.abspath(os.path.expanduser(phase_collection))
                if "/" in phase_collection or "\\" in phase_collection or os.path.exists(expanded):
                    base = os.path.basename(expanded.rstrip("/\\"))
                    if base.lower() == "lancedb":
                        phase_collection = os.path.basename(os.path.dirname(expanded.rstrip("/\\")))
                        phase_db_dir = expanded.replace("\\", "/")
                    else:
                        phase_collection = base
                        phase_db_dir = os.path.join(expanded, "lancedb").replace("\\", "/")
                else:
                    phase_db_dir = os.path.join(rag_context_root, phase_collection, "lancedb").replace("\\", "/")
            else:
                phase_db_dir = ""

            # Per-phase corpus type filter
            rag_type_filter = rag_phase_cfg.get("type_filter") or global_rag.get("type_filter")

            # Oracle side-agent: defaults to the architect model if `rag_agent` is unset.
            RAG_AGENT = models.get("rag_agent", ARCHITECT_AGENT)
            RAG_AGENT_API_BASE = None if not is_local_model(RAG_AGENT) else global_rag_agent_api
            # Grounding verifier (entailment): unset -> cosine fallback (zero behavior change).
            GROUNDING_AGENT = models.get("grounding_agent")
            GROUNDING_API_BASE = (
                None
                if (GROUNDING_AGENT and not is_local_model(GROUNDING_AGENT))
                else global_grounding_api
            )
            # Per-phase retrieval & reranker settings
            phase_retrieval_mode = rag_phase_cfg.get(
                "retrieval_mode", rag_default_retrieval
            )
            phase_top_k = str(rag_phase_cfg.get("top_k", rag_top_k))
            ranking_agent = phase_models.get("ranking_agent") or global_models.get(
                "ranking_agent", ""
            )
            raw_phase_ranking = phase.get("endpoints", {}).get("ranking_api_base") or endpoints.get("ranking_api_base") or global_ranking_api
            ranking_api_base = raw_phase_ranking if is_valid_endpoint(raw_phase_ranking) else None
            recall_k = str(rag_phase_cfg.get("recall_k", global_rag.get("recall_k", 30)))

            try:
                rag_settings = get_model_settings(RAG_AGENT, str(project_directory))
                rag_extra = (rag_settings.get("extra_params") or {}) if isinstance(rag_settings, dict) else {}
            except Exception:
                rag_extra = {}

            phase_reasoning_effort = (
                phase_models.get("reasoning_effort")
                or toggles.get("reasoning_effort")
                or global_models.get("reasoning_effort")
                or rag_extra.get("reasoning_effort")
            )
            if not phase_reasoning_effort and any(p in RAG_AGENT.lower() for p in ("gemini", "o1", "o3", "deepseek")):
                phase_reasoning_effort = "high"

            temp_candidates = [
                phase_models.get("temperature"),
                toggles.get("temperature"),
                global_models.get("temperature"),
                rag_extra.get("temperature"),
            ]
            phase_temperature = next((t for t in temp_candidates if t is not None), None)
            if phase_temperature is None and "gemini" in RAG_AGENT.lower():
                phase_temperature = 0.8

            rag_env = {
                "ORACLE_CONFIG_FILE": str(yaml_path),
                "ORACLE_PHASE_INDEX": str(phase_idx),
                "ORACLE_AGENT_MODEL": RAG_AGENT,
                "ORACLE_RAG_DB_DIR": phase_db_dir,
                "ORACLE_COLLECTION": phase_collection,
                "ORACLE_TOP_K": phase_top_k,
                "ORACLE_RECALL_K": recall_k,
                "ORACLE_RETRIEVE_MODE": phase_retrieval_mode,
                "ORACLE_ARCHITECT_MODEL": ARCHITECT_AGENT,
                "ORACLE_EMBED_MODEL": rag_embed_model,
                "ORACLE_EMBED_BACKEND": rag_embed_backend,
                "ORACLE_QUERY_PREFIX": rag_query_prefix,
                "ORACLE_RANKING_MODEL": ranking_agent,
            }
            if rag_type_filter and str(rag_type_filter).strip().lower() in ("code", "docs"):
                rag_env["ORACLE_TYPE_FILTER"] = str(rag_type_filter).strip().lower()
            if val_cfg.get("claims_only"):
                rag_env["ORACLE_CLAIMS_ONLY"] = "1"
            if phase_reasoning_effort:
                rag_env["ORACLE_REASONING_EFFORT"] = str(phase_reasoning_effort)
            if phase_temperature is not None:
                rag_env["ORACLE_TEMPERATURE"] = str(phase_temperature)
            if ranking_api_base:
                rag_env["ORACLE_RANKING_API_BASE"] = ranking_api_base
            if rag_embed_api_base:
                rag_env["ORACLE_EMBED_API_BASE"] = rag_embed_api_base
            # Resolve real key for LiteLLM routers (Lemonade, OpenRouter, etc.);
            # fall back to "sk-dummy" for local llama.cpp / LM Studio.
            _router_key = os.environ.get("LITELLM_API_KEY", "")
            _router_key = _router_key if _router_key and not is_dummy_key(_router_key) else "sk-dummy"
            if RAG_AGENT_API_BASE:
                rag_env["ORACLE_AGENT_API_BASE"] = RAG_AGENT_API_BASE
                rag_env["ORACLE_AGENT_API_KEY"] = _router_key
            if ARCHITECT_API_BASE:
                rag_env["ORACLE_ARCHITECT_API_BASE"] = ARCHITECT_API_BASE
                rag_env["ORACLE_ARCHITECT_API_KEY"] = _router_key
            # Grounding verifier -> validator.py reads these as env-default args (every path inherits
            # rag_env). Absent when grounding_agent is unset -> validator falls back to cosine.
            if GROUNDING_AGENT:
                rag_env["GROUNDING_AGENT_MODEL"] = GROUNDING_AGENT
                rag_env["GROUNDING_VERIFY_ALL"] = "1" if verify_all_claims else "0"
                rag_env["GROUNDING_ENTAIL_THRESHOLD"] = str(entail_threshold)
                if GROUNDING_API_BASE:
                    rag_env["GROUNDING_AGENT_API_BASE"] = GROUNDING_API_BASE
                    rag_env["GROUNDING_AGENT_API_KEY"] = _router_key

            # Resolve sticky_phases configuration
            sticky_phases = phase.get("sticky_phases", {}) or {}
            sticky_editable = bool(sticky_phases.get("editable", False))
            sticky_readonly = bool(sticky_phases.get("readonly", False))

            files = phase.get("files", {}) or {}
            target_files = files.get("target_files", []) or []

            # If sticky_phases enabled, extract file manifest from plan if not already discovered
            plans_cfg = phase.get("plans", {}) or {}
            explicit_plan = plans_cfg.get("job_one_plan")
            needs_discovery = (
                (sticky_editable and not pipeline_discovered_targets)
                or (sticky_readonly and not pipeline_discovered_contexts)
                or bool(explicit_plan)
            )
            plan_candidate = None
            if (sticky_editable or sticky_readonly) and needs_discovery:
                plan_candidate = resolve_template_path(
                    explicit_plan or "markdown/oracle_pre_plan/strategy_template.md",
                    project_directory=project_directory,
                )
                extracted = _extract_files_from_plan(plan_candidate, project_directory)
                if any(extracted.values()):
                    if extracted["target_files"]:
                        pipeline_discovered_targets = list(extracted["target_files"])
                    if extracted["extra_editable_files"]:
                        pipeline_discovered_extra = list(extracted["extra_editable_files"])
                    if extracted["test_files"]:
                        pipeline_discovered_tests = list(extracted["test_files"])
                    if extracted["context_files_job"]:
                        pipeline_discovered_contexts = list(extracted["context_files_job"])
                    if extracted["context_files_test"]:
                        pipeline_discovered_test_contexts = list(extracted["context_files_test"])

            # If sticky_editable and target_files is empty, inherit discovered targets
            if sticky_editable and not target_files and pipeline_discovered_targets:
                target_files = list(pipeline_discovered_targets)

            # --- Per-document expansion (batch=False) -------------------------------
            if (
                not phase_batch
                and target_files
                and any(glob.has_magic(p) for p in target_files)
            ):
                _job_dir = os.path.join(rag_context_root, phase_collection)
                _first_target = target_files[0]
                _first_target_dir = os.path.dirname(_first_target.split("*")[0])
                _out_dir = os.path.join(str(project_directory), _first_target_dir)

                if os.path.isdir(_job_dir):
                    os.makedirs(_out_dir, exist_ok=True)
                    _src_exts = (
                        rag_manager.IMAGE_EXTS
                        | rag_manager.DOC_EXTS
                        | rag_manager.TEXT_DOC_EXTS_DEFAULT
                    )
                    for _d in sorted(os.listdir(_job_dir)):
                        if (
                            os.path.isfile(os.path.join(_job_dir, _d))
                            and os.path.splitext(_d)[1].lower() in _src_exts
                        ):
                            _md = os.path.join(_out_dir, os.path.splitext(_d)[0] + ".md")
                            if not os.path.exists(_md):
                                open(_md, "a", encoding="utf-8").close()

            target_files = _expand_file_list(target_files, project_directory)

            raw_test_files = files.get("test_files", [])
            if raw_test_files is None:
                raw_test_files = []
            test_files_list = _expand_file_list(raw_test_files, project_directory)
            if not test_files_list and pipeline_discovered_tests:
                test_files_list = list(pipeline_discovered_tests)
            phase.setdefault("files", {})["test_files"] = test_files_list

            extra_editable_files = _expand_file_list(
                files.get("extra_editable_files", []), project_directory
            )
            if not extra_editable_files and pipeline_discovered_extra:
                extra_editable_files = list(pipeline_discovered_extra)

            initial_context_files = _expand_file_list(
                files.get("context_files_job", []), project_directory
            )
            if sticky_readonly and pipeline_discovered_contexts:
                for cf in pipeline_discovered_contexts:
                    if cf not in initial_context_files:
                        initial_context_files.append(cf)

            initial_context_test_files = _expand_file_list(
                files.get("context_files_test", []), project_directory
            )
            if sticky_readonly and pipeline_discovered_test_contexts:
                for cft in pipeline_discovered_test_contexts:
                    if cft not in initial_context_test_files:
                        initial_context_test_files.append(cft)

            if conventions_path not in initial_context_files:
                initial_context_files.append(conventions_path)
            if conventions_path not in initial_context_test_files:
                initial_context_test_files.append(conventions_path)

            rag_env["ORACLE_CONTEXT_FILES"] = (
                "\x1e".join(initial_context_files) if initial_context_files else ""
            )

            if not target_files:
                if sticky_editable:
                    candidate_name = os.path.basename(plan_candidate) if (plan_candidate and os.path.exists(plan_candidate)) else "strategy_template.md"
                    print(
                        f"❌ Error: No valid on-disk target files found in {candidate_name} for phase '{phase_name}'. "
                        f"Please define target files under '## Scope Analysis' in {candidate_name} or configure 'files.target_files'.",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
                    print(
                        f"Error: target_files missing in phase '{phase_name}'. Exiting.",
                        file=sys.stderr,
                        flush=True,
                    )
                sys.exit(1)

            rag_code_chunk = int(rag_phase_cfg.get("code_chunk_size", 2000))
            # Auto-derive from working_directory if not explicitly set. Active target,
            # editable, and context files must always be excluded from the vector store
            # to prevent stale code from polluting oracle retrieval.
            rag_working_repo = rag_phase_cfg.get("working_repo") or os.path.basename(
                str(project_directory).rstrip("/")
            )
            rag_code_exts = rag_phase_cfg.get("code_exts")
            rag_text_doc_exts = rag_phase_cfg.get("text_doc_exts")
            rag_ignore = rag_phase_cfg.get("ignore")

            _active = (
                (target_files or [])
                + (initial_context_files or [])
                + (initial_context_test_files or [])
            )
            code_exclude = set()
            for f in _active:
                if f:
                    if rag_working_repo and f.startswith(rag_working_repo + "/"):
                        code_exclude.add(f[len(rag_working_repo) + 1 :])
                    else:
                        code_exclude.add(f)

            ocr_ingest = None
            if phase_run_ocr_rag:
                ocr_ingest = {
                    "context_root": rag_context_root,
                    "collection_name": phase_collection,
                    "embed_model": rag_embed_model,
                    "embed_backend": rag_embed_backend,
                    "embed_api_base": rag_embed_api_base,
                    "chunk_size_chars": int(
                        rag_phase_cfg.get("chunk_size_chars", rag_chunk_size)
                    ),
                    "chunk_overlap_chars": int(
                        rag_phase_cfg.get("chunk_overlap_chars", rag_chunk_overlap)
                    ),
                    "code_chunk_size": int(
                        rag_phase_cfg.get("code_chunk_size", rag_code_chunk)
                    ),
                    "working_repo": rag_working_repo,
                    "code_exclude": code_exclude,
                    "code_exts": rag_code_exts,
                    "text_doc_exts": rag_text_doc_exts,
                    "ignore": rag_ignore,
                    "ocr_api_base": ocr_api_base,
                    "ocr_agent": models.get("ocr_agent") or rag_default_ocr_agent,
                    "ocr_prompt": rag_phase_cfg.get("ocr_prompt")
                    or phase.get("ocr_prompt")
                    or rag_default_ocr_prompt,
                    "overwrite": phase_overwrite,
                    "cer_threshold": float(
                        rag_phase_cfg.get("cer_threshold", rag_cer_threshold)
                    ),
                    "ocr_max_retries": int(
                        rag_phase_cfg.get("ocr_max_retries", rag_ocr_max_retries)
                    ),
                    "ocr_parallel": int(
                        rag_phase_cfg.get("ocr_parallel", rag_ocr_parallel)
                    ),
                    "ocr_max_tokens": int(
                        rag_phase_cfg.get("ocr_max_tokens", rag_ocr_max_tokens)
                    ),
                    "batch": phase_batch,
                    "use_docling": bool(rag_phase_cfg.get("use_docling", True)),
                    "docling_do_ocr": bool(rag_phase_cfg.get("docling_do_ocr", True)),
                    "docling_timeout": rag_phase_cfg.get("docling_timeout")
                    or global_rag.get("docling_timeout", None),
                }

            plans = phase.get("plans", {}) or {}
            j1_val = plans.get("job_one_plan")
            job_one_plan = (
                resolve_template_path(j1_val, project_directory=project_directory)
                if j1_val
                else None
            )

            j2_val = plans.get("job_two_plan")
            job_two_plan = (
                resolve_template_path(j2_val, project_directory=project_directory)
                if j2_val
                else None
            )

            j3_val = plans.get("job_three_plan")
            job_three_plan = (
                resolve_template_path(j3_val, project_directory=project_directory)
                if j3_val
                else None
            )

            it_val = plans.get("iterate_plan")
            iterate_plan = (
                resolve_template_path(it_val, project_directory=project_directory)
                if it_val
                else None
            )

            delib_val = plans.get(
                "deliberate_plan", "markdown/internal/deliberation_evidence_template.md"
            )
            deliberate_plan = resolve_template_path(
                delib_val, project_directory=project_directory
            )
            applyt_val = plans.get(
                "apply_plan", "markdown/internal/apply_evidence_template.md"
            )
            apply_plan = resolve_template_path(
                applyt_val, project_directory=project_directory
            )

            ab_val = plans.get("analyze_bugs_plan", "markdown/internal/analyze_bugs.md")
            analyze_bugs_plan = resolve_template_path(
                ab_val, project_directory=project_directory
            )

            # Resolve per-phase test naming and runner settings with global fallbacks
            phase_test_convention = (
                phase.get("test_naming_and_path")
                or (phase.get("files", {}) or {}).get("test_naming_and_path")
                or test_file_convention
            )
            phase_test_runner = (
                phase.get("test_runner")
                or (phase.get("toggles", {}) or {}).get("test_runner")
                or test_runner
            )
            phase_test_cmd_prefix = (
                phase.get("test_command_prefix")
                if phase.get("test_command_prefix") is not None
                else test_command_prefix
            )
            phase_cmd_prefix = (
                f"{phase_test_cmd_prefix.strip()} "
                if (phase_test_cmd_prefix and phase_test_cmd_prefix.strip())
                else ""
            )

            # Apply gate command: the strict-validate -> oracle-verbatim heal script, wrapped in
            # the language-agnostic test runner (same convention as the heal/test commands).
            apply_cmd = phase_cmd_prefix + phase_test_runner.replace(
                "{file}", ".aider_factory/tests/validations/apply_evidence.sh"
            )

            all_files_check = (
                target_files
                + extra_editable_files
                + initial_context_files
                + initial_context_test_files
            )
            if not any(
                os.path.exists(os.path.join(factory.project_dir, f))
                for f in all_files_check
            ):
                print(
                    f"Error: None of the specified files exist in the project directory for phase '{phase_name}'. Exiting."
                )
                sys.exit(1)

            # Ingestion runs exactly ONCE per phase (rag_manager.ingest builds every table
            # in a single call). The first task created carries the ingest payload; later
            # per-document tasks depend on it so it always completes first.
            phase_ingest = {
                "payload": ocr_ingest if phase_run_ocr_rag else None,
                "owner_id": None,
            }

            def _claim_ingest(task_id: str) -> Optional[dict]:
                payload = phase_ingest["payload"]
                if payload is not None:
                    phase_ingest["payload"] = None
                    phase_ingest["owner_id"] = task_id
                return payload

            def _with_ingest_owner(base_deps: list[str]) -> list[str]:
                deps = list(base_deps)
                owner_id = phase_ingest["owner_id"]
                if owner_id and owner_id not in deps:
                    deps.append(owner_id)
                return deps

            def _add_task(t: Task) -> None:
                phase_task_ids.append(t.id)
                factory.add_task(t)

            # Build task sequence for target files in this phase (language-agnostic).
            #
            # One skeleton, two modes (adding a 3rd..Nth = new produce/verify parts, same chassis):
            #   produce -> verify (iterate-test loop) -> escalate (debate -> apply) -> finalize
            #   grounding/review: generate+autofix -> heal         -> debate -> apply(verbatim) -> finalize
            #   code/test:        job_one+job_two    -> iterate_test -> debate -> apply(re-iterate)
            # The escalate (debate->apply) block is SHARED; only its gate/issue/template/env differ.
            for current_file in target_files:
                base_name = os.path.splitext(os.path.basename(current_file))[0]
                run_tag = f"{base_name}_{session_name}_{timestamp}"

                def _h_stem(job_prefix: str) -> Optional[str]:
                    return None if shared_history else f"{job_prefix}_{base_name}"

                # Specific test file (broadcast if 1, index-matched if many; else auto-generate).
                # When 1 target_file is paired with multiple test_files, preserve all test_files
                # for sequential execution in Job 3 / Verify.
                test_files_list = phase.get("files", {}).get("test_files")
                if test_files_list:
                    if len(target_files) == 1 and len(test_files_list) > 1:
                        specific_test_files = list(dict.fromkeys(test_files_list))
                        specific_test_file = specific_test_files[0]
                    elif len(test_files_list) == 1:
                        specific_test_file = test_files_list[0]
                        specific_test_files = [specific_test_file]
                    elif len(test_files_list) > target_files.index(current_file):
                        specific_test_file = test_files_list[
                            target_files.index(current_file)
                        ]
                        specific_test_files = [specific_test_file]
                    else:
                        specific_test_file = phase_test_convention.replace(
                            "{stem}", base_name
                        )
                        specific_test_files = [specific_test_file]
                else:
                    specific_test_file = phase_test_convention.replace(
                        "{stem}", base_name
                    )
                    specific_test_files = [specific_test_file]

                def _build_test_cmd(tf_path: str) -> str:
                    if "{file}" in phase_test_runner:
                        runner_resolved = phase_test_runner.replace("{file}", tf_path)
                    elif "{stem}" in phase_test_runner:
                        tf_stem = os.path.splitext(os.path.basename(tf_path))[0]
                        runner_resolved = phase_test_runner.replace("{stem}", tf_stem)
                    else:
                        runner_resolved = f"{phase_test_runner.rstrip()} {tf_path}"
                    return f"{phase_cmd_prefix}{runner_resolved}"

                # Language-agnostic execution: {prefix} {test_runner with {file} filled}.
                cmd_prefix = phase_cmd_prefix
                test_cmd = _build_test_cmd(specific_test_file)

                last_task_for_file = file_last_tasks.get(current_file)
                initial_phase_deps = [last_task_for_file] if last_task_for_file else list(prior_phase_terminal_tasks)

                # Removed: per-file task_ocr_ingest state (managed atomically by phase_ingest closures)

                # ---- mode discriminator ----
                _oa = oracle_cfg or {}
                _start_job = bool(_oa.get("start_job", True))
                pre_edit_cfg = _oa.get("pre_edit_debate", {}) or {}
                debate_j1, debate_j2, debate_j3 = _parse_insert_debate(pre_edit_cfg)

                # A "grounding signal" means this phase intends the evidence-grounding/review path.
                grounding_signal = (
                    (oracle_cfg is not None and _start_job)
                    or post_validate
                    or resolve_evidence
                )
                # Code mode: a code produce-job (run_job_one/two/three), an explicit start_job:false, or a
                # bare iterate_test loop with no grounding intent ("iterate existing code tests").
                code_mode = (
                    bool(run_job_one or run_job_two or run_job_three)
                    or (oracle_cfg is not None and not _start_job and not grounding_signal)
                    or (iterate_test and not grounding_signal)
                )
                grounding_mode = not code_mode
                escalate = bool(debate_loops and debate_loops > 0)

                # Common per-file work paths + oracle env (batch=False -> per-doc table, else shared).
                _out_abs = os.path.join(str(project_directory), current_file)
                _vdir = os.path.join(
                    str(project_directory), ".aider_factory", "logs", "validations"
                )
                _ddir = os.path.join(
                    str(project_directory), ".aider_factory", "logs", "debates"
                )
                _context_md = os.path.join(_vdir, base_name + ".context.md")
                _gate_report = os.path.join(_vdir, base_name + ".gate.md")
                _verdict_abs = os.path.join(_ddir, base_name + ".verdict.md")
                _dledger_abs = os.path.join(_ddir, base_name + ".debate.json")
                file_rag_env = dict(rag_env)
                if not phase_batch:
                    _table = rag_manager.table_name_for(current_file)
                    file_rag_env["ORACLE_COLLECTION"] = _table
                else:
                    _table = phase_collection
                    file_rag_env["ORACLE_COLLECTION"] = "*"
                file_rag_env["ORACLE_RETRIEVE_MODE"] = phase_retrieval_mode

                # Escalation params, filled by whichever mode runs; consumed by the shared block.
                _debate = None
                _apply_kwargs = None
                _build_finalize = False

                def _build_pre_edit_debate_tasks(
                    job_num: int,
                    issue_file: Optional[str],
                    debate_reads: list[str],
                    editable_files: list[str],
                    base_rag_env: dict,
                    editor_model: str,
                    editor_api_base: Optional[str],
                    initial_deps: list[str],
                    testing_context: Optional[dict] = None,
                ) -> tuple[str, str]:
                    # Removed: global bindings; managed via closure over phase_ingest
                    _pre_loops = pre_edit_cfg.get("loops")
                    _job_loops = _pre_loops if _pre_loops is not None else 3
                    _job_rounds = int(pre_edit_cfg.get("rounds", 1))
                    _job_pass_history = bool(pre_edit_cfg.get("pass_history", True))
                    _job_persist = bool(pre_edit_cfg.get("persist", False))
                    _job_orc_persona = pre_edit_cfg.get("oracle_persona", "")
                    _job_arch_persona = pre_edit_cfg.get("architect_persona", "")
                    _job_orc_file = pre_edit_cfg.get("oracle_file", "")
                    _job_arch_file = pre_edit_cfg.get("architect_file", "")

                    _debate_template = _resolve_job_debate_template(
                        pre_edit_cfg,
                        job_num=job_num,
                        project_directory=project_directory,
                    )

                    _raw_coll = pre_edit_cfg.get("job_debate_collection")
                    if isinstance(_raw_coll, (list, tuple)):
                        if len(_raw_coll) >= job_num:
                            _job_coll_entry = _raw_coll[job_num - 1]
                        elif len(_raw_coll) > 0:
                            _job_coll_entry = _raw_coll[0]
                        else:
                            _job_coll_entry = None
                    else:
                        _job_coll_entry = _raw_coll

                    prev_debate_id = None
                    _verdict_job_abs = ""
                    for r_idx in range(1, _job_rounds + 1):
                        _j_coll, _j_db, _j_mode = _resolve_job_debate_collection(
                            pre_edit_cfg,
                            job_num=job_num,
                            default_collection=_table,
                            rag_context_root=rag_context_root,
                            default_db=base_rag_env.get("ORACLE_RAG_DB_DIR", ""),
                            project_directory=project_directory,
                            round_num=r_idx,
                        )
                        _j_rag_env = dict(base_rag_env)
                        if (
                            pre_edit_cfg.get("job_debate_collection") is not None
                            or pre_edit_cfg.get("job_debate_db") is not None
                        ):
                            _j_rag_env["ORACLE_COLLECTION"] = _j_coll
                            _j_rag_env["ORACLE_RAG_DB_DIR"] = _j_db

                        r_suf = f"_r{r_idx}" if _job_rounds > 1 else ""
                        job_debate_id = (
                            f"{env_prefix}_job{job_num}_debate_{base_name}{r_suf}"
                        )
                        _verdict_job_abs = os.path.join(
                            _ddir, f"{base_name}.job{job_num}_verdict{r_suf}.md"
                        )
                        _ledger_job_abs = os.path.join(
                            _ddir, f"{base_name}.job{job_num}_debate{r_suf}.json"
                        )

                        _r_deliberate = {
                            "template": _debate_template,
                            "issue": issue_file,
                            "verdict": _verdict_job_abs,
                            "ledger": _ledger_job_abs,
                            "gate_cmd": None,
                            "loops": _job_loops,
                            "retrieve_mode": _j_mode
                            if pre_edit_cfg.get("job_debate_collection") is not None
                            else phase_retrieval_mode,
                            "mode": "code",
                            "draft_mode": True,
                            "read_files": debate_reads,
                            "editable_files": list(editable_files),
                            "round_idx": r_idx,
                            "pass_history": _job_pass_history,
                            "persist": _job_persist,
                            "oracle_persona": _job_orc_persona,
                            "architect_persona": _job_arch_persona,
                            "oracle_file": _job_orc_file,
                            "architect_file": _job_arch_file,
                            "job_debate_collection": _job_coll_entry,
                        }
                        if r_idx > 1:
                            _r_deliberate["prior_verdict"] = os.path.join(
                                _ddir,
                                f"{base_name}.job{job_num}_verdict_r{r_idx - 1}.md",
                            )
                            _r_deliberate["prior_ledger"] = os.path.join(
                                _ddir,
                                f"{base_name}.job{job_num}_debate_r{r_idx - 1}.json",
                            )

                        _r_depends = (
                            [prev_debate_id]
                            if prev_debate_id
                            else _with_ingest_owner(initial_deps)
                        )
                        _r_ingest = _claim_ingest(job_debate_id) if r_idx == 1 else None
                        _add_task(
                            Task(
                                id=job_debate_id,
                                depends_on=_r_depends,
                                model=ARCHITECT_AGENT,
                                editor_model=editor_model,
                                weak_model=weak_model,
                                weak_model_api_base=weak_model_api_base,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=editor_api_base,
                                rag_env=_j_rag_env,
                                ocr_ingest=_r_ingest,
                                deliberate=_r_deliberate,
                                history_stem=_h_stem(f"job{job_num}"),
                                testing_context=testing_context,
                            )
                        )
                        prev_debate_id = job_debate_id

                    return prev_debate_id, _verdict_job_abs

                def _build_escalation_rounds(
                    base_debate: dict,
                    base_apply_kwargs: dict,
                    apply_files: list[str],
                    delib_rag_env: dict,
                    start_dep_id: Optional[str],
                    tf_suf: str = "",
                    build_finalize: bool = False,
                ) -> Optional[str]:
                    cur_last_task = start_dep_id
                    _r_ledger = ""
                    for round_idx in range(1, debate_rounds + 1):
                        round_suf = f"_r{round_idx}" if debate_rounds > 1 else ""
                        _r_verdict = os.path.join(
                            _ddir, f"{base_name}{tf_suf}{round_suf}.verdict.md"
                        )
                        _r_ledger = os.path.join(
                            _ddir, f"{base_name}{tf_suf}{round_suf}.debate.json"
                        )

                        _round_debate = dict(base_debate)
                        _round_debate["verdict"] = _r_verdict
                        _round_debate["ledger"] = _r_ledger
                        _round_debate["round_idx"] = round_idx
                        _round_debate["pass_history"] = pass_history
                        _round_debate["persist"] = bool(esc_cfg.get("persist", False))
                        _round_debate["oracle_persona"] = esc_cfg.get("oracle_persona", "")
                        _round_debate["architect_persona"] = esc_cfg.get("architect_persona", "")
                        _round_debate["oracle_file"] = esc_cfg.get("oracle_file", "")
                        _round_debate["architect_file"] = esc_cfg.get("architect_file", "")
                        if round_idx > 1:
                            _round_debate["prior_ledger"] = os.path.join(
                                _ddir, f"{base_name}{tf_suf}_r{round_idx - 1}.debate.json"
                            )
                            _round_debate["prior_verdict"] = os.path.join(
                                _ddir, f"{base_name}{tf_suf}_r{round_idx - 1}.verdict.md"
                            )

                        _r_apply_kwargs = dict(base_apply_kwargs)
                        if debate_rounds > 1 and round_idx < debate_rounds:
                            _r_apply_kwargs["soft_fail"] = True
                        if build_finalize:
                            _r_apply_kwargs["rag_env"] = dict(
                                base_apply_kwargs.get("rag_env", {})
                            )
                            _r_apply_kwargs["rag_env"]["ORACLE_BASELINE_LEDGER"] = _r_ledger

                        delib_id = f"{env_prefix}_deliberate_{base_name}{tf_suf}{round_suf}"
                        _delib_deps = (
                            [cur_last_task]
                            if round_idx > 1
                            else _with_ingest_owner(
                                [cur_last_task]
                                if cur_last_task
                                else initial_phase_deps
                            )
                        )
                        _add_task(
                            Task(
                                id=delib_id,
                                depends_on=_delib_deps,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                weak_model=weak_model,
                                weak_model_api_base=weak_model_api_base,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_API,
                                rag_env=delib_rag_env,
                                deliberate=_round_debate,
                                history_stem=_h_stem(f"escalate{tf_suf}"),
                            )
                        )

                        apply_id = f"{env_prefix}_apply_{base_name}{tf_suf}{round_suf}"
                        _add_task(
                            Task(
                                id=apply_id,
                                depends_on=[delib_id],
                                message_file=_r_verdict,
                                verdict_gate=_r_verdict,
                                files=list(apply_files),
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT_TEST,
                                fallback_editor_model=EDITOR_AGENT_TEST_FALLBACK,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_API_FALLBACK,
                                iterate_test=True,
                                auto_test=auto_test,
                                history_stem=_h_stem(f"escalate{tf_suf}"),
                                **_r_apply_kwargs,
                            )
                        )
                        cur_last_task = apply_id

                    if build_finalize:
                        finalize_id = f"{env_prefix}_finalize_{base_name}"
                        _add_task(
                            Task(
                                id=finalize_id,
                                depends_on=[cur_last_task] if cur_last_task else [],
                                rag_env=file_rag_env,
                                validate={
                                    "review": _out_abs,
                                    "source": _source_abs,
                                    "report": _gate_report,
                                    "tag": validation_tag,
                                    "finalize": True,
                                    "baseline_ledger": _r_ledger,
                                },
                                skip_aider=True,
                                history_stem=_h_stem("finalize"),
                            )
                        )
                        cur_last_task = finalize_id

                    return cur_last_task

                if grounding_mode:
                    # produce+verify for a review: generate -> autofix -> heal (all optional).
                    _source_abs = os.path.join(
                        rag_context_root, phase_collection, base_name + ".md"
                    )
                    _ledger_abs = os.path.join(_vdir, base_name + ".ledger.json")

                    # generate (oracle): fill the review template from the paper.
                    if oracle_cfg is not None and _start_job and not pair_programming:
                        _tmpl = resolve_template_path(
                            _oa.get("template"), project_directory=project_directory
                        )
                        gen_id = f"{env_prefix}_oracle_{base_name}"
                        deps = _with_ingest_owner(initial_phase_deps)
                        _gen_ingest = _claim_ingest(gen_id)
                        _add_task(
                            Task(
                                id=gen_id,
                                depends_on=deps,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_API,
                                rag_env=file_rag_env,
                                ocr_ingest=_gen_ingest,
                                oracle={
                                    "template": _tmpl,
                                    "out": _out_abs,
                                    "full_document": bool(_oa.get("full_document", True)),
                                    "redo": redo_oracle_job,
                                    "read_files": [current_file]
                                    + list(initial_context_files),
                                },
                                skip_aider=True,
                                history_stem=_h_stem("oracle"),
                            )
                        )
                        last_task_for_file = gen_id

                    # autofix (deterministic ellipsis-stitch + audit), BEFORE any agent.
                    if resolve_evidence:
                        autofix_id = f"{env_prefix}_autofix_{base_name}"
                        autofix_deps = _with_ingest_owner(
                            [last_task_for_file]
                            if last_task_for_file
                            else initial_phase_deps
                        )
                        _autofix_ingest = _claim_ingest(autofix_id)
                        _add_task(
                            Task(
                                id=autofix_id,
                                depends_on=autofix_deps,
                                rag_env=file_rag_env,
                                ocr_ingest=_autofix_ingest,
                                validate={
                                    "review": _out_abs,
                                    "source": _source_abs,
                                    "report": _context_md,
                                    "tag": validation_tag,
                                    "autofix": True,
                                    "db": phase_db_dir,
                                    "collection": _table,
                                    "region_threshold": region_threshold,
                                    "region_margin": region_margin,
                                    "top_k": region_top_k,
                                },
                                skip_aider=True,
                                history_stem=_h_stem("autofix"),
                            )
                        )
                        last_task_for_file = autofix_id

                    # heal (agent iterate loop; validator gates each attempt).
                    if post_validate:
                        _val_files = phase.get("files", {}).get("test_files") or []
                        _val_script = _val_files[0] if _val_files else None
                        if _val_script:
                            it_env = dict(file_rag_env)
                            it_env["ORACLE_REVIEW_FILE"] = _out_abs
                            it_env["ORACLE_SOURCE_FILE"] = _source_abs
                            it_env["ORACLE_VALIDATION_FILE"] = _context_md
                            it_env["ORACLE_LEDGER_FILE"] = _ledger_abs
                            it_env["ORACLE_VALIDATION_TAG"] = validation_tag
                            it_env["ORACLE_REGION_THRESHOLD"] = str(region_threshold)
                            it_env["ORACLE_REGION_MARGIN"] = str(region_margin)
                            it_env["ORACLE_REGION_PARAGRAPHS"] = str(region_paragraphs)
                            it_env["ORACLE_REGION_TOPK"] = str(region_top_k)
                            _vcmd = (
                                f"{phase_cmd_prefix}{phase_test_runner.replace('{file}', _val_script)}"
                            )
                            heal_id = f"{env_prefix}_heal_{base_name}"
                            heal_deps = _with_ingest_owner(
                                [last_task_for_file]
                                if last_task_for_file
                                else initial_phase_deps
                            )
                            _add_task(
                                Task(
                                    id=heal_id,
                                    depends_on=heal_deps,
                                    iterate_file=iterate_plan,
                                    read_files=list(initial_context_test_files),
                                    files=[
                                        current_file
                                    ],  # review only; script not editable
                                    model=ARCHITECT_AGENT,
                                    editor_model=EDITOR_AGENT_TEST,
                                    fallback_editor_model=EDITOR_AGENT_TEST_FALLBACK,
                                    architect_api_base=ARCHITECT_API_BASE,
                                    editor_api_base=EDITOR_API_FALLBACK,
                                    test_cmd=_vcmd,
                                    iterate_test=True,
                                    max_aider_loops=validation_loops,
                                    auto_test=auto_test,
                                    pair_programming=pair_programming,
                                    rag_env=it_env,
                                    history_stem=_h_stem("heal"),
                                    **task_aider_flags,
                                )
                            )
                            last_task_for_file = heal_id
                        else:
                            print(
                                f"Warning: post_validate enabled for '{phase_name}' but no "
                                f"files.test_files script provided; skipping heal for "
                                f"{current_file}."
                            )

                    # escalation params (grounding): strict grounding gate + verbatim apply + finalize.
                    if escalate:
                        _validator_script = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)), "validator.py"
                        )
                        _grounding_gate = [
                            sys.executable, _validator_script,
                            "--file", _out_abs,
                            "--source", _source_abs,
                            "--report", _gate_report,
                            "--db", phase_db_dir,
                            "--collection", _table,
                            "--tag", validation_tag,
                            "--baseline-ledger", _dledger_abs,
                            "--region-threshold", str(region_threshold),
                            "--region-margin", str(region_margin),
                            "--region-paragraphs", str(region_paragraphs),
                            "--top-k", str(region_top_k),
                        ]
                        _debate = {
                            "template": deliberate_plan,
                            "issue": _context_md,
                            "verdict": _verdict_abs,
                            "ledger": _dledger_abs,
                            "gate_cmd": _grounding_gate,
                            "loops": debate_loops,
                            "retrieve_mode": phase_retrieval_mode,
                            "mode": "grounding",
                            "review": _out_abs,
                            "source": _source_abs,
                            "tag": validation_tag,
                        }
                        _ap_env = dict(file_rag_env)
                        _ap_env["ORACLE_REVIEW_FILE"] = _out_abs
                        _ap_env["ORACLE_SOURCE_FILE"] = _source_abs
                        _ap_env["ORACLE_VALIDATION_FILE"] = _gate_report
                        _ap_env["ORACLE_BASELINE_LEDGER"] = _dledger_abs
                        _ap_env["ORACLE_VALIDATION_TAG"] = validation_tag
                        _ap_env["ORACLE_REGION_THRESHOLD"] = str(region_threshold)
                        _ap_env["ORACLE_REGION_MARGIN"] = str(region_margin)
                        _ap_env["ORACLE_REGION_PARAGRAPHS"] = str(region_paragraphs)
                        _ap_env["ORACLE_REGION_TOPK"] = str(region_top_k)
                        _apply_kwargs = dict(
                            test_cmd=apply_cmd,
                            iterate_file=apply_plan,
                            read_files=list(initial_context_test_files)
                            + ([apply_plan] if apply_plan else []),
                            max_aider_loops=validation_loops,
                            pair_programming=pair_programming,
                            rag_env=_ap_env,
                            soft_fail=True,
                            **task_aider_flags,
                        )
                        _build_finalize = True

                else:
                    # ---------- code / test mode: job_one -> job_two/iterate_test ----------
                    # Removed: local _ingest_deps (unified into _with_ingest_owner)

                    strategy_content = ""
                    strategy_file = plans.get("validate_strategy_file")
                    if not strategy_file and completed_files:
                        strategy_file = next(
                            (f for f in reversed(completed_files) if f.endswith(".md")),
                            completed_files[0],
                        )

                    if not strategy_file and (
                        sticky_editable
                        or sticky_readonly
                        or (j1_val and "strategy_template.md" in str(j1_val))
                    ):
                        default_strat = resolve_template_path(
                            "markdown/oracle_pre_plan/strategy_template.md",
                            project_directory=project_directory,
                        )
                        if (
                            default_strat
                            and os.path.exists(default_strat)
                            and os.path.getsize(default_strat) > 0
                        ):
                            strategy_file = default_strat

                    if strategy_file:
                        strat_abs = (
                            strategy_file
                            if os.path.isabs(strategy_file)
                            else os.path.join(str(project_directory), strategy_file)
                        )
                        if os.path.exists(strat_abs):
                            with open(strat_abs, "r", encoding="utf-8") as sf:
                                raw_strat = sf.read()
                            if (
                                plans.get("validate_strategy_file")
                                or "[Define implementation/refactoring scope and objectives]"
                                not in raw_strat
                            ):
                                strategy_content = raw_strat

                    session_tmpl_dir = os.path.join(session_dir, "templates")
                    baseline_key = f"{env_prefix}_{base_name}"
                    tracked_impl_files = [current_file] + list(extra_editable_files)
                    baseline_capture_ctx = {
                        "role": "capture_baseline",
                        "baseline_key": baseline_key,
                        "tracked_files": tracked_impl_files,
                        "test_file": specific_test_files,
                    }
                    test_rag_env = dict(file_rag_env)
                    test_rag_env["ORACLE_CONTEXT_FILES"] = (
                        "\x1e".join(initial_context_test_files)
                        if initial_context_test_files
                        else ""
                    )

                    # =================================================================
                    # JOB 1: IMPLEMENTATION
                    # =================================================================
                    if run_job_one:
                        job1_id = f"{env_prefix}_job1_{base_name}"
                        is_post_test_sticky_review = bool(
                            sticky_editable
                            and not run_job_two
                            and not run_job_three
                            and not iterate_test
                            and current_file in file_test_files
                        )
                        job1_reads = list(initial_context_files)
                        if is_post_test_sticky_review and sticky_readonly:
                            for cft in initial_context_test_files:
                                if cft not in job1_reads:
                                    job1_reads.append(cft)
                        if sticky_context:
                            for cf in completed_files:
                                if cf not in job1_reads:
                                    job1_reads.append(cf)
                        job1_files = [current_file] + list(extra_editable_files)
                        if is_post_test_sticky_review:
                            prior_tfs = file_test_files[current_file]
                            if isinstance(prior_tfs, str):
                                prior_tfs = [prior_tfs]
                            for prior_tf in prior_tfs:
                                if prior_tf and prior_tf not in job1_files:
                                    job1_files.append(prior_tf)
                        job1_depends = _with_ingest_owner(
                            initial_phase_deps
                        )
                        job1_msg_file = job_one_plan

                        if debate_j1:
                            _debate_reads = list(
                                dict.fromkeys(
                                    [current_file]
                                    + list(extra_editable_files)
                                    + list(initial_context_files)
                                    + (completed_files if sticky_context else [])
                                )
                            )
                            if job_one_plan and job_one_plan not in _debate_reads:
                                _debate_reads.append(job_one_plan)

                            prev_debate_id, _verdict_job1_abs = (
                                _build_pre_edit_debate_tasks(
                                    job_num=1,
                                    issue_file=job_one_plan,
                                    debate_reads=_debate_reads,
                                    editable_files=list(job1_files),
                                    base_rag_env=file_rag_env,
                                    editor_model=EDITOR_AGENT,
                                    editor_api_base=EDITOR_API,
                                    initial_deps=_with_ingest_owner(initial_phase_deps),
                                )
                            )
                            job1_depends = [prev_debate_id]
                            job1_msg_file = _verdict_job1_abs
                            if job_one_plan and job_one_plan not in job1_reads:
                                job1_reads.append(job_one_plan)

                        job1_ingest = _claim_ingest(job1_id)
                        _add_task(
                            Task(
                                id=job1_id,
                                depends_on=job1_depends,
                                message_file=job1_msg_file,
                                verdict_gate=job1_msg_file if debate_j1 else None,
                                read_files=job1_reads,
                                files=job1_files,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_API,
                                rag_env=file_rag_env,
                                ocr_ingest=job1_ingest,
                                pair_programming=pair_programming,
                                history_stem=_h_stem("job1"),
                                testing_context=baseline_capture_ctx,
                                **task_aider_flags,
                            )
                        )
                        last_task_for_file = job1_id

                    # =================================================================
                    # JOB 2: SPEC AUDIT / VALIDATION
                    # =================================================================
                    if run_job_two:
                        job2_id = f"{env_prefix}_job2_{base_name}"
                        job2_depends = _with_ingest_owner(
                            [last_task_for_file] if last_task_for_file else list(initial_phase_deps)
                        )

                        if job_two_plan:
                            if (
                                strategy_content
                                and os.path.exists(job_two_plan)
                                and "## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS"
                                in open(job_two_plan, encoding="utf-8").read()
                            ):
                                rendered_plan = os.path.join(
                                    session_tmpl_dir, f"{base_name}_validate_rendered.md"
                                )
                                job2_msg_file = _render_validate_template(
                                    job_two_plan, strategy_content, rendered_plan
                                )
                            else:
                                job2_msg_file = job_two_plan
                        else:
                            job2_msg_file = None

                        if debate_j2:
                            _debate_reads = list(
                                dict.fromkeys(
                                    [current_file]
                                    + list(extra_editable_files)
                                    + list(initial_context_files)
                                    + (completed_files if sticky_context else [])
                                )
                            )
                            if job2_msg_file and job2_msg_file not in _debate_reads:
                                _debate_reads.append(job2_msg_file)

                            prev_debate_id, _verdict_job2_abs = (
                                _build_pre_edit_debate_tasks(
                                    job_num=2,
                                    issue_file=job2_msg_file,
                                    debate_reads=_debate_reads,
                                    editable_files=[current_file]
                                    + list(extra_editable_files),
                                    base_rag_env=file_rag_env,
                                    editor_model=EDITOR_AGENT,
                                    editor_api_base=EDITOR_API,
                                    initial_deps=_with_ingest_owner(
                                        [last_task_for_file]
                                        if last_task_for_file
                                        else list(initial_phase_deps)
                                    ),
                                )
                            )
                            job2_depends = [prev_debate_id]
                            job2_msg_file = _verdict_job2_abs

                        job2_reads = [current_file] + list(initial_context_files)
                        if sticky_context:
                            for cf in completed_files:
                                if cf not in job2_reads:
                                    job2_reads.append(cf)
                        if job2_msg_file and job2_msg_file not in job2_reads:
                            job2_reads.append(job2_msg_file)

                        job2_ingest = _claim_ingest(job2_id)
                        _add_task(
                            Task(
                                id=job2_id,
                                depends_on=job2_depends,
                                message_file=job2_msg_file,
                                verdict_gate=job2_msg_file if debate_j2 else None,
                                read_files=job2_reads,
                                files=[current_file] + extra_editable_files,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_API,
                                pair_programming=pair_programming,
                                rag_env=file_rag_env,
                                ocr_ingest=job2_ingest,
                                history_stem=_h_stem("job2"),
                                testing_context=baseline_capture_ctx,
                                **task_aider_flags,
                            )
                        )
                        last_task_for_file = job2_id

                    # =================================================================
                    # JOB 3: WRITE TESTS & JOB 4: ITERATE TESTS
                    # =================================================================
                    if run_job_three or iterate_test:
                        file_test_files[current_file] = list(specific_test_files)
                        effective_iterate_plan = iterate_plan
                        if (
                            iterate_plan
                            and os.path.exists(iterate_plan)
                            and strategy_content
                        ):
                            rendered_iterate_plan = os.path.join(
                                session_tmpl_dir,
                                f"{base_name}_testing_iterate_rendered.md",
                            )
                            effective_iterate_plan = _render_testing_template(
                                iterate_plan,
                                strategy_content,
                                rendered_iterate_plan,
                                include_diff=False,
                            )

                        effective_job3_plan = job_three_plan
                        render_job3_ctx = None
                        debated_job3_msg_file = None

                        if run_job_three:
                            if (
                                job_three_plan
                                and os.path.exists(job_three_plan)
                                and (
                                    strategy_content
                                    or os.path.basename(job_three_plan)
                                    in ("testing_exec.md", "testing.md")
                                )
                            ):
                                rendered_job3_plan = os.path.join(
                                    session_tmpl_dir,
                                    f"{base_name}_testing_exec_rendered.md",
                                )
                                effective_job3_plan = _render_testing_template(
                                    job_three_plan,
                                    strategy_content,
                                    rendered_job3_plan,
                                    git_diff_text="",
                                    include_diff=True,
                                )
                                render_job3_ctx = {
                                    "role": "render_testing_exec",
                                    "baseline_key": baseline_key,
                                    "tracked_files": tracked_impl_files,
                                    "test_file": specific_test_files,
                                    "template_path": job_three_plan,
                                    "strategy_content": strategy_content,
                                    "output_path": rendered_job3_plan,
                                }

                            if debate_j3:
                                _debate_reads = list(
                                    dict.fromkeys(
                                        [current_file]
                                        + list(specific_test_files)
                                        + list(extra_editable_files)
                                        + list(initial_context_test_files)
                                        + (completed_files if sticky_context else [])
                                    )
                                )
                                if (
                                    effective_job3_plan
                                    and effective_job3_plan not in _debate_reads
                                ):
                                    _debate_reads.append(effective_job3_plan)

                                prev_debate_id, _verdict_job3_abs = (
                                    _build_pre_edit_debate_tasks(
                                        job_num=3,
                                        issue_file=effective_job3_plan,
                                        debate_reads=_debate_reads,
                                        editable_files=list(specific_test_files),
                                        base_rag_env=test_rag_env,
                                        editor_model=EDITOR_AGENT_TEST,
                                        editor_api_base=EDITOR_API_FALLBACK,
                                        initial_deps=_with_ingest_owner(
                                            [last_task_for_file]
                                            if last_task_for_file
                                            else list(initial_phase_deps)
                                        ),
                                        testing_context=render_job3_ctx,
                                    )
                                )
                                last_task_for_file = prev_debate_id
                                debated_job3_msg_file = _verdict_job3_abs

                        for tf_idx, cur_test_file in enumerate(specific_test_files):
                            tf_suf = "" if tf_idx == 0 else f"_t{tf_idx + 1}"
                            cur_test_cmd = _build_test_cmd(cur_test_file)
                            job3_depends = _with_ingest_owner(
                                [last_task_for_file] if last_task_for_file else list(initial_phase_deps)
                            )

                            if run_job_three:
                                job3_id = f"{env_prefix}_job3_{base_name}{tf_suf}"
                                job3_reads = [current_file] + list(specific_test_files[:tf_idx]) + list(initial_context_test_files)
                                if sticky_context:
                                    for cf in completed_files:
                                        if cf not in job3_reads:
                                            job3_reads.append(cf)
                                if effective_job3_plan and effective_job3_plan not in job3_reads:
                                    job3_reads.append(effective_job3_plan)

                                job3_msg_file = debated_job3_msg_file if debate_j3 else effective_job3_plan
                                job3_ingest = _claim_ingest(job3_id)

                                _add_task(
                                    Task(
                                        id=job3_id,
                                        depends_on=job3_depends,
                                        message_file=job3_msg_file,
                                        verdict_gate=job3_msg_file if debate_j3 else None,
                                        read_files=job3_reads,
                                        files=[cur_test_file, current_file]
                                        + extra_editable_files,
                                        model=ARCHITECT_AGENT,
                                        editor_model=EDITOR_AGENT_TEST,
                                        architect_api_base=ARCHITECT_API_BASE,
                                        editor_api_base=EDITOR_API_FALLBACK,
                                        pair_programming=pair_programming,
                                        rag_env=test_rag_env,
                                        ocr_ingest=job3_ingest,
                                        history_stem=_h_stem(f"job3{tf_suf}"),
                                        testing_context=render_job3_ctx if tf_idx == 0 else None,
                                        **task_aider_flags,
                                    )
                                )
                                last_task_for_file = job3_id
                                job3_depends = [job3_id]

                            if iterate_test:
                                verify_id = f"{env_prefix}_verify_{base_name}{tf_suf}"
                                verify_reads = [current_file] + list(specific_test_files[:tf_idx]) + list(initial_context_test_files)
                                if effective_iterate_plan and effective_iterate_plan not in verify_reads:
                                    verify_reads.append(effective_iterate_plan)

                                verify_ingest = _claim_ingest(verify_id)
                                _add_task(
                                    Task(
                                        id=verify_id,
                                        depends_on=job3_depends,
                                        message_file=None,
                                        iterate_file=effective_iterate_plan,
                                        read_files=verify_reads,
                                        files=[cur_test_file, current_file]
                                        + extra_editable_files,
                                        model=ARCHITECT_AGENT,
                                        editor_model=EDITOR_AGENT_TEST,
                                        fallback_editor_model=EDITOR_AGENT_TEST_FALLBACK,
                                        architect_api_base=ARCHITECT_API_BASE,
                                        editor_api_base=EDITOR_API_FALLBACK,
                                        test_cmd=cur_test_cmd,
                                        iterate_test=True,
                                        max_aider_loops=global_max_aider_loops,
                                        auto_test=auto_test,
                                        pair_programming=pair_programming,
                                        rag_env=test_rag_env,
                                        ocr_ingest=verify_ingest,
                                        soft_fail=escalate,
                                        final_check=True,
                                        history_stem=_h_stem(f"verify{tf_suf}"),
                                        **task_aider_flags,
                                    )
                                )
                                last_task_for_file = verify_id

                            if escalate and iterate_test:
                                _ct = resolve_template_path(
                                    _oa.get("template"), project_directory=project_directory
                                )
                                _esc_debate_reads = []
                                for _rf in (
                                    [current_file, cur_test_file]
                                    + list(extra_editable_files)
                                    + list(initial_context_test_files)
                                ):
                                    if _rf and _rf not in _esc_debate_reads:
                                        _esc_debate_reads.append(_rf)
                                _esc_base_debate = {
                                    "template": _ct or analyze_bugs_plan,
                                    "issue": None,
                                    "verdict": _verdict_abs,
                                    "ledger": _dledger_abs,
                                    "gate_cmd": cur_test_cmd,
                                    "loops": debate_loops,
                                    "retrieve_mode": phase_retrieval_mode,
                                    "mode": "code",
                                    "read_files": _esc_debate_reads,
                                    "editable_files": [cur_test_file, current_file]
                                    + list(extra_editable_files),
                                }
                                _esc_apply_kwargs = dict(
                                    test_cmd=cur_test_cmd,
                                    iterate_file=effective_iterate_plan,
                                    read_files=list(initial_context_test_files)
                                    + ([effective_iterate_plan] if effective_iterate_plan else []),
                                    max_aider_loops=global_max_aider_loops,
                                    pair_programming=pair_programming,
                                    rag_env=test_rag_env,
                                    soft_fail=False,
                                    final_check=True,
                                    **task_aider_flags,
                                )
                                last_task_for_file = _build_escalation_rounds(
                                    base_debate=_esc_base_debate,
                                    base_apply_kwargs=_esc_apply_kwargs,
                                    apply_files=[cur_test_file, current_file]
                                    + extra_editable_files,
                                    delib_rag_env=test_rag_env,
                                    start_dep_id=last_task_for_file,
                                    tf_suf=tf_suf,
                                    build_finalize=False,
                                )
                    elif escalate and not run_job_one and not run_job_two:
                        _ct = resolve_template_path(
                            _oa.get("template"), project_directory=project_directory
                        )
                        _debate_reads = []
                        for _rf in (
                            [current_file, specific_test_file]
                            + list(extra_editable_files)
                            + list(initial_context_test_files)
                        ):
                            if _rf and _rf not in _debate_reads:
                                _debate_reads.append(_rf)
                        _debate = {
                            "template": _ct or analyze_bugs_plan,
                            "issue": None,
                            "verdict": _verdict_abs,
                            "ledger": _dledger_abs,
                            "gate_cmd": test_cmd,
                            "loops": debate_loops,
                            "retrieve_mode": phase_retrieval_mode,
                            "mode": "code",
                            "read_files": _debate_reads,
                            "editable_files": [specific_test_file, current_file]
                            + list(extra_editable_files),
                        }
                        _apply_kwargs = dict(
                            test_cmd=test_cmd,
                            iterate_file=iterate_plan,
                            read_files=list(initial_context_test_files)
                            + ([iterate_plan] if iterate_plan else []),
                            max_aider_loops=global_max_aider_loops,
                            pair_programming=pair_programming,
                            rag_env=test_rag_env,
                            soft_fail=False,
                            final_check=True,
                            **task_aider_flags,
                        )

                # Ingest-only fallback: if nothing above carried the ingest, add a pure setup node
                # (movable, file-coupled) so a run_ocr_rag-only phase still builds the table.
                if phase_ingest["payload"] is not None:
                    ing_id = f"{env_prefix}_ingest_{base_name}"
                    ing_deps = _with_ingest_owner(
                        [last_task_for_file]
                        if last_task_for_file
                        else initial_phase_deps
                    )
                    _ing_payload = _claim_ingest(ing_id)
                    _add_task(
                        Task(
                            id=ing_id,
                            depends_on=ing_deps,
                            rag_env=file_rag_env,
                            ocr_ingest=_ing_payload,
                            skip_aider=True,
                            history_stem=_h_stem("ingest"),
                        )
                    )
                    last_task_for_file = ing_id

                # ---- shared escalation: debate -> apply (-> finalize for grounding) ----
                if escalate and _debate is not None:
                    apply_files = (
                        [specific_test_file, current_file]
                        if code_mode
                        else [current_file]
                    ) + extra_editable_files
                    last_task_for_file = _build_escalation_rounds(
                        base_debate=_debate,
                        base_apply_kwargs=_apply_kwargs,
                        apply_files=apply_files,
                        delib_rag_env=test_rag_env if code_mode else file_rag_env,
                        start_dep_id=last_task_for_file,
                        tf_suf="",
                        build_finalize=_build_finalize,
                    )

                file_last_tasks[current_file] = last_task_for_file
                if current_file not in completed_files:
                    completed_files.append(current_file)

            # Update terminal tasks of this phase to serve as dependency barrier for next phase
            prior_phase_terminal_tasks = [
                last_task for f, last_task in file_last_tasks.items() if last_task in phase_task_ids
            ]

            # In live execution mode (__main__), execute this phase's tasks now
            if __name__ == "__main__":
                factory.execute_pipeline()
                failed = [
                    t
                    for t in factory.tasks.values()
                    if t.id in phase_task_ids
                    and t.status == TaskStatus.FAILED
                    and not getattr(t, "soft_fail", False)
                ]
                if failed:
                    print(
                        f"\n❌ [aider-factory] Phase '{phase_name}' failed at task(s): {[t.id for t in failed]}. Halting pipeline.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
    finally:
        if __name__ == "__main__" and os_tee:
            os_tee.stop()
            print("\n" + "=" * 70)
            print("Run Completed. Aggregating Costs...")
            print("=" * 70)
            aggregate_costs.aggregate_log(log_file_path)
