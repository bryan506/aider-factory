#!/usr/bin/env python3
# oracle_agent.py — Knowledge Oracle side-agent (Tier 2a) for the AI Factory.
#
# Invoked from inside an Aider session:
#   pair mode:        /run .aider_factory/bash/oracle "what is the leverage ratio formula?"
#   autonomous mode:  the architect proposes the same command via --suggest-shell-commands
#
# stdout = the answer ONLY (so Aider folds a clean message into the chat).
# All library noise (model load, HTTP, warnings) + a status line go to stderr.

import contextlib
import datetime
import json
import logging
import os
import subprocess
import sys
import uuid

# Generate session ID once per pipeline run for KV-cache stickiness
_PIPELINE_SESSION_ID = os.environ.get("LITELLM_SESSION_ID") or str(uuid.uuid4())
os.environ["LITELLM_SESSION_ID"] = _PIPELINE_SESSION_ID

# Quiet noisy ML/HTTP libraries (env vars must be set before they import).
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
for _n in ("httpx", "urllib3"):
    logging.getLogger(_n).setLevel(logging.WARNING)
for _n in ("huggingface_hub", "sentence_transformers", "transformers", "LiteLLM"):
    logging.getLogger(_n).setLevel(logging.ERROR)

_DEFAULT_SESSION_FILE = os.path.join(".aider_factory", ".oracle_session.json")
TRANSCRIPT_FILE = os.path.join(".aider_factory", ".oracle_chat.history.md")
_ORACLE_PROCESS_SESSION_COST = 0.0

# Terminal color for oracle debate turns. Configurable via PIPELINE_COLOR_ORACLE env var
# (set by run_workflow.py from the YAML `colors:` block). Default: soft rose #d3869b.
_ORACLE_COLOR = os.environ.get("PIPELINE_COLOR_ORACLE", "\033[38;2;211;134;155m")
_RESET = "\033[0m"


def _session_file():
    """Return the active session file path. Overridable via ORACLE_SESSION_FILE
    env var for debate-specific sessions that survive the apply phase cleanup."""
    return os.environ.get("ORACLE_SESSION_FILE", _DEFAULT_SESSION_FILE)


def _session_cost_file():
    """Sidecar for cumulative oracle session cost (Aider-style 'session' total)."""
    return _session_file() + ".costs.json"


SYSTEM_PROMPT = (
    "You are the Knowledge Oracle, a side agent consulted by a coding architect inside "
    "an Aider session. Answer concisely and precisely. Ground every answer in the "
    "provided CONTEXT from the knowledge base. If the context is insufficient, say so "
    "plainly. Prefer exact formulas, definitions, and cite the source document."
)


def _load_session():
    sf = _session_file()
    if os.path.exists(sf):
        try:
            with open(sf, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def _save_session(messages):
    sf = _session_file()
    os.makedirs(os.path.dirname(sf), exist_ok=True)
    with open(sf, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


try:
    from aider_factory.python.cost_tracker import (
        load_session_cost as _load_session_cost,
        save_session_cost as _save_session_cost,
        clear_session as _clear_session,
        response_content as _response_content,
        litellm_cost_line as _litellm_cost_line,
    )
except ImportError:
    from cost_tracker import (
        load_session_cost as _load_session_cost,
        save_session_cost as _save_session_cost,
        clear_session as _clear_session,
        response_content as _response_content,
        litellm_cost_line as _litellm_cost_line,
    )


def _rrf_merge(result_lists, k, c=60):
    """Reciprocal Rank Fusion across per-table hit lists -> one deterministic top-k.

    Pure arithmetic (score = sum of 1/(c+rank)); a chunk appearing near the top of
    several tables ranks higher. Dedup key = (source_file, text prefix)."""
    scores, keep = {}, {}
    for rows in result_lists:
        for rank, r in enumerate(rows):
            key = (r.get("source_file", ""), (r.get("text", "") or "")[:64])
            scores[key] = scores.get(key, 0.0) + 1.0 / (c + rank)
            keep[key] = r
    ranked = sorted(scores, key=scores.get, reverse=True)[:k]
    return [keep[key] for key in ranked]


def _retrieve(query, k):
    """Grounding snippets from the active job's LanceDB, or '' if unavailable.

    Default (ORACLE_COLLECTION unset or '*') fuses ALL tables in the dir via RRF -> a
    unified code+docs answer. A concrete ORACLE_COLLECTION targets one table.
    ORACLE_TYPE_FILTER ('code'|'docs', set by --type) narrows the fuse to one corpus.
    """
    from rag_manager import embed_texts

    db_dir = os.environ.get("ORACLE_RAG_DB_DIR")
    collection = os.environ.get("ORACLE_COLLECTION", "knowledge")
    backend = os.environ.get("ORACLE_EMBED_BACKEND", "sentence-transformers")
    api_base = os.environ.get("ORACLE_EMBED_API_BASE")
    model = os.environ.get("ORACLE_EMBED_MODEL", "gemini/text-embedding-004")
    prefix = os.environ.get("ORACLE_QUERY_PREFIX", "")
    type_filter = os.environ.get("ORACLE_TYPE_FILTER", "")

    if not db_dir:
        print("[oracle] WARNING: ORACLE_RAG_DB_DIR is not set. Cannot retrieve chunks.", file=sys.stderr)
        return ""
    if not os.path.isdir(db_dir):
        print(f"[oracle] WARNING: RAG database directory does not exist: {db_dir}", file=sys.stderr)
        return ""

    if backend == "openai" and api_base:
        os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")
        import requests

        try:
            requests.get(f"{api_base}/models", timeout=10).raise_for_status()
        except Exception as e:
            print(
                f"[embed] endpoint unreachable at {api_base}: {e}; aborting.",
                file=sys.stderr,
            )
            sys.exit(2)

    try:
        import lancedb

        db = lancedb.connect(db_dir)
        _n = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        all_tables = list(getattr(_n, "tables", _n))
    except Exception:
        return ""

    # Choose tables: concrete collection -> single table/fused prefix; '*'/unset -> fuse all
    if collection and collection != "*":
        if collection in all_tables:
            tables = [collection]
        else:
            tables = [t for t in all_tables if t.startswith(collection + "_")]
            if type_filter == "code":
                tables = [t for t in tables if t.endswith("_code")]
            elif type_filter == "docs":
                tables = [t for t in tables if t.endswith("_docs")]
    else:
        tables = list(all_tables)
        if type_filter == "code":
            tables = [t for t in tables if t.endswith("_code")]
        elif type_filter == "docs":
            tables = [t for t in tables if t.endswith("_docs")]
    if not tables:
        return ""

    # Truncate the query to fit the embedding model's context window. In debate
    # mode the "query" is the full prompt (code files + architect proposal) which
    # can be 30K+ chars — far beyond the embedding context. Keeping the query
    # short (~500-800 tokens) produces a focused embedding vector that retrieves
    # structurally similar patterns rather than broadly related code.
    _MAX_EMBED_CHARS = 6000
    embed_input = prefix + query[:_MAX_EMBED_CHARS]
    try:
        qvec = embed_texts([embed_input], backend, model, api_base)[0]
    except Exception as e:
        return f"[knowledge base unavailable: {e}]"

    per_table = []
    for t in tables:
        try:
            per_table.append(db.open_table(t).search(qvec).limit(k).to_list())
        except Exception as e:
            print(
                f"[oracle] warning: table '{t}' unavailable ({e}); skipping.",
                file=sys.stderr,
            )
            continue

    rows = (
        _rrf_merge(per_table, k)
        if len(per_table) > 1
        else (per_table[0] if per_table else [])
    )
    if not rows:
        return ""

    def _cite(r):
        loc = f":{r['line_start']}-{r['line_end']}" if r.get("line_start") else ""
        return f"[source: {r.get('source_type', 'doc')} | {r.get('source_file', 'unknown')}{loc}]"

    return "\n\n---\n\n".join(
        f"{_cite(r)}\n{(r.get('text', '') or '').strip()}" for r in rows
    )


def _append_transcript(question, answer, context):
    os.makedirs(os.path.dirname(TRANSCRIPT_FILE), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(TRANSCRIPT_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n## {stamp}\n\n**Q:** {question}\n\n")
        if context:
            f.write(
                "<details><summary>retrieved context</summary>\n\n"
                f"{context}\n\n</details>\n\n"
            )
        f.write(f"**A:** {answer}\n")


def _validate_oracle_response(answer_text):
    """Instantly runs --claims-only validation on the Oracle's generated response."""
    if os.environ.get("ORACLE_CLAIMS_ONLY") != "1":
        return

    import tempfile
    import validator

    fd, tmp_file = tempfile.mkstemp(suffix=".md", text=True)
    os.close(fd)  # Close the file descriptor immediately to prevent leaks
    
    with open(tmp_file, "w", encoding="utf-8") as f:
        f.write(answer_text)

    report_path = os.path.join(os.getcwd(), ".aider_factory", "temp", "oracle_claims_report.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    class ValArgs:
        pass
    a = ValArgs()
    a.file = tmp_file
    a.report = report_path
    a.claims_only = True
    a.no_print = os.environ.get("ORACLE_NO_PRINT") == "1"
    a.db = os.environ.get("ORACLE_RAG_DB_DIR")
    a.collection = os.environ.get("ORACLE_COLLECTION")
    try:
        a.top_k = int(os.environ.get("ORACLE_TOP_K", "5"))
    except (ValueError, TypeError):
        a.top_k = 5
    try:
        a.region_threshold = float(os.environ.get("ORACLE_REGION_THRESHOLD", "0.60"))
    except (ValueError, TypeError):
        a.region_threshold = 0.60
    try:
        a.entail_threshold = float(os.environ.get("GROUNDING_ENTAIL_THRESHOLD", "0.5"))
    except (ValueError, TypeError):
        a.entail_threshold = 0.5
    a.grounding_model = os.environ.get("GROUNDING_AGENT_MODEL")
    a.grounding_api_base = os.environ.get("GROUNDING_AGENT_API_BASE")
    a.grounding_api_key = os.environ.get("GROUNDING_AGENT_API_KEY")

    if not a.no_print:
        print(f"\n[oracle-validate] Verifying claims in response...", file=sys.stderr)
        
    rc = validator._run_claims_only(a)

    if rc == 0:
        if not a.no_print:
            print(f"[oracle-validate] ✅ All claims grounded.", file=sys.stderr)
    else:
        if not a.no_print:
            print(f"[oracle-validate] ⚠️  Unsupported claims detected!", file=sys.stderr)

    try:
        os.remove(tmp_file)
    except OSError:
        pass


def _full_document(db_dir, collection):
    """Return the ENTIRE text of a single collection's table (no similarity search).

    Used by --auto so a whole-paper job (e.g. a literature review) sees every chunk,
    not just the top-k closest to a query. Returns '' if the table is unavailable.
    """
    if not db_dir or not os.path.isdir(db_dir) or collection == "*":
        return ""
    try:
        import lancedb

        db = lancedb.connect(db_dir)
        table = db.open_table(collection)  # raises if the table doesn't exist
        rows = table.to_arrow().to_pylist()  # full table dump, insertion order
    except Exception:
        return ""
    if not rows:
        return ""
    src = rows[0].get("source_file", "unknown")
    body = "\n\n".join((r.get("text", "") or "").strip() for r in rows)
    return f"[source: {src}]\n{body}"


def _run_auto():
    """Programmatic, no-Aider job: fill a template from one collection's knowledge
    and write the synthesized result straight to disk. Driven entirely by env vars
    set by orchestrate.py:

        ORACLE_AGENT_MODEL / ORACLE_AGENT_API_BASE / ORACLE_AGENT_API_KEY
        ORACLE_RAG_DB_DIR / ORACLE_COLLECTION / ORACLE_TOP_K
        ORACLE_JOB_TEMPLATE  -> instruction/template file (the "query")
        ORACLE_JOB_OUT       -> output file to write the answer to
        ORACLE_JOB_FULLDOC   -> "1" = whole-document context, "0" = top_k search

    stdout = one confirmation line; everything else -> stderr.
    """
    template_path = os.environ.get("ORACLE_JOB_TEMPLATE")
    out_path = os.environ.get("ORACLE_JOB_OUT")
    full_doc = os.environ.get("ORACLE_JOB_FULLDOC", "1") not in (
        "0",
        "false",
        "False",
        "",
    )
    model = os.environ.get("ORACLE_AGENT_MODEL")
    api_base = os.environ.get("ORACLE_AGENT_API_BASE")  # None for gemini/
    api_key = os.environ.get("ORACLE_AGENT_API_KEY")  # 'sk-dummy' for local
    db_dir = os.environ.get("ORACLE_RAG_DB_DIR")
    collection = os.environ.get("ORACLE_COLLECTION", "knowledge")
    try:
        k = int(os.environ.get("ORACLE_TOP_K", "5"))
    except ValueError:
        k = 5

    if not model:
        print("[oracle-job] ORACLE_AGENT_MODEL not set; skipping.", file=sys.stderr)
        return 1
    if not template_path or not os.path.isfile(template_path):
        print(f"[oracle-job] template not found: {template_path}", file=sys.stderr)
        return 1
    if not out_path:
        print("[oracle-job] ORACLE_JOB_OUT not set; nothing to write.", file=sys.stderr)
        return 1

    with open(template_path, "r", encoding="utf-8") as f:
        instructions = f.read()

    answer = None
    cost_line = ""
    # Keep stdout pristine: stray library prints during retrieval / the model call
    # are redirected to stderr; only the final confirmation lands on stdout.
    with contextlib.redirect_stdout(sys.stderr):
        context = (
            _full_document(db_dir, collection)
            if full_doc
            else _retrieve(instructions, k)
        )

        prompt = ""
        rf_str = os.environ.get("ORACLE_JOB_READ_FILES")
        if rf_str:
            _ctx = []
            for rf in rf_str.split("\x1e"):
                if os.path.isfile(rf):
                    try:
                        with open(rf, encoding="utf-8") as fh:
                            _ctx.append(f"File: {rf}\n```\n{fh.read()}\n```")
                    except Exception:
                        pass
            if _ctx:
                prompt += "<project_files>\n" + "\n\n".join(_ctx) + "\n</project_files>\n\n"

        if context:
            prompt += f"<knowledge_base>\n{context}\n</knowledge_base>\n\n"
        else:
            print(
                f"[oracle-job] WARNING: no context for collection '{collection}' "
                f"(db: {db_dir}); answering from instructions only.",
                file=sys.stderr,
            )

        prompt += f"<instructions>\n{instructions}\n</instructions>"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            import litellm

            kwargs = {
                "model": model,
                "messages": messages,
                "custom_headers": {"x-litellm-session-id": _PIPELINE_SESSION_ID}
            }
            if api_base:
                kwargs["api_base"] = api_base
            if api_key:
                kwargs["api_key"] = api_key
            resp = litellm.completion(**kwargs)
            answer = _response_content(resp)
            cost_line = _litellm_cost_line(resp, persist_session=False)
        except Exception as e:
            print(f"[oracle-job] model call failed: {e}", file=sys.stderr)
            return 1

        out_dir = os.path.dirname(os.path.abspath(out_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(answer if answer is not None else "")

    nblocks = context.count("[source:") if context else 0
    print(
        f"[oracle-job] collection={collection} · {nblocks} source block(s) · "
        f"model={model} -> {out_path}",
        file=sys.stderr,
    )
    print(f"[oracle] wrote {out_path}")
    if cost_line:
        print(cost_line, file=sys.stderr)
    return 0


def _resolve_file_path(path_str, base_dir=None):
    """Shared path resolver for all --file parameters across the AI Factory.

    1. Expands user tilde (~/ -> /home/user).
    2. Resolves relative paths against base_dir or current working repo root (os.getcwd()).
    3. Returns normalized absolute path string (or None if path_str is empty/None).
    """
    if not path_str:
        return None
    expanded = os.path.expanduser(str(path_str).strip())
    if not os.path.isabs(expanded):
        base = base_dir or os.getcwd()
        expanded = os.path.join(base, expanded)
    return os.path.normpath(expanded)


def _build_question(argv):
    """Build the question from positional args + an optional single `--file <path>`.

    Returns (question, display): `question` is the full text sent to the model
    (inline note first, then the file's contents); `display` is a compact form
    stored in the session/transcript so a large --file payload never bloats
    memory. Returns (None, None) if --file was given but could not be read.
    """
    args = list(argv)
    inline_parts = []
    file_path = None
    i = 0
    while i < len(args):
        if args[i] == "--file":
            if i + 1 >= len(args):
                print("[oracle] --file requires a path", file=sys.stderr)
                return None, None
            file_path = args[i + 1]
            i += 2
            continue
        inline_parts.append(args[i])
        i += 1
    inline = " ".join(inline_parts).strip()

    if file_path is None:
        return inline, inline
    resolved = _resolve_file_path(file_path)
    if not os.path.isfile(resolved):
        print(f"[oracle] --file not found: {resolved}", file=sys.stderr)
        return None, None
    with open(resolved, "r", encoding="utf-8") as f:
        file_text = f.read()
    question = f"{inline}\n\n{file_text}" if inline else file_text
    display = (
        f"{inline} [file: {resolved}]".strip() if inline else f"[file: {resolved}]"
    )
    return question, display


_RETRIEVE_MODES = ("top_k", "no_retrieve", "full_document")


def _extract_overrides(argv):
    """Consume target-overrides from argv and apply them to the environment.

    `--collection <name>` overrides ORACLE_COLLECTION (the LanceDB table to open;
    e.g. a single paper's table in a batch=false collection). `--db <dir>`
    overrides ORACLE_RAG_DB_DIR (the lancedb directory). `--mode <m>` overrides
    ORACLE_RETRIEVE_MODE for this call (top_k|no_retrieve|full_document). `--list`
    requests a listing of the tables and exits. Returns (remaining_args, do_list, did_clear, maintenance_action, maintenance_target).
    """
    os.environ.pop("ORACLE_EXPLICIT_COLLECTION", None)
    out, do_list, did_clear, i, args = [], False, False, 0, list(argv)
    no_rag_forced = False
    maintenance_action = None
    maintenance_target = None
    while i < len(args):
        a = args[i]
        if a == "--clear":
            _clear_session()
            # Also clear debate-specific session files
            _project = os.getcwd()
            for _df in [
                os.path.join(_project, ".aider_factory", ".oracle_debate_session.json"),
                os.path.join(_project, ".aider_factory", ".debate_aider_history.md"),
            ]:
                if os.path.exists(_df):
                    try:
                        os.remove(_df)
                    except OSError:
                        pass
            did_clear = True
            i += 1
            if i < len(args) and args[i].strip().lower() == "oracle":
                i += 1
            continue
        if a == "--no-rag":
            no_rag_forced = True
            os.environ["ORACLE_NO_RAG_INGEST"] = "1"
            i += 1
            continue
        if a == "--claims-only":
            os.environ["ORACLE_CLAIMS_ONLY"] = "1"
            i += 1
            continue
        if a == "--no-print":
            os.environ["ORACLE_NO_PRINT"] = "1"
            i += 1
            continue
        if a == "--debate":
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                os.environ["ORACLE_DEBATE_MODE"] = args[i + 1].strip().lower()
                i += 2
            else:
                os.environ["ORACLE_DEBATE_MODE"] = "code"  # default to code mode
                i += 1
            continue
        if a == "--type":
            if i + 1 < len(args) and args[i + 1].strip().lower() in ("code", "docs"):
                os.environ["ORACLE_TYPE_FILTER"] = args[i + 1].strip().lower()
                i += 2
                continue
            print("[oracle] --type must be code|docs", file=sys.stderr)
            return out, do_list, did_clear, None, None
        if a == "--loops":
            if i + 1 < len(args):
                os.environ["ORACLE_DEBATE_LOOPS"] = args[i + 1].strip()
                i += 2
            else:
                i += 1
            continue
        if a == "--rounds":
            if i + 1 < len(args):
                os.environ["ORACLE_DEBATE_ROUNDS"] = args[i + 1].strip()
                i += 2
            else:
                i += 1
            continue
        if a == "--collection":
            if i + 1 < len(args):
                os.environ["ORACLE_COLLECTION"] = args[i + 1]
                os.environ["ORACLE_EXPLICIT_COLLECTION"] = "1"
                i += 2
                continue
            print("[oracle] --collection requires a name", file=sys.stderr)
            return out, do_list, did_clear, None, None
        if a == "--db":
            if i + 1 < len(args):
                os.environ["ORACLE_RAG_DB_DIR"] = args[i + 1]
                i += 2
                continue
            print("[oracle] --db requires a path", file=sys.stderr)
            return out, do_list, did_clear, None, None
        if a == "--mode":
            if i + 1 < len(args):
                m = args[i + 1].strip().lower()
                if m in _RETRIEVE_MODES:
                    os.environ["ORACLE_RETRIEVE_MODE"] = m
                else:
                    print(
                        f"[oracle] --mode must be one of {'|'.join(_RETRIEVE_MODES)} (got '{m}'); ignoring",
                        file=sys.stderr,
                    )
                i += 2
                continue
            print("[oracle] --mode requires a value", file=sys.stderr)
            return out, do_list, did_clear, None, None
        if a == "--list":
            do_list = True
            i += 1
            continue
        if a == "--list-files":
            maintenance_action = "list-files"
            i += 1
            continue
        if a == "--rm-table":
            if i + 1 < len(args):
                maintenance_action = "rm-table"
                maintenance_target = args[i + 1]
                i += 2
                continue
            print("[oracle] --rm-table requires a table name", file=sys.stderr)
            return out, do_list, did_clear, None, None
        if a == "--rm-file":
            if i + 1 < len(args):
                maintenance_action = "rm-file"
                maintenance_target = args[i + 1]
                i += 2
                continue
            print("[oracle] --rm-file requires a filename", file=sys.stderr)
            return out, do_list, did_clear, None, None
        if a == "--rm-db":
            maintenance_action = "rm-db"
            i += 1
            continue
        if a == "--add-file":
            targets = []
            i += 1
            while i < len(args) and not args[i].startswith("-"):
                targets.append(args[i])
                i += 1
            if not targets:
                print("[oracle] --add-file requires at least one path", file=sys.stderr)
                return out, do_list, did_clear, None, None
            maintenance_action = "add-file"
            maintenance_target = targets
            continue
        if a == "--add-table":
            targets = []
            i += 1
            while i < len(args) and not args[i].startswith("-"):
                targets.append(args[i])
                i += 1
            if not targets:
                print(
                    "[oracle] --add-table requires at least one path", file=sys.stderr
                )
                return out, do_list, did_clear, None, None
            maintenance_action = "add-table"
            maintenance_target = targets
            continue
        if a in ("--workers", "--num-cores", "-w"):
            if i + 1 < len(args):
                os.environ["ORACLE_WEB_WORKERS"] = args[i + 1]
                i += 2
                continue
            print("[oracle] --workers requires an integer count", file=sys.stderr)
            return out, do_list, did_clear, None, None
        if a in ("--add-web", "--web-url"):
            maintenance_action = "add-web"
            targets = []
            i += 1
            while i < len(args):
                arg = args[i]
                if arg == "--file":
                    i += 1
                    if i < len(args):
                        targets.append(f"--file:{args[i]}")
                        i += 1
                    else:
                        print("[oracle] --file requires a file path", file=sys.stderr)
                        return out, do_list, did_clear, None, None
                elif arg == "--no-rag":
                    os.environ["ORACLE_RETRIEVE_MODE"] = "no_retrieve"
                    os.environ["ORACLE_NO_RAG_INGEST"] = "1"
                    i += 1
                elif arg in ("--workers", "--num-cores", "-w") and i + 1 < len(args):
                    os.environ["ORACLE_WEB_WORKERS"] = args[i + 1]
                    i += 2
                elif arg.startswith("-") and not arg.startswith("--file:"):
                    break
                else:
                    targets.append(arg)
                    i += 1
            if not targets:
                print(
                    "[oracle] --add-web requires at least one URL or --file <path>",
                    file=sys.stderr,
                )
                return out, do_list, did_clear, None, None
            maintenance_target = targets
            continue
        out.append(a)
        i += 1

    if no_rag_forced:
        os.environ["ORACLE_RETRIEVE_MODE"] = "no_retrieve"

    # Auto-derive DB from collection. If the user passed --collection explicitly,
    # it MUST override any leaked ORACLE_RAG_DB_DIR from the environment.
    coll = os.environ.get("ORACLE_COLLECTION")
    explicit_coll = os.environ.get("ORACLE_EXPLICIT_COLLECTION") == "1"
    
    if coll and (explicit_coll or not os.environ.get("ORACLE_RAG_DB_DIR")):
        # If the collection contains a slash, treat it as a global path
        if "/" in coll or "\\" in coll:
            abs_coll = os.path.abspath(os.path.normpath(coll))
            os.environ["ORACLE_COLLECTION"] = os.path.basename(abs_coll)
            os.environ["ORACLE_RAG_DB_DIR"] = os.path.join(abs_coll, "lancedb")
        else:
            # Otherwise, treat it as a local project collection
            os.environ["ORACLE_RAG_DB_DIR"] = os.path.join(os.getcwd(), ".aider_factory", "markdown", "lanceDB", coll, "lancedb")

    return out, do_list, did_clear, maintenance_action, maintenance_target


def _list_tables():
    """Print the LanceDB tables in ORACLE_RAG_DB_DIR (one per line) to stdout."""
    db_dir = os.environ.get("ORACLE_RAG_DB_DIR")
    if not db_dir or not os.path.isdir(db_dir):
        print(
            f"[oracle] no lancedb dir to list (ORACLE_RAG_DB_DIR={db_dir})",
            file=sys.stderr,
        )
        return 0
    names = []
    with contextlib.redirect_stdout(sys.stderr):
        try:
            import lancedb

            db = lancedb.connect(db_dir)
            _n = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
            names = list(getattr(_n, "tables", _n))
        except Exception as e:
            print(f"[oracle] cannot list tables: {e}", file=sys.stderr)
    for n in names:
        print(n)
    print(f"[oracle] {len(names)} table(s) in {db_dir}", file=sys.stderr)
    return 0


def _list_files():
    """Print all unique source files across all tables in the active collection."""
    db_dir = os.environ.get("ORACLE_RAG_DB_DIR")
    collection = os.environ.get("ORACLE_COLLECTION", "knowledge")
    if not db_dir or not os.path.isdir(db_dir):
        print(
            f"[oracle] no lancedb dir to list files (ORACLE_RAG_DB_DIR={db_dir})",
            file=sys.stderr,
        )
        return 1

    try:
        import lancedb

        db = lancedb.connect(db_dir)
        _n = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        all_tables = list(getattr(_n, "tables", _n))
    except Exception as e:
        print(f"[oracle] cannot connect to database: {e}", file=sys.stderr)
        return 1

    if collection and collection != "*":
        tables = [
            t for t in all_tables if t == collection or t.startswith(collection + "_")
        ]
    else:
        tables = list(all_tables)

    if not tables:
        print(
            f"[oracle] no tables found for collection '{collection}'", file=sys.stderr
        )
        return 0

    print(f"[oracle] Scanning files in collection '{collection}'...", file=sys.stderr)
    for tname in sorted(tables):
        try:
            tbl = db.open_table(tname)
            if "source_file" not in tbl.schema.names:
                continue
            rows = tbl.search().select(["source_file"]).to_list()
            unique_files = sorted(
                list(set(r["source_file"] for r in rows if "source_file" in r))
            )
            print(
                f"\nTable: {tname} ({tbl.count_rows()} chunks, {len(unique_files)} files)"
            )
            for uf in unique_files:
                print(f"  - {uf}")
        except Exception as e:
            print(f"[oracle] error reading table {tname}: {e}", file=sys.stderr)
    return 0


def _remove_table(table_name):
    """Drop a specific table from the active database."""
    db_dir = os.environ.get("ORACLE_RAG_DB_DIR")
    if not db_dir or not os.path.isdir(db_dir):
        print(f"[oracle] no lancedb dir (ORACLE_RAG_DB_DIR={db_dir})", file=sys.stderr)
        return 1

    try:
        import lancedb

        db = lancedb.connect(db_dir)
        _n = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        all_tables = list(getattr(_n, "tables", _n))

        if table_name not in all_tables:
            print(
                f"[oracle] table '{table_name}' does not exist in the database.",
                file=sys.stderr,
            )
            return 1

        db.drop_table(table_name)
        print(
            f"[oracle] Table '{table_name}' successfully dropped from the database.",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[oracle] failed to drop table '{table_name}': {e}", file=sys.stderr)
        return 1
    return 0


def _remove_file(filename):
    """Surgically delete all chunks belonging to a file across all tables in the active collection."""
    db_dir = os.environ.get("ORACLE_RAG_DB_DIR")
    collection = os.environ.get("ORACLE_COLLECTION", "knowledge")
    if not db_dir or not os.path.isdir(db_dir):
        print(f"[oracle] no lancedb dir (ORACLE_RAG_DB_DIR={db_dir})", file=sys.stderr)
        return 1

    try:
        import lancedb

        db = lancedb.connect(db_dir)
        _n = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        all_tables = list(getattr(_n, "tables", _n))
    except Exception as e:
        print(f"[oracle] failed to connect to database: {e}", file=sys.stderr)
        return 1

    if collection and collection != "*":
        tables = [
            t for t in all_tables if t == collection or t.startswith(collection + "_")
        ]
    else:
        tables = list(all_tables)

    total_deleted = 0
    print(
        f"[oracle] Surgically removing file '{filename}' from collection '{collection}'...",
        file=sys.stderr,
    )

    for tname in tables:
        try:
            tbl = db.open_table(tname)
            if "source_file" not in tbl.schema.names:
                continue

            count_before = tbl.count_rows()
            where_clause = (
                f"source_file = '{filename}' OR source_file LIKE '%/{filename}'"
            )
            tbl.delete(where=where_clause)

            count_after = tbl.count_rows()
            deleted = count_before - count_after

            if deleted > 0:
                print(
                    f"  - Table '{tname}': Deleted {deleted} chunk(s).", file=sys.stderr
                )
                total_deleted += deleted

                if count_after == 0:
                    db.drop_table(tname)
                    print(
                        f"  - Table '{tname}' is now empty; dropped table.",
                        file=sys.stderr,
                    )
        except Exception as e:
            print(f"[oracle] error processing table {tname}: {e}", file=sys.stderr)

    if total_deleted > 0:
        print(
            f"[oracle] Success! Surgically removed {total_deleted} total chunk(s) from the database.",
            file=sys.stderr,
        )
    else:
        print(
            f"[oracle] No matching chunks found for file '{filename}' in the active collection.",
            file=sys.stderr,
        )
    return 0


def _remove_db():
    """Surgically delete ONLY the lancedb directory for the active collection, preserving OCR files."""
    db_dir = os.environ.get("ORACLE_RAG_DB_DIR")
    collection = os.environ.get("ORACLE_COLLECTION", "knowledge")
    if not db_dir or not os.path.isdir(db_dir):
        print(
            f"[oracle] no lancedb dir to remove (ORACLE_RAG_DB_DIR={db_dir})",
            file=sys.stderr,
        )
        return 1

    import shutil

    print(
        f"[oracle] Surgically wiping vector database for collection '{collection}'...",
        file=sys.stderr,
    )
    print(f"[oracle] Target: {db_dir}", file=sys.stderr)
    try:
        shutil.rmtree(db_dir)
        print(
            f"[oracle] Success! Vector database wiped. OCR text cache and images preserved.",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[oracle] failed to remove database directory: {e}", file=sys.stderr)
        return 1
    return 0


def _resolve_active_collection(cfg):
    """Resolve collection name for maintenance commands (--add-file, --add-web, etc.).

    Explicit CLI --collection overrides take highest priority. Otherwise, reads the
    phase collection_name from config, avoiding inherited per-doc table names.
    """
    if os.environ.get("ORACLE_EXPLICIT_COLLECTION") == "1" and os.environ.get("ORACLE_COLLECTION"):
        return os.environ.get("ORACLE_COLLECTION")

    phases = cfg.get("phases", [])
    if phases:
        active_phase = None
        phase_idx_str = os.environ.get("ORACLE_PHASE_INDEX")
        if phase_idx_str is not None:
            try:
                idx = int(phase_idx_str)
                if 0 <= idx < len(phases):
                    active_phase = phases[idx]
            except ValueError:
                pass
        if active_phase is None:
            active_phase = next((ph for ph in phases if ph.get("enabled")), phases[0])

        rag_phase = active_phase.get("rag", {}) or {}
        if isinstance(rag_phase, dict) and rag_phase.get("collection_name"):
            return rag_phase.get("collection_name")

    return "knowledge"


def _add_maintenance(action, paths):
    """Implement --add-file and --add-table maintenance commands."""
    import shutil

    import rag_manager
    import yaml

    # 1. Resolve project directory and default directories
    project_dir = os.getcwd()
    context_root = os.path.join(project_dir, ".aider_factory", "markdown", "lanceDB")

    # 2. Resolve active configuration path automatically on disk
    config_path = os.environ.get("ORACLE_CONFIG_FILE")
    if not config_path or not os.path.exists(config_path):
        config_path = os.path.join(project_dir, ".aider_factory", ".env.yml")
    if not os.path.exists(config_path):
        config_path = os.path.join(project_dir, ".env.yml")

    if not os.path.exists(config_path):
        print(f"[oracle] config file not found: {config_path}", file=sys.stderr)
        return 1

    print(f"[oracle] Loading configuration from: {config_path}", file=sys.stderr)
    try:
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[oracle] failed to load config: {e}", file=sys.stderr)
        return 1

    project_dir = str(cfg.get("working_directory", project_dir))
    context_root = os.path.join(project_dir, ".aider_factory", "markdown", "lanceDB")

    endpoints = cfg.get("endpoints", {}) or {}
    
    # Find the active phase to resolve models
    phases = cfg.get("phases", []) or []
    active_phase = next((ph for ph in phases if ph.get("enabled")), {}) if phases else {}
    phase_models = active_phase.get("models", {}) or {}

    # 3. Resolve active collection
    collection = _resolve_active_collection(cfg)

    # Update environment variable so rag_manager uses the correct collection
    os.environ["ORACLE_COLLECTION"] = collection

    job_dir = os.path.join(context_root, collection)
    print(f"[oracle] Active collection: {collection}", file=sys.stderr)
    print(f"[oracle] Collection directory: {job_dir}", file=sys.stderr)

    # 4. Bootstrap collection directory if it doesn't exist
    if not os.path.exists(job_dir):
        print(f"[oracle] Bootstrapping new collection directory...", file=sys.stderr)
        os.makedirs(job_dir, exist_ok=True)

    # 5. Process and copy paths
    for p in paths:
        if not os.path.exists(p):
            print(f"[oracle] Error: Path does not exist: {p}", file=sys.stderr)
            return 1

        abs_p = os.path.abspath(p)
        abs_job_dir = os.path.abspath(job_dir)

        # Check if the path is already inside the collection directory
        if abs_p.startswith(abs_job_dir + os.sep) or abs_p == abs_job_dir:
            print(
                f"[oracle] Path is already inside collection directory: {p}",
                file=sys.stderr,
            )
            continue

        # Copy file or directory
        name = os.path.basename(p)
        dest_p = os.path.join(job_dir, name)

        if os.path.isdir(p):
            if action == "file":
                print(
                    f"[oracle] Error: Cannot add directory '{p}' using --add-file. Use --add-table instead.",
                    file=sys.stderr,
                )
                return 1
            print(f"[oracle] Copying directory {p} -> {dest_p}...", file=sys.stderr)
            if os.path.exists(dest_p):
                # Merge directory contents recursively
                for root, dirs, files in os.walk(p):
                    rel_path = os.path.relpath(root, p)
                    target_dir = os.path.join(dest_p, rel_path)
                    os.makedirs(target_dir, exist_ok=True)
                    for f in files:
                        shutil.copy2(os.path.join(root, f), os.path.join(target_dir, f))
            else:
                shutil.copytree(p, dest_p)
        else:
            print(f"[oracle] Copying file {p} -> {dest_p}...", file=sys.stderr)
            shutil.copy2(p, dest_p)

    # 6. Determine settings from active phase
    batch_setting = True
    chunk_size = 800
    chunk_overlap = 100
    cer_thresh = 0.05
    max_retries = 2
    parallel = 1
    ocr_max_tokens = 4096
    code_chunk_size = 2000
    
    phases = cfg.get("phases", [])
    if phases:
        active_phase = next((ph for ph in phases if ph.get("enabled")), phases[0])
        phase_rag = active_phase.get("rag", {}) or {}
        phase_val = active_phase.get("validation", {}) or {}
        batch_setting = bool(phase_rag.get("batch", True))
        chunk_size = int(phase_rag.get("chunk_size_chars", 800))
        chunk_overlap = int(phase_rag.get("chunk_overlap_chars", 100))
        cer_thresh = float(phase_rag.get("cer_threshold", 0.05))
        max_retries = int(phase_rag.get("ocr_max_retries", 2))
        parallel = int(phase_rag.get("ocr_parallel", 1))
        ocr_max_tokens = int(phase_rag.get("ocr_max_tokens", 4096))
        code_chunk_size = int(phase_rag.get("code_chunk_size", 2000))

    # Resolve embedding settings with proper fallbacks to rag blocks
    global_rag = cfg.get("rag", {}) or {}
    phase_rag = {}
    if phases:
        active_phase = next((ph for ph in phases if ph.get("enabled")), phases[0])
        phase_rag = active_phase.get("rag", {}) or {}

    embed_model = (
        phase_rag.get("embed_model")
        or global_rag.get("embed_model")
        or phase_models.get("embed_model", "gemini/text-embedding-004")
    )
    embed_api_base = (
        phase_rag.get("embed_api_base")
        or global_rag.get("embed_api_base")
        or endpoints.get("embed_api_base")
    )
    embed_backend = (
        phase_rag.get("embed_backend")
        or global_rag.get("embed_backend")
        or ("openai" if "embedding" in embed_model.lower() else "sentence-transformers")
    )
    if embed_api_base and embed_backend == "sentence-transformers":
        embed_backend = "openai"

    ocr_only_mode = os.environ.get("ORACLE_NO_RAG_INGEST") == "1"
    if ocr_only_mode:
        print(f"[oracle] --no-rag active: Files will be OCR'd to Markdown but NOT indexed into LanceDB.", file=sys.stderr)
    else:
        print(
            f"[oracle] Running incremental ingestion (batch={batch_setting}, model={embed_model}, backend={embed_backend})...",
            file=sys.stderr,
        )

    # 7. Call rag_manager.ingest
    try:
        success = rag_manager.ingest(
            context_root=context_root,
            collection_name=collection,
            embed_model=embed_model,
            embed_backend=embed_backend,
            embed_api_base=embed_api_base,
            chunk_size_chars=chunk_size,
            chunk_overlap_chars=chunk_overlap,
            ocr_api_base=endpoints.get("ocr_api_base"),
            ocr_agent=phase_models.get("ocr_agent"),
            ocr_prompt=rag_manager.DEFAULT_OCR_PROMPT,
            overwrite=False,  # CRITICAL: incremental update!
            cer_threshold=cer_thresh,
            ocr_max_retries=max_retries,
            ocr_parallel=parallel,
            ocr_max_tokens=ocr_max_tokens,
            code_chunk_size=code_chunk_size,
            batch=batch_setting,
            ocr_only=ocr_only_mode,
        )
        if success:
            print("[oracle] Ingestion completed successfully.", file=sys.stderr)
            return 0
        else:
            print(
                "[oracle] Ingestion completed but no new files were added or an error occurred.",
                file=sys.stderr,
            )
            return 0
    except Exception as e:
        print(f"[oracle] Ingestion failed with error: {e}", file=sys.stderr)
        return 1


def _add_web_maintenance(urls):
    """Implement --add-web maintenance command: fetch web content, convert to <stem>.md / <stem>.pdf,
    and incrementally ingest into LanceDB via rag_manager.ingest()."""
    import rag_manager
    import rag_web
    import yaml

    project_dir = os.getcwd()
    context_root = os.path.join(project_dir, ".aider_factory", "markdown", "lanceDB")

    config_path = os.environ.get("ORACLE_CONFIG_FILE")
    if not config_path or not os.path.exists(config_path):
        config_path = os.path.join(project_dir, ".aider_factory", ".env.yml")
    if not os.path.exists(config_path):
        config_path = os.path.join(project_dir, ".env.yml")

    if not os.path.exists(config_path):
        print(f"[oracle] config file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[oracle] failed to load config: {e}", file=sys.stderr)
        return 1

    project_dir = str(cfg.get("working_directory", project_dir))
    context_root = os.path.join(project_dir, ".aider_factory", "markdown", "lanceDB")

    endpoints = cfg.get("endpoints", {}) or {}
    phases = cfg.get("phases", []) or []
    active_phase = next((ph for ph in phases if ph.get("enabled")), {}) if phases else {}
    phase_models = active_phase.get("models", {}) or {}
    collection = _resolve_active_collection(cfg)
    os.environ["ORACLE_COLLECTION"] = collection

    job_dir = os.path.join(context_root, collection)
    os.makedirs(job_dir, exist_ok=True)

    # Process file inputs (--file <path> or positional file paths) and direct URLs
    expanded_urls = []
    for t in urls:
        is_explicit_file = t.startswith("--file:")
        raw_path = t[7:] if is_explicit_file else t

        resolved_path = _resolve_file_path(raw_path, project_dir)

        if is_explicit_file or os.path.isfile(resolved_path):
            if not os.path.isfile(resolved_path):
                print(
                    f"[oracle] Error: URL file not found: {resolved_path}",
                    file=sys.stderr,
                )
                return 1
            print(
                f"[oracle] Reading URLs from file: {resolved_path}", file=sys.stderr
            )
            try:
                with open(resolved_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            expanded_urls.append(line)
            except Exception as e:
                print(
                    f"[oracle] Error reading URL file '{resolved_path}': {e}",
                    file=sys.stderr,
                )
                return 1
        else:
            expanded_urls.append(t)

    try:
        workers = int(os.environ.get("ORACLE_WEB_WORKERS", "1"))
    except ValueError:
        workers = 1

    success_count, skipped_count = rag_web.fetch_urls_batch(expanded_urls, job_dir, workers=workers)

    print(f"\n[rag-web] Batch Web Download Summary:", file=sys.stderr)
    print(f"          - Successfully Ingested: {success_count} file(s)", file=sys.stderr)
    print(f"          - Skipped / Failed:        {skipped_count} file(s)", file=sys.stderr)

    if success_count == 0:
        print("[oracle] No web files were successfully fetched.", file=sys.stderr)
        return 1

    # Check for --no-rag flag override (Markdown conversion only, skip LanceDB indexing)
    if os.environ.get("ORACLE_NO_RAG_INGEST") == "1":
        print(f"[oracle] --no-rag active: Saved Markdown files to '{job_dir}'. Bypassing LanceDB vector indexing.", file=sys.stderr)
        return 0

    batch_setting = True
    chunk_size = 800
    chunk_overlap = 100
    cer_thresh = 0.05
    max_retries = 2
    parallel = 1
    ocr_max_tokens = 4096
    code_chunk_size = 2000

    phases = cfg.get("phases", [])
    if phases:
        active_phase = next((ph for ph in phases if ph.get("enabled")), phases[0])
        phase_rag = active_phase.get("rag", {}) or {}
        batch_setting = bool(phase_rag.get("batch", True))
        chunk_size = int(phase_rag.get("chunk_size_chars", 800))
        chunk_overlap = int(phase_rag.get("chunk_overlap_chars", 100))
        cer_thresh = float(phase_rag.get("cer_threshold", 0.05))
        max_retries = int(phase_rag.get("ocr_max_retries", 2))
        parallel = int(phase_rag.get("ocr_parallel", 1))
        ocr_max_tokens = int(phase_rag.get("ocr_max_tokens", 4096))
        code_chunk_size = int(phase_rag.get("code_chunk_size", 2000))

    # Resolve embedding settings with proper fallbacks to rag blocks
    global_rag = cfg.get("rag", {}) or {}
    phase_rag = {}
    if phases:
        active_phase = next((ph for ph in phases if ph.get("enabled")), phases[0])
        phase_rag = active_phase.get("rag", {}) or {}

    embed_model = (
        phase_rag.get("embed_model")
        or global_rag.get("embed_model")
        or phase_models.get("embed_model", "BAAI/bge-m3")
    )
    embed_api_base = (
        phase_rag.get("embed_api_base")
        or global_rag.get("embed_api_base")
        or endpoints.get("embed_api_base")
    )
    embed_backend = (
        phase_rag.get("embed_backend")
        or global_rag.get("embed_backend")
        or ("openai" if "embedding" in embed_model.lower() else "sentence-transformers")
    )
    if embed_api_base and embed_backend == "sentence-transformers":
        embed_backend = "openai"

    print(
        f"[oracle] Incremental LanceDB ingestion for collection '{collection}' (model={embed_model}, backend={embed_backend})...",
        file=sys.stderr,
    )

    try:
        success = rag_manager.ingest(
            context_root=context_root,
            collection_name=collection,
            embed_model=embed_model,
            embed_backend=embed_backend,
            embed_api_base=embed_api_base,
            chunk_size_chars=chunk_size,
            chunk_overlap_chars=chunk_overlap,
            ocr_api_base=endpoints.get("ocr_api_base"),
            ocr_agent=phase_models.get("ocr_agent"),
            ocr_prompt=rag_manager.DEFAULT_OCR_PROMPT,
            overwrite=False,
            cer_threshold=cer_thresh,
            ocr_max_retries=max_retries,
            ocr_parallel=parallel,
            ocr_max_tokens=ocr_max_tokens,
            code_chunk_size=code_chunk_size,
            batch=batch_setting,
        )
        if success:
            print("[oracle] Web ingestion completed successfully.", file=sys.stderr)
            return 0
        else:
            print(
                "[oracle] Web ingestion completed but no new chunks were added or an error occurred.",
                file=sys.stderr,
            )
            return 0
    except Exception as e:
        print(f"[oracle] Web ingestion failed with error: {e}", file=sys.stderr)
        return 1


def _run_cli_debate(question, mode, max_turns, rounds=1):
    """Executes a unified, Aider-driven pair-programming debate with perfect persistence.

    Supports multiple rounds (outer loop) and loops (inner turns per round).
    Context preservation across rounds is controlled by pass_round_history
    from the active phase's oracle_toggles (YAML config).
    """
    import contextlib
    import sys

    import deliberate
    import yaml
    from orchestrate import AiderFactory, Task

    project_dir = os.getcwd()
    factory = AiderFactory(project_dir=project_dir)

    # 1. Gather Models & Endpoints
    oracle_model = os.environ.get("ORACLE_AGENT_MODEL")
    oracle_api = os.environ.get("ORACLE_AGENT_API_BASE")
    arch_model = os.environ.get("ORACLE_ARCHITECT_MODEL") or oracle_model
    arch_api = os.environ.get("ORACLE_ARCHITECT_API_BASE") or oracle_api

    task = Task(
        id="cli_debate",
        model=arch_model,
        editor_model=oracle_model,
        architect_api_base=arch_api,
        editor_api_base=oracle_api,
    )

    # 2. Automatically load active phase files + toggles from YAML
    yaml_path = os.environ.get("ORACLE_CONFIG_FILE")
    if not yaml_path or not os.path.exists(yaml_path):
        yaml_path = os.path.join(project_dir, ".aider_factory", ".env.yml")
    if not os.path.exists(yaml_path):
        yaml_path = os.path.join(project_dir, ".env.yml")

    _reads = []
    _pass_round_history = False
    active_idx = os.environ.get("ORACLE_PHASE_INDEX")
    target_coll = os.environ.get("ORACLE_COLLECTION")
    if os.path.exists(yaml_path):
        try:
            with open(yaml_path, "r") as f:
                config = yaml.safe_load(f)
            for idx, phase in enumerate(config.get("phases", [])):
                if not phase.get("enabled", True):
                    continue
                if active_idx is not None and str(idx) != active_idx:
                    continue
                elif active_idx is None and target_coll:
                    phase_coll = (phase.get("vector_store") or {}).get("collection_name")
                    if phase_coll and phase_coll != target_coll:
                        continue
                files = phase.get("files", {})
                for k in [
                    "target_files",
                    "extra_editable_files",
                    "test_files",
                    "context_files_job",
                    "context_files_test",
                ]:
                    for f_pat in files.get(k, []) or []:
                        if f_pat and f_pat not in _reads:
                            _reads.append(f_pat)
                _ot = phase.get("escalation_debate", {}) or {}
                _pass_round_history = bool(_ot.get("pass_history", False))
                break
        except Exception:
            pass

    # 3. Session state: Aider history file (architect) + persistent oracle session
    debate_aider_history = os.path.join(
        project_dir, ".aider_factory", ".debate_aider_history.md"
    )
    _debate_session_file = os.path.join(
        project_dir, ".aider_factory", ".oracle_debate_session.json"
    )

    # 4. Determine oracle system prompt (stable across all turns)
    if mode == "code":
        oracle_sys = (
            "You are the Knowledge Oracle advising a software Architect. "
            "Judge the Architect's PROPOSAL against the context. Cite exact evidence. "
            "End with EXACTLY one line: 'VERDICT: AGREE' if sound, or "
            "'VERDICT: OBJECT - <reason>' if not."
        )
    else:
        oracle_sys = (
            "You are the Knowledge Oracle reviewing the Architect's PROPOSAL "
            "against the knowledge base. Cite verbatim source quotes. "
            "End with EXACTLY one line: 'VERDICT: AGREE' or "
            "'VERDICT: OBJECT - <reason>'."
        )

    # 5. File-list-gated session reuse.  Reload the prior debate session ONLY
    #    when the target file list is unchanged (same working context).
    #    Different files = different context = fresh start.
    #    Same files + different question = continuation (follow-up).
    #    --clear = always fresh start.
    import hashlib

    _files_hash = hashlib.sha256("\n".join(sorted(_reads)).encode("utf-8")).hexdigest()

    _session_loaded = False
    if os.path.exists(_debate_session_file):
        try:
            with open(_debate_session_file, "r", encoding="utf-8") as _sf:
                _stored = json.load(_sf)
            if isinstance(_stored, dict) and _stored.get("files_hash") == _files_hash:
                oracle_messages = _stored["messages"]
                _session_loaded = len(oracle_messages) > 1
            else:
                # File list changed or old format — fresh start.
                oracle_messages = [{"role": "system", "content": oracle_sys}]
                if os.path.exists(debate_aider_history):
                    try:
                        os.remove(debate_aider_history)
                    except OSError:
                        pass
        except Exception:
            oracle_messages = [{"role": "system", "content": oracle_sys}]
    else:
        oracle_messages = [{"role": "system", "content": oracle_sys}]

    # 6. Retrieve database context unconditionally on every debate query.
    #    This ensures fresh, relevant chunks are loaded for follow-up questions.
    context = ""
    ret_mode = (os.environ.get("ORACLE_RETRIEVE_MODE") or "top_k").strip().lower()
    try:
        k = int(os.environ.get("ORACLE_TOP_K", "5"))
    except ValueError:
        k = 5
    with contextlib.redirect_stdout(sys.stderr):
        if ret_mode == "full_document":
            context = _full_document(
                os.environ.get("ORACLE_RAG_DB_DIR"),
                os.environ.get("ORACLE_COLLECTION", "knowledge"),
            )
        elif ret_mode != "no_retrieve":
            context = _retrieve(question, k)

    # Log retrieved chunks for debates to stderr (keeps stdout pristine)
    nchunks = context.count("[source:") if context else 0
    print(
        f"[oracle] {nchunks} source chunk(s) retrieved for debate · mode={ret_mode}",
        file=sys.stderr,
    )

    total_turns = max_turns * rounds
    print(
        f"\n[oracle] Starting CLI debate ({mode} mode): "
        f"{max_turns} loops x {rounds} round(s) = {total_turns} max turns, "
        f"pass_round_history={_pass_round_history}\n",
        file=sys.stderr,
    )

    last_proposal = ""
    state = "continue"
    last_oracle = ""

    for round_idx in range(1, rounds + 1):
        _clear = not _pass_round_history and round_idx > 1
        if _clear:
            oracle_messages = [{"role": "system", "content": oracle_sys}]
            _session_loaded = False  # Force turn 0 + retrieval on next round
            # Re-run retrieval since context was cleared
            if not context:
                ret_mode = (
                    (os.environ.get("ORACLE_RETRIEVE_MODE") or "top_k").strip().lower()
                )
                try:
                    k = int(os.environ.get("ORACLE_TOP_K", "5"))
                except ValueError:
                    k = 5
                with contextlib.redirect_stdout(sys.stderr):
                    if ret_mode == "full_document":
                        context = _full_document(
                            os.environ.get("ORACLE_RAG_DB_DIR"),
                            os.environ.get("ORACLE_COLLECTION", "knowledge"),
                        )
                    elif ret_mode != "no_retrieve":
                        context = _retrieve(question, k)
            if os.path.exists(debate_aider_history):
                try:
                    os.remove(debate_aider_history)
                except OSError:
                    pass
            if os.path.exists(_debate_session_file):
                try:
                    os.remove(_debate_session_file)
                except OSError:
                    pass

        ledger = deliberate.new_ledger(f"cli_debate_r{round_idx}")
        state = "continue"

        if rounds > 1:
            print(
                f"\n[oracle] --- Round {round_idx}/{rounds} ---\n",
                file=sys.stderr,
            )

        # --- ORACLE TURN 0: always runs ---
        # Fresh session: full context + files + question.
        # Loaded session: just the new question (context/files are in history).
        if not _session_loaded:
            _file_ctx = []
            for _rf in _reads:
                _full = os.path.join(project_dir, _rf)
                if os.path.isfile(_full):
                    try:
                        with open(_full, encoding="utf-8") as _fh:
                            _file_ctx.append(f"## {_rf}\n```\n{_fh.read()}\n```")
                    except Exception:
                        pass
            cli_file_text = ("\n\n".join(_file_ctx)) if _file_ctx else ""

            orc_seed = ""
            if cli_file_text:
                orc_seed += f"<project_files>\n{cli_file_text}\n</project_files>\n\n"
            if context:
                orc_seed += f"<knowledge_base>\n{context}\n</knowledge_base>\n\n"
            orc_seed += f"<question>\n{question}\n</question>"
        else:
            orc_seed = ""
            if context:
                orc_seed += f"<knowledge_base>\n{context}\n</knowledge_base>\n\n"
            orc_seed += f"<new_question>\n{question}\n</new_question>"

        oracle_messages.append({"role": "user", "content": orc_seed})

        try:
            import litellm

            _t0_kwargs = {
                "model": oracle_model,
                "messages": oracle_messages,
                "custom_headers": {"x-litellm-session-id": _PIPELINE_SESSION_ID}
            }
            if oracle_api:
                _t0_kwargs["api_base"] = oracle_api
                _t0_kwargs["api_key"] = "sk-dummy"
            resp = litellm.completion(**_t0_kwargs)
            initial_oracle = _response_content(resp)
            oracle_cost_line_0 = _litellm_cost_line(resp, persist_session=False)
        except Exception as e:
            print(f"Oracle API Error (turn 0): {e}", file=sys.stderr)
            return 1

        oracle_messages.append({"role": "assistant", "content": initial_oracle})
        last_oracle = initial_oracle
        # Mark context as loaded so subsequent rounds (pass_round_history=True)
        # send only the delta question instead of re-sending all files + context
        # that are already in oracle_messages from this round's turn 0.
        _session_loaded = True

        # Persist oracle session after turn 0
        os.makedirs(os.path.dirname(_debate_session_file), exist_ok=True)
        with open(_debate_session_file, "w", encoding="utf-8") as _sf:
            json.dump(
                {"files_hash": _files_hash, "messages": oracle_messages},
                _sf,
                ensure_ascii=False,
                indent=2,
            )

        turn_label_0 = f"r{round_idx} turn 0/{max_turns}"
        print(
            f"\n{_ORACLE_COLOR}┌── oracle {turn_label_0} ──",
            file=sys.stderr,
        )
        print(initial_oracle, file=sys.stderr)
        if oracle_cost_line_0:
            print(oracle_cost_line_0, file=sys.stderr)
        print(f"└──{_RESET}", file=sys.stderr)
        
        _validate_oracle_response(initial_oracle)

        for turn in range(max_turns):
            turn_label = f"r{round_idx} turn {turn + 1}/{max_turns}"

            # --- ARCHITECT TURN ---
            if turn == 0 and round_idx == 1:
                arch_prompt = (
                    "You are the software Architect. The Oracle has provided "
                    "an initial assessment based on the knowledge base. "
                    "Review it and address the user's issue.\n\n"
                    f"USER ISSUE: {question}\n\n"
                    f"ORACLE ASSESSMENT:\n{last_oracle}\n\n"
                    "End with EXACTLY one line:\n"
                    "PROPOSAL: <one-line concrete resolution>"
                )
            elif turn == 0:
                # First turn of a new round: re-seed with the question + prior state
                arch_prompt = (
                    "You are the software Architect. The previous debate round "
                    "ended without full resolution. Continue working on the issue "
                    "using all prior context.\n\n"
                    f"USER ISSUE: {question}\n\n"
                    f"LAST ORACLE RESPONSE:\n{last_oracle}\n\n"
                    "Refine your approach. End with EXACTLY one line:\n"
                    "PROPOSAL: <one-line concrete resolution>"
                )
            else:
                arch_prompt = (
                    "The Oracle reviewed your proposal and responded:\n\n"
                    f"{last_oracle}\n\n"
                    "Please address the Oracle's objections and refine your fix. "
                    "End with EXACTLY one line:\n"
                    "PROPOSAL: <one-line concrete resolution>"
                )

            arch_text = factory._aider_ask_turn(
                task,
                arch_prompt,
                _reads,
                label=turn_label,
                history_file=debate_aider_history,
            )
            pline = deliberate.proposal_line(arch_text) or "(no PROPOSAL line)"
            last_proposal = pline

            deliberate.record_turn(
                ledger,
                turn,
                "architect",
                pline,
                proposal_hash=deliberate.proposal_hash(arch_text),
            )

            # --- ORACLE TURN (persistent in-memory session for KV cache) ---
            # Run vector search specifically on the Architect's proposal to get fresh validation chunks
            loop_context = ""
            if ret_mode != "no_retrieve":
                try:
                    loop_k = int(os.environ.get("ORACLE_TOP_K", "5"))
                    if loop_k < 5: loop_k = 5
                except ValueError:
                    loop_k = 5
                with contextlib.redirect_stdout(sys.stderr):
                    loop_context = _retrieve(arch_text, loop_k)
                
                # Log retrieved chunks for this turn
                if loop_context:
                    nchunks = loop_context.count("[source:")
                    print(
                        f"[oracle] {nchunks} source chunk(s) retrieved to validate Architect proposal ({turn_label})",
                        file=sys.stderr,
                    )

            if turn == 0:
                orc_msg = ""
                if loop_context:
                    orc_msg += f"<additional_knowledge_base>\n{loop_context}\n</additional_knowledge_base>\n\n"
                orc_msg += (
                    "Review the Architect's proposal against the context and "
                    "files provided above.\n\n"
                    f"<architect_proposal>\n{arch_text}\n</architect_proposal>"
                )
            else:
                orc_msg = ""
                if loop_context:
                    orc_msg += f"<additional_knowledge_base>\n{loop_context}\n</additional_knowledge_base>\n\n"
                orc_msg += f"<revised_architect_proposal>\n{arch_text}\n</revised_architect_proposal>"
            oracle_messages.append({"role": "user", "content": orc_msg})

            try:
                import litellm

                kwargs = {
                    "model": oracle_model,
                    "messages": oracle_messages,
                    "custom_headers": {"x-litellm-session-id": _PIPELINE_SESSION_ID}
                }
                if oracle_api:
                    kwargs["api_base"] = oracle_api
                    kwargs["api_key"] = "sk-dummy"
                resp = litellm.completion(**kwargs)
                last_oracle = _response_content(resp)
                oracle_cost_line = _litellm_cost_line(resp, persist_session=False)
            except Exception as e:
                print(f"Oracle API Error: {e}", file=sys.stderr)
                return 1

            oracle_messages.append({"role": "assistant", "content": last_oracle})
            # Persist oracle debate session within the current invocation
            with open(_debate_session_file, "w", encoding="utf-8") as _sf:
                json.dump(
                    {"files_hash": _files_hash, "messages": oracle_messages},
                    _sf,
                    ensure_ascii=False,
                    indent=2,
                )

            verdict = deliberate.oracle_verdict(last_oracle)

            print(f"\n{_ORACLE_COLOR}┌── oracle {turn_label} ──", file=sys.stderr)
            print(last_oracle, file=sys.stderr)
            if oracle_cost_line:
                print(oracle_cost_line, file=sys.stderr)
            print(f"└──{_RESET}", file=sys.stderr)
            
            _validate_oracle_response(last_oracle)

            deliberate.record_turn(ledger, turn, "oracle", last_oracle, verdict=verdict)

            # --- ARBITRATION ---
            state = deliberate.consensus_state(ledger)
            if state != "continue":
                break

        if state == "continue":
            state = "exhausted"

        # Early exit on agreement (no need for more rounds)
        if state == "agreed":
            break

    # Final Output to stdout (Aider reads this)
    print(f"## DEBATE VERDICT: {state.upper()}\n")
    if state == "agreed":
        print("The Oracle agreed with the Architect's proposal.")
    else:
        print("The debate ended without agreement (deadlock or exhausted loops).")
    print(f"\n### Final Proposal\n{last_proposal}")
    return 0


def _ensure_oracle_config():
    """Populate missing ORACLE_* environment variables from the active YAML config."""
    # Inject LITELLM_BASE_URL fallback for cluster mode
    if os.environ.get("LITELLM_BASE_URL"):
        os.environ.setdefault("ORACLE_AGENT_API_BASE", os.environ["LITELLM_BASE_URL"])
        os.environ.setdefault("ORACLE_EMBED_API_BASE", os.environ["LITELLM_BASE_URL"])
    if os.environ.get("LITELLM_API_KEY"):
        os.environ.setdefault("ORACLE_AGENT_API_KEY", os.environ["LITELLM_API_KEY"])

    project_dir = os.getcwd()
    yaml_path = os.environ.get("ORACLE_CONFIG_FILE")
    if not yaml_path or not os.path.exists(yaml_path):
        yaml_path = os.path.join(project_dir, ".aider_factory", ".env.yml")
    if not os.path.exists(yaml_path):
        yaml_path = os.path.join(project_dir, ".env.yml")

    if not os.path.exists(yaml_path):
        return

    try:
        import yaml
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        project_dir = str(config.get("working_directory", project_dir))
        endpoints = config.get("endpoints", {}) or {}
        global_rag = config.get("rag", {}) or {}
        phases = config.get("phases", []) or []

        target_coll = os.environ.get("ORACLE_COLLECTION")
        active_idx = os.environ.get("ORACLE_PHASE_INDEX")
        active_phase = None

        for idx, p in enumerate(phases):
            if not p.get("enabled", True):
                continue
            if active_idx is not None and str(idx) == active_idx:
                active_phase = p
                break
            elif active_idx is None and target_coll:
                p_coll = (p.get("rag") or {}).get("collection_name") or (p.get("vector_store") or {}).get("collection_name")
                if p_coll == target_coll:
                    active_phase = p
                    break

        if not active_phase and phases:
            active_phase = next((p for p in phases if p.get("enabled", True)), phases[0])

        explicit_coll = os.environ.get("ORACLE_EXPLICIT_COLLECTION") == "1"
        if not explicit_coll:
            yaml_coll = (active_phase.get("rag") or {}).get("collection_name") if active_phase else None
            if yaml_coll:
                os.environ["ORACLE_COLLECTION"] = yaml_coll
                os.environ["ORACLE_RAG_DB_DIR"] = os.path.join(
                    project_dir, ".aider_factory", "markdown", "lanceDB", yaml_coll, "lancedb"
                )
        else:
            # If explicit collection is a local name (no slashes), ensure it respects the YAML working_directory
            coll = os.environ.get("ORACLE_COLLECTION")
            if coll and "/" not in coll and "\\" not in coll:
                os.environ["ORACLE_RAG_DB_DIR"] = os.path.join(
                    project_dir, ".aider_factory", "markdown", "lanceDB", coll, "lancedb"
                )

        phase_models = (active_phase.get("models") or {}) if active_phase else {}
        phase_rag = (active_phase.get("rag") or {}) if active_phase else {}

        rag_agent = phase_models.get("rag_agent") or config.get("models", {}).get("rag_agent", "gemini/gemini-2.5-flash")
        arch_agent = phase_models.get("architect_agent") or config.get("models", {}).get("architect_agent", "gemini/gemini-3.6-flash")

        embed_model = (
            phase_models.get("embed_model")
            or phase_rag.get("embed_model")
            or global_rag.get("embed_model")
            or config.get("models", {}).get("embed_model", "gemini/text-embedding-004")
        )
        embed_api_base = (
            phase_rag.get("embed_api_base")
            or global_rag.get("embed_api_base")
            or endpoints.get("embed_api_base")
        )
        embed_backend = (
            phase_rag.get("embed_backend")
            or global_rag.get("embed_backend")
            or phase_models.get("embed_backend")
            or ("openai" if (embed_api_base or "gemini" in embed_model) else "sentence-transformers")
        )
        if (embed_api_base or "gemini" in embed_model) and embed_backend == "sentence-transformers":
            embed_backend = "openai"

        os.environ.setdefault("ORACLE_AGENT_MODEL", rag_agent)
        os.environ.setdefault("ORACLE_ARCHITECT_MODEL", arch_agent)
        os.environ.setdefault("ORACLE_EMBED_MODEL", embed_model)
        os.environ.setdefault("ORACLE_EMBED_BACKEND", embed_backend)
        if embed_api_base:
            os.environ.setdefault("ORACLE_EMBED_API_BASE", embed_api_base)
        if "gemini/" not in rag_agent and endpoints.get("rag_agent_api"):
            os.environ.setdefault("ORACLE_AGENT_API_BASE", endpoints.get("rag_agent_api"))
        if "gemini/" not in arch_agent and endpoints.get("architect_api_base"):
            os.environ.setdefault("ORACLE_ARCHITECT_API_BASE", endpoints.get("architect_api_base"))
    except Exception:
        pass


def main():
    # Programmatic, no-Aider mode (template -> file). Triggered by --job, --auto, or ORACLE_JOB.
    if (
        "--job" in sys.argv[1:]
        or "--auto" in sys.argv[1:]
        or os.environ.get("ORACLE_JOB")
    ):
        return _run_auto()

    # Target overrides (apply before retrieval): --collection / --db / --list.
    args, do_list, did_clear, maint_act, maint_tgt = _extract_overrides(sys.argv[1:])
    _ensure_oracle_config()
    if maint_act:
        if maint_act == "list-files":
            return _list_files()
        elif maint_act == "rm-table":
            return _remove_table(maint_tgt)
        elif maint_act == "rm-file":
            return _remove_file(maint_tgt)
        elif maint_act == "rm-db":
            return _remove_db()
        elif maint_act == "add-file":
            return _add_maintenance("file", maint_tgt)
        elif maint_act == "add-table":
            return _add_maintenance("table", maint_tgt)
        elif maint_act == "add-web":
            return _add_web_maintenance(maint_tgt)
        return 0

    if do_list:
        return _list_tables()

    # Interactive/autonomous query: positional text and/or `--file <path>`.
    question, display = _build_question(args)
    if question is None:
        return 0  # --file error already reported to stderr
    if not question:
        if did_clear:
            return 0  # Standalone --clear command; exit cleanly without showing usage.
        print(
            'usage: oracle "<question>" | oracle --file <path> ["note"] '
            '| oracle --collection <table> [--db <dir>] "<q>" '
            '| oracle --no-rag "<q>" | oracle --debate [code|review] [--loops N] [--rounds N] "<q>" '
            '| oracle --type [code|docs] "<q>" (fuse-only; excludes per-doc literature tables) '
            "| oracle --clear [oracle] | oracle --list\n"
            "       oracle --list-files\n"
            "       oracle --rm-table <table_name>\n"
            "       oracle --rm-file <filename>\n"
            "       oracle --rm-db"
        )
        return 0

    debate_mode = os.environ.get("ORACLE_DEBATE_MODE")
    if debate_mode:
        try:
            loops = int(os.environ.get("ORACLE_DEBATE_LOOPS", "3"))
        except ValueError:
            loops = 3
        try:
            rounds = int(os.environ.get("ORACLE_DEBATE_ROUNDS", "1"))
        except ValueError:
            rounds = 1
        return _run_cli_debate(question, debate_mode, loops, rounds)

    model = os.environ.get("ORACLE_AGENT_MODEL")
    if not model:
        print(
            "[oracle] ORACLE_AGENT_MODEL not set; side-agent not configured for this phase.",
            file=sys.stderr,
        )
        return 0
    api_base = os.environ.get("ORACLE_AGENT_API_BASE")  # None for gemini/
    api_key = os.environ.get("ORACLE_AGENT_API_KEY")  # 'sk-dummy' for local
    try:
        k = int(os.environ.get("ORACLE_TOP_K", "5"))
    except ValueError:
        k = 5

    # Retrieval strategy for this session (set per-phase via the YAML -> env):
    #   top_k (default) | no_retrieve | full_document
    mode = (os.environ.get("ORACLE_RETRIEVE_MODE") or "top_k").strip().lower()

    # Always use session history during debates to enable perfect persistent caching.
    use_session = True

    answer = None
    cost_line = ""
    # Keep stdout pristine: any stray library prints during retrieval / the model
    # call are redirected to stderr so only the final answer lands on stdout.
    with contextlib.redirect_stdout(sys.stderr):
        if use_session:
            messages = _load_session()
        else:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        _session_loaded = isinstance(messages, list) and len(messages) > 1

        # 1. Exact pre-regression behavior: vector search runs on every turn
        if mode == "no_retrieve":
            context = ""  # pure LLM over the question/--file; no vector search
        elif mode == "full_document":
            context = _full_document(
                os.environ.get("ORACLE_RAG_DB_DIR"),
                os.environ.get("ORACLE_COLLECTION", "knowledge"),
            )
        else:  # top_k (default)
            context = _retrieve(question, k)

        # 2. Gate ONLY static context file injection to Turn 1 (prevents token inflation)
        prompt = ""
        if not _session_loaded:
            rf_str = os.environ.get("ORACLE_JOB_READ_FILES") or os.environ.get(
                "ORACLE_CONTEXT_FILES"
            )
            if rf_str:
                _ctx = []
                for rf in rf_str.split("\x1e"):
                    if rf and os.path.isfile(rf):
                        try:
                            with open(rf, encoding="utf-8") as fh:
                                _ctx.append(f"File: {rf}\n```\n{fh.read()}\n```")
                        except Exception:
                            pass
                if _ctx:
                    prompt += "<project_files>\n" + "\n\n".join(_ctx) + "\n</project_files>\n\n"

        if context:
            prompt += f"<knowledge_base>\n{context}\n</knowledge_base>\n\n"

        prompt += f"<question>\n{question}\n</question>"

        messages.append({"role": "user", "content": prompt})
        try:
            import litellm

            kwargs = {
                "model": model,
                "messages": messages,
                "custom_headers": {"x-litellm-session-id": _PIPELINE_SESSION_ID}
            }
            if api_base:
                kwargs["api_base"] = api_base
            if api_key:
                kwargs["api_key"] = api_key
            resp = litellm.completion(**kwargs)
            answer = _response_content(resp)
            cost_line = _litellm_cost_line(resp, persist_session=use_session)
        except Exception as e:
            print(f"[oracle] model call failed: {e}", file=sys.stderr)
            return 0

        # Keep memory lean: store the compact display (not a large --file payload).
        # Only use session history for interactive manual queries (no --file passed).
        if use_session:
            # Keep full question exactly as sent to the model in session history
            # so that multi-turn debates retain the exact prefix for 100% KV cache hits.
            messages.append({"role": "assistant", "content": answer})
            _save_session(messages)
            _append_transcript(display, answer, context)
        else:
            _append_transcript(display, answer, context)
            
        _validate_oracle_response(answer)

    # Status -> stderr; answer -> stdout (folds cleanly into the aider chat).
    nchunks = context.count("[source:") if context else 0
    if context:
        import re
        sources = set(re.findall(r"\[source: (?:.*? \| )?(.*?)(?::\d+-\d+)?\]", context))
        src_str = f" from {len(sources)} file(s): {', '.join(sorted(sources)[:5])}" + ("..." if len(sources) > 5 else "") if sources else ""
    else:
        src_str = ""

    print(
        f"[oracle] {nchunks} source chunk(s){src_str} · mode={mode} · model={model}",
        file=sys.stderr,
    )
    if sys.stdout.isatty() or os.environ.get("FORCE_COLOR"):
        print(f"{_ORACLE_COLOR}{answer}{_RESET}", flush=True)
    else:
        print(answer, flush=True)
    if cost_line:
        print(cost_line, file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
