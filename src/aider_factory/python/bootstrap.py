
import os
import sys
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

# Generate session ID once per pipeline run for KV-cache stickiness
_PIPELINE_SESSION_ID = os.environ.get("LITELLM_SESSION_ID") or str(uuid.uuid4())
os.environ["LITELLM_SESSION_ID"] = _PIPELINE_SESSION_ID

# Quiet noisy ML/HTTP/API libraries
for _n in ("httpx", "urllib3", "LiteLLM", "litellm"):
    import logging
    logging.getLogger(_n).setLevel(logging.WARNING)

_RESET = "\033[0m"
_HELPER_COLOR = "\033[38;2;56;189;248m"  # Sky blue

PERSONA_PROMPT = (
    "You are the Master Configuration Architect and Agent Helper of the AI Factory Pipeline.\n"
    "Your sole purpose is to assist the user in bootstrapping, configuring, and optimizing their "
    "multi-phase DAG pipeline execution configurations (.env.yml files), Aider templates, and active "
    "environment variables.\n\n"
    "You have access to the user's active .env.yml pipeline configuration inside the <active_configuration> "
    "block, and the master reference schema inside the <reference_schema> block. When answering questions "
    "about the active pipeline, phases, agents, models, or target files, inspect the <active_configuration> "
    "block. Use <reference_schema> strictly as a read-only guide for valid schema keys and structural options. "
    "You communicate with absolute precision, objectivity, and technical clarity. You prioritize deterministic, "
    "minimal-delta edits to configurations, preserving all inline comments and inactive blocks unless explicitly "
    "instructed to change them. Do NOT copy unused keys, comments, or defaults from <reference_schema> into the "
    "target configuration unless explicitly requested. When asked to modify a configuration, apply the requested "
    "changes to <active_configuration> and return ONLY the complete, updated YAML content inside a markdown code block."
)

TERMINAL_PERSONA_PROMPT = (
    "You are a general-purpose AI software engineering assistant working in an interactive terminal session.\n"
    "Answer questions clearly, accurately, and concisely based on the user's prompt and provided context files.\n"
    "Provide well-structured code, explanations, and unix commands when requested."
)

def _discover_cluster_config():
    """Auto-discover cluster configuration from LiteLLM router."""
    import os
    import requests

    base_url = os.environ.get("LITELLM_BASE_URL")
    api_key = os.environ.get("LITELLM_API_KEY")

    if not base_url:
        return None

    config = {
        "architect_api_base": base_url,
        "editor_api": base_url,
        "rag_agent_api": base_url,
        "api_key": api_key or "sk-dummy",
    }

    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = requests.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=10)
        if response.status_code == 200:
            models = response.json().get("data", [])
            # Prepend openai/ so Aider knows to use the OpenAI-compatible API format
            model_ids = [m["id"] if "/" in m["id"] else f"openai/{m['id']}" for m in models]
            config["available_models"] = model_ids
            if model_ids:
                chosen = next((m for m in model_ids if "27b" in m.lower()), model_ids[0])
                config["architect_agent"] = chosen
                config["editor_agent"] = chosen
    except Exception as e:
        print(f"[bootstrap] Warning: Could not query /models: {e}", file=sys.stderr)

    return config


def get_repo_name():
    return os.path.basename(os.getcwd()).strip().replace(" ", "_")

def get_helper_session_file():
    return os.path.join(".aider_factory", ".helper_session.json")

def get_helper_terminal_session_file():
    return os.path.join(".aider_factory", ".helper_terminal_session.json")

def clear_helper_session(terminal_mode=False):
    """Wipes the helper LLM session history."""
    sf = get_helper_terminal_session_file() if terminal_mode else get_helper_session_file()
    if os.path.exists(sf):
        try:
            os.remove(sf)
            label = "Terminal session" if terminal_mode else "Session"
            print(f"[aider-helper] 🧹 {label} cleared.", file=sys.stderr)
        except OSError:
            pass

try:
    from aider_factory.python.env_utils import is_dummy_key, resolve_api_key, load_env_files
except ImportError:
    from env_utils import is_dummy_key, resolve_api_key, load_env_files

load_env_files()


def detect_api_key():
    if os.environ.get("AIDER_HELPER_API_BASE"):
        return "CUSTOM_LOCAL", "dummy"
    keys = ["GEMINI_API_KEY", "GOOGLE_API_KEY", "AIDER_GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "OPENCODE_API_KEY", "LITELLM_API_KEY"]
    for k in keys:
        val = os.environ.get(k)
        if val and not is_dummy_key(val):
            return k, val
    return None, None

def print_key_help_and_exit():
    print("❌ No active LLM API key detected.", file=sys.stderr)
    print("To run the bootstrapper, set one of the following environment variables:", file=sys.stderr)
    print("\n  export GEMINI_API_KEY=\"your-key-here\"", file=sys.stderr)
    print("  export ANTHROPIC_API_KEY=\"your-key-here\"", file=sys.stderr)
    print("  export OPENAI_API_KEY=\"your-key-here\"", file=sys.stderr)
    print("\nTo make this permanent, add the export line to your ~/.bashrc or ~/.zshrc file.", file=sys.stderr)
    sys.exit(1)

def _detect_framework(cwd: str) -> tuple:
    """Scan filesystem to infer test framework deterministically.

    Returns (framework_name, test_runner, test_path_template, test_command_prefix).
    Checks in priority order; first match wins. Defaults to py.
    """
    checks = [
        ("py",
         "uv run --with pytest pytest",
         "tests/test_{stem}.py",
         ""),
        ("R",
         "Rscript .aider_factory/tests/run_tests.R {file}",
         "tests/testthat/test-{stem}.R",
         ""),
        ("rs",
         "cargo test --test {stem}",
         "tests/{stem}.rs",
         ""),
        ("js",
         "npm test {file}",
         "tests/{stem}.test.js",
         ""),
        ("go",
         "go test {file}",
         "tests/{stem}_test.go",
         ""),
    ]
    # Map framework to filesystem markers
    markers = {
        "py": ["pytest.ini", "setup.cfg"],
        "R": ["DESCRIPTION"],
        "rs": ["Cargo.toml"],
        "js": ["package.json"],
        "go": ["go.mod"],
    }
    for name, runner, path, prefix in checks:
        for marker in markers[name]:
            if os.path.exists(os.path.join(cwd, marker)):
                # For py, also accept pyproject.toml with [tool.pytest]
                if name == "py" and marker == "setup.cfg":
                    try:
                        with open(os.path.join(cwd, "setup.cfg"), "r") as f:
                            if "[tool:pytest]" not in f.read():
                                continue
                    except Exception:
                        continue
                return name, runner, path, prefix
    # Additional py check: pyproject.toml containing [tool.pytest]
    pyproject = os.path.join(cwd, "pyproject.toml")
    if os.path.exists(pyproject):
        try:
            with open(pyproject, "r") as f:
                if "[tool.pytest" in f.read():
                    return "py", checks[0][1], checks[0][2], ""
        except Exception:
            pass
    # Default fallback
    return "py", checks[0][1], checks[0][2], ""


def _select_models(available: list) -> dict:
    """Pick architect, editor, embed, and reranker from a router model list.

    Returns dict with keys: architect, editor, embed, reranker (values may be None).
    """
    if not available:
        return {}
    arch = next((m for m in available if "27b" in m.lower()), available[0])
    embed = next((m for m in available if "embed" in m.lower()), None)
    rerank = next((m for m in available if "rerank" in m.lower()), None)
    return {"architect": arch, "editor": arch, "embed": embed, "reranker": rerank}


def run_bootstrap(target_dir: str) -> None:
    """Deterministic workspace scaffold. No interview. No LLM calls.

    Steps:
      1. Detect API keys / router availability from environment.
      2. Detect test framework from filesystem markers.
      3. Query router for available models; select architect/editor/embed/reranker.
      4. Write .aider_factory/.env_<repo>.yml via regex substitution on template.
      5. Provision directory structure and print structured summary.

    Always produces a valid YAML file even with zero keys or no router.
    """
    cwd = os.path.abspath(target_dir)
    os.makedirs(cwd, exist_ok=True)
    repo_name = os.path.basename(cwd).strip().replace(" ", "_")

    # --- Step 1: Detect keys ---
    key_name, _ = detect_api_key()
    router_base = (
        os.environ.get("LITELLM_BASE_URL")
        or os.environ.get("AIDER_HELPER_API_BASE")
    )
    router_key = os.environ.get("LITELLM_API_KEY")

    # --- Step 2: Detect framework ---
    fw_name, fw_runner, fw_path, fw_prefix = _detect_framework(cwd)

    # --- Step 3: Select models ---
    available_models = None
    if router_base:
        from env_utils import probe_router
        available_models = probe_router(router_base, router_key)
    model_choices = _select_models(available_models) if available_models else {}

    # --- Step 4: Write config via regex substitution ---
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_path = os.path.join(pkg_dir, "default_configs", "env.yml")

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Project identity
    sensible_name = f"{repo_name.replace('_', ' ').replace('-', ' ').title()} Pipeline"
    content = re.sub(r'name:\s*".*?"', lambda _: f'name: "{sensible_name}"', content, count=1)
    cwd_forward = cwd.replace("\\", "/")
    content = re.sub(r'working_directory:\s*".*?"', lambda _: f'working_directory: "{cwd_forward}"', content, count=1)

    # Test framework
    content = re.sub(r'test_command_prefix:\s*".*?"', lambda _: f'test_command_prefix: "{fw_prefix}"', content, count=1)
    content = re.sub(r'test_runner:\s*".*?"', lambda _: f'test_runner: "{fw_runner}"', content, count=1)
    content = re.sub(r'test_naming_and_path:\s*".*?"', lambda _: f'test_naming_and_path: "{fw_path}"', content, count=1)

    # Router endpoints: only traditional-LLM slots get the detected router URL.
    # RAG, OCR, embed, ranking, grounding stay at template defaults —
    # auto-resolved locally at runtime (llama.cpp, sentence-transformers, MiniCheck).
    if router_base:
        _ROUTER_ENDPOINTS = ("architect_api_base", "editor_api",
                             "editor_api_fallback")
        for ep_key in _ROUTER_ENDPOINTS:
            content = re.sub(
                rf'{ep_key}:\s*".*?"',
                lambda _, k=ep_key: f'{k}: "{router_base}"',
                content,
                count=1,
            )

    # Models (only if router returned results)
    if model_choices.get("architect"):
        arch = model_choices["architect"]
        editor = model_choices["editor"]
        content = re.sub(r'architect_agent:\s*".*?"', lambda _: f'architect_agent: "{arch}"', content, count=1)
        content = re.sub(r'editor_agent:\s*".*?"', lambda _: f'editor_agent: "{editor}"', content, count=1)
        content = re.sub(r'editor_agent_test:\s*".*?"', lambda _: f'editor_agent_test: "{editor}"', content, count=1)
        content = re.sub(r'editor_agent_test_fallback:\s*".*?"', lambda _: f'editor_agent_test_fallback: "{editor}"', content, count=1)
    if model_choices.get("embed"):
        _embed_m = model_choices["embed"]
        content = re.sub(r'embed_model:\s*".*?"', lambda _: f'embed_model: "{_embed_m}"', content, count=1)
        # Align embed_backend to prevent cloud-model / local-backend mismatch
        _eb = "openai" if any(x in _embed_m.lower() for x in ("gemini", "openai", "embedding", "qwen")) else "sentence-transformers"
        content = re.sub(r'embed_backend:\s*".*?"', lambda _: f'embed_backend: "{_eb}"', content, count=1)
    if model_choices.get("reranker"):
        content = re.sub(r'ranking_agent:\s*".*?"', lambda _: f'ranking_agent: "{model_choices["reranker"]}"', content, count=1)

    # Standardize analyze_bugs template path
    content = re.sub(
        r'template:\s*"\.?\.?/?(?:aider_factory/)?markdown/internal/analyze_bugs\.md"',
        'template: "src/aider_factory/markdown/internal/analyze_bugs.md"',
        content,
        count=1,
    )

    # --- Step 4b: Auto-discover target_files and context_files_job ---
    _SOURCE_EXTS = {".py", ".r", ".rs", ".go", ".js", ".ts", ".jsx", ".tsx"}
    _EXCLUDE_DIRS = frozenset({
        ".git", ".aider_factory", "node_modules", "__pycache__",
        ".venv", "venv", "dist", "build", ".cache", ".pytest_cache",
        "site-packages", ".eggs",
    })
    _EXCLUDE_RE = re.compile(
        r"(?:^|[\\/])(?:tests?[\\/]|test_|conftest\.py|setup\.py|__init__\.py$)"
    )

    def _discover_target_files(base_dir: str) -> list:
        found = []
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs
                       if d not in _EXCLUDE_DIRS
                       and not d.endswith(".egg-info")]
            for fname in files:
                if os.path.splitext(fname)[1].lower() not in _SOURCE_EXTS:
                    continue
                rel = os.path.relpath(os.path.join(root, fname), base_dir).replace("\\", "/")
                if _EXCLUDE_RE.search(rel):
                    continue
                found.append(rel)
        found.sort()
        return found

    def _discover_context_files(base_dir: str) -> list:
        ctx = []
        for name in ("README.md", "CHANGELOG.md"):
            if os.path.isfile(os.path.join(base_dir, name)):
                ctx.append(name)
        docs_dir = os.path.join(base_dir, "docs")
        if os.path.isdir(docs_dir):
            for sub in sorted(os.listdir(docs_dir)):
                if sub.endswith(".md"):
                    ctx.append(os.path.join("docs", sub).replace("\\", "/"))
        return ctx

    target_files = _discover_target_files(cwd)
    context_files = _discover_context_files(cwd)

    # Pipeline processes one file per session — pick exactly ONE anchor file
    # that physically exists. Prefer first source file; fall back to any
    # discoverable file so aider never creates a phantom path.
    _anchor = None
    if target_files:
        _anchor = target_files[0]
    else:
        # Broaden: pick any real file at repo root (README, DESCRIPTION, etc.)
        for _candidate in sorted(os.listdir(cwd)):
            _full = os.path.join(cwd, _candidate)
            if os.path.isfile(_full) and not _candidate.startswith("."):
                _anchor = _candidate
                break

    if _anchor:
        content = re.sub(
            r'(target_files:\s*)\[\]',
            lambda m: m.group(1) + f'\n        - "{_anchor}"',
            content,
            count=1,
        )

    if context_files:
        _cf = "\n".join(f'        - "{f}"' for f in context_files[:15])
        content = re.sub(
            r'(context_files_job:\s*)\[\]',
            lambda m: m.group(1) + "\n" + _cf,
            content,
            count=1,
        )
    # context_files_test: left as [] — user populates manually.

    # Provision .aider_factory directory
    local_aider_factory_dir = Path(cwd) / ".aider_factory"
    local_aider_factory_dir.mkdir(parents=True, exist_ok=True)

    target_yaml_path = local_aider_factory_dir / f".env_{repo_name}.yml"
    with open(target_yaml_path, "w", encoding="utf-8") as f:
        f.write(content)

    # --- Step 5: Provision + report ---
    _parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    from cli import init_user_project
    init_user_project(cwd)

    # Print structured summary
    print(f"\n\u2705 .aider_factory/.env_{repo_name}.yml written")
    print(f"   Framework:  {fw_name} (detected from filesystem)")
    print(f"   Target:     {_anchor or '\u26a0\ufe0f none found'}"
          + (f"  ({len(target_files)} source files available)" if len(target_files) > 1 else ""))
    print(f"   Context:    {len(context_files)} file(s)"
          + (f"  e.g. {context_files[0]}" if context_files else ""))
    if model_choices.get("embed"):
        _em = model_choices["embed"]
        _src = "cloud/router" if any(x in _em.lower() for x in ("gemini", "openai", "embedding", "qwen")) else "local"
        print(f"   Embed:      {_em} ({_src})")
    elif 'embed_backend: "sentence-transformers"' in content:
        print("   Embed:      sentence-transformers (weights ~2 GB download on first RAG run)")
    if router_base and available_models:
        print(f"   Router:     {router_base} ({len(available_models)} models)")
        print(f"   Architect:  {model_choices.get('architect', 'default')}")
        print(f"   Editor:     {model_choices.get('editor', 'default')}")
        if model_choices.get("reranker"):
            print(f"   Reranker:   {model_choices['reranker']}")
    elif router_base:
        print(f"   Router:     {router_base} (unreachable \u2014 template defaults preserved)")
    else:
        print(f"   Router:     none detected (placeholder endpoints in file)")

    if not key_name:
        print(f"\n   \u26a0\ufe0f  No API key detected. To enable inference, set:")
        print(f"      export LITELLM_BASE_URL=\"http://<host>:4000/v1\"")
        print(f"      export LITELLM_API_KEY=\"sk-...\"")
        print(f"   Or a cloud provider key (GEMINI_API_KEY, ANTHROPIC_API_KEY, etc.)")

    print(f"\n   Run:  aider-factory .aider_factory/.env_{repo_name}.yml")
    print(f"   Edit: .aider_factory/.env_{repo_name}.yml\n")

def run_query(instruction, file_path, context_paths, ask_mode, terminal_mode=False, master_mode=False, expert_mode=False, repo_map=False):
    """Query configuration or run general terminal assistant using direct litellm session persistence."""
    key_name, _ = detect_api_key()
    if not key_name:
        print_key_help_and_exit()
        return

    repo_name = get_repo_name()
    if terminal_mode:
        ask_mode = True  # Terminal mode is always conversational
        session_file = get_helper_terminal_session_file()
    else:
        session_file = get_helper_session_file()
        if not file_path:
            std_path = os.path.join(".aider_factory", ".env.yml")
            repo_path = os.path.join(".aider_factory", f".env_{repo_name}.yml")
            
            if os.path.exists(std_path):
                file_path = std_path
            elif os.path.exists(repo_path):
                file_path = repo_path
            else:
                if ask_mode:
                    # In ask mode, do not create files on disk. Use template in memory.
                    file_path = None
                else:
                    file_path = std_path
                    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    master_env_path = os.path.join(pkg_dir, "default_configs", "env.yml")
                    os.makedirs(".aider_factory", exist_ok=True)
                    sensible_name = f"{repo_name.replace('_', ' ').replace('-', ' ').title()} Pipeline"
                    cwd = os.getcwd()
                    cwd_forward = cwd.replace("\\", "/")
                    with open(master_env_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    content = re.sub(r'name:\s*".*?"', lambda _: f'name: "{sensible_name}"', content)
                    content = re.sub(r'working_directory:\s*".*?"', lambda _: f'working_directory: "{cwd_forward}"', content)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    print(f"ℹ️ Created configuration file from template: {file_path}")
        elif file_path and not os.path.exists(file_path):
            print(f"❌ Error: Configuration file not found: {file_path}", file=sys.stderr)
            sys.exit(1)

    messages = []
    if os.path.exists(session_file):
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    messages = data
                elif isinstance(data, dict) and "messages" in data:
                    messages = data["messages"]
        except Exception:
            pass

    if not messages:
        system_prompt = TERMINAL_PERSONA_PROMPT if terminal_mode else PERSONA_PROMPT
        messages.append({"role": "system", "content": system_prompt})

    history_text = "".join([m.get("content", "") for m in messages if m.get("role") != "system"])
    persistent_additions = ""
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(os.path.dirname(pkg_dir))
    
    if not terminal_mode and "<reference_schema>" not in history_text:
        candidate_ref_schemas = [
            os.path.join(".aider_factory", "sample_yaml_config", "complete_env.yml"),
            os.path.join(pkg_dir, "default_configs", "sample_yaml_config", "complete_env.yml"),
            os.path.join(repo_root, "src", "aider_factory", "default_configs", "sample_yaml_config", "complete_env.yml"),
            os.path.join(pkg_dir, "sample_yaml_config", "complete_env.yml"),
            os.path.join(pkg_dir, "default_configs", "env.yml"),
        ]
        ref_schema_path = next((p for p in candidate_ref_schemas if os.path.exists(p)), None)
        ref_schema_content = ""
        if ref_schema_path:
            try:
                with open(ref_schema_path, "r", encoding="utf-8") as f:
                    ref_schema_content = f.read()
            except Exception:
                pass
        if ref_schema_content:
            persistent_additions += f"<reference_schema>\n{ref_schema_content.strip()}\n</reference_schema>\n\n"

    if (master_mode or expert_mode) and "<yaml_documentation>" not in history_text:
        candidate_yaml_docs = [
            os.path.join(".aider_factory", "markdown", "docs", "yaml_docs_sample.md"),
            os.path.join(pkg_dir, "markdown", "docs", "yaml_docs_sample.md"),
            os.path.join(repo_root, "src", "aider_factory", "markdown", "docs", "yaml_docs_sample.md"),
            os.path.join(pkg_dir, "markdown", "yaml_docs_sample.md"),
        ]
        yaml_docs_path = next((p for p in candidate_yaml_docs if os.path.exists(p)), None)
        yaml_docs = ""
        if yaml_docs_path:
            try:
                with open(yaml_docs_path, "r", encoding="utf-8") as f:
                    yaml_docs = f.read()
            except Exception:
                pass
        if yaml_docs:
            persistent_additions += f"<yaml_documentation>\n{yaml_docs.strip()}\n</yaml_documentation>\n\n"

    if (master_mode or expert_mode) and "<skills_reference>" not in history_text:
        candidate_skills_dirs = [
            os.path.join(".aider_factory", "markdown", "skills"),
            os.path.join(pkg_dir, "markdown", "skills"),
            os.path.join(repo_root, "src", "aider_factory", "markdown", "skills"),
        ]
        skills_dir = next((d for d in candidate_skills_dirs if os.path.isdir(d)), None)
        skills_content = ""
        if skills_dir and os.path.isdir(skills_dir):
            for skill_file in sorted(os.listdir(skills_dir)):
                if skill_file.endswith(".md"):
                    with open(os.path.join(skills_dir, skill_file), "r", encoding="utf-8") as f:
                        skills_content += f"\nFile: {skill_file}\n```\n{f.read()}\n```\n"
        if skills_content:
            persistent_additions += f"<skills_reference>\n{skills_content.strip()}\n</skills_reference>\n\n"

    if expert_mode and "<factory_service_manual>" not in history_text:
        repo_root = os.path.dirname(os.path.dirname(pkg_dir))
        candidate_paths = [
            os.path.join(".aider_factory", "markdown", "docs", "factory_service_manual.md"),
            os.path.join(pkg_dir, "markdown", "docs", "factory_service_manual.md"),
            os.path.join(repo_root, "docs", "factory_service_manual.md"),
            os.path.join(pkg_dir, "markdown", "factory_service_manual.md"),
            os.path.join(pkg_dir, "docs", "factory_service_manual.md"),
            os.path.join(repo_root, "src", "aider_factory", "markdown", "docs", "factory_service_manual.md"),
            os.path.join(repo_root, "src", "aider_factory", "docs", "factory_service_manual.md"),
        ]
        manual_path = next((p for p in candidate_paths if os.path.exists(p)), None)
        if manual_path:
            with open(manual_path, "r", encoding="utf-8") as f:
                manual_docs = f.read()
            persistent_additions += f"<factory_service_manual>\n{manual_docs}\n</factory_service_manual>\n\n"

    if repo_map and "<repository_map>" not in history_text:
        repo_map_path = os.path.join(".aider_factory", "static_repo_map.md")
        if os.path.exists(repo_map_path):
            try:
                with open(repo_map_path, "r", encoding="utf-8") as f:
                    repo_map_content = f.read()
                persistent_additions += f"<repository_map>\n{repo_map_content}\n</repository_map>\n\n"
            except Exception:
                pass
        else:
            print("⚠️ [aider-helper] Warning: --repo-map requested, but '.aider_factory/static_repo_map.md' not found. Generate it via: aider-factory --repo-map", file=sys.stderr)

    if context_paths:
        ctx_blocks = []
        for path in context_paths.split(","):
            path = path.strip()
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        ctx_blocks.append(f"File: {path}\n```\n{f.read()}\n```")
                except Exception:
                    pass
        if ctx_blocks:
            persistent_additions += "<extra_context_files>\n" + "\n\n".join(ctx_blocks) + "\n</extra_context_files>\n\n"

    if not terminal_mode and "<active_configuration>" not in history_text:
        active_config = ""
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    active_config = f.read()
            except Exception:
                pass
        if not active_config:
            master_env_path = os.path.join(pkg_dir, "default_configs", "env.yml")
            if os.path.exists(master_env_path):
                try:
                    with open(master_env_path, "r", encoding="utf-8") as f:
                        active_config = f.read()
                except Exception:
                    pass
        if active_config:
            persistent_additions += f"<active_configuration>\n{active_config}\n</active_configuration>\n\n"

    user_msg_content = f"{persistent_additions}<question>\n{instruction}\n</question>" if persistent_additions else f"<question>\n{instruction}\n</question>"
    messages.append({"role": "user", "content": user_msg_content.strip()})
    
    llm_messages = list(messages)

    # Call litellm with streaming
    import litellm
    model_map = {
        "GEMINI_API_KEY": "gemini/gemini-3.6-flash",
        "GOOGLE_API_KEY": "gemini/gemini-3.6-flash",
        "AIDER_GEMINI_API_KEY": "gemini/gemini-3.6-flash",
        "ANTHROPIC_API_KEY": "anthropic/claude-3-5-sonnet-20241022",
        "OPENROUTER_API_KEY": "openrouter/auto",
        "GROQ_API_KEY": "groq/llama-3.3-70b-versatile",
        "OPENCODE_API_KEY": "openai/opencode",
        "OPENAI_API_KEY": "openai/gpt-4o"
    }
    model = os.environ.get("AIDER_HELPER_MODEL")
    api_base = os.environ.get("AIDER_HELPER_API_BASE")
    
    if api_base:
        if not model or any(model.startswith(p) for p in ("gemini/", "anthropic/", "groq/", "openrouter/")):
            try:
                import requests
                r = requests.get(f"{api_base.rstrip('/')}/models", headers={"Authorization": "Bearer sk-dummy"}, timeout=2)
                if r.status_code == 200:
                    m_list = r.json().get("data", [])
                    m_ids = [m["id"] for m in m_list if "id" in m]
                    favored = [m for m in m_ids if "27b" in m.lower()]
                    m_id = favored[0] if favored else (m_ids[0] if m_ids else None)
                    if m_id:
                        model = m_id if "/" in m_id else f"openai/{m_id}"
            except Exception:
                pass
            if not model or any(model.startswith(p) for p in ("gemini/", "anthropic/", "groq/", "openrouter/")):
                model = "openai/qwen3.6-27b-90k:LATEST"
        elif "/" not in model:
            model = f"openai/{model}"
    else:
        model = model or model_map.get(key_name, "gemini/gemini-2.5-flash")
    
    print(f"{_HELPER_COLOR}[aider-helper] Asking {model}...{_RESET}\n")
    try:
        kwargs = {
            "model": model,
            "messages": llm_messages,
            "custom_headers": {"x-litellm-session-id": _PIPELINE_SESSION_ID},
            "stream": True,
            "stream_options": {"include_usage": True}
        }
        if api_base:
            _explicit = (
                os.environ.get(key_name) if key_name != "CUSTOM_LOCAL"
                else os.environ.get("LITELLM_API_KEY")
            )
            helper_key = resolve_api_key(
                model=model,
                api_base=api_base,
                explicit_key=_explicit,
            )
            kwargs["api_base"] = api_base
            if helper_key and not is_dummy_key(helper_key):
                kwargs["api_key"] = helper_key
            elif _explicit and not is_dummy_key(_explicit):
                kwargs["api_key"] = _explicit
            # else: omit api_key entirely → litellm picks from env / no auth for local

        response = litellm.completion(**kwargs)

        final_usage = None

        try:
            from rich.console import Console
            from rich.live import Live
            from rich.markdown import Markdown

            console = Console()
            reply_text = ""
            with Live(console=console, refresh_per_second=15, transient=False) as live:
                for chunk in response:
                    content = chunk.choices[0].delta.content or "" if chunk.choices else ""
                    reply_text += content
                    live.update(Markdown(reply_text))
                    
                    if getattr(chunk, "usage", None):
                        final_usage = chunk.usage
            print("\n")
        except ImportError:
            # Fallback if rich is somehow unavailable
            full_reply = []
            for chunk in response:
                content = chunk.choices[0].delta.content or "" if chunk.choices else ""
                print(content, end="", flush=True)
                full_reply.append(content)
                if getattr(chunk, "usage", None):
                    final_usage = chunk.usage
            print("\n")
            reply_text = "".join(full_reply)
            
        try:
            try:
                from aider_factory.python.cost_tracker import fmt_token_count, fmt_cost_usd
                import aider_factory.python.cost_tracker as ct
            except ImportError:
                from cost_tracker import fmt_token_count, fmt_cost_usd
                import cost_tracker as ct
            
            if final_usage:
                sent = getattr(final_usage, "prompt_tokens", 0)
                recv = getattr(final_usage, "completion_tokens", 0)
                
                try:
                    cost_tuple = litellm.cost_calculator.cost_per_token(model=model, prompt_tokens=sent, completion_tokens=recv)
                    msg_cost = float(cost_tuple[0] + cost_tuple[1]) if isinstance(cost_tuple, tuple) else float(cost_tuple)
                except Exception:
                    msg_cost = 0.0
                    
                ct._PROCESS_SESSION_COST += msg_cost
                session_cost = ct._PROCESS_SESSION_COST
                
                print(
                    f"Tokens: {fmt_token_count(sent)} sent, "
                    f"{fmt_token_count(recv)} received. "
                    f"Cost: ${fmt_cost_usd(msg_cost)} message, "
                    f"${fmt_cost_usd(session_cost)} session.",
                    file=sys.stderr
                )
        except Exception as e:
            pass

        messages.append({"role": "assistant", "content": reply_text})
        
        # Save session history directly
        session_dir = os.path.dirname(session_file)
        # In ask/terminal mode, do not pollute pristine directories with .aider_factory
        if not ask_mode or not session_dir or os.path.exists(session_dir):
            if session_dir:
                os.makedirs(session_dir, exist_ok=True)
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)

        # Hardcoded deterministic check: write back ONLY if ask_mode is False
        if not ask_mode:
            yaml_content = None
            if "```yaml" in reply_text:
                yaml_content = reply_text.split("```yaml")[1].split("```")[0].strip()
            elif "```" in reply_text:
                yaml_content = reply_text.split("```")[1].split("```")[0].strip()
                
            if yaml_content:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(yaml_content)
                print(f"✅ Successfully updated configuration: {file_path}")

    except Exception as e:
        print(f"\n❌ Helper call failed: {e}", file=sys.stderr)
