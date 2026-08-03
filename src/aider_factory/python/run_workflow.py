#!/usr/bin/env python3
# run_workflow.py

import glob
import os
import shlex
import sys

import rag_manager  # for table_name_for(): shared per-document table-name sanitizer
import yaml  # type: ignore
from orchestrate import AiderFactory, Task


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


# Ensure user project space and bash wrappers are initialized and up-to-date
try:
    # Add parent directory of python/ to path to allow importing cli
    _parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    from cli import init_user_project
    init_user_project()
except Exception as e:
    print(f"⚠️ [run_workflow] Auto-initialization warning: {e}", file=sys.stderr)

# Defaults to .env.yml config file
if len(sys.argv) > 1:
    yaml_path = sys.argv[1]
else:
    clean_path = os.path.join(os.getcwd(), ".aider_factory", ".env.yml")
    root_path = os.path.join(os.getcwd(), ".env.yml")
    yaml_path = clean_path if os.path.exists(clean_path) else root_path

if not os.path.exists(yaml_path):
    print(f"Error: Configuration file {yaml_path} not found. Exiting.")
    sys.exit(1)

try:
    with open(yaml_path, "r") as f:
        config = yaml.safe_load(f)
except yaml.YAMLError as exc:
    print(
        f"\n❌ YAML Parsing Error: The configuration file is malformed.\nDetails: {exc}"
    )
    sys.exit(1)

if not isinstance(config, dict):
    print(
        "\n❌ YAML Error: Configuration must resolve to a valid dictionary structure."
    )
    sys.exit(1)

project_directory = config.get("working_directory")
test_command_prefix = config.get("test_command_prefix", "").strip()
global_max_aider_loops = int(config.get("loop_aider_test", 1))

# Language-agnostic test execution. `test_runner` is the command template applied
# to a test file ({file} is substituted); the default preserves the R behaviour
# (Rscript runner, now living under .aider_factory/tests/). `test_naming_and_path`
# is the convention used to auto-generate a per-target test file path when a phase
# omits files.test_files ({stem} -> the target's basename).
test_runner = config.get("test_runner", "Rscript .aider_factory/tests/run_tests.R {file}")
test_file_convention = config.get(
    "test_naming_and_path", "tests/testthat/test-{stem}.R"
)

if not project_directory:
    print("Error: working_directory not found in the yaml file. Exiting.")
    sys.exit(1)

factory: AiderFactory = AiderFactory(project_dir=str(project_directory))
file_last_tasks = {}
completed_files = []

# Parse Endpoints and Models
endpoints = config.get("endpoints", {})

global_architect_api_base = endpoints.get("architect_api_base")
global_editor_api = endpoints.get("editor_ollama_api")
global_editor_test_api = endpoints.get("editor_test_ollama_api")
global_rag_agent_api = endpoints.get("rag_agent_api")
global_grounding_api = endpoints.get("grounding_agent_api")

# Find the first enabled phase to extract default RAG models if present
first_enabled_phase = next((p for p in config.get("phases", []) if p.get("enabled", True)), {})
phase_models = first_enabled_phase.get("models", {})

# --- RAG / Oracle globals: infrastructure + DEFAULTS ---
DEFAULT_OCR_PROMPT = (
    "Extract the text, tables, and mathematical formulas from this page into "
    "clean Markdown. Preserve all structural integrity."
)
ocr_api_base = endpoints.get("ocr_api_base")
rag_context_root = os.path.join(
    str(project_directory), ".aider_factory", "markdown", "lanceDB"
)
rag_embed_model = phase_models.get("embed_model") or "BAAI/bge-m3"
rag_embed_backend = "openai" if "embedding" in rag_embed_model.lower() else "sentence-transformers"
rag_embed_api_base = endpoints.get("embed_api_base")
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

# Write embed config into os.environ so in-process validator._region() calls
# get the correct backend
os.environ["ORACLE_EMBED_MODEL"] = rag_embed_model
os.environ["ORACLE_EMBED_BACKEND"] = rag_embed_backend
if rag_embed_api_base:
    os.environ["ORACLE_EMBED_API_BASE"] = rag_embed_api_base
rag_default_retrieval = "top_k"

# --- Pipeline display colors (non-Aider output) ---
# Parsed once at startup; injected as env vars so orchestrate.py and oracle_agent.py
# (which runs as a subprocess) both pick them up. Hex -> 24-bit ANSI truecolor.
_colors_cfg = config.get("colors", {}) or {}


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


os.environ["PIPELINE_COLOR_ARCHITECT"] = _hex_to_ansi(
    _colors_cfg.get("architect_debate"), "\033[38;2;56;189;248m"
)
os.environ["PIPELINE_COLOR_ORACLE"] = _hex_to_ansi(
    _colors_cfg.get("oracle_debate"), "\033[38;2;211;134;155m"
)

script_dir = os.path.dirname(os.path.abspath(__file__))


def resolve_template_path(path_val):
    """Resolves a template path, checking the local project directory first,
    then falling back to the package's bundled resources."""
    if not path_val:
        return None

    if os.path.isabs(path_val):
        if os.path.exists(path_val):
            return path_val
        return path_val

    # Strip `.aider_factory/` prefix for fallback checks
    rel_stripped = path_val
    if rel_stripped.startswith(".aider_factory/"):
        rel_stripped = rel_stripped.replace(".aider_factory/", "", 1)
    elif rel_stripped.startswith(".aider_factory\\"):
        rel_stripped = rel_stripped.replace(".aider_factory\\", "", 1)

    # Priority 1: Check exact relative path in project root
    local_exact = os.path.join(str(project_directory), path_val)
    if os.path.exists(local_exact):
        return local_exact

    # Priority 2: Check under project_root/.aider_factory/ (preserving subfolders if any)
    local_aider_factory = os.path.join(str(project_directory), ".aider_factory", rel_stripped)
    if os.path.exists(local_aider_factory):
        return local_aider_factory

    # Priority 3: Check flat fallback under project_root/.aider_factory/ (e.g., CONVENTIONS.md)
    flat_filename = os.path.basename(path_val)
    local_flat = os.path.join(str(project_directory), ".aider_factory", flat_filename)
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


conventions_path = resolve_template_path(".aider_factory/markdown/CONVENTIONS.md")

# Loop through each phase in the pipeline
for phase_idx, phase in enumerate(config.get("phases", [])):
    if not phase.get("enabled", True):
        continue

    phase_name = phase.get("name", f"Phase_{phase_idx}")
    env_prefix = phase_name.replace(" ", "_").replace("&", "and").lower()

    toggles = phase.get("toggles", {})
    run_job_one = toggles.get("run_job_one", True)
    run_job_two = toggles.get("run_job_two", False)
    iterate_test = toggles.get("iterate_test", False)
    sticky_context = toggles.get("sticky_context", True)
    auto_test = toggles.get("auto_test", False)
    pair_programming = toggles.get("pair_programming", False)

    # Phase-level RAG settings
    rag_phase_cfg = phase.get("rag", {}) or {}
    phase_run_ocr_rag = rag_phase_cfg.get("run_ocr_rag", False)
    phase_overwrite = rag_phase_cfg.get("vectordb_overwrite", rag_default_overwrite)
    phase_batch = bool(rag_phase_cfg.get("batch", True))
    phase_retrieval_mode = rag_phase_cfg.get("retrieval_mode", rag_default_retrieval)

    # Validation settings
    validation_cfg = phase.get("validation", {}) or {}
    post_validate = validation_cfg.get("enabled", False)
    validation_tag = validation_cfg.get("validation_tag", "evidence")
    redo_oracle_job = validation_cfg.get("redo_oracle_job", True)
    validation_loops = int(validation_cfg.get("validation_loops", global_max_aider_loops))
    region_threshold = float(validation_cfg.get("region_threshold", 0.60))
    region_margin = int(validation_cfg.get("region_margin", 2))
    region_paragraphs = int(validation_cfg.get("region_paragraphs", 0))
    region_top_k = int(validation_cfg.get("region_top_k", 5))
    verify_all_claims = bool(validation_cfg.get("verify_all_claims", False))
    entail_threshold = float(validation_cfg.get("entail_threshold", 0.5))

    # Escalation Debate settings
    escalation_cfg = phase.get("escalation_debate", {}) or {}
    _dl_raw = escalation_cfg.get("loops", None)
    debate_loops = int(_dl_raw) if _dl_raw is not None else None
    debate_rounds = int(escalation_cfg.get("rounds", 1))
    pass_round_history = bool(escalation_cfg.get("pass_history", False))
    resolve_evidence = debate_loops is not None

    # Programmatic side-agent and pre-edit debate configuration
    oracle_cfg = phase.get("oracle") or None

    if (
        not run_job_one
        and not run_job_two
        and not iterate_test
        and not phase_run_ocr_rag
        and not oracle_cfg
        and not resolve_evidence
        and not post_validate
    ):
        print(f"Phase '{phase_name}': All toggles False. Skipping.")
        continue

    models = phase.get("models", {})
    ARCHITECT_AGENT = models.get("architect_agent", "")
    EDITOR_AGENT = models.get("editor_agent", "")
    # RAG-only phases need not define a test editor; fall back to the main editor.
    EDITOR_AGENT_TEST = models.get("editor_agent_test", EDITOR_AGENT)
    EDITOR_AGENT_TEST_FALLBACK = models.get("editor_agent_test_fallback", None)

    if not all([ARCHITECT_AGENT, EDITOR_AGENT]):
        print(f"Error: Missing agent configurations in phase '{phase_name}'. Exiting.")
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
    # Per-phase retrieval strategy, else the global default.
    phase_retrieval_mode = rag_phase_cfg.get("retrieval_mode", rag_default_retrieval)
    rag_env = {
        "ORACLE_CONFIG_FILE": str(yaml_path),
        "ORACLE_PHASE_INDEX": str(phase_idx),
        "ORACLE_AGENT_MODEL": RAG_AGENT,
        "ORACLE_RAG_DB_DIR": phase_db_dir,
        "ORACLE_COLLECTION": phase_collection,
        "ORACLE_TOP_K": rag_top_k,
        "ORACLE_RETRIEVE_MODE": phase_retrieval_mode,
        "ORACLE_ARCHITECT_MODEL": ARCHITECT_AGENT,
        "ORACLE_EMBED_MODEL": rag_embed_model,
        "ORACLE_EMBED_BACKEND": rag_embed_backend,
        "ORACLE_QUERY_PREFIX": rag_query_prefix,
    }
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
            "chunk_size_chars": rag_chunk_size,
            "chunk_overlap_chars": rag_chunk_overlap,
            "code_chunk_size": rag_code_chunk,
            "working_repo": rag_working_repo,
            "code_exclude": code_exclude,
            "code_exts": rag_code_exts,
            "text_doc_exts": rag_text_doc_exts,
            "ignore": rag_ignore,
            "ocr_api_base": ocr_api_base,
            "ocr_agent": models.get("ocr_agent") or rag_default_ocr_agent,
            "ocr_prompt": phase.get("ocr_prompt") or rag_default_ocr_prompt,
            "overwrite": phase_overwrite,
            "cer_threshold": rag_cer_threshold,
            "ocr_max_retries": rag_ocr_max_retries,
            "ocr_parallel": rag_ocr_parallel,
            "ocr_max_tokens": rag_ocr_max_tokens,
            "batch": phase_batch,
        }

    plans = phase.get("plans", {})
    j1_val = plans.get("job_one_plan", "markdown/templates/implement.md")
    job_one_plan = resolve_template_path(j1_val)

    j2_val = plans.get("job_two_plan", "markdown/templates/testing.md")
    job_two_plan = resolve_template_path(j2_val)

    it_val = plans.get("iterate_plan")
    iterate_plan = resolve_template_path(it_val)

    # Evidence-resolution templates: code defaults, overridable via plans.* (joined like
    # the other plans). Used by the debate (deliberate node) and the gated apply node.
    delib_val = plans.get(
        "deliberate_plan", "markdown/internal/deliberation_evidence_template.md"
    )
    deliberate_plan = resolve_template_path(delib_val)
    applyt_val = plans.get("apply_plan", "markdown/internal/apply_evidence_template.md")
    apply_plan = resolve_template_path(applyt_val)

    ab_val = plans.get("analyze_bugs_plan", "markdown/internal/analyze_bugs.md")
    analyze_bugs_plan = resolve_template_path(ab_val)
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
        os.path.exists(os.path.join(factory.project_dir, f)) for f in all_files_check
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
                specific_test_file = test_files_list[target_files.index(current_file)]
            else:
                specific_test_file = test_file_convention.replace("{stem}", base_name)
        else:
            specific_test_file = test_file_convention.replace("{stem}", base_name)
        # Language-agnostic execution: {prefix} {test_runner with {file} filled}.
        cmd_prefix = f"{test_command_prefix} " if test_command_prefix else ""
        test_cmd = f"{cmd_prefix}{test_runner.replace('{file}', specific_test_file)}"

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
        architect_oracle_chat = bool(pre_edit_cfg.get("enabled", False))

        # A "grounding signal" means this phase intends the evidence-grounding/review path.
        grounding_signal = (
            (oracle_cfg is not None and _start_job) or post_validate or resolve_evidence
        )
        # Code mode: a code produce-job (run_job_one/two), an explicit start_job:false, or a
        # bare iterate_test loop with no grounding intent ("iterate existing code tests").
        code_mode = (
            bool(run_job_one or run_job_two)
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
        _ddir = os.path.join(str(project_directory), ".aider_factory", "logs", "debates")
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
                _tmpl = resolve_template_path(_oa.get("template"))
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
                            "read_files": [current_file] + list(initial_context_files),
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
                        depends_on=[last_task_for_file] if last_task_for_file else [],
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
                    _vcmd = f"{cmd_prefix}{test_runner.replace('{file}', _val_script)}"
                    heal_id = f"{env_prefix}_heal_{base_name}"
                    factory.add_task(
                        Task(
                            id=heal_id,
                            depends_on=[last_task_for_file]
                            if last_task_for_file
                            else [],
                            iterate_file=iterate_plan,
                            read_files=list(initial_context_test_files),
                            files=[current_file],  # review only; script not editable
                            model=ARCHITECT_AGENT,
                            editor_model=EDITOR_AGENT_TEST,
                            fallback_editor_model=EDITOR_AGENT_TEST_FALLBACK,
                            architect_api_base=ARCHITECT_API_BASE,
                            editor_api_base=EDITOR_TEST_OLLAMA_API,
                            test_cmd=_vcmd,
                            iterate_test=True,
                            max_aider_loops=validation_loops,
                            auto_test=auto_test,
                            rag_env=it_env,
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
                    rag_env=_ap_env,
                    soft_fail=True,
                )
                _build_finalize = True

        else:
            # ---------- code / test mode: job_one -> job_two/iterate_test ----------
            def _ingest_deps(base_deps):
                d = list(base_deps)
                if phase_ingest_owner_id and phase_ingest_owner_id not in d:
                    d.append(phase_ingest_owner_id)
                return d

            if run_job_one:
                job1_id = f"{env_prefix}_job1_{base_name}"
                job1_reads = list(initial_context_files) + (
                    completed_files if sticky_context else []
                )
                job1_depends = _ingest_deps(
                    [last_task_for_file] if last_task_for_file else []
                )
                job1_msg_file = job_one_plan

                if architect_oracle_chat:
                    job1_debate_id = f"{env_prefix}_job1_debate_{base_name}"
                    _verdict_job1_abs = os.path.join(
                        _ddir, base_name + ".job1_verdict.md"
                    )
                    _ledger_job1_abs = os.path.join(
                        _ddir, base_name + ".job1_debate.json"
                    )

                    _debate_template = resolve_template_path(
                        pre_edit_cfg.get("job_debate_template")
                    )

                    _debate_reads = (
                        [current_file]
                        + list(extra_editable_files)
                        + list(initial_context_files)
                    )
                    if job_one_plan and job_one_plan not in _debate_reads:
                        _debate_reads.append(job_one_plan)

                    _last_debate_id = None
                    for round_idx in range(1, (debate_rounds or 1) + 1):
                        round_suf = f"_r{round_idx}" if (debate_rounds or 1) > 1 else ""
                        _r_debate_id = f"{job1_debate_id}{round_suf}"
                        _r_verdict = (
                            f"{os.path.splitext(_verdict_job1_abs)[0]}{round_suf}.md"
                        )
                        _r_ledger = (
                            f"{os.path.splitext(_ledger_job1_abs)[0]}{round_suf}.json"
                        )

                        _r_deliberate = {
                            "template": _debate_template,
                            "issue": job_one_plan,
                            "verdict": _r_verdict,
                            "ledger": _r_ledger,
                            "gate_cmd": None,
                            "loops": debate_loops or 3,
                            "retrieve_mode": phase_retrieval_mode,
                            "mode": "code",
                            "draft_mode": True,
                            "read_files": _debate_reads,
                            "round_idx": round_idx,
                            "pass_round_history": pass_round_history,
                        }
                        if round_idx > 1:
                            _r_deliberate["prior_ledger"] = (
                                f"{os.path.splitext(_ledger_job1_abs)[0]}_r{round_idx - 1}.json"
                            )
                            _r_deliberate["prior_verdict"] = (
                                f"{os.path.splitext(_verdict_job1_abs)[0]}_r{round_idx - 1}.md"
                            )

                        _r_depends = (
                            [_last_debate_id] if _last_debate_id else job1_depends
                        )
                        factory.add_task(
                            Task(
                                id=_r_debate_id,
                                depends_on=_r_depends,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                architect_api_base=ARCHITECT_API_BASE,
                                rag_env=file_rag_env,
                                ocr_ingest=task_ocr_ingest if round_idx == 1 else None,
                                deliberate=_r_deliberate,
                            )
                        )
                        if round_idx == 1 and task_ocr_ingest is not None:
                            phase_ingest_owner_id = _r_debate_id
                            task_ocr_ingest = None
                        _last_debate_id = _r_debate_id

                    job1_depends = [_last_debate_id]
                    job1_msg_file = _r_verdict
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
                    )
                )
                if task_ocr_ingest is not None:
                    phase_ingest_owner_id = job1_id
                    task_ocr_ingest = None
                last_task_for_file = job1_id

            if run_job_two or iterate_test:
                job2_depends = _ingest_deps(
                    [last_task_for_file] if last_task_for_file else []
                )

                # --- SPLIT NODE 1: Write the Code (Job 2) ---
                if run_job_two:
                    job2_id = f"{env_prefix}_job2_{base_name}"
                    job2_reads = [current_file] + list(initial_context_test_files)
                    if job_two_plan and job_two_plan not in job2_reads:
                        job2_reads.append(job_two_plan)

                    job2_msg_file = job_two_plan

                    if architect_oracle_chat:
                        job2_debate_id = f"{env_prefix}_job2_debate_{base_name}"
                        _verdict_job2_abs = os.path.join(
                            _ddir, base_name + ".job2_verdict.md"
                        )
                        _ledger_job2_abs = os.path.join(
                            _ddir, base_name + ".job2_debate.json"
                        )

                        _debate_template = resolve_template_path(
                            pre_edit_cfg.get("job_debate_template")
                        )

                        _debate_reads = (
                            [current_file, specific_test_file]
                            + list(extra_editable_files)
                            + list(initial_context_test_files)
                        )
                        if job_two_plan and job_two_plan not in _debate_reads:
                            _debate_reads.append(job_two_plan)

                        _last_debate_id = None
                        for round_idx in range(1, (debate_rounds or 1) + 1):
                            round_suf = (
                                f"_r{round_idx}" if (debate_rounds or 1) > 1 else ""
                            )
                            _r_debate_id = f"{job2_debate_id}{round_suf}"
                            _r_verdict = f"{os.path.splitext(_verdict_job2_abs)[0]}{round_suf}.md"
                            _r_ledger = f"{os.path.splitext(_ledger_job2_abs)[0]}{round_suf}.json"

                            _r_deliberate = {
                                "template": _debate_template,
                                "issue": job_two_plan,
                                "verdict": _r_verdict,
                                "ledger": _r_ledger,
                                "gate_cmd": None,
                                "loops": debate_loops or 3,
                                "retrieve_mode": phase_retrieval_mode,
                                "mode": "code",
                                "draft_mode": True,
                                "read_files": _debate_reads,
                                "round_idx": round_idx,
                                "pass_round_history": pass_round_history,
                            }
                            if round_idx > 1:
                                _r_deliberate["prior_ledger"] = (
                                    f"{os.path.splitext(_ledger_job2_abs)[0]}_r{round_idx - 1}.json"
                                )
                                _r_deliberate["prior_verdict"] = (
                                    f"{os.path.splitext(_verdict_job2_abs)[0]}_r{round_idx - 1}.md"
                                )

                            _r_depends = (
                                [_last_debate_id] if _last_debate_id else job2_depends
                            )
                            factory.add_task(
                                Task(
                                    id=_r_debate_id,
                                    depends_on=_r_depends,
                                    model=ARCHITECT_AGENT,
                                    editor_model=EDITOR_AGENT_TEST,
                                    architect_api_base=ARCHITECT_API_BASE,
                                    rag_env=file_rag_env,
                                    ocr_ingest=task_ocr_ingest
                                    if round_idx == 1
                                    else None,
                                    deliberate=_r_deliberate,
                                )
                            )
                            if round_idx == 1 and task_ocr_ingest is not None:
                                phase_ingest_owner_id = _r_debate_id
                                task_ocr_ingest = None
                            _last_debate_id = _r_debate_id

                        job2_depends = [_last_debate_id]
                        job2_msg_file = _r_verdict

                    factory.add_task(
                        Task(
                            id=job2_id,
                            depends_on=job2_depends,
                            message_file=job2_msg_file,
                            read_files=job2_reads,
                            files=[specific_test_file, current_file]
                            + extra_editable_files,
                            model=ARCHITECT_AGENT,
                            editor_model=EDITOR_AGENT_TEST,
                            architect_api_base=ARCHITECT_API_BASE,
                            editor_api_base=EDITOR_TEST_OLLAMA_API,
                            # NO test_cmd and NO iterate_test here. Just write it once.
                            pair_programming=pair_programming,
                            rag_env=file_rag_env,
                            ocr_ingest=task_ocr_ingest,
                        )
                    )
                    if task_ocr_ingest is not None:
                        phase_ingest_owner_id = job2_id
                        task_ocr_ingest = None
                    last_task_for_file = job2_id

                    # Update dependency for the next block to chain correctly
                    job2_depends = [job2_id]

                # --- SPLIT NODE 2: Iterate the Tests ---
                if iterate_test:
                    verify_id = f"{env_prefix}_verify_{base_name}"
                    verify_reads = [current_file] + list(initial_context_test_files)
                    if iterate_plan and iterate_plan not in verify_reads:
                        verify_reads.append(iterate_plan)

                    factory.add_task(
                        Task(
                            id=verify_id,
                            depends_on=job2_depends,
                            message_file=None,  # Force immediate test_cmd failure check
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
                            iterate_test=True,  # Engages iteration logic
                            max_aider_loops=global_max_aider_loops,
                            auto_test=auto_test,
                            pair_programming=pair_programming,
                            rag_env=file_rag_env,
                            ocr_ingest=task_ocr_ingest,  # Carries ingest if run_job_two was false
                            soft_fail=escalate,
                            final_check=True,
                        )
                    )
                    if task_ocr_ingest is not None:
                        phase_ingest_owner_id = verify_id
                        task_ocr_ingest = None
                    last_task_for_file = verify_id

            # escalation params (code): the test suite IS the gate; the failure log +
            # retrieved corpus chunks are the debate's evidence; apply re-iterates the suite.
            if escalate and iterate_test:
                _ct = resolve_template_path(_oa.get("template"))
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
                    rag_env=file_rag_env,
                    soft_fail=False,
                    # Code mode has no finalize authority: after the iterate loop, re-run the
                    # test suite ONCE to verify the last edit and report honest pass/fail.
                    final_check=True,
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
                    _r_apply_kwargs["rag_env"] = dict(_apply_kwargs.get("rag_env", {}))
                    _r_apply_kwargs["rag_env"]["ORACLE_BASELINE_LEDGER"] = _r_ledger

                delib_id = f"{env_prefix}_deliberate_{base_name}{round_suf}"
                factory.add_task(
                    Task(
                        id=delib_id,
                        depends_on=[last_task_for_file] if last_task_for_file else [],
                        model=ARCHITECT_AGENT,
                        editor_model=EDITOR_AGENT,
                        architect_api_base=ARCHITECT_API_BASE,
                        editor_api_base=EDITOR_OLLAMA_API,
                        rag_env=file_rag_env,
                        deliberate=_round_debate,
                    )
                )

                apply_id = f"{env_prefix}_apply_{base_name}{round_suf}"
                factory.add_task(
                    Task(
                        id=apply_id,
                        depends_on=[delib_id],
                        message_file=_r_verdict,  # attempt 0 seeds with the verdict
                        verdict_gate=_r_verdict,  # skip unless agreed + gate-backed
                        files=[current_file] + extra_editable_files,
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

import datetime
import threading
import aggregate_costs


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


if __name__ == "__main__":
    config_base = os.path.basename(yaml_path)
    config_stem = os.path.splitext(config_base)[0].lstrip(".")
    logs_dir = os.path.join(str(project_directory), ".aider_factory", "logs")
    os.makedirs(logs_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = os.path.join(logs_dir, f"{config_stem}_run_{timestamp}.log")

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
