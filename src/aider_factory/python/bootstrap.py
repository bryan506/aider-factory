
import os
import sys
import json
import shutil
import hashlib
import subprocess
from pathlib import Path

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
    "You communicate with absolute precision, objectivity, and technical clarity. You prioritize "
    "deterministic, minimal-delta edits to configurations, preserving all inline comments and "
    "inactive blocks unless explicitly instructed to change them. When asked to modify a configuration, "
    "return ONLY the complete, updated YAML content inside a markdown code block."
)

TERMINAL_PERSONA_PROMPT = (
    "You are a general-purpose AI software engineering assistant working in an interactive terminal session.\n"
    "Answer questions clearly, accurately, and concisely based on the user's prompt and provided context files.\n"
    "Provide well-structured code, explanations, and unix commands when requested."
)

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

def detect_api_key():
    keys = ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "OPENCODE_API_KEY"]
    for k in keys:
        if os.environ.get(k):
            return k, os.environ.get(k)
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
    if not key_name:
        print_key_help_and_exit()

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
    arch_default = "gemini/gemini-3.5-flash" if provider == "gemini" else "openai/gpt-4o"
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

    # Synthesize config
    repo_name = get_repo_name()
    # __file__ is in src/aider_factory/python/, so parent is src/aider_factory/
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    master_env_path = os.path.join(pkg_dir, "default_configs", "env.yml")
    yaml_docs_path = os.path.join(pkg_dir, "markdown", "yaml_docs_sample.md")
    
    # Bootstrap .aider_factory directory structure
    local_aider_factory_dir = Path(target_dir) / ".aider_factory"
    local_aider_factory_dir.mkdir(parents=True, exist_ok=True)
    
    target_yaml_path = local_aider_factory_dir / f".env_{repo_name}.yml"
    
    print("\n[+] Customizing configuration template...")
    try:
        import litellm
        
        with open(master_env_path, "r", encoding="utf-8") as f:
            master_content = f.read()
        with open(yaml_docs_path, "r", encoding="utf-8") as f:
            yaml_docs = f.read()

        prompt = (
            f"Customize the following master env.yml template based on the user's profile.\n\n"
            f"USER PROFILE:\n{json.dumps(profile, indent=2)}\n\n"
            f"MASTER TEMPLATE:\n{master_content}\n\n"
            f"YAML DOCUMENTATION REFERENCE:\n{yaml_docs[:15000]}\n\n"
            f"CRITICAL INSTRUCTION: The generated YAML must contain EXACTLY ONE phase under the 'phases:' block, "
            f"configured strictly according to the USER PROFILE. Do not include or append any other placeholder, "
            f"example, or extra phases from the documentation or templates.\n\n"
            f"Return ONLY the complete, updated YAML content inside a markdown code block."
        )

        response = litellm.completion(
            model=arch_model if "gemini/" in arch_model else "gemini/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": PERSONA_PROMPT},
                {"role": "user", "content": prompt}
            ]
        )
        ans = response.choices[0].message.content
        
        # Extract YAML from markdown code block
        yaml_content = ans
        if "```yaml" in ans:
            yaml_content = ans.split("```yaml")[1].split("```")[0].strip()
        elif "```" in ans:
            yaml_content = ans.split("```")[1].split("```")[0].strip()

        # Sanity check to ensure LLM output conforms to standardized dynamic requirements
        sensible_name = f"{os.path.basename(os.getcwd()).replace('_', ' ').replace('-', ' ').title()} Pipeline"
        cwd = os.getcwd()
        yaml_content = yaml_content.replace('name: "My Project"', f'name: "{sensible_name}"')
        yaml_content = yaml_content.replace('working_directory: "/path/to/project"', f'working_directory: "{cwd}"')

        # Standardize the analyze_bugs template path to use the portable src/aider_factory relative path
        yaml_content = yaml_content.replace('template: ".aider_factory/markdown/internal/analyze_bugs.md"', 'template: "src/aider_factory/markdown/internal/analyze_bugs.md"')
        yaml_content = yaml_content.replace('template: "markdown/internal/analyze_bugs.md"', 'template: "src/aider_factory/markdown/internal/analyze_bugs.md"')

        # Inject user RAG choices into synthesized LLM output if RAG is enabled
        if profile["use_rag"]:
            yaml_content = yaml_content.replace('collection_name: ""', f'collection_name: "{profile["rag_collection"]}"')
            yaml_content = yaml_content.replace('run_ocr_rag: false', 'run_ocr_rag: true')
            yaml_content = yaml_content.replace('grounding_agent: "openai/minicheck-flan-t5-large"', 'grounding_agent: ""') # Disabled by default
            if profile["rag_agent"]:
                yaml_content = yaml_content.replace('rag_agent: "gemini/gemini-2.5-flash"', f'rag_agent: "{profile["rag_agent"]}"')
            if profile["ocr_agent"]:
                yaml_content = yaml_content.replace('ocr_agent: "glm-ocr-f16:LATEST"', f'ocr_agent: "{profile["ocr_agent"]}"')
            if profile["embed_model"]:
                yaml_content = yaml_content.replace('embed_model: "qwen3-embedding-8b-8k:LATEST"', f'embed_model: "{profile["embed_model"]}"')
            if profile["embed_backend"]:
                yaml_content = yaml_content.replace('embed_backend: "sentence-transformers"', f'embed_backend: "{profile["embed_backend"]}"')
            if profile["query_prefix"]:
                yaml_content = yaml_content.replace('query_prefix: "Query: "', f'query_prefix: "{profile["query_prefix"]}"')

        with open(target_yaml_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)
            
        print(f"✅ Created {target_yaml_path}")
        
    except Exception as e:
        print(f"⚠️ Synthesis failed: {e}. Copying master template directly as fallback.")
        sensible_name = f"{os.path.basename(os.getcwd()).replace('_', ' ').replace('-', ' ').title()} Pipeline"
        cwd = os.getcwd()
        with open(master_env_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace('name: "My Project"', f'name: "{sensible_name}"')
        content = content.replace('working_directory: "/path/to/project"', f'working_directory: "{cwd}"')

        # Standardize the analyze_bugs template path to use the portable src/aider_factory relative path
        content = content.replace('template: ".aider_factory/markdown/internal/analyze_bugs.md"', 'template: "src/aider_factory/markdown/internal/analyze_bugs.md"')
        content = content.replace('template: "markdown/internal/analyze_bugs.md"', 'template: "src/aider_factory/markdown/internal/analyze_bugs.md"')
        
        if profile["use_rag"]:
            content = content.replace('collection_name: ""', f'collection_name: "{profile["rag_collection"]}"')
            content = content.replace('run_ocr_rag: false', 'run_ocr_rag: true')
            content = content.replace('grounding_agent: "openai/minicheck-flan-t5-large"', 'grounding_agent: ""') # Disabled by default
            if profile["rag_agent"]:
                content = content.replace('rag_agent: "gemini/gemini-2.5-flash"', f'rag_agent: "{profile["rag_agent"]}"')
            if profile["ocr_agent"]:
                content = content.replace('ocr_agent: "glm-ocr-f16:LATEST"', f'ocr_agent: "{profile["ocr_agent"]}"')
            if profile["embed_model"]:
                content = content.replace('embed_model: "qwen3-embedding-8b-8k:LATEST"', f'embed_model: "{profile["embed_model"]}"')
            if profile["embed_backend"]:
                content = content.replace('embed_backend: "sentence-transformers"', f'embed_backend: "{profile["embed_backend"]}"')
            if profile["query_prefix"]:
                content = content.replace('query_prefix: "Query: "', f'query_prefix: "{profile["query_prefix"]}"')

        with open(target_yaml_path, "w", encoding="utf-8") as f:
            f.write(content)

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

def run_query(instruction, file_path, context_paths, ask_mode, terminal_mode=False):
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
            file_path = os.path.join(".aider_factory", f".env_{repo_name}.yml")
            if not os.path.exists(file_path):
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
        if terminal_mode:
            messages.append({"role": "system", "content": TERMINAL_PERSONA_PROMPT})
            messages.append({"role": "assistant", "content": "Terminal agent initialized. Ready to assist with your workspace tasks."})
        else:
            pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            yaml_docs_path = os.path.join(pkg_dir, "markdown", "yaml_docs_sample.md")
            with open(yaml_docs_path, "r", encoding="utf-8") as f:
                yaml_docs = f.read()
            with open(file_path, "r", encoding="utf-8") as f:
                active_config = f.read()
            messages.append({"role": "system", "content": PERSONA_PROMPT})
            messages.append({"role": "user", "content": f"YAML DOCUMENTATION:\n{yaml_docs[:15000]}\n\nACTIVE CONFIGURATION:\n{active_config}"})
            messages.append({"role": "assistant", "content": "Acknowledged. I have loaded the pipeline documentation and your active configuration. How can I help you modify or understand your pipeline today?"})

    # Append user context files if specified
    user_context = ""
    if context_paths:
        ctx_blocks = []
        for path in context_paths.split(","):
            path = path.strip()
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        ctx_blocks.append(f"### File: {path}\n```\n{f.read()}\n```")
                except Exception:
                    pass
        if ctx_blocks:
            user_context = "\n\nEXTRA CONTEXT FILES:\n" + "\n\n".join(ctx_blocks)

    messages.append({"role": "user", "content": f"{instruction}{user_context}"})

    # Call litellm with streaming
    import litellm
    model_map = {
        "GEMINI_API_KEY": "gemini/gemini-2.5-flash",
        "ANTHROPIC_API_KEY": "anthropic/claude-3-5-sonnet-20241022",
        "OPENROUTER_API_KEY": "openrouter/auto",
        "GROQ_API_KEY": "groq/llama-3.3-70b-versatile",
        "OPENCODE_API_KEY": "openai/opencode",
        "OPENAI_API_KEY": "openai/gpt-4o"
    }
    model = model_map.get(key_name, "openai/gpt-4o")
    
    print(f"{_HELPER_COLOR}[aider-helper] Asking {model}...{_RESET}\n")
    try:
        response = litellm.completion(
            model=model,
            messages=messages,
            stream=True
        )
        
        full_reply = []
        for chunk in response:
            content = chunk.choices[0].delta.content or ""
            print(content, end="", flush=True)
            full_reply.append(content)
        print("\n")
        
        reply_text = "".join(full_reply)
        messages.append({"role": "assistant", "content": reply_text})
        
        # Save session history directly
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
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
