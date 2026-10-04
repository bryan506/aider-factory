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


def _expand_file_list(file_patterns, base_dir):
    """Expand glob patterns into a deduplicated, alphabetically sorted list of relative paths.
    Literal paths with no glob magic are preserved verbatim if they exist.
    Empty or None inputs return an empty list."""
    if not file_patterns:
        return []

    if isinstance(file_patterns, str):
        file_patterns = [file_patterns]

    expanded = []
    for pat in file_patterns:
        if glob.has_magic(pat):
            abs_pat = pat if os.path.isabs(pat) else os.path.join(str(base_dir), pat)
            abs_pat = os.path.normpath(abs_pat)
            for match in sorted(glob.glob(abs_pat)):
                rel_path = os.path.relpath(match, str(base_dir)).replace("\\", "/")
                if rel_path not in expanded:
                    expanded.append(rel_path)
        else:
            clean_pat = pat.replace("\\", "/")
            if clean_pat not in expanded:
                expanded.append(clean_pat)

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
    default_db: str = "",
    project_directory: str = None,
) -> tuple[str, str]:
    """Resolve specialized vector collection and LanceDB dir for Job 1, 2, or 3."""
    chosen = default_collection
    if pre_edit_cfg and "job_debate_collection" in pre_edit_cfg:
        raw = pre_edit_cfg.get("job_debate_collection")
        if isinstance(raw, (list, tuple)):
            if 0 <= (job_num - 1) < len(raw):
                chosen = str(raw[job_num - 1]).strip() if raw[job_num - 1] is not None else default_collection
            elif raw and raw[0] is not None:
                chosen = str(raw[0]).strip()
        elif isinstance(raw, str):
            chosen = raw.strip()

    raw_db = pre_edit_cfg.get("job_debate_db") if pre_edit_cfg else None
    chosen_db = None
    if isinstance(raw_db, (list, tuple)):
        if 0 <= (job_num - 1) < len(raw_db):
            chosen_db = str(raw_db[job_num - 1]).strip() if raw_db[job_num - 1] is not None else ""
        elif raw_db and raw_db[0] is not None:
            chosen_db = str(raw_db[0]).strip()
    elif isinstance(raw_db, str):
        chosen_db = raw_db.strip()

    if chosen_db:
        base_dir = str(project_directory or os.getcwd())
        db_dir = (
            chosen_db if os.path.isabs(chosen_db) else os.path.join(base_dir, chosen_db)
        ).replace("\\", "/")
    elif default_db:
        db_dir = default_db
    elif chosen and chosen != "*" and not os.path.isabs(chosen):
        db_dir = os.path.join(rag_context_root, chosen, "lancedb").replace("\\", "/")
    elif chosen == "":
        db_dir = ""
    else:
        db_dir = (
            os.path.join(rag_context_root, default_collection, "lancedb").replace("\\", "/")
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
            lambda _: injection + "\n",
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
    """Resolves a template path, prioritizing local workspace paths (.aider_factory/ and project root)
    before falling back to package bundled resources."""
    if not path_val:
        return None

    if os.path.isabs(path_val):
        return path_val

    base_proj = str(project_directory or os.getcwd())
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pkg_dir = os.path.abspath(os.path.join(script_dir, ".."))

    # Strip `.aider_factory/` or `src/aider_factory/` prefixes
    rel_stripped = path_val
    for prefix in (
        ".aider_factory/",
        ".aider_factory\\",
        "src/aider_factory/",
        "src\\aider_factory\\",
    ):
        if rel_stripped.startswith(prefix):
            rel_stripped = rel_stripped[len(prefix) :]
            break

    flat_filename = os.path.basename(path_val)

    # Primary Workspace Candidates (Checked first in order of specificity)
    workspace_candidates = [
        os.path.join(base_proj, path_val),
        os.path.join(base_proj, ".aider_factory", rel_stripped),
        os.path.join(base_proj, ".aider_factory", "markdown", rel_stripped),
        os.path.join(base_proj, ".aider_factory", flat_filename),
        os.path.join(base_proj, ".aider_factory", "markdown", flat_filename),
    ]

    for cand in workspace_candidates:
        if os.path.isfile(cand):
            return cand.replace("\\", "/")

    # Package Fallback Candidates (Checked only if workspace has no matching file)
    pkg_candidates = [
        os.path.join(pkg_dir, rel_stripped),
        os.path.join(pkg_dir, "markdown", rel_stripped),
        os.path.join(pkg_dir, flat_filename),
        os.path.join(pkg_dir, "markdown", flat_filename),
    ]

    for cand in pkg_candidates:
        if os.path.isfile(cand):
            return cand.replace("\\", "/")

    return os.path.join(base_proj, path_val).replace("\\", "/")


def _extract_files_from_plan(plan_path: str, project_directory: str) -> dict[str, list[str]]:
    """Deterministically extracts 5-field files configuration from a plan markdown file."""
    result = {
        "target_files": [],
        "extra_editable_files": [],
        "test_files": [],
        "context_files_job": [],
        "context_files_test": [],
    }
    if not plan_path or not os.path.isfile(plan_path):
        return result

    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return result

    # 1. Primary: YAML block inside plan (scoped to Scope Analysis if present)
    scope_match = re.search(r"(?i)#{2,3}\s*Scope Analysis.*?(?=\n#{2,3}\s|\Z)", content, re.DOTALL)
    search_space = scope_match.group(0) if scope_match else content

    yaml_found = False
    yaml_blocks = re.findall(r"```ya?ml[^\n]*\n(.*?)```", search_space, re.DOTALL | re.IGNORECASE)
    for block in yaml_blocks:
        if "files:" in block:
            try:
                parsed = yaml.safe_load(block)
                if isinstance(parsed, dict) and "files" in parsed and isinstance(parsed["files"], dict):
                    f_block = parsed["files"]
                    if not any(f_block.get(k) for k in result.keys()):
                        continue
                    for k in result.keys():
                        vals = f_block.get(k, []) or []
                        if isinstance(vals, str):
                            vals = [vals]
                        result[k] = [str(v).strip() for v in vals if v and isinstance(v, (str, int, float))]
                    yaml_found = True
                    break
            except Exception:
                continue

    # 2. Fallback: Markdown section headers ONLY if no YAML block was parsed
    if not yaml_found:
        def _parse_section(pattern: str) -> list[str]:
            m = re.search(
                rf"(?i)[ \t]*(?:###|##)\s*{pattern}(?:\s*:)?\s*\r?\n(.*?)(?=\r?\n[ \t]*(?:###|##|#\s|---)|\Z)",
                content,
                re.DOTALL,
            )
            if not m:
                return []
            found = []
            for line in m.group(1).splitlines():
                line = line.strip()
                item_match = re.search(r"^(?:[-*]|\d+\.)\s*(?:\[[ xX]\]\s*)?(?:[`'\"]([^`'\"\n\r#]+)[`'\"]|([^\s#`'\"]+))", line)
                if item_match:
                    raw_p = (item_match.group(1) or item_match.group(2) or "").strip()
                    p = re.sub(r"[:—–-]+$", "", raw_p).strip()
                    if p and not p.startswith("<") and not p.startswith("path/to/") and p not in ("...", "None", "null"):
                        found.append(p)
            return found

        result["target_files"] = _parse_section(r"Target\s+Files?")
        result["extra_editable_files"] = _parse_section(r"Extra\s+Editable\s+Files?")
        result["test_files"] = _parse_section(r"Test\s+Files?")
        result["context_files_job"] = _parse_section(r"(?:Context|Readonly)\s+Files?")
        result["context_files_test"] = _parse_section(r"(?:Context\s+Files?\s+Test|Test\s+Context\s+Files?)")

    # Default context_files_test to context_files_job if omitted or empty
    if not result["context_files_test"] and result["context_files_job"]:
        result["context_files_test"] = list(result["context_files_job"])

    # 3. Path sanitization, test separation, and physical disk verification
    def _canon_rel(p: str) -> str:
        clean = os.path.normpath(p).replace("\\", "/")
        if os.path.isabs(clean):
            try:
                return os.path.relpath(clean, project_directory).replace("\\", "/")
            except ValueError:
                return clean
        return clean

    verified: dict[str, list[str]] = {k: [] for k in result.keys()}

    def _add_entry(category: str, raw_path: str):
        if not raw_path or raw_path.startswith(("path/to/", "<")) or raw_path in ("...", "None", "null"):
            return
        abs_p = raw_path if os.path.isabs(raw_path) else os.path.join(project_directory, raw_path)
        if glob.has_magic(raw_path):
            matches = sorted(glob.glob(abs_p))
            if not matches:
                print(f"⚠️ [sticky_phases] Pruning non-matching pattern: '{raw_path}'", file=sys.stderr, flush=True)
                return
            for m in matches:
                if os.path.isfile(m):
                    _add_entry(category, m)
            return

        rel_p = _canon_rel(raw_path)
        dest_cat = "test_files" if (category == "target_files" and is_test_path(rel_p)) else category
        if dest_cat == "test_files" or os.path.isfile(abs_p):
            if rel_p not in verified[dest_cat]:
                verified[dest_cat].append(rel_p)
        else:
            print(f"⚠️ [sticky_phases] Pruning non-existent path: '{raw_path}'", file=sys.stderr, flush=True)

    for k, paths in result.items():
        for p in paths:
            _add_entry(k, p)

    return verified


class _TeeWriter:
    """Write-through wrapper: every write goes to both the original stream and a log file.
    Used on Windows where os.dup2 on fd 1/2 is unreliable with buffered I/O."""

    def __init__(self, original, log_file):
        self._original = original
        self._log = log_file
        self._lock = threading.RLock()

    def write(self, data):
        with self._lock:
            self._original.write(data)
            try:
                self._log.write(data)
                self._log.flush()
            except (ValueError, OSError):
                pass

    def flush(self):
        with self._lock:
            self._original.flush()
            try:
                self._log.flush()
            except (ValueError, OSError):
                pass

    def fileno(self):
        return self._original.fileno()

    def __getattr__(self, name):
        return getattr(self._original, name)


class OSTee:
    """Redirects OS file descriptors 1 (stdout) and 2 (stderr) so that ALL output from
    Python AND child subprocesses (script, aider, Rscript) is captured to log_file
    while streaming live to the terminal.
    """

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.log_file = open(self.log_path, "a", encoding="utf-8", errors="replace")
        self._lock = threading.Lock()
        self.running = True
        self._stopped = False

        if sys.platform == "win32":
            self._orig_stdout = sys.stdout
            self._orig_stderr = sys.stderr
            sys.stdout = _TeeWriter(self._orig_stdout, self.log_file)
            sys.stderr = _TeeWriter(self._orig_stderr, self.log_file)
            self.orig_stdout_fd = None
            self.orig_stderr_fd = None
            self.pipe_r = None
            self.pipe_w = None
            self.thread = None
        else:
            self._orig_stdout = None
            self.orig_stdout_fd = os.dup(1)
            self.orig_stderr_fd = os.dup(2)
            self.pipe_r, self.pipe_w = os.pipe()
            os.dup2(self.pipe_w, 1)
            os.dup2(self.pipe_w, 2)
            self.thread = threading.Thread(target=self._pump, daemon=True)
            self.thread.start()

    def _pump(self):
        while True:
            try:
                if self.pipe_r is None:
                    break
                data = os.read(self.pipe_r, 4096)
                if not data:
                    break
                if self.orig_stdout_fd is not None:
                    os.write(self.orig_stdout_fd, data)
                text = data.decode("utf-8", errors="replace")
                try:
                    self.log_file.write(text)
                    self.log_file.flush()
                except (ValueError, OSError):
                    break
            except Exception:
                break

    def stop(self):
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self.running = False

            if sys.platform == "win32":
                if self._orig_stdout:
                    sys.stdout = self._orig_stdout
                if self._orig_stderr:
                    sys.stderr = self._orig_stderr
                try:
                    self.log_file.close()
                except OSError:
                    pass
            else:
                sys.stdout.flush()
                sys.stderr.flush()
                if self.orig_stdout_fd is not None:
                    try:
                        os.dup2(self.orig_stdout_fd, 1)
                    except OSError:
                        pass
                if self.orig_stderr_fd is not None:
                    try:
                        os.dup2(self.orig_stderr_fd, 2)
                    except OSError:
                        pass
                if self.pipe_w is not None:
                    try:
                        os.close(self.pipe_w)
                    except OSError:
                        pass
                    self.pipe_w = None
                if self.thread and self.thread.is_alive():
                    self.thread.join(timeout=2.0)
                if self.pipe_r is not None:
                    try:
                        os.close(self.pipe_r)
                    except OSError:
                        pass
                    self.pipe_r = None
                for fd_attr in ("orig_stdout_fd", "orig_stderr_fd"):
                    fd = getattr(self, fd_attr, None)
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        setattr(self, fd_attr, None)
                try:
                    self.log_file.close()
                except OSError:
                    pass


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
        global_ranking_api = endpoints.get("ranking_api_base")

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
                None if "gemini/" in ARCHITECT_AGENT else global_architect_api_base
            )
            EDITOR_API = None if "gemini/" in EDITOR_AGENT else global_editor_api
            EDITOR_API_FALLBACK = (
                None if "gemini/" in EDITOR_AGENT_TEST else global_editor_test_api
            )

            # Per-phase RAG collection
            phase_collection = rag_phase_cfg.get("collection_name", rag_default_collection)

            # Zero-RAG mode bypass: if collection_name is explicitly [], "", or None
            if not phase_collection or phase_collection == []:
                phase_collection = ""
                phase_run_ocr_rag = False

            # Per-phase custom DB override
            rag_custom_db = rag_phase_cfg.get("db") or global_rag.get("db")
            if rag_custom_db:
                phase_db_dir = (
                    rag_custom_db
                    if os.path.isabs(rag_custom_db)
                    else os.path.join(str(project_directory), rag_custom_db)
                ).replace("\\", "/")
            else:
                phase_db_dir = (
                    os.path.join(rag_context_root, phase_collection, "lancedb")
                    if phase_collection
                    else ""
                )

            # Per-phase corpus type filter
            rag_type_filter = rag_phase_cfg.get("type_filter") or global_rag.get("type_filter")

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
            ingest_attached = False
            phase_ingest_owner_id = None

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

                def _h_stem(job_prefix: str) -> Optional[str]:
                    return None if shared_history else f"{job_prefix}_{base_name}"

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
                        specific_test_file = phase_test_convention.replace(
                            "{stem}", base_name
                        )
                else:
                    specific_test_file = phase_test_convention.replace(
                        "{stem}", base_name
                    )
                # Language-agnostic execution: {prefix} {test_runner with {file} filled}.
                cmd_prefix = phase_cmd_prefix
                test_cmd = (
                    f"{phase_cmd_prefix}{phase_test_runner.replace('{file}', specific_test_file)}"
                )

                last_task_for_file = file_last_tasks.get(current_file)
                initial_phase_deps = [last_task_for_file] if last_task_for_file else list(prior_phase_terminal_tasks)

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
                        deps = list(initial_phase_deps)
                        if phase_ingest_owner_id and phase_ingest_owner_id not in deps:
                            deps.append(phase_ingest_owner_id)
                        _add_task(
                            Task(
                                id=gen_id,
                                depends_on=deps,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_API,
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
                                history_stem=_h_stem("oracle"),
                            )
                        )
                        if task_ocr_ingest is not None:
                            phase_ingest_owner_id = gen_id
                            task_ocr_ingest = None
                        last_task_for_file = gen_id

                    # autofix (deterministic ellipsis-stitch + audit), BEFORE any agent.
                    if resolve_evidence:
                        autofix_id = f"{env_prefix}_autofix_{base_name}"
                        _add_task(
                            Task(
                                id=autofix_id,
                                depends_on=[last_task_for_file] if last_task_for_file else list(initial_phase_deps),
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
                                history_stem=_h_stem("autofix"),
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
                                f"{phase_cmd_prefix}{phase_test_runner.replace('{file}', _val_script)}"
                            )
                            heal_id = f"{env_prefix}_heal_{base_name}"
                            _add_task(
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
                        job1_reads = list(initial_context_files)
                        if sticky_context:
                            for cf in completed_files:
                                if cf not in job1_reads:
                                    job1_reads.append(cf)
                        job1_depends = _ingest_deps(
                            initial_phase_deps
                        )
                        job1_msg_file = job_one_plan

                        if debate_j1:
                            _pre_loops = pre_edit_cfg.get("loops")
                            _job1_loops = _pre_loops if _pre_loops is not None else 3
                            _job1_rounds = int(pre_edit_cfg.get("rounds", 1))
                            _job1_pass_history = bool(pre_edit_cfg.get("pass_history", True))
                            _job1_persist = bool(pre_edit_cfg.get("persist", False))
                            _job1_orc_persona = pre_edit_cfg.get("oracle_persona", "")
                            _job1_arch_persona = pre_edit_cfg.get("architect_persona", "")
                            _job1_orc_file = pre_edit_cfg.get("oracle_file", "")
                            _job1_arch_file = pre_edit_cfg.get("architect_file", "")

                            _debate_template = _resolve_job_debate_template(
                                pre_edit_cfg, job_num=1, project_directory=project_directory
                            )
                            _j1_coll, _j1_db = _resolve_job_debate_collection(
                                pre_edit_cfg,
                                job_num=1,
                                default_collection=_table,
                                rag_context_root=rag_context_root,
                                default_db=phase_db_dir,
                                project_directory=project_directory,
                            )
                            _j1_rag_env = dict(file_rag_env)
                            if pre_edit_cfg.get("job_debate_collection") is not None:
                                _j1_rag_env["ORACLE_COLLECTION"] = _j1_coll
                                _j1_rag_env["ORACLE_RAG_DB_DIR"] = _j1_db

                            _debate_reads = list(dict.fromkeys(
                                [current_file]
                                + list(extra_editable_files)
                                + list(initial_context_files)
                                + (completed_files if sticky_context else [])
                            ))
                            if job_one_plan and job_one_plan not in _debate_reads:
                                _debate_reads.append(job_one_plan)

                            prev_debate_id = None
                            for r_idx in range(1, _job1_rounds + 1):
                                r_suf = f"_r{r_idx}" if _job1_rounds > 1 else ""
                                job1_debate_id = f"{env_prefix}_job1_debate_{base_name}{r_suf}"
                                _verdict_job1_abs = os.path.join(
                                    _ddir, f"{base_name}.job1_verdict{r_suf}.md"
                                )
                                _ledger_job1_abs = os.path.join(
                                    _ddir, f"{base_name}.job1_debate{r_suf}.json"
                                )

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
                                    "round_idx": r_idx,
                                    "pass_history": _job1_pass_history,
                                    "persist": _job1_persist,
                                    "oracle_persona": _job1_orc_persona,
                                    "architect_persona": _job1_arch_persona,
                                    "oracle_file": _job1_orc_file,
                                    "architect_file": _job1_arch_file,
                                }
                                if r_idx > 1:
                                    _r_deliberate["prior_verdict"] = os.path.join(
                                        _ddir, f"{base_name}.job1_verdict_r{r_idx - 1}.md"
                                    )
                                    _r_deliberate["prior_ledger"] = os.path.join(
                                        _ddir, f"{base_name}.job1_debate_r{r_idx - 1}.json"
                                    )

                                _r_depends = [prev_debate_id] if prev_debate_id else _ingest_deps(initial_phase_deps)
                                _add_task(
                                    Task(
                                        id=job1_debate_id,
                                        depends_on=_r_depends,
                                        model=ARCHITECT_AGENT,
                                        editor_model=EDITOR_AGENT,
                                        weak_model=weak_model,
                                        weak_model_api_base=weak_model_api_base,
                                        architect_api_base=ARCHITECT_API_BASE,
                                        rag_env=_j1_rag_env,
                                        ocr_ingest=task_ocr_ingest if r_idx == 1 else None,
                                        deliberate=_r_deliberate,
                                        history_stem=_h_stem("job1"),
                                    )
                                )
                                if task_ocr_ingest is not None and r_idx == 1:
                                    phase_ingest_owner_id = job1_debate_id
                                    task_ocr_ingest = None
                                prev_debate_id = job1_debate_id

                            job1_depends = [prev_debate_id]
                            job1_msg_file = _verdict_job1_abs
                            if job_one_plan and job_one_plan not in job1_reads:
                                job1_reads.append(job_one_plan)

                        _add_task(
                            Task(
                                id=job1_id,
                                depends_on=job1_depends,
                                message_file=job1_msg_file,
                                read_files=job1_reads,
                                files=[current_file] + extra_editable_files,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_API,
                                rag_env=file_rag_env,
                                ocr_ingest=task_ocr_ingest,
                                pair_programming=pair_programming,
                                history_stem=_h_stem("job1"),
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
                            [last_task_for_file] if last_task_for_file else list(initial_phase_deps)
                        )

                        strategy_content = ""
                        strategy_file = plans.get("validate_strategy_file")
                        if not strategy_file and completed_files:
                            strategy_file = next(
                                (f for f in reversed(completed_files) if f.endswith(".md")),
                                completed_files[0],
                            )

                        if not strategy_file:
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
                                    strategy_content = sf.read()

                        session_tmpl_dir = os.path.join(session_dir, "templates")
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
                            _pre_loops = pre_edit_cfg.get("loops")
                            _job2_loops = _pre_loops if _pre_loops is not None else 3
                            _job2_rounds = int(pre_edit_cfg.get("rounds", 1))
                            _job2_pass_history = bool(pre_edit_cfg.get("pass_history", True))
                            _job2_persist = bool(pre_edit_cfg.get("persist", False))
                            _job2_orc_persona = pre_edit_cfg.get("oracle_persona", "")
                            _job2_arch_persona = pre_edit_cfg.get("architect_persona", "")
                            _job2_orc_file = pre_edit_cfg.get("oracle_file", "")
                            _job2_arch_file = pre_edit_cfg.get("architect_file", "")

                            _debate_template = _resolve_job_debate_template(
                                pre_edit_cfg, job_num=2, project_directory=project_directory
                            )
                            _j2_coll, _j2_db = _resolve_job_debate_collection(
                                pre_edit_cfg,
                                job_num=2,
                                default_collection=_table,
                                rag_context_root=rag_context_root,
                                default_db=phase_db_dir,
                                project_directory=project_directory,
                            )
                            _j2_rag_env = dict(file_rag_env)
                            if pre_edit_cfg.get("job_debate_collection") is not None:
                                _j2_rag_env["ORACLE_COLLECTION"] = _j2_coll
                                _j2_rag_env["ORACLE_RAG_DB_DIR"] = _j2_db

                            _debate_reads = list(dict.fromkeys(
                                [current_file]
                                + list(extra_editable_files)
                                + list(initial_context_files)
                                + (completed_files if sticky_context else [])
                            ))
                            if job2_msg_file and job2_msg_file not in _debate_reads:
                                _debate_reads.append(job2_msg_file)

                            prev_debate_id = None
                            for r_idx in range(1, _job2_rounds + 1):
                                r_suf = f"_r{r_idx}" if _job2_rounds > 1 else ""
                                job2_debate_id = f"{env_prefix}_job2_debate_{base_name}{r_suf}"
                                _verdict_job2_abs = os.path.join(
                                    _ddir, f"{base_name}.job2_verdict{r_suf}.md"
                                )
                                _ledger_job2_abs = os.path.join(
                                    _ddir, f"{base_name}.job2_debate{r_suf}.json"
                                )

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
                                    "round_idx": r_idx,
                                    "pass_history": _job2_pass_history,
                                    "persist": _job2_persist,
                                    "oracle_persona": _job2_orc_persona,
                                    "architect_persona": _job2_arch_persona,
                                    "oracle_file": _job2_orc_file,
                                    "architect_file": _job2_arch_file,
                                }
                                if r_idx > 1:
                                    _r_deliberate["prior_verdict"] = os.path.join(
                                        _ddir, f"{base_name}.job2_verdict_r{r_idx - 1}.md"
                                    )
                                    _r_deliberate["prior_ledger"] = os.path.join(
                                        _ddir, f"{base_name}.job2_debate_r{r_idx - 1}.json"
                                    )

                                _r_depends = [prev_debate_id] if prev_debate_id else _ingest_deps(
                                    [last_task_for_file] if last_task_for_file else list(initial_phase_deps)
                                )
                                _add_task(
                                    Task(
                                        id=job2_debate_id,
                                        depends_on=_r_depends,
                                        model=ARCHITECT_AGENT,
                                        editor_model=EDITOR_AGENT,
                                        weak_model=weak_model,
                                        weak_model_api_base=weak_model_api_base,
                                        architect_api_base=ARCHITECT_API_BASE,
                                        rag_env=_j2_rag_env,
                                        ocr_ingest=task_ocr_ingest if r_idx == 1 else None,
                                        deliberate=_r_deliberate,
                                        history_stem=_h_stem("job2"),
                                    )
                                )
                                if task_ocr_ingest is not None and r_idx == 1:
                                    phase_ingest_owner_id = job2_debate_id
                                    task_ocr_ingest = None
                                prev_debate_id = job2_debate_id

                            job2_depends = [prev_debate_id]
                            job2_msg_file = _verdict_job2_abs

                        job2_reads = [current_file] + list(initial_context_files)
                        if sticky_context:
                            for cf in completed_files:
                                if cf not in job2_reads:
                                    job2_reads.append(cf)
                        if job2_msg_file and job2_msg_file not in job2_reads:
                            job2_reads.append(job2_msg_file)

                        _add_task(
                            Task(
                                id=job2_id,
                                depends_on=job2_depends,
                                message_file=job2_msg_file,
                                read_files=job2_reads,
                                files=[current_file] + extra_editable_files,
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_API,
                                pair_programming=pair_programming,
                                rag_env=file_rag_env,
                                ocr_ingest=task_ocr_ingest,
                                history_stem=_h_stem("job2"),
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
                            [last_task_for_file] if last_task_for_file else list(initial_phase_deps)
                        )

                        if run_job_three:
                            job3_id = f"{env_prefix}_job3_{base_name}"
                            job3_reads = [current_file] + list(initial_context_test_files)
                            if sticky_context:
                                for cf in completed_files:
                                    if cf not in job3_reads:
                                        job3_reads.append(cf)
                            if job_three_plan and job_three_plan not in job3_reads:
                                job3_reads.append(job_three_plan)

                            job3_msg_file = job_three_plan

                            if debate_j3:
                                _pre_loops = pre_edit_cfg.get("loops")
                                _job3_loops = _pre_loops if _pre_loops is not None else 3
                                _job3_rounds = int(pre_edit_cfg.get("rounds", 1))
                                _job3_pass_history = bool(pre_edit_cfg.get("pass_history", True))
                                _job3_persist = bool(pre_edit_cfg.get("persist", False))
                                _job3_orc_persona = pre_edit_cfg.get("oracle_persona", "")
                                _job3_arch_persona = pre_edit_cfg.get("architect_persona", "")
                                _job3_orc_file = pre_edit_cfg.get("oracle_file", "")
                                _job3_arch_file = pre_edit_cfg.get("architect_file", "")

                                _debate_template = _resolve_job_debate_template(
                                    pre_edit_cfg,
                                    job_num=3,
                                    project_directory=project_directory,
                                )
                                _j3_coll, _j3_db = _resolve_job_debate_collection(
                                    pre_edit_cfg,
                                    job_num=3,
                                    default_collection=_table,
                                    rag_context_root=rag_context_root,
                                    default_db=phase_db_dir,
                                    project_directory=project_directory,
                                )
                                _j3_rag_env = dict(file_rag_env)
                                if pre_edit_cfg.get("job_debate_collection") is not None:
                                    _j3_rag_env["ORACLE_COLLECTION"] = _j3_coll
                                    _j3_rag_env["ORACLE_RAG_DB_DIR"] = _j3_db

                                _debate_reads = list(dict.fromkeys(
                                    [current_file, specific_test_file]
                                    + list(extra_editable_files)
                                    + list(initial_context_test_files)
                                    + (completed_files if sticky_context else [])
                                ))
                                if job_three_plan and job_three_plan not in _debate_reads:
                                    _debate_reads.append(job_three_plan)

                                prev_debate_id = None
                                for r_idx in range(1, _job3_rounds + 1):
                                    r_suf = f"_r{r_idx}" if _job3_rounds > 1 else ""
                                    job3_debate_id = f"{env_prefix}_job3_debate_{base_name}{r_suf}"
                                    _verdict_job3_abs = os.path.join(
                                        _ddir, f"{base_name}.job3_verdict{r_suf}.md"
                                    )
                                    _ledger_job3_abs = os.path.join(
                                        _ddir, f"{base_name}.job3_debate{r_suf}.json"
                                    )

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
                                        "round_idx": r_idx,
                                        "pass_history": _job3_pass_history,
                                        "persist": _job3_persist,
                                        "oracle_persona": _job3_orc_persona,
                                        "architect_persona": _job3_arch_persona,
                                        "oracle_file": _job3_orc_file,
                                        "architect_file": _job3_arch_file,
                                    }
                                    if r_idx > 1:
                                        _r_deliberate["prior_verdict"] = os.path.join(
                                            _ddir, f"{base_name}.job3_verdict_r{r_idx - 1}.md"
                                        )
                                        _r_deliberate["prior_ledger"] = os.path.join(
                                            _ddir, f"{base_name}.job3_debate_r{r_idx - 1}.json"
                                        )

                                    _r_depends = [prev_debate_id] if prev_debate_id else _ingest_deps(
                                        [last_task_for_file] if last_task_for_file else list(initial_phase_deps)
                                    )
                                    _add_task(
                                        Task(
                                            id=job3_debate_id,
                                            depends_on=_r_depends,
                                            model=ARCHITECT_AGENT,
                                            editor_model=EDITOR_AGENT_TEST,
                                            weak_model=weak_model,
                                            weak_model_api_base=weak_model_api_base,
                                            architect_api_base=ARCHITECT_API_BASE,
                                            rag_env=_j3_rag_env,
                                            ocr_ingest=task_ocr_ingest if r_idx == 1 else None,
                                            deliberate=_r_deliberate,
                                            history_stem=_h_stem("job3"),
                                        )
                                    )
                                    if task_ocr_ingest is not None and r_idx == 1:
                                        phase_ingest_owner_id = job3_debate_id
                                        task_ocr_ingest = None
                                    prev_debate_id = job3_debate_id

                                job3_depends = [prev_debate_id]
                                job3_msg_file = _verdict_job3_abs

                            _add_task(
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
                                    editor_api_base=EDITOR_API_FALLBACK,
                                    pair_programming=pair_programming,
                                    rag_env=file_rag_env,
                                    ocr_ingest=task_ocr_ingest,
                                    history_stem=_h_stem("job3"),
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

                            _add_task(
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
                                    editor_api_base=EDITOR_API_FALLBACK,
                                    test_cmd=test_cmd,
                                    iterate_test=True,
                                    max_aider_loops=global_max_aider_loops,
                                    auto_test=auto_test,
                                    pair_programming=pair_programming,
                                    rag_env=file_rag_env,
                                    ocr_ingest=task_ocr_ingest,
                                    soft_fail=escalate,
                                    final_check=True,
                                    history_stem=_h_stem("verify"),
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
                    _add_task(
                        Task(
                            id=ing_id,
                            depends_on=[last_task_for_file] if last_task_for_file else [],
                            rag_env=file_rag_env,
                            ocr_ingest=task_ocr_ingest,
                            skip_aider=True,
                            history_stem=_h_stem("ingest"),
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
                        _r_verdict = os.path.join(_ddir, f"{base_name}{round_suf}.verdict.md")
                        _r_ledger = os.path.join(_ddir, f"{base_name}{round_suf}.debate.json")

                        _round_debate = dict(_base_debate)
                        _round_debate["verdict"] = _r_verdict
                        _round_debate["ledger"] = _r_ledger
                        _round_debate["round_idx"] = round_idx
                        _round_debate["pass_history"] = pass_history
                        _round_debate["persist"] = bool(esc_cfg.get("persist", False))
                        _round_debate["oracle_persona"] = esc_cfg.get("oracle_persona", "")
                        _round_debate["architect_persona"] = esc_cfg.get("architect_persona", "")
                        _round_debate["oracle_file"] = esc_cfg.get("oracle_file", "")
                        _round_debate["architect_file"] = esc_cfg.get("architect_file", "")
                        # Give this round the ledger of the PREVIOUS round so it knows what was just tried
                        if round_idx > 1:
                            _round_debate["prior_ledger"] = (
                                os.path.join(_ddir, f"{base_name}_r{round_idx - 1}.debate.json")
                            )
                            _round_debate["prior_verdict"] = (
                                os.path.join(_ddir, f"{base_name}_r{round_idx - 1}.verdict.md")
                            )

                        _r_apply_kwargs = dict(_apply_kwargs)
                        if debate_rounds > 1 and round_idx < debate_rounds:
                            _r_apply_kwargs["soft_fail"] = True
                        if _build_finalize:
                            _r_apply_kwargs["rag_env"] = dict(
                                _apply_kwargs.get("rag_env", {})
                            )
                            _r_apply_kwargs["rag_env"]["ORACLE_BASELINE_LEDGER"] = _r_ledger

                        delib_id = f"{env_prefix}_deliberate_{base_name}{round_suf}"
                        _add_task(
                            Task(
                                id=delib_id,
                                depends_on=[last_task_for_file]
                                if last_task_for_file
                                else [],
                                model=ARCHITECT_AGENT,
                                editor_model=EDITOR_AGENT,
                                weak_model=weak_model,
                                weak_model_api_base=weak_model_api_base,
                                architect_api_base=ARCHITECT_API_BASE,
                                editor_api_base=EDITOR_API,
                                rag_env=file_rag_env,
                                deliberate=_round_debate,
                                history_stem=_h_stem("escalate"),
                            )
                        )

                        apply_id = f"{env_prefix}_apply_{base_name}{round_suf}"
                        apply_files = (
                            [specific_test_file, current_file]
                            if code_mode
                            else [current_file]
                        ) + extra_editable_files
                        _add_task(
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
                                editor_api_base=EDITOR_API_FALLBACK,
                                iterate_test=True,
                                auto_test=auto_test,
                                history_stem=_h_stem("escalate"),
                                **_r_apply_kwargs,
                            )
                        )
                        last_task_for_file = apply_id

                    # Finalize ONLY runs once, at the very end of all escalation rounds
                    if _build_finalize:
                        finalize_id = f"{env_prefix}_finalize_{base_name}"
                        _add_task(
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
                                history_stem=_h_stem("finalize"),
                            )
                        )
                        last_task_for_file = finalize_id

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
