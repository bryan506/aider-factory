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
    from aider_factory.python.env_utils import load_env_files
except ImportError:
    from env_utils import load_env_files

load_env_files()

try:
    import rag_manager  # for table_name_for(): shared per-document table-name sanitizer
except ImportError:
    from aider_factory.python import rag_manager

import yaml  # type: ignore

try:
    from orchestrate import AiderFactory, Task
except ImportError:
    from aider_factory.python.orchestrate import AiderFactory, Task

try:
    import aggregate_costs
except ImportError:
    from aider_factory.python import aggregate_costs


def _expand_file_list(file_patterns, base_dir):
    """Expand glob patterns into a deduplicated, alphabetically sorted list of relative paths.
    Literal paths with no glob magic are preserved verbatim if they exist.
    Empty or None inputs return an empty list."""
    if not file_patterns:
        return []

    expanded = []
    for pat in file_patterns:
        if glob.has_magic(pat):
            abs_pat = pat if os.path.isabs(pat) else os.path.join(str(base_dir), pat)
            for match in sorted(glob.glob(abs_pat)):
                rel_path = os.path.relpath(match, str(base_dir))
                if rel_path not in expanded:
                    expanded.append(rel_path)
        elif pat not in expanded:
            expanded.append(pat)

    return expanded


def _hex_to_ansi(hex_color: str, fallback: str) -> str:
    """Convert '#RRGGBB' to '\\033[38;2;R;G;Bm'. Returns fallback on bad input."""
    h = (hex_color or "").strip().lstrip("#")
    if len(h) != 6:
        return fallback
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"
    except ValueError:
        return fallback


script_dir = os.path.dirname(os.path.abspath(__file__))  # Verified


def _parse_insert_debate(pre_edit_cfg: dict) -> tuple[bool, bool, bool]:
    """Parse insert_debate into a 3-tuple (job1, job2, job3) boolean triggers."""
    if not pre_edit_cfg or not pre_edit_cfg.get("enabled", False):
        return (False, False, False)

    raw = pre_edit_cfg.get("insert_debate")
    if raw is None:
        return (True, False, False)

    if isinstance(raw, (list, tuple)):
        vals = [bool(x) for x in raw]
        while len(vals) < 3:
            vals.append(False)
        return (bool(vals[0]), bool(vals[1]), bool(vals[2]))

    if isinstance(raw, str):
        cleaned = re.sub(r"[^\d, ]", "", raw).replace(" ", ",")
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        vals = [bool(int(p)) if p.isdigit() else False for p in parts]
        while len(vals) < 3:
            vals.append(False)
        return (bool(vals[0]), bool(vals[1]), bool(vals[2]))

    return (True, False, False)


def _resolve_job_debate_template(
    pre_edit_cfg: dict, job_num: int, project_directory: str = None
) -> Optional[str]:
    """Resolve specialized debate prompt template for Job 1, 2, or 3."""
    if not pre_edit_cfg:
        return None

    raw = pre_edit_cfg.get("job_debate_template")
    target = None
    if isinstance(raw, (list, tuple)):
        if 0 <= (job_num - 1) < len(raw) and raw[job_num - 1]:
            target = str(raw[job_num - 1]).strip()
        elif raw and raw[0]:
            target = str(raw[0]).strip()
    elif isinstance(raw, str) and raw.strip():
        target = raw.strip()

    return (
        resolve_template_path(target, project_directory=project_directory)
        if target
        else None
    )


def _resolve_job_debate_collection(
    pre_edit_cfg: dict,
    job_num: int,
    default_collection: str,
    rag_context_root: str,
) -> tuple[str, str]:
    """Resolve specialized vector collection and LanceDB dir for Job 1, 2, or 3."""
    chosen = default_collection
    if pre_edit_cfg:
        raw = pre_edit_cfg.get("job_debate_collection")
        if isinstance(raw, (list, tuple)):
            if 0 <= (job_num - 1) < len(raw) and raw[job_num - 1]:
                chosen = str(raw[job_num - 1]).strip()
            elif raw and raw[0]:
                chosen = str(raw[0]).strip()
        elif isinstance(raw, str) and raw.strip():
            chosen = raw.strip()

    if chosen and chosen != "*" and not os.path.isabs(chosen):
        db_dir = os.path.join(rag_context_root, chosen, "lancedb")
    else:
        db_dir = (
            os.path.join(rag_context_root, default_collection, "lancedb")
            if default_collection and default_collection != "*"
            else ""
        )

    return chosen, db_dir


def _render_validate_template(
    template_path: str, strategy_content: str, output_path: str
) -> str:
    """Inject strategy_content into the validate template's placeholder section."""
    if not template_path or not os.path.exists(template_path):
        return template_path

    with open(template_path, "r", encoding="utf-8") as vf:
        val_text = vf.read()

    injection = f"## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS\n\n{strategy_content.strip()}\n"
    placeholder = "## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS"

    if placeholder in val_text:
        final_text = re.sub(
            r"## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS.*?(?=\n---|\n## 2\.|\Z)",
            injection + "\n",
            val_text,
            flags=re.DOTALL,
        )
    else:
        final_text = val_text + "\n\n" + injection

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as rf:
        rf.write(final_text)

    return output_path


def resolve_template_path(path_val, project_directory=None):
    """Resolves a template path, checking the local project directory first,
    then falling back to the package's bundled resources."""
    if not path_val:
        return None

    if os.path.isabs(path_val):
        return path_val

    base_proj = str(project_directory or os.getcwd())
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Strip `.aider_factory/` prefix for fallback checks
    rel_stripped = path_val
    if rel_stripped.startswith(".aider_factory/"):
        rel_stripped = rel_stripped.replace(".aider_factory/", "", 1)
    elif rel_stripped.startswith(".aider_factory\\"):
        rel_stripped = rel_stripped.replace(".aider_factory\\", "", 1)

    # Priority 1: Check exact relative path in project root
    local_exact = os.path.join(base_proj, path_val)
    if os.path.exists(local_exact):
        return local_exact

    # Priority 2: Check under project_root/.aider_factory/ (preserving subfolders if any)
    local_aider_factory = os.path.join(base_proj, ".aider_factory", rel_stripped)
    if os.path.exists(local_aider_factory):
        return local_aider_factory

    # Priority 3: Check flat fallback under project_root/.aider_factory/ (e.g., CONVENTIONS.md)
    flat_filename = os.path.basename(path_val)
    local_flat = os.path.join(base_proj, ".aider_factory", flat_filename)
    if os.path.exists(local_flat):
        return local_flat

    # Priority 4: Fall back to globally packaged site-packages resources
    pkg_fallback = os.path.join(script_dir, "..", rel_stripped)
    if os.path.exists(pkg_fallback):
        return pkg_fallback

    # Priority 5: Fall back to globally packaged site-packages root-level (e.g., packaged CONVENTIONS.md)
    pkg_flat = os.path.join(script_dir, "..", flat_filename)
    if os.path.exists(pkg_flat):
        return pkg_flat

    return local_exact


class OSTee:
    """Redirects OS file descriptors 1 (stdout) and 2 (stderr) so that ALL output from
    Python AND child subprocesses (script, aider, Rscript) is captured to log_file
    while streaming live to the terminal.
    """

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.orig_stdout_fd = os.dup(1)
        self.orig_stderr_fd = os.dup(2)

        self.pipe_r, self.pipe_w = os.pipe()

        os.dup2(self.pipe_w, 1)
        os.dup2(self.pipe_w, 2)

        self.log_file = open(self.log_path, "a", encoding="utf-8", errors="replace")

        self.running = True
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        while self.running:
            try:
                data = os.read(self.pipe_r, 4096)
                if not data:
                    break
                os.write(self.orig_stdout_fd, data)
                text = data.decode("utf-8", errors="replace")
                self.log_file.write(text)
                self.log_file.flush()
            except Exception:
                break

    def stop(self):
        self.running = False
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(self.orig_stdout_fd, 1)
        os.dup2(self.orig_stderr_fd, 2)
        try:
            os.close(self.pipe_w)
        except OSError:
            pass
        self.thread.join(timeout=1.0)
        try:
            os.close(self.pipe_r)
        except OSError:
            pass
        os.close(self.orig_stdout_fd)
        os.close(self.orig_stderr_fd)
        self.log_file.close()


if __name__ in ("__main__", "__test__"):
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
        local_std = os.path.join(base_cwd, ".aider_factory", ".env.yml")
        if os.path.exists(local_std):
            default_config = local_std
        else:
            aider_factory_dir = os.path.join(base_cwd, ".aider_factory")
            if os.path.exists(aider_factory_dir):
                for f in os.listdir(aider_factory_dir):
                    if f.endswith(".yml") and not f.startswith("."):
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
    completed_files = []

    # Parse Endpoints and Models
    endpoints = config.get("endpoints", {})

    global_architect_api_base = endpoints.get("architect_api_base")
    global_editor_api = endpoints.get("editor_ollama_api")
    global_editor_test_api = endpoints.get("editor_test_ollama_api")
    global_rag_agent_api = endpoints.get("rag_agent_api")
    global_grounding_api = endpoints.get("grounding_agent_api")
    global_ranking_api = endpoints.get("ranking_api_base")

    # Find the first enabled phase to extract default RAG models if present
    global_models = config.get("models", {}) or {}
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

        # Per-phase toggles
        toggles = phase.get("toggles", {}) or {}
        run_job_one = toggles.get("run_job_one", True)
        run_job_two = toggles.get("run_job_two", False)
        run_job_three = toggles.get("run_job_three", False)
        iterate_test = toggles.get("iterate_test", False)
        auto_test = toggles.get("auto_test", False)
        sticky_context = toggles.get("sticky_context", False)
        pair_programming = toggles.get("pair_programming", False)

        oracle_cfg = phase.get("oracle")
        val_cfg = phase.get("validation", {}) or {}
        resolve_evidence = val_cfg.get("enabled", False)
        post_validate = val_cfg.get("post_validate", False)

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

        task_aider_flags = {
            "map_tokens": toggles.get("map_tokens"),
            "map_refresh": toggles.get("map_refresh"),
            "map_multiplier_no_files": toggles.get("map_multiplier_no_files"),
            "max_chat_history_tokens": toggles.get("max_chat_history_tokens"),
            "yes_always": yes_always,
            "auto_accept_architect": auto_accept_architect,
            "auto_commits": auto_commits,
            "suggest_shell_commands": suggest_shell_commands,
            "detect_urls": detect_urls,
            "disable_playwright": disable_playwright,
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
        pass_round_history = esc_cfg.get("pass_round_history", True)

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
            None if "gemini/" in ARCHITECT_AGENT else global_architect_api_base
        )
        EDITOR_OLLAMA_API = None if "gemini/" in EDITOR_AGENT else global_editor_api
        EDITOR_TEST_OLLAMA_API = (
            None if "gemini/" in EDITOR_AGENT_TEST else global_editor_test_api
        )

        # Per-phase RAG collection
        phase_collection = rag_phase_cfg.get("collection_name", rag_default_collection)

        # Zero-RAG mode bypass: if collection_name is explicitly [], "", or None
        if not phase_collection or phase_collection == []:
            phase_collection = ""
            phase_run_ocr_rag = False

        phase_db_dir = (
            os.path.join(rag_context_root, phase_collection, "lancedb")
            if phase_collection
            else ""
        )

        # Oracle side-agent: defaults to the architect model if `rag_agent` is unset.
        RAG_AGENT = models.get("rag_agent", ARCHITECT_AGENT)
        RAG_AGENT_API_BASE = None if "gemini/" in RAG_AGENT else global_rag_agent_api
        # Grounding verifier (entailment): unset -> cosine fallback (zero behavior change). gemini/
        # needs no api_base (same rule as architect/oracle).
        GROUNDING_AGENT = models.get("grounding_agent")
        GROUNDING_API_BASE = (
            None
            if (GROUNDING_AGENT and "gemini/" in GROUNDING_AGENT)
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
        ranking_api_base = endpoints.get("ranking_api_base") or global_ranking_api
        recall_k = str(rag_phase_cfg.get("recall_k", global_rag.get("recall_k", 30)))

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
        if ranking_api_base:
            rag_env["ORACLE_RANKING_API_BASE"] = ranking_api_base
        if rag_embed_api_base:
            rag_env["ORACLE_EMBED_API_BASE"] = rag_embed_api_base
        if RAG_AGENT_API_BASE:
            rag_env["ORACLE_AGENT_API_BASE"] = RAG_AGENT_API_BASE
            rag_env["ORACLE_AGENT_API_KEY"] = "sk-dummy"
        if ARCHITECT_API_BASE:
            rag_env["ORACLE_ARCHITECT_API_BASE"] = ARCHITECT_API_BASE
            rag_env["ORACLE_ARCHITECT_API_KEY"] = "sk-dummy"
        # Grounding verifier -> validator.py reads these as env-default args (every path inherits
        # rag_env). Absent when grounding_agent is unset -> validator falls back to cosine.
        if GROUNDING_AGENT:
            rag_env["GROUNDING_AGENT_MODEL"] = GROUNDING_AGENT
            rag_env["GROUNDING_VERIFY_ALL"] = "1" if verify_all_claims else "0"
            rag_env["GROUNDING_ENTAIL_THRESHOLD"] = str(entail_threshold)
            if GROUNDING_API_BASE:
                rag_env["GROUNDING_AGENT_API_BASE"] = GROUNDING_API_BASE
                rag_env["GROUNDING_AGENT_API_KEY"] = "sk-dummy"

        # If this phase ingests, build the params for rag_manager.ingest(...) which
        # orchestrate.py runs as the first step of this phase's task (movable, repeatable).
        files = phase.get("files", {})
        target_files = files.get("target_files", []) or []

        # --- Per-document expansion (batch=False) -------------------------------
        # Each source document becomes its own LanceDB table AND its own output .md.
        # Auto-create the per-doc output files so a wildcard in target_files resolves
        # on a fresh collection (no manual `touch` needed). The output directory is
        # inferred from the wildcard pattern's directory.
        if (
            not phase_batch
            and target_files
            and any(glob.has_magic(p) for p in target_files)
        ):
            _job_dir = os.path.join(rag_context_root, phase_collection)

            # Safely handle wildcards or bare filenames to infer output directory
            _first_target = target_files[0]
            # Strip out wildcard characters to find the base directory
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

        # Expand wildcard patterns (sorted alphabetically for determinism and alignment).
        target_files = _expand_file_list(target_files, project_directory)

        # Note: If test_files glob yields multiple files, it relies on alphabetical symmetry
        # to index-match with target_files (e.g., target 'a.R', 'b.R' matches 'test-a.R', 'test-b.R').
        raw_test_files = files.get("test_files", [])
        if raw_test_files is None:
            raw_test_files = []
        test_files_list = _expand_file_list(raw_test_files, project_directory)
        # Put it back into the phase dict so the downstream loop finds the expanded list
        phase.setdefault("files", {})["test_files"] = test_files_list

        extra_editable_files = _expand_file_list(
            files.get("extra_editable_files", []), project_directory
        )
        initial_context_files = _expand_file_list(
            files.get("context_files_job", []), project_directory
        )
        initial_context_test_files = _expand_file_list(
            files.get("context_files_test", []), project_directory
        )

        if conventions_path not in initial_context_files:
            initial_context_files.append(conventions_path)
        if conventions_path not in initial_context_test_files:
            initial_context_test_files.append(conventions_path)

        rag_env["ORACLE_CONTEXT_FILES"] = (
            "\x1e".join(initial_context_files) if initial_context_files else ""
        )

        if not target_files or not initial_context_files:
            print(
                f"Error: target_files and context_files missing in phase '{phase_name}'. Exiting."
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

        plans = phase.get("plans", {})
        j1_val = plans.get("job_one_plan") or "markdown/templates/implement.md"
        job_one_plan = resolve_template_path(
            j1_val, project_directory=project_directory
        )

        j2_val = plans.get("job_two_plan")
        job_two_plan = (
            resolve_template_path(j2_val, project_directory=project_directory)
            if j2_val
            else None
        )

        j3_val = plans.get("job_three_plan") or "markdown/templates/testing.md"
        job_three_plan = resolve_template_path(
            j3_val, project_directory=project_directory
        )

        it_val = (
            plans.get("iterate_plan") or "markdown/templates/testing_unit_iterate.md"
        )
        iterate_plan = resolve_template_path(
            it_val, project_directory=project_directory
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
        # Apply gate command: the strict-validate -> oracle-verbatim heal script, wrapped in
        # the language-agnostic test runner (same convention as the heal/test commands).
        _aprefix = f"{test_command_prefix} " if test_command_prefix else ""
        apply_cmd = _aprefix + test_runner.replace(
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
        ingest_attached = False
        phase_ingest_owner_id = None

        # Build task sequence for target files in this phase (language-agnostic).
        #
        # One skeleton, two modes (adding a 3rd..Nth = new produce/verify parts, same chassis):
        #   produce -> verify (iterate-test loop) -> escalate (debate -> apply) -> finalize
        #   grounding/review: generate+autofix -> heal         -> debate -> apply(verbatim) -> finalize
        #   code/test:        job_one+job_two    -> iterate_test -> debate -> apply(re-iterate)
        # The escalate (debate->apply) block is SHARED; only its gate/issue/template/env differ.
        for current_file in target_files:
            base_name = os.path.splitext(os.path.basename(current_file))[0]

            # Specific test file (broadcast if 1, index-matched if many; else auto-generate).
            test_files_list = phase.get("files", {}).get("test_files")
            if test_files_list:
                if len(test_files_list) == 1:
                    specific_test_file = test_files_list[0]
                elif len(test_files_list) > target_files.index(current_file):
                    specific_test_file = test_files_list[
                        target_files.index(current_file)
                    ]
                else:
                    specific_test_file = test_file_convention.replace(
                        "{stem}", base_name
                    )
            else:
                specific_test_file = test_file_convention.replace("{stem}", base_name)
            # Language-agnostic execution: {prefix} {test_runner with {file} filled}.
            cmd_prefix = f"{test_command_prefix} " if test_command_prefix else ""
            test_cmd = (
                f"{cmd_prefix}{test_runner.replace('{file}', specific_test_file)}"
            )

            last_task_for_file = file_last_tasks.get(current_file)

            # Ingest once per phase, carried on the first node built (any mode).
            task_ocr_ingest = None
            if phase_run_ocr_rag and not ingest_attached:
                task_ocr_ingest = ocr_ingest
                ingest_attached = True

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
                or (oracle_cfg is not None and not _start_job)
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
                    deps = [last_task_for_file] if last_task_for_file else []
                    if phase_ingest_owner_id and phase_ingest_owner_id not in deps:
                        deps.append(phase_ingest_owner_id)
                    factory.add_task(
                        Task(
                            id=gen_id,
                            depends_on=deps,
                            model=ARCHITECT_AGENT,
                            editor_model=EDITOR_AGENT,
                            architect_api_base=ARCHITECT_API_BASE,
                            editor_api_base=EDITOR_OLLAMA_API,
                            rag_env=file_rag_env,
                            ocr_ingest=task_ocr_ingest,
                            oracle={
                                "template": _tmpl,
                                "out": _out_abs,
                                "full_document": bool(_oa.get("full_document", True)),
                                "redo": redo_oracle_job,
                                "read_files": [current_file]
                                + list(initial_context_files),
                            },
                            skip_aider=True,
                        )
                    )
                    if task_ocr_ingest is not None:
                        phase_ingest_owner_id = gen_id
                        task_ocr_ingest = None
                    last_task_for_file = gen_id

                # autofix (deterministic ellipsis-stitch + audit), BEFORE any agent.
                if resolve_evidence:
                    autofix_id = f"{env_prefix}_autofix_{base_name}"
                    factory.add_task(
                        Task(
                            id=autofix_id,
                            depends_on=[last_task_for_file]
                            if last_task_for_file
                            else [],
                            rag_env=file_rag_env,
                            ocr_ingest=task_ocr_ingest,
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
                        )
                    )
                    if task_ocr_ingest is not None:
                        phase_ingest_owner_id = autofix_id
                        task_ocr_ingest = None
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
                            f"{cmd_prefix}{test_runner.replace('{file}', _val_script)}"
                        )
                        heal_id = f"{env_prefix}_heal_{base_name}"
                        factory.add_task(
                            Task(
                                id=heal_id,
                                depends_on=[last_task_for_file]
                                if last_task_for_file
                                else [],
                                iterate_file=iterate_plan,
                                read_files=list(initial_context_test_files),
                                files=[
                                    current_file
                                ],  # review only; script not editable
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT_TEST,
                                fallback_editor_model=EDITOR_AGENT_TEST_FALLBACK,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_TEST_OLLAMA_API,
                                test_cmd=_vcmd,
                                iterate_test=True,
                                max_aider_loops=validation_loops,
                                auto_test=auto_test,
                                pair_programming=pair_programming,
                                rag_env=it_env,
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
                    _grounding_gate = (
                        ".aider_factory/bash/validate "
                        f"--file {shlex.quote(_out_abs)} --source {shlex.quote(_source_abs)} "
                        f"--report {shlex.quote(_gate_report)} --db {shlex.quote(phase_db_dir)} "
                        f"--collection {shlex.quote(_table)} --tag {validation_tag} "
                        f"--baseline-ledger {shlex.quote(_dledger_abs)} "
                        f"--region-threshold {region_threshold} --region-margin {region_margin} "
                        f"--region-paragraphs {region_paragraphs} --top-k {region_top_k}"
                    )
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
                def _ingest_deps(base_deps):
                    d = list(base_deps)
                    if phase_ingest_owner_id and phase_ingest_owner_id not in d:
                        d.append(phase_ingest_owner_id)
                    return d

                # =================================================================
                # JOB 1: IMPLEMENTATION
                # =================================================================
                if run_job_one:
                    job1_id = f"{env_prefix}_job1_{base_name}"
                    job1_reads = list(initial_context_files) + (
                        completed_files if sticky_context else []
                    )
                    job1_depends = _ingest_deps(
                        [last_task_for_file] if last_task_for_file else []
                    )
                    job1_msg_file = job_one_plan

                    if debate_j1:
                        job1_debate_id = f"{env_prefix}_job1_debate_{base_name}"
                        _verdict_job1_abs = os.path.join(
                            _ddir, base_name + ".job1_verdict.md"
                        )
                        _ledger_job1_abs = os.path.join(
                            _ddir, base_name + ".job1_debate.json"
                        )

                        _debate_template = _resolve_job_debate_template(
                            pre_edit_cfg, job_num=1, project_directory=project_directory
                        )
                        _j1_coll, _j1_db = _resolve_job_debate_collection(
                            pre_edit_cfg, job_num=1, default_collection=_table, rag_context_root=rag_context_root
                        )
                        _j1_rag_env = dict(file_rag_env)
                        if _j1_coll:
                            _j1_rag_env["ORACLE_COLLECTION"] = _j1_coll
                            _j1_rag_env["ORACLE_RAG_DB_DIR"] = _j1_db

                        _debate_reads = (
                            [current_file]
                            + list(extra_editable_files)
                            + list(initial_context_files)
                            + (completed_files if sticky_context else [])
                        )
                        if job_one_plan and job_one_plan not in _debate_reads:
                            _debate_reads.append(job_one_plan)

                        _pre_loops = pre_edit_cfg.get("loops")
                        _job1_loops = _pre_loops if _pre_loops is not None else 3

                        _r_deliberate = {
                            "template": _debate_template,
                            "issue": job_one_plan,
                            "verdict": _verdict_job1_abs,
                            "ledger": _ledger_job1_abs,
                            "gate_cmd": None,
                            "loops": _job1_loops,
                            "retrieve_mode": phase_retrieval_mode,
                            "mode": "code",
                            "draft_mode": True,
                            "read_files": _debate_reads,
                            "round_idx": 1,
                            "pass_round_history": pass_round_history,
                        }

                        _r_depends = _ingest_deps(
                            [last_task_for_file] if last_task_for_file else []
                        )
                        factory.add_task(
                            Task(
                                id=job1_debate_id,
                                depends_on=_r_depends,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                architect_api_base=ARCHITECT_API_BASE,
                                rag_env=_j1_rag_env,
                                ocr_ingest=task_ocr_ingest,
                                deliberate=_r_deliberate,
                            )
                        )
                        if task_ocr_ingest is not None:
                            phase_ingest_owner_id = job1_debate_id
                            task_ocr_ingest = None

                        job1_depends = [job1_debate_id]
                        job1_msg_file = _verdict_job1_abs
                        if job_one_plan and job_one_plan not in job1_reads:
                            job1_reads.append(job_one_plan)

                    factory.add_task(
                        Task(
                            id=job1_id,
                            depends_on=job1_depends,
                            message_file=job1_msg_file,
                            read_files=job1_reads,
                            files=[current_file] + extra_editable_files,
                            model=ARCHITECT_AGENT,
                            editor_model=EDITOR_AGENT,
                            architect_api_base=ARCHITECT_API_BASE,
                            editor_api_base=EDITOR_OLLAMA_API,
                            rag_env=file_rag_env,
                            ocr_ingest=task_ocr_ingest,
                            pair_programming=pair_programming,
                            **task_aider_flags,
                        )
                    )
                    if task_ocr_ingest is not None:
                        phase_ingest_owner_id = job1_id
                        task_ocr_ingest = None
                    last_task_for_file = job1_id

                # =================================================================
                # JOB 2: SPEC AUDIT / VALIDATION
                # =================================================================
                if run_job_two:
                    job2_id = f"{env_prefix}_job2_{base_name}"
                    job2_depends = _ingest_deps(
                        [last_task_for_file] if last_task_for_file else []
                    )

                    strategy_content = ""
                    strategy_file = plans.get("validate_strategy_file")
                    if not strategy_file and completed_files:
                        strategy_file = next(
                            (f for f in reversed(completed_files) if f.endswith(".md")),
                            completed_files[0],
                        )

                    if not strategy_file:
                        default_strat = os.path.join(
                            str(project_directory),
                            ".aider_factory",
                            "markdown",
                            "oracle_pre_plan",
                            "strategy_template.md",
                        )
                        if os.path.exists(default_strat) and os.path.getsize(default_strat) > 0:
                            strategy_file = default_strat

                    if strategy_file:
                        strat_abs = (
                            strategy_file
                            if os.path.isabs(strategy_file)
                            else os.path.join(str(project_directory), strategy_file)
                        )
                        if os.path.exists(strat_abs):
                            with open(strat_abs, "r", encoding="utf-8") as sf:
                                strategy_content = sf.read()

                    session_tmpl_dir = os.path.join(session_dir, "templates")
                    default_val_tmpl = resolve_template_path(
                        "markdown/templates/validate.md",
                        project_directory=project_directory,
                    )

                    if not job_two_plan and strategy_content:
                        rendered_plan = os.path.join(
                            session_tmpl_dir, f"{base_name}_validate_rendered.md"
                        )
                        job2_msg_file = _render_validate_template(
                            default_val_tmpl, strategy_content, rendered_plan
                        )
                    elif job_two_plan:
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
                        job2_msg_file = default_val_tmpl

                    if debate_j2:
                        job2_debate_id = f"{env_prefix}_job2_debate_{base_name}"
                        _verdict_job2_abs = os.path.join(
                            _ddir, base_name + ".job2_verdict.md"
                        )
                        _ledger_job2_abs = os.path.join(
                            _ddir, base_name + ".job2_debate.json"
                        )

                        _debate_template = _resolve_job_debate_template(
                            pre_edit_cfg, job_num=2, project_directory=project_directory
                        )
                        _j2_coll, _j2_db = _resolve_job_debate_collection(
                            pre_edit_cfg, job_num=2, default_collection=_table, rag_context_root=rag_context_root
                        )
                        _j2_rag_env = dict(file_rag_env)
                        if _j2_coll:
                            _j2_rag_env["ORACLE_COLLECTION"] = _j2_coll
                            _j2_rag_env["ORACLE_RAG_DB_DIR"] = _j2_db

                        _debate_reads = (
                            [current_file]
                            + list(extra_editable_files)
                            + list(initial_context_files)
                            + (completed_files if sticky_context else [])
                        )
                        if job2_msg_file and job2_msg_file not in _debate_reads:
                            _debate_reads.append(job2_msg_file)

                        _pre_loops = pre_edit_cfg.get("loops")
                        _job2_loops = _pre_loops if _pre_loops is not None else 3

                        _r_deliberate = {
                            "template": _debate_template,
                            "issue": job2_msg_file,
                            "verdict": _verdict_job2_abs,
                            "ledger": _ledger_job2_abs,
                            "gate_cmd": None,
                            "loops": _job2_loops,
                            "retrieve_mode": phase_retrieval_mode,
                            "mode": "code",
                            "draft_mode": True,
                            "read_files": _debate_reads,
                            "round_idx": 1,
                            "pass_round_history": pass_round_history,
                        }

                        _r_depends = _ingest_deps(
                            [last_task_for_file] if last_task_for_file else []
                        )
                        factory.add_task(
                            Task(
                                id=job2_debate_id,
                                depends_on=_r_depends,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                architect_api_base=ARCHITECT_API_BASE,
                                rag_env=_j2_rag_env,
                                ocr_ingest=task_ocr_ingest,
                                deliberate=_r_deliberate,
                            )
                        )
                        if task_ocr_ingest is not None:
                            phase_ingest_owner_id = job2_debate_id
                            task_ocr_ingest = None

                        job2_depends = [job2_debate_id]
                        job2_msg_file = _verdict_job2_abs

                    job2_reads = (
                        [current_file]
                        + list(initial_context_files)
                        + (completed_files if sticky_context else [])
                    )
                    if job2_msg_file and job2_msg_file not in job2_reads:
                        job2_reads.append(job2_msg_file)

                    factory.add_task(
                        Task(
                            id=job2_id,
                            depends_on=job2_depends,
                            message_file=job2_msg_file,
                            read_files=job2_reads,
                            files=[current_file] + extra_editable_files,
                            model=ARCHITECT_AGENT,
                            editor_model=EDITOR_AGENT,
                            architect_api_base=ARCHITECT_API_BASE,
                            editor_api_base=EDITOR_OLLAMA_API,
                            pair_programming=pair_programming,
                            rag_env=file_rag_env,
                            ocr_ingest=task_ocr_ingest,
                            **task_aider_flags,
                        )
                    )
                    if task_ocr_ingest is not None:
                        phase_ingest_owner_id = job2_id
                        task_ocr_ingest = None
                    last_task_for_file = job2_id

                # =================================================================
                # JOB 3: WRITE TESTS & JOB 4: ITERATE TESTS
                # =================================================================
                if run_job_three or iterate_test:
                    job3_depends = _ingest_deps(
                        [last_task_for_file] if last_task_for_file else []
                    )

                    if run_job_three:
                        job3_id = f"{env_prefix}_job3_{base_name}"
                        job3_reads = (
                            [current_file]
                            + list(initial_context_test_files)
                            + (completed_files if sticky_context else [])
                        )
                        if job_three_plan and job_three_plan not in job3_reads:
                            job3_reads.append(job_three_plan)

                        job3_msg_file = job_three_plan

                        if debate_j3:
                            job3_debate_id = f"{env_prefix}_job3_debate_{base_name}"
                            _verdict_job3_abs = os.path.join(
                                _ddir, base_name + ".job3_verdict.md"
                            )
                            _ledger_job3_abs = os.path.join(
                                _ddir, base_name + ".job3_debate.json"
                            )

                            _debate_template = _resolve_job_debate_template(
                                pre_edit_cfg, job_num=3, project_directory=project_directory
                            )
                            _j3_coll, _j3_db = _resolve_job_debate_collection(
                                pre_edit_cfg, job_num=3, default_collection=_table, rag_context_root=rag_context_root
                            )
                            _j3_rag_env = dict(file_rag_env)
                            if _j3_coll:
                                _j3_rag_env["ORACLE_COLLECTION"] = _j3_coll
                                _j3_rag_env["ORACLE_RAG_DB_DIR"] = _j3_db

                            _debate_reads = (
                                [current_file, specific_test_file]
                                + list(extra_editable_files)
                                + list(initial_context_test_files)
                                + (completed_files if sticky_context else [])
                            )
                            if job_three_plan and job_three_plan not in _debate_reads:
                                _debate_reads.append(job_three_plan)

                            _pre_loops = pre_edit_cfg.get("loops")
                            _job3_loops = _pre_loops if _pre_loops is not None else 3

                            _r_deliberate = {
                                "template": _debate_template,
                                "issue": job_three_plan,
                                "verdict": _verdict_job3_abs,
                                "ledger": _ledger_job3_abs,
                                "gate_cmd": None,
                                "loops": _job3_loops,
                                "retrieve_mode": phase_retrieval_mode,
                                "mode": "code",
                                "draft_mode": True,
                                "read_files": _debate_reads,
                                "round_idx": 1,
                                "pass_round_history": pass_round_history,
                            }

                            _r_depends = _ingest_deps(
                                [last_task_for_file] if last_task_for_file else []
                            )
                            factory.add_task(
                                Task(
                                    id=job3_debate_id,
                                    depends_on=_r_depends,
                                    model=ARCHITECT_AGENT,
                                    editor_model=EDITOR_AGENT_TEST,
                                    architect_api_base=ARCHITECT_API_BASE,
                                    rag_env=_j3_rag_env,
                                    ocr_ingest=task_ocr_ingest,
                                    deliberate=_r_deliberate,
                                )
                            )
                            if task_ocr_ingest is not None:
                                phase_ingest_owner_id = job3_debate_id
                                task_ocr_ingest = None

                            job3_depends = [job3_debate_id]
                            job3_msg_file = _verdict_job3_abs

                        factory.add_task(
                            Task(
                                id=job3_id,
                                depends_on=job3_depends,
                                message_file=job3_msg_file,
                                read_files=job3_reads,
                                files=[specific_test_file, current_file]
                                + extra_editable_files,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT_TEST,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_TEST_OLLAMA_API,
                                pair_programming=pair_programming,
                                rag_env=file_rag_env,
                                ocr_ingest=task_ocr_ingest,
                                **task_aider_flags,
                            )
                        )
                        if task_ocr_ingest is not None:
                            phase_ingest_owner_id = job3_id
                            task_ocr_ingest = None
                        last_task_for_file = job3_id

                        job3_depends = [job3_id]

                    if iterate_test:
                        verify_id = f"{env_prefix}_verify_{base_name}"
                        verify_reads = [current_file] + list(initial_context_test_files)
                        if iterate_plan and iterate_plan not in verify_reads:
                            verify_reads.append(iterate_plan)

                        factory.add_task(
                            Task(
                                id=verify_id,
                                depends_on=job3_depends,
                                message_file=None,
                                iterate_file=iterate_plan,
                                read_files=verify_reads,
                                files=[specific_test_file, current_file]
                                + extra_editable_files,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT_TEST,
                                fallback_editor_model=EDITOR_AGENT_TEST_FALLBACK,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_TEST_OLLAMA_API,
                                test_cmd=test_cmd,
                                iterate_test=True,
                                max_aider_loops=global_max_aider_loops,
                                auto_test=auto_test,
                                pair_programming=pair_programming,
                                rag_env=file_rag_env,
                                ocr_ingest=task_ocr_ingest,
                                soft_fail=escalate,
                                final_check=True,
                                **task_aider_flags,
                            )
                        )
                        if task_ocr_ingest is not None:
                            phase_ingest_owner_id = verify_id
                            task_ocr_ingest = None
                        last_task_for_file = verify_id

                # escalation params (code): the test suite IS the gate; the failure log +
                # retrieved corpus chunks are the debate's evidence; apply re-iterates the suite.
                if escalate and iterate_test:
                    _ct = resolve_template_path(
                        _oa.get("template"), project_directory=project_directory
                    )
                    # Both the architect AND the oracle need the real code context to reason:
                    # target + test + editable helpers + context files (deduped, existing only).
                    # (In grounding mode this is deliberately NOT done — the paper table is the
                    # oracle's source of truth there.)
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
                    }
                    _apply_kwargs = dict(
                        test_cmd=test_cmd,
                        iterate_file=iterate_plan,
                        read_files=list(initial_context_test_files)
                        + ([iterate_plan] if iterate_plan else []),
                        max_aider_loops=global_max_aider_loops,
                        pair_programming=pair_programming,
                        rag_env=file_rag_env,
                        soft_fail=False,
                        # Code mode has no finalize authority: after the iterate loop, re-run the
                        # test suite ONCE to verify the last edit and report honest pass/fail.
                        final_check=True,
                        **task_aider_flags,
                    )
                    _build_finalize = False

            # Ingest-only fallback: if nothing above carried the ingest, add a pure setup node
            # (movable, file-coupled) so a run_ocr_rag-only phase still builds the table.
            if task_ocr_ingest is not None:
                ing_id = f"{env_prefix}_ingest_{base_name}"
                factory.add_task(
                    Task(
                        id=ing_id,
                        depends_on=[last_task_for_file] if last_task_for_file else [],
                        rag_env=file_rag_env,
                        ocr_ingest=task_ocr_ingest,
                        skip_aider=True,
                    )
                )
                phase_ingest_owner_id = ing_id
                task_ocr_ingest = None
                last_task_for_file = ing_id

            # ---- shared escalation: debate -> apply (-> finalize for grounding) ----
            if escalate and _debate is not None:
                # We loop the exact number of times requested by `debate_rounds` (default 1)
                # Each round gets a unique ID suffix and chains dependencies: apply_R1 -> delib_R2
                _base_debate = dict(_debate)
                for round_idx in range(1, debate_rounds + 1):
                    round_suf = f"_r{round_idx}" if debate_rounds > 1 else ""

                    # Suffix the ledger and verdict files so they don't clobber each other across rounds
                    _r_verdict = f"{os.path.splitext(_verdict_abs)[0]}{round_suf}.md"
                    _r_ledger = f"{os.path.splitext(_dledger_abs)[0]}{round_suf}.json"

                    _round_debate = dict(_base_debate)
                    _round_debate["verdict"] = _r_verdict
                    _round_debate["ledger"] = _r_ledger
                    _round_debate["round_idx"] = round_idx
                    _round_debate["pass_round_history"] = pass_round_history
                    # Give this round the ledger of the PREVIOUS round so it knows what was just tried
                    if round_idx > 1:
                        _round_debate["prior_ledger"] = (
                            f"{os.path.splitext(_dledger_abs)[0]}_r{round_idx - 1}.json"
                        )
                        _round_debate["prior_verdict"] = (
                            f"{os.path.splitext(_verdict_abs)[0]}_r{round_idx - 1}.md"
                        )

                    _r_apply_kwargs = dict(_apply_kwargs)
                    if _build_finalize:
                        _r_apply_kwargs["rag_env"] = dict(
                            _apply_kwargs.get("rag_env", {})
                        )
                        _r_apply_kwargs["rag_env"]["ORACLE_BASELINE_LEDGER"] = _r_ledger

                    delib_id = f"{env_prefix}_deliberate_{base_name}{round_suf}"
                    factory.add_task(
                        Task(
                            id=delib_id,
                            depends_on=[last_task_for_file]
                            if last_task_for_file
                            else [],
                            model=ARCHITECT_AGENT,
                            editor_model=EDITOR_AGENT,
                            architect_api_base=ARCHITECT_API_BASE,
                            editor_api_base=EDITOR_OLLAMA_API,
                            rag_env=file_rag_env,
                            deliberate=_round_debate,
                        )
                    )

                    apply_id = f"{env_prefix}_apply_{base_name}{round_suf}"
                    apply_files = (
                        [specific_test_file, current_file]
                        if code_mode
                        else [current_file]
                    ) + extra_editable_files
                    factory.add_task(
                        Task(
                            id=apply_id,
                            depends_on=[delib_id],
                            message_file=_r_verdict,  # attempt 0 seeds with the verdict
                            verdict_gate=_r_verdict,  # skip unless agreed + gate-backed
                            files=apply_files,
                            model=ARCHITECT_AGENT,
                            editor_model=EDITOR_AGENT_TEST,
                            fallback_editor_model=EDITOR_AGENT_TEST_FALLBACK,
                            architect_api_base=ARCHITECT_API_BASE,
                            editor_api_base=EDITOR_TEST_OLLAMA_API,
                            iterate_test=True,
                            auto_test=auto_test,
                            **_r_apply_kwargs,
                        )
                    )
                    last_task_for_file = apply_id

                # Finalize ONLY runs once, at the very end of all escalation rounds
                if _build_finalize:
                    finalize_id = f"{env_prefix}_finalize_{base_name}"
                    factory.add_task(
                        Task(
                            id=finalize_id,
                            depends_on=[last_task_for_file],
                            rag_env=file_rag_env,
                            validate={
                                "review": _out_abs,
                                "source": _source_abs,
                                "report": _gate_report,
                                "tag": validation_tag,
                                "finalize": True,
                                # Points back to the last ledger used in the final round
                                "baseline_ledger": _r_ledger,
                            },
                            skip_aider=True,
                        )
                    )
                    last_task_for_file = finalize_id

            file_last_tasks[current_file] = last_task_for_file
            if current_file not in completed_files:
                completed_files.append(current_file)

    config_base = os.path.basename(yaml_path)
    config_stem = os.path.splitext(config_base)[0].lstrip(".")
    logs_dir = os.path.join(str(project_directory), ".aider_factory", "logs")
    os.makedirs(logs_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = os.path.join(logs_dir, f"{config_stem}_run_{timestamp}.log")

    if __name__ == "__main__":
        os_tee = OSTee(log_file_path)

        try:
            print(
                f"Starting AI Factory Pipeline\n   Config: {yaml_path}\n   Log:    {log_file_path}",
                file=sys.stderr,
            )
            factory.execute_pipeline()
        finally:
            os_tee.stop()
            print("\n" + "=" * 70)
            print("Run Completed. Aggregating Costs...")
            print("=" * 70)
            aggregate_costs.aggregate_log(log_file_path)
