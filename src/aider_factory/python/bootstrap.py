
import os
import sys
import json
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
    "block. When answering questions about the active pipeline, phases, agents, models, or target files, "
    "inspect the <active_configuration> block. You communicate with absolute precision, objectivity, and "
    "technical clarity. You prioritize deterministic, minimal-delta edits to configurations, preserving all "
    "inline comments and inactive blocks unless explicitly instructed to change them. When asked to modify "
    "a configuration, apply the requested changes to <active_configuration> and return ONLY the complete, "
    "updated YAML content inside a markdown code block."
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
        "editor_ollama_api": base_url,
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
    keys = ["GEMINI_API_KEY", "GOOGLE_API_KEY", "AIDER_GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "OPENCODE_API_KEY"]
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

def run_bootstrap(target_dir):
    """Conduct terminal-based interview to capture user intent and generate initial .env_<repo>.yml."""
    print("====================================================")
    print("         AI FACTORY WORKSPACE BOOTSTRAPPER          ")
    print("====================================================\n")
    
    key_name, _ = detect_api_key()

    profile = {}
    
    # 1. Target Files
    print("[1] Target Files to Modify:")
    t_files = input("Enter files you want the agent to edit (comma-separated, e.g. src/main.py, R/logic.R): ").strip()
    if not t_files:
        print("Error: Target files are required to bootstrap a workspace.", file=sys.stderr)
        sys.exit(1)
    profile["target_files"] = [f.strip() for f in t_files.split(",") if f.strip()]

    # 2. Context Files
    print("\n[2] Context Files (Read-Only):")
    c_files = input("Enter read-only files the agent should look at (comma-separated, optional): ").strip()
    profile["context_files"] = [f.strip() for f in c_files.split(",") if f.strip()]

    # 3. Language & Testing
    print("\n[3] Language & Testing Framework:")
    print("  1) Python (pytest)")
    print("  2) R (testthat)")
    print("  3) Rust (cargo test)")
    print("  4) JavaScript (npm test)")
    print("  5) Go (go test)")
    print("  6) Custom")
    choice = input("Select framework [default: 1]: ").strip() or "1"
    
    frameworks = {
        "1": {"runner": "python -m pytest {file}", "path": "tests/test_{stem}.py", "prefix": ""},
        "2": {"runner": "Rscript .aider_factory/tests/run_tests.R {file}", "path": "tests/testthat/test-{stem}.R", "prefix": ""},
        "3": {"runner": "cargo test --test {stem}", "path": "tests/{stem}.rs", "prefix": ""},
        "4": {"runner": "npm test {file}", "path": "tests/{stem}.test.js", "prefix": ""},
        "5": {"runner": "go test {file}", "path": "tests/{stem}_test.go", "prefix": ""},
        "6": {"runner": "echo 'custom'", "path": "tests/{stem}.test", "prefix": ""}
    }
    selected = frameworks.get(choice, frameworks["1"])
    profile["test_runner"] = selected["runner"]
    profile["test_naming_and_path"] = selected["path"]
    profile["test_command_prefix"] = selected["prefix"]

    # 4. Operating Mode
    print("\n[4] Operating Mode:")
    print("  1) Autonomous Pipeline (Iterative test-fixing loops)")
    print("  2) Interactive Pair Programming (PTY-wrapped architect prompt)")
    choice = input("Select operating mode [default: 1]: ").strip() or "1"
    profile["operating_mode"] = "autonomous" if choice == "1" else "pair"

    # 5. Model Discovery & Selection
    provider_map = {
        "GEMINI_API_KEY": "gemini",
        "ANTHROPIC_API_KEY": "anthropic",
        "OPENAI_API_KEY": "openai",
        "OPENROUTER_API_KEY": "openrouter",
        "GROQ_API_KEY": "groq"
    }
    provider = provider_map.get(key_name, "gemini")
    
    print(f"\n[+] Retrieving available models for provider '{provider}' via Aider...")
    try:
        subprocess.run(["aider", "--list-models", provider], check=False)
    except Exception:
        print("  (Aider model list unavailable. Using standard presets.)")

    print("\n[5] Model Selection:")
    arch_default = "gemini/gemini-3.6-flash" if provider == "gemini" else "openai/gpt-4o"
    edit_default = "gemini/gemini-2.5-flash" if provider == "gemini" else "openai/gpt-4o-mini"
    
    arch_model = input(f"Enter Architect model [default: {arch_default}]: ").strip() or arch_default
    edit_model = input(f"Enter Editor model [default: {edit_default}]: ").strip() or edit_default

    profile["architect_agent"] = arch_model
    profile["editor_agent"] = edit_model
    profile["working_directory"] = os.getcwd()

    # 6. Knowledge Oracle (RAG)
    print("\n[6] Knowledge Oracle (RAG):")
    choice = input("Do you want to attach a RAG database to query documentation? (y/n) [default: n]: ").strip().lower() or "n"
    profile["use_rag"] = choice == "y"
    if profile["use_rag"]:
        profile["rag_collection"] = input("Enter your document collection directory name [default: docs]: ").strip() or "docs"
        profile["rag_agent"] = input(f"Enter RAG Agent (Oracle) model [default: {arch_model}]: ").strip() or arch_model
        profile["ocr_agent"] = input(f"Enter OCR Agent model [default: {arch_model}]: ").strip() or arch_model
        profile["embed_model"] = input("Enter Embedding Model [default: BAAI/bge-m3]: ").strip() or "BAAI/bge-m3"
        profile["embed_backend"] = input("Enter Embedding Backend (sentence-transformers/openai) [default: sentence-transformers]: ").strip() or "sentence-transformers"
        
        # Dynamic query_prefix auto-detection & fallback menu
        emb_lower = profile["embed_model"].lower()
        if "bge" in emb_lower:
            profile["query_prefix"] = "Instruct: Given a coding or financial query, retrieve relevant passages\\nQuery: "
        elif "qwen" in emb_lower:
            profile["query_prefix"] = "Query: "
        else:
            print(f"\n⚠️ No known query prefix preset found for embedding model '{profile['embed_model']}'.")
            print("Available presets:")
            print("  1) BGE (\"Instruct: Given a coding or financial query, retrieve relevant passages\\nQuery: \")")
            print("  2) Qwen / Standard (\"Query: \")")
            print("  3) Custom (Enter your own)")
            preset_choice = input("Select preset or enter custom prefix [default: 2]: ").strip() or "2"
            if preset_choice == "1":
                profile["query_prefix"] = "Instruct: Given a coding or financial query, retrieve relevant passages\\nQuery: "
            elif preset_choice == "2":
                profile["query_prefix"] = "Query: "
            elif preset_choice == "3" or preset_choice == "":
                profile["query_prefix"] = input("Enter custom query prefix: ").strip()
            else:
                profile["query_prefix"] = preset_choice
    else:
        profile["rag_collection"] = ""
        profile["rag_agent"] = ""
        profile["ocr_agent"] = ""
        profile["embed_model"] = ""
        profile["embed_backend"] = ""
        profile["query_prefix"] = ""

    # Synthesize config deterministically
    repo_name = get_repo_name()
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    master_env_path = os.path.join(pkg_dir, "default_configs", "env.yml")
    
    # Bootstrap .aider_factory directory structure
    local_aider_factory_dir = Path(target_dir) / ".aider_factory"
    local_aider_factory_dir.mkdir(parents=True, exist_ok=True)
    
    target_yaml_path = local_aider_factory_dir / f".env_{repo_name}.yml"
    
    print("\n[+] Generating configuration...")
    
    with open(master_env_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Project Identity
    sensible_name = f"{os.path.basename(os.getcwd()).replace('_', ' ').replace('-', ' ').title()} Pipeline"
    cwd = os.getcwd()
    content = content.replace('name: "My Project"', f'name: "{sensible_name}"')
    content = content.replace('working_directory: "/path/to/project"', f'working_directory: "{cwd}"')

    # Auto-discover cluster config and override defaults if present
    cluster_config = _discover_cluster_config()
    if cluster_config:
        content = content.replace('architect_api_base: "http://192.168.100.2:8080/v1"', f'architect_api_base: "{cluster_config["architect_api_base"]}"')
        content = content.replace('editor_ollama_api: "http://192.168.100.1:8080/v1"', f'editor_ollama_api: "{cluster_config["editor_ollama_api"]}"')
        content = content.replace('rag_agent_api: "http://192.168.100.1:8080/v1"', f'rag_agent_api: "{cluster_config["rag_agent_api"]}"')
        if "architect_agent" in cluster_config:
            profile["architect_agent"] = cluster_config["architect_agent"]
            profile["editor_agent"] = cluster_config["editor_agent"]

    # 2. Test Framework
    content = content.replace('test_command_prefix: "docker exec -i --user myuser -w /path/to/project -e RETICULATE_PYTHON=/home/myuser/.venv-rocker/bin/python3 rocker-rstudio"', f'test_command_prefix: "{profile["test_command_prefix"]}"')
    content = content.replace('test_runner: "Rscript .aider_factory/tests/run_tests.R {file}"', f'test_runner: "{profile["test_runner"]}"')
    content = content.replace('test_naming_and_path: "tests/testthat/test-{stem}.R"', f'test_naming_and_path: "{profile["test_naming_and_path"]}"')

    # 3. Models
    content = content.replace('architect_agent: "gemini/gemini-3.6-flash"', f'architect_agent: "{profile["architect_agent"]}"')
    content = content.replace('editor_agent: "gemini/gemini-2.5-flash"', f'editor_agent: "{profile["editor_agent"]}"')
    content = content.replace('editor_agent_test: "gemini/gemini-2.5-flash"', f'editor_agent_test: "{profile["editor_agent"]}"')
    content = content.replace('editor_agent_test_fallback: "gemini/gemini-2.5-flash"', f'editor_agent_test_fallback: "{profile["architect_agent"]}"')

    # 4. Operating Mode
    if profile["operating_mode"] == "autonomous":
        content = content.replace('pair_programming: true', 'pair_programming: false')
        content = content.replace('auto_test: false', 'auto_test: true')
        content = content.replace('yes_always: false', 'yes_always: true')
        content = content.replace('auto_accept_architect: false', 'auto_accept_architect: true')

    # 5. File Lists
    def format_yaml_list(items):
        if not items:
            return "[]"
        return "\n" + "\n".join(f'        - "{item}"' for item in items)

    content = content.replace('target_files: []', f'target_files: {format_yaml_list(profile["target_files"])}')
    content = content.replace('context_files_job: []', f'context_files_job: {format_yaml_list(profile.get("context_files", []))}')
    content = content.replace('context_files_test: []', f'context_files_test: {format_yaml_list(profile.get("context_files", []))}')

    # 6. Knowledge Oracle (RAG)
    if profile["use_rag"]:
        content = content.replace('collection_name: "working_repo_lib"', f'collection_name: "{profile["rag_collection"]}"')
        content = content.replace('run_ocr_rag: false', 'run_ocr_rag: true')
        content = content.replace('grounding_agent: "gemini/gemini-2.5-flash"', 'grounding_agent: ""') # Disabled by default
        if profile["rag_agent"]:
            content = content.replace('rag_agent: "gemini/gemini-2.5-flash"', f'rag_agent: "{profile["rag_agent"]}"')
        if profile["ocr_agent"]:
            content = content.replace('ocr_agent: "gemini/gemini-2.5-flash"', f'ocr_agent: "{profile["ocr_agent"]}"')
        if profile["embed_model"]:
            content = content.replace('embed_model: "gemini/text-embedding-004"', f'embed_model: "{profile["embed_model"]}"')
        if profile["embed_backend"]:
            content = content.replace('embed_backend: "sentence-transformers"', f'embed_backend: "{profile["embed_backend"]}"')
        if profile["query_prefix"]:
            content = content.replace('query_prefix: "Instruct: Given a coding or financial query, retrieve relevant passages\\nQuery: "', f'query_prefix: "{profile["query_prefix"]}"')

    # Standardize the analyze_bugs template path to use the portable src/aider_factory relative path
    content = content.replace('template: ".aider_factory/markdown/internal/analyze_bugs.md"', 'template: "src/aider_factory/markdown/internal/analyze_bugs.md"')
    content = content.replace('template: "markdown/internal/analyze_bugs.md"', 'template: "src/aider_factory/markdown/internal/analyze_bugs.md"')

    with open(target_yaml_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    print(f"✅ Created {target_yaml_path}")

    # Initialize other default files
    # Add parent directory (src/aider_factory/) to path dynamically to import cli
    _parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    from cli import init_user_project
    init_user_project(target_dir)
    
    # Automatically provision the LanceDB directory if RAG is enabled
    if profile["use_rag"] and profile["rag_collection"]:
        rag_dir = os.path.join(target_dir, ".aider_factory", "markdown", "lanceDB", profile["rag_collection"])
        os.makedirs(rag_dir, exist_ok=True)

    print("\n🎉 Workspace initialized successfully!")
    if profile["use_rag"]:
        print(f"👉 Note: Copy your source documents (PDFs, MD, images, etc.) to:\n  .aider_factory/markdown/lanceDB/{profile['rag_collection']}/")
    print(f"To run your pipeline, execute:\n  .aider_factory/bash/factory .aider_factory/.env_{repo_name}.yml")
    
    print("\n💡 Tip: You can customize or change the aider-helper model at any time:")
    print("  # For local endpoints (e.g., llama.cpp/LM Studio):")
    print("  export AIDER_HELPER_MODEL=\"qwen3.6-27B-90k-udq4kxl:LATEST\"")
    print("  export AIDER_HELPER_API_BASE=\"http://192.168.100.1:8080/v1\"")
    print("  # For other cloud providers (e.g., Anthropic):")
    print("  export AIDER_HELPER_MODEL=\"anthropic/claude-3-5-sonnet-20241022\"")
    print("  export ANTHROPIC_API_KEY=\"your-key\"")
    print("  # To revert back to default cloud settings:")
    print("  unset AIDER_HELPER_MODEL AIDER_HELPER_API_BASE")

    if not key_name:
        print("\n⚠️  No LLM API key was detected in your environment.")
        print("If you plan to use cloud models, remember to export your key (e.g., export GEMINI_API_KEY=\"...\")")
        print("and add it to your ~/.bashrc or ~/.zshrc.")

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
                    with open(master_env_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    content = content.replace('name: "My Project"', f'name: "{sensible_name}"')
                    content = content.replace('working_directory: "/path/to/project"', f'working_directory: "{cwd}"')
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
    
    if not terminal_mode and "<yaml_documentation>" not in history_text:
        yaml_docs_path = os.path.join(pkg_dir, "markdown", "yaml_docs_sample.md")
        yaml_docs = ""
        if os.path.exists(yaml_docs_path):
            try:
                with open(yaml_docs_path, "r", encoding="utf-8") as f:
                    yaml_docs = f.read()
            except Exception:
                pass
        persistent_additions += f"<yaml_documentation>\n{yaml_docs[:15000]}\n</yaml_documentation>\n\n"

    if (master_mode or expert_mode) and "<skills_reference>" not in history_text:
        skills_dir = os.path.join(pkg_dir, "markdown", "skills")
        skills_content = ""
        if os.path.exists(skills_dir) and os.path.isdir(skills_dir):
            for skill_file in sorted(os.listdir(skills_dir)):
                if skill_file.endswith(".md"):
                    with open(os.path.join(skills_dir, skill_file), "r", encoding="utf-8") as f:
                        skills_content += f"\nFile: {skill_file}\n```\n{f.read()}\n```\n"
        if skills_content:
            persistent_additions += f"<skills_reference>\n{skills_content.strip()}\n</skills_reference>\n\n"

    if expert_mode and "<factory_service_manual>" not in history_text:
        manual_path = os.path.join(pkg_dir, "markdown", "factory_service_manual.md")
        if os.path.exists(manual_path):
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
            print("⚠️ [aider-helper] Warning: --repo-map requested, but '.aider_factory/static_repo_map.md' not found. Generate it via: aider --map-tokens 4096 --show-repo-map > .aider_factory/static_repo_map.md", file=sys.stderr)

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
            helper_key = resolve_api_key(
                model=model,
                api_base=api_base,
                explicit_key=os.environ.get(key_name) if key_name != "CUSTOM_LOCAL" else None,
            )
            kwargs["api_base"] = api_base
            kwargs["api_key"] = helper_key or "sk-dummy"

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
        if session_dir and os.path.exists(session_dir):
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
        elif not ask_mode:
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
