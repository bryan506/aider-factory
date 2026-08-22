import json
import os
import runpy
import shutil
import subprocess
import sys
import time
import urllib.request


pkg_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.join(pkg_dir, "python")
if python_dir not in sys.path:
    sys.path.insert(0, python_dir)

try:
    from aider_factory.python.env_utils import load_env_files
except ImportError:
    from env_utils import load_env_files

_load_env_files = load_env_files

import re

BASELINE_AIDERIGNORE = """# Ignore RAG database, logs, and caches
.aider_factory/

# Ignore temp folders
temp/
tmp/

# Ignore package-level build, documentation, and installation folders
docs/
doc/
man/
inst/
site/
_site/

# Ignore binaries, media, and heavy data files
*.pdf
*.png
*.jpg
*.jpeg
*.gif
*.svg
*.ico
*.mp4
*.wasm
*.woff
*.woff2
*.csv
*.tsv
*.parquet
*.feather
*.h5
*.bin
*.exe
*.zip
*.tar.gz
*.lock
package-lock.json
Cargo.lock
*.log
*.map
"""

TEST_DIR_NAMES = frozenset({
    "test",
    "tests",
    "testing",
    "testthat",
    "__tests__",
    "spec",
    "specs",
    "e2e",
    "end-to-end",
    "fixtures",
    "testdata",
    "test_fixtures",
    "benchmarks",
    "benches",
})

# 1. Delimited test patterns (case-insensitive) - requires delimiter boundary
TEST_DELIMITED_RE = re.compile(
    r"(^|/)((tests?|specs?|unit_?tests?)[_\-\.][^/]+|.+[_\-\.](tests?|specs?|unit_?tests?)\.[^/]+)$",
    re.IGNORECASE,
)

# 2. Exact test harness & fixture files (case-insensitive)
TEST_EXACT_RE = re.compile(
    r"(^|/)(conftest\.py|tests?\.py|tests?\.rs|test_helper\.rb|setupTests\.[^/]+)$",
    re.IGNORECASE,
)

# 3. CamelCase test classes (case-sensitive to avoid matching contest.java, latest.ts, etc.)
TEST_CAMEL_RE = re.compile(
    r"(^|/)[a-zA-Z0-9_]*(Test|Tests|TestCase|Spec)\.[a-zA-Z0-9]+$"
)


def _is_test_path(rel_path: str) -> bool:
    """Classify whether a normalized relative path is a test file or inside a test directory."""
    clean_path = rel_path.replace("\\", "/").strip("/")
    if not clean_path:
        return False
    parts = clean_path.split("/")
    # 1. Directory component check
    for p in parts[:-1]:
        if p.lower() in TEST_DIR_NAMES:
            return True
    # 2. Delimited pattern check (test_*.py, *.test.tsx, *-test.R)
    if TEST_DELIMITED_RE.search(clean_path):
        return True
    # 3. Exact filename check (conftest.py, tests.rs)
    if TEST_EXACT_RE.search(clean_path):
        return True
    # 4. CamelCase class check (UserTest.java, AuthSpec.scala)
    if TEST_CAMEL_RE.search(clean_path):
        return True
    return False


def _read_user_aiderignore(cwd: str) -> list[str]:
    """Read active ignore rules from workspace .aiderignore, stripping comments and blank lines."""
    ignore_file = os.path.join(cwd, ".aiderignore")
    rules: list[str] = []
    if os.path.isfile(ignore_file):
        try:
            with open(ignore_file, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#"):
                        rules.append(s)
        except Exception:
            pass
    if not rules:
        for line in BASELINE_AIDERIGNORE.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                rules.append(s)
    # Always guarantee AI Factory internal directory is ignored
    if ".aider_factory/" not in rules:
        rules.insert(0, ".aider_factory/")
    return list(dict.fromkeys(rules))


def _scan_repo_files(cwd: str) -> list[str]:
    """Discover all repository files using git ls-files with an os.walk fallback."""
    files: list[str] = []
    # Fast path: git ls-files
    try:
        res = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.splitlines():
                f = line.strip().replace("\\", "/").lstrip("./")
                if f and not f.startswith(".git/") and not f.startswith(".aider_factory/"):
                    files.append(f)
            if files:
                return sorted(list(dict.fromkeys(files)))
    except Exception:
        pass

    # Fallback path: os.walk
    ignored_dirs = {
        ".git", ".aider_factory", "node_modules", "dist", "build",
        "target", ".venv", "venv", "__pycache__", ".pytest_cache",
        "temp", "tmp", "docs", "doc", "man", "inst",
    }
    for root, dirs, filenames in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
        for fn in filenames:
            full_path = os.path.join(root, fn)
            rel = os.path.relpath(full_path, cwd).replace("\\", "/").lstrip("./")
            if rel and not rel.startswith(".git/") and not rel.startswith(".aider_factory/"):
                files.append(rel)
    return sorted(list(dict.fromkeys(files)))


def _ensure_baseline_aiderignore(cwd):
    """Ensure the root .aiderignore exists and matches the baseline standard if missing."""
    local_aider_ignore = os.path.join(cwd, ".aiderignore")
    if not os.path.exists(local_aider_ignore):
        with open(local_aider_ignore, "w", encoding="utf-8") as f:
            f.write(BASELINE_AIDERIGNORE)


def _build_repomap_ignore_content(cwd, mode="source", all_files=None):
    """Construct deterministic ignore content for source mapping vs. test mapping,
    inheriting all user-defined base rules from .aiderignore."""
    user_base_rules = _read_user_aiderignore(cwd)

    if all_files is None:
        all_files = _scan_repo_files(cwd)

    if mode == "source":
        # Broad patterns to catch test directories + dynamic test files
        universal_test_rules = [
            "tests/",
            "test/",
            "testing/",
            "testthat/",
            "__tests__/",
            "spec/",
            "specs/",
            "e2e/",
            "end-to-end/",
            "fixtures/",
            "testdata/",
            "test_fixtures/",
            "benchmarks/",
            "benches/",
            "**/tests/**",
            "**/test/**",
            "**/testing/**",
            "**/testthat/**",
            "**/__tests__/**",
            "**/spec/**",
            "**/specs/**",
            "**/e2e/**",
            "**/end-to-end/**",
            "**/fixtures/**",
            "**/testdata/**",
            "**/benchmarks/**",
            "**/benches/**",
            "test_*.*",
            "tests_*.*",
            "*_test.*",
            "*_tests.*",
            "test-*.*",
            "tests-*.*",
            "*-test.*",
            "*-tests.*",
            "*.test.*",
            "*.spec.*",
            "*Test.*",
            "*Tests.*",
            "*TestCase.*",
            "*Spec.*",
            "conftest.py",
        ]
        dynamic_test_files = [f for f in all_files if _is_test_path(f)]
        combined = user_base_rules + universal_test_rules + dynamic_test_files
        return "\n".join(dict.fromkeys(combined)) + "\n"
    elif mode == "tests":
        # Exclude all non-test source files so only test code remains
        dynamic_non_test_files = [f for f in all_files if not _is_test_path(f)]
        combined = user_base_rules + dynamic_non_test_files
        return "\n".join(dict.fromkeys(combined)) + "\n"
    return "\n".join(user_base_rules) + "\n"


def _generate_repo_maps(cwd, map_tokens=4096, target="all", is_global=False):
    """Generate static repo maps (source and/or tests) using ephemeral ignore files."""
    ensure_aider_installed()
    projects = _get_registered_projects() if is_global else [os.path.abspath(cwd)]
    if not projects:
        projects = [os.path.abspath(cwd)]

    for proj in projects:
        af_dir = os.path.join(proj, ".aider_factory")
        os.makedirs(af_dir, exist_ok=True)
        p_name = os.path.basename(proj)
        if is_global:
            print(f"\nWorkspace: {p_name} ({proj})")

        all_files = _scan_repo_files(proj)

        targets = []
        if target in ("source", "all"):
            targets.append(("source", os.path.join(af_dir, "static_repo_map.md")))
        if target in ("tests", "all"):
            targets.append(("tests", os.path.join(af_dir, "static_repo_map_tests.md")))

        ephemeral_files = []
        try:
            for mode, out_path in targets:
                e_ignore = os.path.join(af_dir, f".aiderignore_{mode}")
                ephemeral_files.append(e_ignore)
                with open(e_ignore, "w", encoding="utf-8") as f:
                    f.write(_build_repomap_ignore_content(proj, mode=mode, all_files=all_files))

                cmd = [
                    "aider",
                    "--map-tokens", str(map_tokens),
                    "--show-repo-map",
                    "--no-show-model-warnings",
                    "--aiderignore", e_ignore,
                ]
                res = subprocess.run(cmd, cwd=proj, capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(res.stdout)
                    line_count = len(res.stdout.splitlines())
                    size_kb = max(1, os.path.getsize(out_path) // 1024)
                    print(f"  Generated {os.path.basename(out_path)} ({line_count} lines, {size_kb} KB)")
                else:
                    err = res.stderr.strip() or "No output generated"
                    print(f"  Warning generating {os.path.basename(out_path)}: {err}", file=sys.stderr)
        finally:
            for ef in ephemeral_files:
                if os.path.exists(ef):
                    try:
                        os.remove(ef)
                    except OSError:
                        pass
            _ensure_baseline_aiderignore(proj)


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
        "apply": f'#!/bin/bash\nexec "{aider_py}" "{os.path.join(python_dir, "apply_agent.py")}" "$@"\n',
    }

    for script, content in wrappers.items():
        target_path = os.path.join(bash_dir, script)
        # Always overwrite or update wrappers to ensure they point to the correct active package path
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(target_path, 0o755)


def _get_registry_path():
    """Return the global workspace registry JSON path (~/.config/aider_factory/registry.json)."""
    config_dir = os.path.expanduser("~/.config/aider_factory")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "registry.json")


def _register_project(cwd):
    """Auto-register the project root directory in the global registry."""
    try:
        reg_file = _get_registry_path()
        abs_cwd = os.path.abspath(cwd)
        projects = []
        if os.path.exists(reg_file):
            try:
                with open(reg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    projects = data.get("projects", []) if isinstance(data, dict) else []
            except Exception:
                projects = []
        if abs_cwd not in projects:
            projects.append(abs_cwd)
            with open(reg_file, "w", encoding="utf-8") as f:
                json.dump({"projects": projects}, f, indent=2)
    except Exception:
        pass


def _get_registered_projects():
    """Retrieve all valid, registered project directories, auto-pruning non-existent paths."""
    reg_file = _get_registry_path()
    if not os.path.exists(reg_file):
        return []
    try:
        with open(reg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw_list = data.get("projects", []) if isinstance(data, dict) else []
        valid = [p for p in raw_list if os.path.isdir(p) and os.path.isdir(os.path.join(p, ".aider_factory"))]
        if len(valid) != len(raw_list):
            with open(reg_file, "w", encoding="utf-8") as f:
                json.dump({"projects": valid}, f, indent=2)
        return sorted(valid)
    except Exception:
        return []


def init_user_project(cwd=None):
    """Onboarding: Auto-creates default config files in the CWD if they are missing."""
    if cwd is None:
        cwd = os.getcwd()
    _register_project(cwd)
    _load_env_files(cwd)
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
        _ensure_baseline_aiderignore(cwd)

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


def _list_sessions(cwd, is_global=False):
    projects = _get_registered_projects() if is_global else [os.path.abspath(cwd)]
    if not projects:
        projects = [os.path.abspath(cwd)]

    total_found = []
    for proj in projects:
        sess_root = os.path.join(proj, ".aider_factory", "sessions")
        p_name = os.path.basename(proj)
        if is_global:
            print(f"\n📂 Project: {p_name} ({proj})")

        if not os.path.exists(sess_root) or not os.listdir(sess_root):
            if not is_global:
                print("No active sessions found.")
            else:
                print("  (No active sessions)")
            continue

        if not is_global:
            print("Active Sessions:")

        for item in sorted(os.listdir(sess_root)):
            sess_dir = os.path.join(sess_root, item)
            if os.path.isdir(sess_dir):
                total_found.append(f"{p_name}/{item}" if is_global else item)
                mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(sess_dir)))
                chat_file = os.path.join(sess_dir, ".aider.chat.history.md")
                size_str = f"{os.path.getsize(chat_file) // 1024} KB" if os.path.exists(chat_file) else "empty"
                yml_file = os.path.join(sess_dir, "session.yml")
                yml_status = "paired" if os.path.exists(yml_file) else "no config"
                print(f"  - {item:<26} (Active: {mtime}, History: {size_str}, Config: {yml_status})")
    return total_found


def _clear_session(cwd, name, is_global=False):
    import re
    target_project = None
    target_session = name.strip()

    if "/" in target_session:
        parts = target_session.split("/", 1)
        target_project, target_session = parts[0], parts[1]

    slug = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', target_session)
    projects = _get_registered_projects() if is_global else [os.path.abspath(cwd)]
    if not projects:
        projects = [os.path.abspath(cwd)]

    cleared = 0
    for proj in projects:
        p_name = os.path.basename(proj)
        if target_project and p_name != target_project:
            continue
        sess_dir = os.path.join(proj, ".aider_factory", "sessions", slug)
        if os.path.exists(sess_dir):
            shutil.rmtree(sess_dir, ignore_errors=True)
            print(f"Session '{slug}' cleared in project '{p_name}'.")
            cleared += 1

    if cleared == 0:
        print(f"Session '{slug}' not found.")


def _clear_all_sessions(cwd, is_global=False):
    projects = _get_registered_projects() if is_global else [os.path.abspath(cwd)]
    if not projects:
        projects = [os.path.abspath(cwd)]

    for proj in projects:
        p_name = os.path.basename(proj)
        sess_root = os.path.join(proj, ".aider_factory", "sessions")
        if os.path.exists(sess_root):
            shutil.rmtree(sess_root, ignore_errors=True)
            print(f"All session archives cleared in '{p_name}'.")
        elif not is_global:
            print("No session directory found.")


def _get_cluster_endpoints(cwd):
    """Discover active cluster endpoints from environment and .env.yml."""
    endpoints = set()
    for env_k in ["LITELLM_BASE_URL", "ARCHITECT_API_BASE", "ORACLE_AGENT_API_BASE", "RANKING_API_BASE"]:
        val = os.environ.get(env_k)
        if val and val.startswith("http"):
            endpoints.add(val.rstrip("/"))

    for yaml_path in [
        os.path.join(cwd, ".aider_factory", ".env.yml"),
        os.path.join(cwd, ".env.yml"),
    ]:
        if os.path.exists(yaml_path):
            try:
                import yaml
                with open(yaml_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                ep_cfg = cfg.get("endpoints", {}) or {}
                for v in ep_cfg.values():
                    if isinstance(v, str) and v.startswith("http"):
                        endpoints.add(v.rstrip("/"))
            except Exception:
                pass
    return sorted(list(endpoints))


def _probe_cluster_slots(base_url, timeout=1.0):
    """Safely query llama-server or cluster /slots endpoint."""
    clean_base = base_url[:-3] if base_url.endswith("/v1") else base_url
    slots_url = f"{clean_base}/slots"
    try:
        req = urllib.request.Request(
            slots_url,
            headers={"User-Agent": "AI-Factory/1.0", "Authorization": "Bearer sk-dummy"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list):
                    active = sum(1 for s in data if isinstance(s, dict) and (s.get("is_processing") or s.get("state") == 1))
                    return len(data), active, slots_url
    except Exception:
        pass
    return None, None, None


def _release_cluster_slots(base_url, timeout=2.0):
    """Send release request to llama-server /slots to free cached context and GPU VRAM."""
    clean_base = base_url[:-3] if base_url.endswith("/v1") else base_url
    released = 0
    try:
        req = urllib.request.Request(
            f"{clean_base}/slots",
            headers={"User-Agent": "AI-Factory/1.0", "Authorization": "Bearer sk-dummy"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list):
                    for slot in data:
                        if isinstance(slot, dict) and "id" in slot:
                            slot_id = slot["id"]
                            rel_url = f"{clean_base}/slots/{slot_id}?action=release"
                            try:
                                post_req = urllib.request.Request(
                                    rel_url,
                                    data=b"{}",
                                    headers={"Content-Type": "application/json", "Authorization": "Bearer sk-dummy"},
                                    method="POST",
                                )
                                with urllib.request.urlopen(post_req, timeout=timeout) as r:
                                    if r.status == 200:
                                        released += 1
                            except Exception:
                                pass
    except Exception:
        pass
    return released


def _get_side_session_artifacts(cwd):
    """Enumerate all side-agent JSON and Markdown session files."""
    af_dir = os.path.join(cwd, ".aider_factory")
    candidates = [
        ("Helper Config Session", os.path.join(af_dir, ".helper_session.json")),
        ("Helper Terminal Session", os.path.join(af_dir, ".helper_terminal_session.json")),
        ("Oracle Session", os.path.join(af_dir, ".oracle_session.json")),
        ("Oracle Cost Ledger", os.path.join(af_dir, ".oracle_session.json.costs.json")),
        ("Oracle Debate Session", os.path.join(af_dir, ".oracle_debate_session.json")),
        ("Debate Aider History", os.path.join(af_dir, ".debate_aider_history.md")),
    ]
    sess_root = os.path.join(af_dir, "sessions")
    if os.path.isdir(sess_root):
        for s in sorted(os.listdir(sess_root)):
            s_dir = os.path.join(sess_root, s)
            if os.path.isdir(s_dir):
                candidates.append((f"Session '{s}' Oracle", os.path.join(s_dir, ".oracle_session.json")))
                candidates.append((f"Session '{s}' Debate", os.path.join(s_dir, ".oracle_debate_session.json")))

    found = []
    for label, p in candidates:
        if os.path.exists(p):
            turns = None
            size_kb = max(1, os.path.getsize(p) // 1024) if os.path.getsize(p) > 0 else 0
            if p.endswith(".json") and not p.endswith(".costs.json"):
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        content = json.load(fh)
                        if isinstance(content, list):
                            turns = len(content)
                        elif isinstance(content, dict) and "messages" in content:
                            turns = len(content["messages"])
                except Exception:
                    pass
            found.append({"label": label, "path": p, "size_kb": size_kb, "turns": turns, "mtime": os.path.getmtime(p)})
    return found


def _clear_side_session_by_name(cwd, target_name, is_global=False):
    """Surgically delete a specific side-agent session by alias or session name."""
    projects = _get_registered_projects() if is_global else [os.path.abspath(cwd)]
    if not projects:
        projects = [os.path.abspath(cwd)]

    alias = target_name.strip().lower()
    total_deleted = 0

    for proj in projects:
        af_dir = os.path.join(proj, ".aider_factory")
        targets_to_delete = []

        if alias in ("helper", "config"):
            targets_to_delete.append(os.path.join(af_dir, ".helper_session.json"))
        elif alias in ("terminal", "term"):
            targets_to_delete.append(os.path.join(af_dir, ".helper_terminal_session.json"))
        elif alias == "oracle":
            targets_to_delete.extend([
                os.path.join(af_dir, ".oracle_session.json"),
                os.path.join(af_dir, ".oracle_session.json.costs.json"),
            ])
        elif alias == "debate":
            targets_to_delete.extend([
                os.path.join(af_dir, ".oracle_debate_session.json"),
                os.path.join(af_dir, ".debate_aider_history.md"),
            ])
        else:
            # Check for session-scoped sidecars: sessions/<name>/.oracle_*
            sess_dir = os.path.join(af_dir, "sessions", target_name.strip())
            targets_to_delete.extend([
                os.path.join(sess_dir, ".oracle_session.json"),
                os.path.join(sess_dir, ".oracle_session.json.costs.json"),
                os.path.join(sess_dir, ".oracle_debate_session.json"),
            ])

        for path in targets_to_delete:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    total_deleted += 1
                except OSError:
                    pass

    p_info = " across registered projects" if is_global else ""
    if total_deleted > 0:
        print(f"🧹 Successfully cleared {total_deleted} side-agent session file(s) for '{target_name}'{p_info}.")
    else:
        print(f"No side-agent session artifacts found matching '{target_name}'{p_info}.")


def _status(cwd, is_global=False):
    """Print comprehensive diagnostic status of sessions, side agents, and cluster resources."""
    projects = _get_registered_projects() if is_global else [os.path.abspath(cwd)]
    if not projects:
        projects = [os.path.abspath(cwd)]

    title_suffix = " (Global - All Registered Workspaces)" if is_global else ""
    print("==================================================")
    print(f"AI Factory Session & Cluster Status{title_suffix}")
    print("==================================================")

    all_endpoints = set()

    for proj in projects:
        p_name = os.path.basename(proj)
        if is_global:
            print(f"\n📂 Workspace: {p_name} ({proj})")

        # 1. Main Aider Sessions
        print("\n[1] Main Aider Sessions:")
        sess_root = os.path.join(proj, ".aider_factory", "sessions")
        sessions = []
        if os.path.isdir(sess_root):
            for item in sorted(os.listdir(sess_root)):
                s_dir = os.path.join(sess_root, item)
                if os.path.isdir(s_dir):
                    sessions.append(item)
                    mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(s_dir)))
                    chat_file = os.path.join(s_dir, ".aider.chat.history.md")
                    size_str = f"{os.path.getsize(chat_file) // 1024} KB" if os.path.exists(chat_file) else "empty"
                    yml_file = os.path.join(s_dir, "session.yml")
                    yml_status = "paired" if os.path.exists(yml_file) else "no config"
                    print(f"  - {item:<26} (Modified: {mtime}, History: {size_str}, Config: {yml_status})")
        if not sessions:
            print("  (None active)")

        # 2. Side-Agent Sessions & KV Caches
        print("\n[2] Side-Agent Sessions & KV Caches:")
        side_artifacts = _get_side_session_artifacts(proj)
        if side_artifacts:
            for art in side_artifacts:
                mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(art["mtime"]))
                turn_str = f", {art['turns']} turn(s)" if art["turns"] is not None else ""
                print(f"  - {art['label']:<26} ({art['size_kb']} KB{turn_str}, Modified: {mtime})")
        else:
            print("  (No active side-agent sessions)")

        for ep in _get_cluster_endpoints(proj):
            all_endpoints.add(ep)

    # 3. Cluster Inference Endpoints & Slots
    print("\n[3] Remote Inference Cluster & KV Slots:")
    if all_endpoints:
        for ep in sorted(list(all_endpoints)):
            total_slots, active_slots, slots_url = _probe_cluster_slots(ep)
            if total_slots is not None:
                print(f"  - {ep:<30} ONLINE ({active_slots}/{total_slots} slots active via {slots_url})")
            else:
                try:
                    req = urllib.request.Request(f"{ep}/models", headers={"Authorization": "Bearer sk-dummy"}, method="GET")
                    with urllib.request.urlopen(req, timeout=1.0) as r:
                        status = "ONLINE" if r.status == 200 else f"HTTP {r.status}"
                except Exception:
                    status = "OFFLINE / Unreachable"
                print(f"  - {ep:<30} {status} (slots API not supported)")
    else:
        print("  (No remote endpoints configured)")
    print()


def _clear_side_sessions(cwd, is_global=False):
    """Surgically clear side-agent session files and release cluster slots."""
    projects = _get_registered_projects() if is_global else [os.path.abspath(cwd)]
    if not projects:
        projects = [os.path.abspath(cwd)]

    deleted_total = 0
    all_endpoints = set()

    for proj in projects:
        artifacts = _get_side_session_artifacts(proj)
        for art in artifacts:
            try:
                os.remove(art["path"])
                deleted_total += 1
            except OSError:
                pass
        for ep in _get_cluster_endpoints(proj):
            all_endpoints.add(ep)

    scope_str = " across all registered workspaces" if is_global else ""
    print(f"🧹 Cleared {deleted_total} side-agent session file(s){scope_str}.")

    released_total = 0
    for ep in all_endpoints:
        rel = _release_cluster_slots(ep)
        if rel > 0:
            print(f"  - Released {rel} slot(s) on {ep}")
            released_total += rel
    if released_total > 0:
        print(f"✅ Released {released_total} remote cluster inference slot(s).")


def main():
    """Global 'aider-factory' CLI entry point."""
    ensure_aider_installed()
    init_user_project()

    cwd = os.getcwd()
    args = sys.argv[1:]

    is_global = "--global" in args or "-g" in args
    _register_project(cwd)

    # Parse repo map options and flags
    map_tokens = 4096
    if "--map-tokens" in args:
        try:
            idx = args.index("--map-tokens")
            map_tokens = int(args[idx + 1])
        except (IndexError, ValueError):
            pass
    else:
        for arg in args:
            if arg.startswith("--map-tokens="):
                try:
                    map_tokens = int(arg.split("=", 1)[1])
                except ValueError:
                    pass

    if "--repo-map" in args:
        _generate_repo_maps(cwd, map_tokens=map_tokens, target="source", is_global=is_global)
        sys.exit(0)

    if "--repo-map-tests" in args:
        _generate_repo_maps(cwd, map_tokens=map_tokens, target="tests", is_global=is_global)
        sys.exit(0)

    if "--repo-map-all" in args:
        _generate_repo_maps(cwd, map_tokens=map_tokens, target="all", is_global=is_global)
        sys.exit(0)

    # Parse session management flags
    if "--status" in args:
        _status(cwd, is_global=is_global)
        sys.exit(0)

    if "--clear-side-session" in args:
        try:
            idx = args.index("--clear-side-session")
            target = args[idx + 1]
            _clear_side_session_by_name(cwd, target, is_global=is_global)
            sys.exit(0)
        except (IndexError, ValueError):
            print("Error: --clear-side-session requires a target name (e.g. helper, terminal, oracle, debate, <session_name>).", file=sys.stderr)
            sys.exit(1)

    if "--clear-side-sessions" in args:
        _clear_side_sessions(cwd, is_global=is_global)
        sys.exit(0)

    if "--list-sessions" in args:
        _list_sessions(cwd, is_global=is_global)
        sys.exit(0)

    if "--clear-all" in args:
        _clear_all_sessions(cwd, is_global=is_global)
        sys.exit(0)

    if "--clear-session" in args:
        try:
            idx = args.index("--clear-session")
            name = args[idx + 1]
            _clear_session(cwd, name, is_global=is_global)
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
    _load_env_files()
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


def apply_cli():
    """Global 'aider-apply' CLI entry point."""
    ensure_aider_installed()
    _load_env_files()
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(pkg_dir, "python"))
    os.environ["AI_FACTORY_PKG_DIR"] = pkg_dir

    apply_path = os.path.join(pkg_dir, "python", "apply_agent.py")
    runpy.run_path(apply_path, run_name="__main__")


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

