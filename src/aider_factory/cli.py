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


def init_user_project():
    """Onboarding: Auto-creates default config files in the CWD if they are missing."""
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

    # 1. Create .env.yml inside .aider_factory/ if missing (zero-clutter workspace)
    if not os.path.exists(local_env_yaml):
        print(
            f"📦 First run detected! Initializing default '.env.yml' in {local_aider_factory_dir}..."
        )
        import getpass
        username = getpass.getuser()
        with open(os.path.join(default_configs_dir, "env.yml"), "r", encoding="utf-8") as f:
            content = f.read()
        
        # Replace hardcoded home directory and username dynamically
        content = content.replace("/home/bryanr/wf/BaseFeatures", cwd)
        content = content.replace("bryanr", username)
        
        with open(local_env_yaml, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        # If the file exists but was initialized with the default template's hardcoded path, patch it
        import getpass
        username = getpass.getuser()
        if username != "bryanr":
            try:
                with open(local_env_yaml, "r", encoding="utf-8") as f:
                    content = f.read()
                if "/home/bryanr/wf/BaseFeatures" in content:
                    print(f"📦 Patching hardcoded template paths in {local_env_yaml}...")
                    content = content.replace("/home/bryanr/wf/BaseFeatures", cwd)
                    content = content.replace("bryanr", username)
                    with open(local_env_yaml, "w", encoding="utf-8") as f:
                        f.write(content)
            except Exception:
                pass

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


def main():
    """Global 'aider-factory' CLI entry point."""
    init_user_project()

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))

    # Set environment variable so internal scripts know where package resources are
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir

    # Execute the workflow runner as __main__
    run_workflow_path = os.path.join(pkg_dir, "python", "run_workflow.py")
    runpy.run_path(run_workflow_path, run_name="__main__")


def oracle_cli():
    """Global 'aider-oracle' CLI entry point."""
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir

    # Execute the oracle agent as __main__
    oracle_path = os.path.join(pkg_dir, "python", "oracle_agent.py")
    runpy.run_path(oracle_path, run_name="__main__")


def validate_cli():
    """Global 'aider-validate' CLI entry point."""
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir

    # Execute the validator as __main__
    validator_path = os.path.join(pkg_dir, "python", "validator.py")
    runpy.run_path(validator_path, run_name="__main__")


def research_cli():
    """Global 'aider-research' CLI entry point."""
    ensure_searxng_service()
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir

    research_path = os.path.join(pkg_dir, "python", "research_agent.py")
    runpy.run_path(research_path, run_name="__main__")

