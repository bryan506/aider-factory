#!/usr/bin/env python3
# run_workflow_utils.py — Stateless template, path, manifest, and OS-tee utilities for run_workflow.py.

import glob
import os
import re
import sys
import threading
from typing import Optional

import yaml  # type: ignore

_python_dir = os.path.dirname(os.path.abspath(__file__))
if _python_dir not in sys.path:
    sys.path.insert(0, _python_dir)

try:
    from aider_factory.python.env_utils import is_test_path
except ImportError:
    from env_utils import is_test_path


def _expand_file_list(file_patterns, base_dir=None):
    """Expand glob patterns into a deduplicated, alphabetically sorted list of relative paths.
    Literal paths with no glob magic are preserved verbatim if they exist.
    Empty or None inputs return an empty list."""
    if not file_patterns:
        return []

    base_dir_str = str(base_dir) if base_dir else os.getcwd()

    if isinstance(file_patterns, str):
        file_patterns = [file_patterns]

    expanded = []
    for pat in file_patterns:
        if glob.has_magic(pat):
            abs_pat = pat if os.path.isabs(pat) else os.path.join(base_dir_str, pat)
            abs_pat = os.path.normpath(abs_pat)
            for match in sorted(glob.glob(abs_pat)):
                rel_path = os.path.relpath(match, base_dir_str).replace("\\", "/")
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


def _parse_insert_debate(pre_edit_cfg: dict) -> tuple[bool, bool, bool]:
    """Parse insert_debate into a 3-tuple (job1, job2, job3) boolean triggers."""
    if not isinstance(pre_edit_cfg, dict):
        return (False, False, False)

    enabled = pre_edit_cfg.get("enabled", False)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in ("0", "false", "no", "off", "none", "")
    if not enabled:
        return (False, False, False)

    raw = pre_edit_cfg.get("insert_debate")
    if raw is None:
        return (True, False, False)

    if isinstance(raw, bool):
        return (raw, False, False)

    if isinstance(raw, (int, float)):
        return (bool(raw), False, False)

    def _to_bool(item) -> bool:
        if isinstance(item, str):
            s = item.strip().lower()
            if s in ("0", "false", "no", "off", "none", ""):
                return False
            if s.isdigit():
                return bool(int(s))
            return True
        return bool(item)

    if isinstance(raw, (list, tuple)):
        vals = [_to_bool(x) for x in raw]
        while len(vals) < 3:
            vals.append(False)
        return (bool(vals[0]), bool(vals[1]), bool(vals[2]))

    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("false", "no", "off", "none", ""):
            return (False, False, False)
        if s in ("true", "yes", "on"):
            return (True, False, False)
        cleaned = re.sub(r"[^\d, ]", "", raw).replace(" ", ",")
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        vals = [bool(int(p)) if p.isdigit() else False for p in parts]
        while len(vals) < 3:
            vals.append(False)
        return (bool(vals[0]), bool(vals[1]), bool(vals[2]))

    return (bool(raw), False, False)


def _resolve_job_debate_template(
    pre_edit_cfg: dict, job_num: int, project_directory: str = None
) -> Optional[str]:
    """Resolve specialized debate prompt template for Job 1, 2, or 3."""
    if not isinstance(pre_edit_cfg, dict) or not pre_edit_cfg:
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
    rag_context_root: str = "",
    default_db: str = "",
    project_directory: str = None,
    round_num: int = 1,
) -> tuple[str, str, str]:
    """Resolve specialized vector collection, LanceDB dir, and retrieve_mode for Job and Round.
    Supports flow sequences: [job1_coll, [round1_coll, round2_coll], job3_coll].
    Empty, None, or 'no_retrieve' returns retrieve_mode='no_retrieve' to guarantee pure AST analysis."""
    chosen = default_collection or ""
    r_num = max(1, int(round_num or 1))
    rag_root_str = str(rag_context_root) if rag_context_root is not None else ""
    if isinstance(pre_edit_cfg, dict) and "job_debate_collection" in pre_edit_cfg:
        raw = pre_edit_cfg.get("job_debate_collection")
        if isinstance(raw, (list, tuple)):
            if 0 <= (job_num - 1) < len(raw):
                job_entry = raw[job_num - 1]
                if isinstance(job_entry, (list, tuple)):
                    if job_entry:
                        idx = min(r_num - 1, len(job_entry) - 1)
                        chosen = str(job_entry[idx]).strip() if job_entry[idx] is not None else ""
                    else:
                        chosen = ""
                else:
                    chosen = str(job_entry).strip() if job_entry is not None else (default_collection or "")
            elif raw and raw[0] is not None:
                if isinstance(raw[0], (list, tuple)):
                    if raw[0]:
                        idx = min(r_num - 1, len(raw[0]) - 1)
                        chosen = str(raw[0][idx]).strip() if raw[0][idx] is not None else ""
                    else:
                        chosen = ""
                else:
                    chosen = str(raw[0]).strip()
        elif isinstance(raw, str):
            chosen = raw.strip()

    has_explicit_db = False
    chosen_db = default_db or ""
    if isinstance(pre_edit_cfg, dict) and "job_debate_db" in pre_edit_cfg:
        raw_db = pre_edit_cfg.get("job_debate_db")
        if isinstance(raw_db, (list, tuple)):
            if 0 <= (job_num - 1) < len(raw_db):
                entry_db = raw_db[job_num - 1]
                if isinstance(entry_db, (list, tuple)):
                    if entry_db:
                        idx = min(r_num - 1, len(entry_db) - 1)
                        if entry_db[idx] is not None and str(entry_db[idx]).strip():
                            chosen_db = str(entry_db[idx]).strip()
                            has_explicit_db = True
                elif entry_db is not None and str(entry_db).strip():
                    chosen_db = str(entry_db).strip()
                    has_explicit_db = True
            elif raw_db and raw_db[0] is not None and str(raw_db[0]).strip():
                chosen_db = str(raw_db[0]).strip()
                has_explicit_db = True
        elif isinstance(raw_db, str) and raw_db.strip():
            chosen_db = raw_db.strip()
            has_explicit_db = True

    if chosen_db:
        chosen_db = os.path.expanduser(chosen_db)
        if project_directory and not (
            chosen_db.startswith("/")
            or chosen_db.startswith("\\")
            or (len(chosen_db) > 1 and chosen_db[1] == ":")
        ):
            chosen_db = os.path.join(str(project_directory), chosen_db)
        chosen_db = chosen_db.replace("\\", "/")

    if not chosen or str(chosen).lower() in ("no_retrieve", "none"):
        return "", (chosen_db if has_explicit_db else ""), "no_retrieve"

    if chosen == "*":
        return "*", chosen_db or "", "top_k"

    expanded = os.path.abspath(os.path.expanduser(chosen))
    if "/" in chosen or "\\" in chosen or os.path.exists(expanded):
        base = os.path.basename(expanded.rstrip("/\\"))
        if base.lower() == "lancedb":
            coll = os.path.basename(os.path.dirname(expanded.rstrip("/\\")))
            db_dir = expanded.replace("\\", "/")
        else:
            coll = base
            db_dir = os.path.join(expanded, "lancedb").replace("\\", "/")
        return coll, (chosen_db if has_explicit_db else (db_dir or chosen_db)), "top_k"

    return chosen, (chosen_db or os.path.join(rag_root_str, chosen, "lancedb").replace("\\", "/")), "top_k"


def _render_validate_template(
    template_path: str, strategy_content: str, output_path: str
) -> str:
    """Inject strategy_content into the validate template's placeholder section."""
    if not template_path or not os.path.exists(template_path):
        return template_path

    with open(template_path, "r", encoding="utf-8") as vf:
        val_text = vf.read()

    clean_strategy = (strategy_content or "").strip()
    injection = f"## PREVIOUS COMPLETED SYSTEM GOALS AND CONSTRAINTS\n\n{clean_strategy}\n"
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


def _render_testing_template(
    template_path: str,
    strategy_content: str,
    output_path: str,
    git_diff_text: Optional[str] = None,
    include_diff: bool = False,
) -> str:
    """Inject read-only strategy specification and optional implementation git diff into a testing template."""
    if not template_path or not os.path.exists(template_path):
        return template_path

    with open(template_path, "r", encoding="utf-8") as tf:
        base_text = tf.read()

    header = "## COMPLETED IMPLEMENTATION CONTEXT (READ-ONLY REFERENCE FOR TESTING)"
    parts = [
        header,
        "",
        "> **STRICT ROLE DIRECTIVE**: The specification and code changes below were **already executed** in Job 1 (Implementation) and Job 2 (Validation).",
        "> - Do **NOT** re-execute the implementation plan below as a builder task list.",
        "> - Use `<completed_strategy_specification>` as the **Normative Oracle** to identify required invariants, formulas, boundary conditions, edge cases, and acceptance criteria—including any requirements the implementation may have missed.",
    ]
    if include_diff:
        parts.append(
            "> - Use `<implementation_git_diff>` to inspect the **Exact Net Code Delta** applied to the editable files during Job 1 & Job 2."
        )
    parts.append(
        "> - Only modify source files (`target_files` / `extra_editable_files`) if your tests uncover a genuine bug, contract discrepancy, or missing edge case in the implementation."
    )

    clean_strategy = (strategy_content or "").strip()
    if clean_strategy:
        clean_strategy = re.sub(
            r"```ya?ml[^\n]*\n(?:(?!```).)*?\bfiles\s*:.*?```\s*",
            "",
            clean_strategy,
            flags=re.DOTALL | re.IGNORECASE,
        )
        clean_strategy = re.sub(
            r"(?i)(?:^|\n)#{2,3}\s*Scope Analysis[ \t]*\r?\n(?=\s*(?:#{1,3}\s|\Z))",
            "\n",
            clean_strategy,
        ).strip()

    if clean_strategy:
        parts.extend(
            [
                "",
                "<completed_strategy_specification>",
                clean_strategy,
                "</completed_strategy_specification>",
            ]
        )

    if include_diff:
        clean_diff = (git_diff_text or "").strip()
        diff_body = (
            f"```diff\n{clean_diff}\n```"
            if clean_diff
            else "(No net code changes detected in Job 1 / Job 2.)"
        )
        parts.extend(
            [
                "",
                "<implementation_git_diff>",
                diff_body,
                "</implementation_git_diff>",
            ]
        )

    injection = "\n".join(parts) + "\n"
    if header in base_text:
        final_text = re.sub(
            rf"{re.escape(header)}.*\Z",
            lambda _: injection,
            base_text,
            flags=re.DOTALL,
        )
    else:
        final_text = base_text.rstrip() + "\n\n---\n\n" + injection

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as rf:
        rf.write(final_text)

    return output_path


def resolve_template_path(path_val, project_directory=None):
    """Resolves a template path, prioritizing local workspace paths (.aider_factory/ and project root)
    before falling back to package bundled resources."""
    if not path_val:
        return None

    path_str = str(path_val).strip()
    if not path_str:
        return None

    if os.path.isabs(path_str):
        return path_str.replace("\\", "/")

    base_proj = str(project_directory or os.getcwd())
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pkg_dir = os.path.abspath(os.path.join(script_dir, ".."))

    rel_stripped = path_str
    for prefix in (
        ".aider_factory/",
        ".aider_factory\\",
        "src/aider_factory/",
        "src\\aider_factory\\",
    ):
        if rel_stripped.startswith(prefix):
            rel_stripped = rel_stripped[len(prefix) :]
            break

    flat_filename = os.path.basename(path_str)

    workspace_candidates = [
        os.path.join(base_proj, path_str),
        os.path.join(base_proj, ".aider_factory", rel_stripped),
        os.path.join(base_proj, ".aider_factory", "markdown", rel_stripped),
        os.path.join(base_proj, ".aider_factory", flat_filename),
        os.path.join(base_proj, ".aider_factory", "markdown", flat_filename),
    ]

    for cand in workspace_candidates:
        if os.path.isfile(cand):
            return cand.replace("\\", "/")

    pkg_candidates = [
        os.path.join(pkg_dir, rel_stripped),
        os.path.join(pkg_dir, "markdown", rel_stripped),
        os.path.join(pkg_dir, flat_filename),
        os.path.join(pkg_dir, "markdown", flat_filename),
    ]

    for cand in pkg_candidates:
        if os.path.isfile(cand):
            return cand.replace("\\", "/")

    return os.path.join(base_proj, path_str).replace("\\", "/")


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

    if not result["context_files_test"] and result["context_files_job"]:
        result["context_files_test"] = list(result["context_files_job"])

    base_proj = str(project_directory) if project_directory else os.getcwd()

    def _canon_rel(p: str) -> str:
        clean = os.path.normpath(p).replace("\\", "/")
        if os.path.isabs(clean):
            try:
                return os.path.relpath(clean, base_proj).replace("\\", "/")
            except ValueError:
                return clean
        return clean

    verified: dict[str, list[str]] = {k: [] for k in result.keys()}

    def _add_entry(category: str, raw_path: str):
        if not raw_path or raw_path.startswith(("path/to/", "<")) or raw_path in ("...", "None", "null"):
            return
        abs_p = raw_path if os.path.isabs(raw_path) else os.path.join(base_proj, raw_path)
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
