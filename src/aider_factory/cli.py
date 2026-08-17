import os
import runpy
import shutil
import subprocess
import sys
import time
import urllib.request


def ensure_searxng_service():
    """Hands-off runtime provisioner: checks SearXNG status and starts user systemd service if needed."""
    url = os.environ.get("SEARXNG_BASE_URL", "http://localhost:8088")
    health_url = f"{url.rstrip('/')}/healthz"

    # 1. Fast 1-second health check
    try:
        req = urllib.request.Request(
            health_url, headers={"User-Agent": "AI-Factory/1.0"}
        )
        with urllib.request.urlopen(req, timeout=1) as resp:
            if resp.status == 200:
                return  # SearXNG is up and healthy
    except Exception:
        pass  # Service not running; proceed with auto-provisioning

    # 2. Detect container engine (Podman preferred for rootless/zero-sudo, Docker as fallback)
    engine_bin = None
    engine_name = None

    # 2a. Check Podman (rootless zero-sudo container engine)
    podman_bin = shutil.which("podman")
    if podman_bin:
        podman_check = subprocess.run(
            [podman_bin, "info"], capture_output=True, text=True
        )
        if podman_check.returncode == 0:
            engine_bin = podman_bin
            engine_name = "podman"

    # 2b. Check Docker if Podman is not available
    if not engine_bin:
        docker_bin = shutil.which("docker")
        if docker_bin:
            docker_check = subprocess.run(
                [docker_bin, "info"], capture_output=True, text=True
            )
            if docker_check.returncode == 0:
                engine_bin = docker_bin
                engine_name = "docker"
            elif "permission denied" in docker_check.stderr.lower():
                subprocess.run(
                    ["systemctl", "--user", "stop", "searxng.service"],
                    check=False,
                    capture_output=True,
                )
                print(
                    "⚠️ [aider-factory] Docker permission denied. Install 'podman' for rootless execution (sudo apt install -y podman) or add user to docker group: 'sudo usermod -aG docker $USER'.",
                    file=sys.stderr,
                )
                return

    if not engine_bin:
        return

    # 3. Ensure SearXNG configuration (~/.config/searxng/settings.yml) enables JSON format
    searxng_config_dir = os.path.expanduser("~/.config/searxng")
    os.makedirs(searxng_config_dir, exist_ok=True)
    searxng_settings_file = os.path.join(searxng_config_dir, "settings.yml")
    if not os.path.exists(searxng_settings_file):
        settings_content = """use_default_settings: true
server:
  secret_key: "aider_factory_searxng_secret_key"
search:
  formats:
    - html
    - json
engines:
  - name: wikidata
    disabled: true  # Disable wikidata to prevent startup 403 suspension errors
enabled_plugins:
  - 'Hash plugin'
  - 'Self-contained tracker'
  # Omitting 'Limiter' plugin disables bot detection / rate limiting
"""
        with open(searxng_settings_file, "w", encoding="utf-8") as f:
            f.write(settings_content)

    # 4. Write systemd user service file (~/.config/systemd/user/searxng.service)
    user_systemd_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(user_systemd_dir, exist_ok=True)
    service_file = os.path.join(user_systemd_dir, "searxng.service")

    if not os.path.exists(service_file):
        service_content = f"""[Unit]
Description=SearXNG Meta-Search Engine (User Service)
After=network.target

[Service]
Type=simple
ExecStartPre=-{engine_bin} rm -f searxng
ExecStart={engine_bin} run --rm --name searxng -p 8088:8080 -v {searxng_settings_file}:/etc/searxng/settings.yml:ro -e SEARXNG_BASE_URL=http://localhost:8088/ docker.io/searxng/searxng:latest
ExecStop={engine_bin} stop searxng
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
        with open(service_file, "w", encoding="utf-8") as f:
            f.write(service_content)

    # 4. Enable and start service in user space (no sudo)
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"], check=False, capture_output=True
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "searxng.service"],
            check=False,
            capture_output=True,
        )
        print(
            f"📦 [aider-factory] Hands-off setup: Auto-provisioned SearXNG via {engine_name} on http://localhost:8088",
            file=sys.stderr,
        )

        # 5. Wait for container HTTP readiness
        for _ in range(30):
            time.sleep(0.5)
            try:
                req = urllib.request.Request(
                    health_url, headers={"User-Agent": "AI-Factory/1.0"}
                )
                with urllib.request.urlopen(req, timeout=1) as resp:
                    if resp.status == 200:
                        print("✅ [aider-factory] SearXNG background service is ready.", file=sys.stderr)
                        return
            except Exception:
                pass
    except Exception as e:
        print(
            f"⚠️ [aider-factory] Could not start SearXNG user service automatically: {e}",
            file=sys.stderr,
        )


def ensure_bash_wrappers(project_aider_factory_dir):
    """Ensures .aider_factory/bash/ launcher scripts exist and are executable."""
    bash_dir = os.path.join(project_aider_factory_dir, "bash")
    os.makedirs(bash_dir, exist_ok=True)

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    python_dir = os.path.join(pkg_dir, "python")
    
    # Determine the best python interpreter to use
    aider_py = sys.executable or "python3"

    # Define wrappers dynamically to point to the actual package scripts
    wrappers = {
        "factory": f'#!/bin/bash\nexec "{aider_py}" "{os.path.join(python_dir, "run_workflow.py")}" "$@"\n',
        "oracle": f'#!/bin/bash\nexec "{aider_py}" "{os.path.join(python_dir, "oracle_agent.py")}" "$@"\n',
        "validate": f'#!/bin/bash\nexec "{aider_py}" "{os.path.join(python_dir, "validator.py")}" "$@"\n',
        "research": f'#!/bin/bash\nexec "{aider_py}" "{os.path.join(python_dir, "research_agent.py")}" "$@"\n',
    }

    for script, content in wrappers.items():
        target_path = os.path.join(bash_dir, script)
        # Always overwrite or update wrappers to ensure they point to the correct active package path
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(target_path, 0o755)


def init_user_project(cwd=None):
    """Onboarding: Auto-creates default config files in the CWD if they are missing."""
    if cwd is None:
        cwd = os.getcwd()
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    default_configs_dir = os.path.join(pkg_dir, "default_configs")

    # Target paths in user's working directory
    local_aider_factory_dir = os.path.join(cwd, ".aider_factory")
    os.makedirs(local_aider_factory_dir, exist_ok=True)

    # Provision executable bash launchers & SearXNG service automatically
    ensure_bash_wrappers(local_aider_factory_dir)
    ensure_searxng_service()

    # Ensure Playwright browser binaries are installed automatically if playwright is present
    try:
        import playwright
        # Check if the browser cache directory exists and is populated
        playwright_cache = os.path.expanduser("~/.cache/ms-playwright")
        if not os.path.exists(playwright_cache) or not os.listdir(playwright_cache):
            print("📦 [aider-factory] Provisioning Playwright browser binaries...")
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=False,
                capture_output=True,
            )
    except ImportError:
        pass  # Playwright not installed in this environment; skip

    local_env_yaml = os.path.join(local_aider_factory_dir, ".env.yml")
    local_aider_ignore = os.path.join(cwd, ".aiderignore")
    local_aider_conf = os.path.join(local_aider_factory_dir, ".aider.conf.yml")
    local_aider_settings = os.path.join(
        local_aider_factory_dir, ".aider.model.settings.yml"
    )
    local_conventions = os.path.join(local_aider_factory_dir, "CONVENTIONS.md")
    local_tests_dir = os.path.join(local_aider_factory_dir, "tests")

    # DRY framework-to-extension mapping
    framework_map = {
        "Rscript": "R",
        "pytest": "py",
        "cargo": "rs",
        "go test": "go",
        "npm": "js",
    }
    chosen_ext = "py"  # Default fallback
    if os.path.exists(local_aider_factory_dir):
        try:
            for item in os.listdir(local_aider_factory_dir):
                if item.endswith(".yml"):
                    yaml_path = os.path.join(local_aider_factory_dir, item)
                    with open(yaml_path, "r", encoding="utf-8") as f:
                        yaml_content = f.read()
                        for kw, ext in framework_map.items():
                            if kw in yaml_content:
                                chosen_ext = ext
                                break
                    if chosen_ext != "py":
                        break
        except Exception:
            pass

    # Provision language-specific optimized test runner dynamically
    os.makedirs(local_tests_dir, exist_ok=True)
    pkg_tests_dir = os.path.join(pkg_dir, "tests")
    if os.path.exists(pkg_tests_dir):
        src_runner = os.path.join(pkg_tests_dir, f"run_tests.{chosen_ext}")
        dst_runner = os.path.join(local_tests_dir, f"run_tests.{chosen_ext}")
        if os.path.exists(src_runner) and not os.path.exists(dst_runner):
            shutil.copy(src_runner, dst_runner)

    # 1. Create .env.yml inside .aider_factory/ if missing (zero-clutter workspace)
    if not os.path.exists(local_env_yaml):
        print(
            f"📦 First run detected! Initializing default '.env.yml' in {local_aider_factory_dir}..."
        )
        sensible_name = f"{os.path.basename(cwd).replace('_', ' ').replace('-', ' ').title()} Pipeline"
        with open(os.path.join(default_configs_dir, "env.yml"), "r", encoding="utf-8") as f:
            content = f.read()
        
        # Standardized dynamic instantiation
        content = content.replace('name: "My Project"', f'name: "{sensible_name}"')
        content = content.replace('working_directory: "/path/to/project"', f'working_directory: "{cwd}"')
        
        # Quickstart: Auto-discover a target file and context file
        target_file = None
        for ext in [".py", ".R", ".js", ".ts", ".go", ".rs", ".md", ".txt"]:
            for f in os.listdir(cwd):
                if f.endswith(ext) and not f.startswith(".") and os.path.isfile(os.path.join(cwd, f)):
                    target_file = f
                    break
            if target_file:
                break
        
        if not target_file:
            target_file = "scratchpad.py"
            with open(os.path.join(cwd, target_file), "w", encoding="utf-8") as f:
                f.write("# Quickstart scratchpad\n")
                
        context_file = None
        for ext in [".md", ".txt", ".py", ".R"]:
            for f in os.listdir(cwd):
                if f.endswith(ext) and not f.startswith(".") and f != target_file and os.path.isfile(os.path.join(cwd, f)):
                    context_file = f
                    break
            if context_file:
                break

        content = content.replace('target_files: []', f'target_files:\n        - "{target_file}"')
        if context_file:
            content = content.replace('context_files_job: []', f'context_files_job:\n        - "{context_file}"')
            
        # Quickstart: Auto-discover cluster configuration
        try:
            python_dir = os.path.join(pkg_dir, "python")
            if python_dir not in sys.path:
                sys.path.insert(0, python_dir)
            from bootstrap import _discover_cluster_config
            cluster_config = _discover_cluster_config()
            if cluster_config:
                content = content.replace('architect_api_base: "http://192.168.100.2:8080/v1"', f'architect_api_base: "{cluster_config["architect_api_base"]}"')
                content = content.replace('editor_ollama_api: "http://192.168.100.1:8080/v1"', f'editor_ollama_api: "{cluster_config["editor_ollama_api"]}"')
                content = content.replace('rag_agent_api: "http://192.168.100.1:8080/v1"', f'rag_agent_api: "{cluster_config["rag_agent_api"]}"')
                if "architect_agent" in cluster_config:
                    content = content.replace('architect_agent: "gemini/gemini-3.6-flash"', f'architect_agent: "{cluster_config["architect_agent"]}"')
                    content = content.replace('editor_agent: "gemini/gemini-2.5-flash"', f'editor_agent: "{cluster_config["editor_agent"]}"')
                    content = content.replace('editor_agent_test: "gemini/gemini-2.5-flash"', f'editor_agent_test: "{cluster_config["editor_agent"]}"')
                    content = content.replace('editor_agent_test_fallback: "gemini/gemini-2.5-flash"', f'editor_agent_test_fallback: "{cluster_config["architect_agent"]}"')
        except Exception:
            pass
        
        with open(local_env_yaml, "w", encoding="utf-8") as f:
            f.write(content)

    # 2. Create .aiderignore at root if missing
    if not os.path.exists(local_aider_ignore):
        print(f"📦 Initializing default '.aiderignore' in {cwd}...")
        shutil.copy(
            os.path.join(default_configs_dir, "aiderignore"), local_aider_ignore
        )

    # 3. Create .aider.conf.yml inside .aider_factory/ if missing
    if not os.path.exists(local_aider_conf):
        print(f"📦 Initializing default '.aider.conf.yml' in {local_aider_factory_dir}...")
        shutil.copy(
            os.path.join(default_configs_dir, "aider.conf.yml"), local_aider_conf
        )

    # 4. Create .aider.model.settings.yml inside .aider_factory/ if missing
    if not os.path.exists(local_aider_settings):
        shutil.copy(
            os.path.join(default_configs_dir, "aider.model.settings.yml"),
            local_aider_settings,
        )

    # 5. Create CONVENTIONS.md inside .aider_factory/ if missing
    if not os.path.exists(local_conventions):
        src_conventions = os.path.join(pkg_dir, "markdown", "CONVENTIONS.md")
        if os.path.exists(src_conventions):
            shutil.copy(src_conventions, local_conventions)


def ensure_aider_installed():
    """Ensure ~/.local/bin is in PATH and aider is installed globally."""
    local_bin = os.path.expanduser("~/.local/bin")
    current_path = os.environ.get("PATH", "")
    if os.path.exists(local_bin) and local_bin not in current_path.split(os.pathsep):
        os.environ["PATH"] = f"{local_bin}{os.pathsep}{current_path}"
        
    if not shutil.which("aider"):
        print("📦 [aider-factory] 'aider' not found. Auto-installing aider-chat globally via uv...", file=sys.stderr)
        try:
            subprocess.run(["uv", "tool", "install", "aider-chat"], check=False)
        except Exception as e:
            print(f"⚠️ [aider-factory] Could not auto-install aider-chat: {e}", file=sys.stderr)


def _list_sessions(cwd):
    sess_root = os.path.join(cwd, ".aider_factory", "sessions")
    if not os.path.exists(sess_root) or not os.listdir(sess_root):
        print("No active sessions found.")
        return []
    print("Active Sessions:")
    found = []
    for item in sorted(os.listdir(sess_root)):
        sess_dir = os.path.join(sess_root, item)
        if os.path.isdir(sess_dir):
            found.append(item)
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(sess_dir)))
            chat_file = os.path.join(sess_dir, ".aider.chat.history.md")
            size_str = f"{os.path.getsize(chat_file) // 1024} KB" if os.path.exists(chat_file) else "empty"
            yml_file = os.path.join(sess_dir, "session.yml")
            yml_status = "paired" if os.path.exists(yml_file) else "no config"
            print(f"  - {item:<26} (Active: {mtime}, History: {size_str}, Config: {yml_status})")
    return found


def _clear_session(cwd, name):
    import re
    slug = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name.strip())
    sess_dir = os.path.join(cwd, ".aider_factory", "sessions", slug)
    if os.path.exists(sess_dir):
        shutil.rmtree(sess_dir, ignore_errors=True)
        print(f"Session '{slug}' cleared.")
    else:
        print(f"Session '{slug}' not found.")


def _clear_all_sessions(cwd):
    sess_root = os.path.join(cwd, ".aider_factory", "sessions")
    if os.path.exists(sess_root):
        shutil.rmtree(sess_root, ignore_errors=True)
        print("All session archives cleared.")
    else:
        print("No session directory found.")


def main():
    """Global 'aider-factory' CLI entry point."""
    ensure_aider_installed()
    init_user_project()

    cwd = os.getcwd()
    args = sys.argv[1:]

    # Parse session management flags
    if "--list-sessions" in args:
        _list_sessions(cwd)
        sys.exit(0)

    if "--clear-all" in args:
        _clear_all_sessions(cwd)
        sys.exit(0)

    if "--clear-session" in args:
        try:
            idx = args.index("--clear-session")
            name = args[idx + 1]
            _clear_session(cwd, name)
            sys.exit(0)
        except (IndexError, ValueError):
            print("Error: --clear-session requires a session name.", file=sys.stderr)
            sys.exit(1)

    # Extract session name or config file from positional arguments
    session_name = None
    config_file = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--session", "-s") and i + 1 < len(args):
            session_name = args[i + 1]
            i += 2
            continue
        elif arg.startswith("--session="):
            session_name = arg.split("=", 1)[1]
            i += 1
            continue

        if arg.endswith(".yml") or arg.endswith(".yaml") or os.path.isfile(os.path.join(cwd, arg)):
            config_file = arg
        elif not arg.startswith("-"):
            session_name = arg
        i += 1

    if session_name:
        os.environ["AI_FACTORY_SESSION"] = session_name
    if config_file:
        os.environ["AI_FACTORY_CONFIG"] = config_file

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))

    # Set environment variable so internal scripts know where package resources are
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir

    # Execute the workflow runner as __main__
    run_workflow_path = os.path.join(pkg_dir, "python", "run_workflow.py")
    runpy.run_path(run_workflow_path, run_name="__main__")


def oracle_cli():
    """Global 'aider-oracle' CLI entry point."""
    ensure_aider_installed()
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir

    # Execute the oracle agent as __main__
    oracle_path = os.path.join(pkg_dir, "python", "oracle_agent.py")
    runpy.run_path(oracle_path, run_name="__main__")


def validate_cli():
    """Global 'aider-validate' CLI entry point."""
    ensure_aider_installed()
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir

    # Execute the validator as __main__
    validator_path = os.path.join(pkg_dir, "python", "validator.py")
    runpy.run_path(validator_path, run_name="__main__")


def research_cli():
    """Global 'aider-research' CLI entry point."""
    ensure_aider_installed()
    ensure_searxng_service()
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir

    research_path = os.path.join(pkg_dir, "python", "research_agent.py")
    runpy.run_path(research_path, run_name="__main__")


def helper_cli():
    """Global 'aider-helper' CLI entry point."""
    ensure_aider_installed()
    import argparse
    
    epilog_text = """
Environment Variables for Custom Models:
  You can customize the model and endpoint used by aider-helper at any time.

  For local endpoints (e.g., llama.cpp/LM Studio):
    export AIDER_HELPER_MODEL="openai/qwen2.5-coder:latest"
    export AIDER_HELPER_API_BASE="http://192.168.100.1:8080/v1"
    export OPENAI_API_KEY="sk-dummy"

  For other cloud providers (e.g., Anthropic):
    export AIDER_HELPER_MODEL="anthropic/claude-3-5-sonnet-20241022"
    export ANTHROPIC_API_KEY="your-key"

  To revert back to default cloud settings:
    unset AIDER_HELPER_MODEL AIDER_HELPER_API_BASE
"""

    parser = argparse.ArgumentParser(
        description="aider-helper: Your lifetime AI Factory configuration assistant.",
        epilog=epilog_text,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command")
    
    # Bootstrap command
    subparsers.add_parser("bootstrap", help="Bootstrap a new workspace configuration.")
    
    # Query command (default)
    query_parser = subparsers.add_parser(
        "query", 
        help="Query or modify configurations.",
        epilog=epilog_text,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    query_parser.add_argument("instruction", nargs="?", help="The instruction or question for the helper.")
    query_parser.add_argument("--file", "-f", default=None, help="Target configuration YAML file.")
    query_parser.add_argument("--context", "-c", default="", help="Comma-separated extra context files.")
    query_parser.add_argument("--ask", "-a", action="store_true", help="Conversational mode (no file writing).")
    query_parser.add_argument("--terminal", "-t", action="store_true", help="Terminal agent mode (strips YAML config context).")
    query_parser.add_argument("--clear", action="store_true", help="Wipe the active helper session history.")
    query_parser.add_argument("--master", "-m", action="store_true", help="Master mode: loads the skills reference documents into context.")
    query_parser.add_argument("--expert", "-e", action="store_true", help="Expert mode: loads both the skills reference and the full Factory Service Manual into context.")
    query_parser.add_argument("--repo-map", "-r", action="store_true", help="Repository Map mode: loads the static repository map (.aider_factory/static_repo_map.md) into context.")
    
    # Parse args
    args, unknown = parser.parse_known_args()
    
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir
    
    from bootstrap import run_bootstrap, run_query, clear_helper_session
    
    if args.command == "bootstrap":
        run_bootstrap(".")
    else:
        terminal_val = getattr(args, "terminal", False) or ("--terminal" in sys.argv or "-t" in sys.argv)
        clear_val = getattr(args, "clear", False) or ("--clear" in sys.argv)
        master_val = getattr(args, "master", False) or ("--master" in sys.argv or "-m" in sys.argv)
        expert_val = getattr(args, "expert", False) or ("--expert" in sys.argv or "-e" in sys.argv)
        repo_map_val = getattr(args, "repo_map", False) or ("--repo-map" in sys.argv or "-r" in sys.argv)

        if clear_val:
            clear_helper_session(terminal_mode=terminal_val)
            sys.exit(0)
            return

        instruction_parts = []
        if getattr(args, "instruction", None):
            instruction_parts.append(args.instruction)
        if unknown:
            instruction_parts.extend([u for u in unknown if u not in ("--terminal", "-t", "--ask", "-a", "--clear", "--master", "-m", "--expert", "-e", "--repo-map", "-r")])
        instruction = " ".join(instruction_parts)
        
        file_val = getattr(args, "file", None)
        context_val = getattr(args, "context", "")
        ask_val = getattr(args, "ask", False) or ("--ask" in sys.argv or "-a" in sys.argv)
        
        if not instruction:
            parser.print_help()
            sys.exit(0)
            
        run_query(instruction, file_val, context_val, ask_val, terminal_mode=terminal_val, master_mode=master_val, expert_mode=expert_val, repo_map=repo_map_val)


if __name__ == "__main__":
    main()

