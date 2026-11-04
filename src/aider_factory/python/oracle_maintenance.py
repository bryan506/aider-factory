#!/usr/bin/env python3
# oracle_maintenance.py — LanceDB and Web RAG maintenance operations for the Knowledge Oracle.

import contextlib
import os
import shutil
import sys

_python_dir = os.path.dirname(os.path.abspath(__file__))
if _python_dir not in sys.path:
    sys.path.insert(0, _python_dir)

sys.modules.setdefault("oracle_maintenance", sys.modules[__name__])
sys.modules.setdefault(
    "aider_factory.python.oracle_maintenance", sys.modules[__name__]
)

rag_context_root = None


def _safe_int(val, default: int) -> int:
    if val is None or (isinstance(val, str) and not val.strip()):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val, default: float) -> float:
    if val is None or (isinstance(val, str) and not val.strip()):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _resolve_file_path(path_str, base_dir=None):
    """Shared path resolver for all --file parameters across the AI Factory.

    1. Expands user tilde (~/ -> /home/user).
    2. Resolves relative paths against base_dir or current working repo root (os.getcwd()).
    3. Returns normalized absolute path string (or None if path_str is empty/None).
    """
    if path_str is None:
        return None
    stripped = str(path_str).strip()
    if not stripped:
        return None
    expanded = os.path.expanduser(stripped)
    if not os.path.isabs(expanded):
        base = base_dir or os.getcwd()
        expanded = os.path.join(base, expanded)
    return os.path.normpath(expanded)


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
                else:
                    try:
                        tbl.optimize()
                    except Exception:
                        pass
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

    print(
        f"[oracle] Surgically wiping vector database for collection '{collection}'...",
        file=sys.stderr,
    )
    print(f"[oracle] Target: {db_dir}", file=sys.stderr)
    try:
        shutil.rmtree(db_dir)
        print(
            "[oracle] Success! Vector database wiped. OCR text cache and images preserved.",
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
    if os.environ.get("ORACLE_EXPLICIT_COLLECTION") == "1" and os.environ.get(
        "ORACLE_COLLECTION"
    ):
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


def _load_maintenance_config():
    """Load active YAML config and resolve (cfg, project_dir, context_root, collection, job_dir)."""
    import yaml

    project_dir = os.getcwd()
    config_path = os.environ.get("ORACLE_CONFIG_FILE")
    if not config_path or not os.path.exists(config_path):
        config_path = os.path.join(project_dir, ".aider_factory", ".env.yml")
    if not os.path.exists(config_path):
        config_path = os.path.join(project_dir, ".env.yml")

    cfg = {}
    if config_path and os.path.exists(config_path):
        print(f"[oracle] Loading configuration from: {config_path}", file=sys.stderr)
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[oracle] failed to load config: {e}", file=sys.stderr)
            return None
    else:
        print(
            "[oracle] Config file not found; using default configuration.",
            file=sys.stderr,
        )

    raw_wd = cfg.get("working_directory")
    if raw_wd is not None and str(raw_wd).strip():
        project_dir = str(raw_wd).strip()

    oa_mod = sys.modules.get("oracle_agent") or sys.modules.get(
        "aider_factory.python.oracle_agent"
    )
    custom_root = getattr(oa_mod, "rag_context_root", None) if oa_mod else None
    if not custom_root:
        custom_root = rag_context_root
    context_root = custom_root or os.path.join(
        project_dir, ".aider_factory", "markdown", "lanceDB"
    )

    collection = _resolve_active_collection(cfg)
    os.environ["ORACLE_COLLECTION"] = collection
    job_dir = os.path.join(context_root, collection)
    return cfg, project_dir, context_root, collection, job_dir


def _run_maintenance_ingest(
    cfg,
    context_root,
    collection,
    *,
    default_embed_model="gemini/text-embedding-004",
    ocr_only=False,
    empty_return_code=1,
    label="Ingestion",
):
    """Resolve active phase RAG/embedding settings and run rag_manager.ingest()."""
    import rag_manager

    endpoints = cfg.get("endpoints", {}) or {}
    global_rag = cfg.get("rag", {}) or {}
    phases = cfg.get("phases", []) or []
    active_phase = (
        next((ph for ph in phases if ph.get("enabled")), phases[0]) if phases else {}
    )
    phase_models = active_phase.get("models", {}) or {}
    phase_rag = active_phase.get("rag", {}) or {}

    batch_setting = bool(phase_rag.get("batch", True))
    chunk_size = _safe_int(phase_rag.get("chunk_size_chars"), 1500)
    chunk_overlap = _safe_int(phase_rag.get("chunk_overlap_chars"), 300)
    cer_thresh = _safe_float(phase_rag.get("cer_threshold"), 0.05)
    max_retries = _safe_int(phase_rag.get("ocr_max_retries"), 2)
    parallel = _safe_int(phase_rag.get("ocr_parallel"), 1)
    ocr_max_tokens = _safe_int(phase_rag.get("ocr_max_tokens"), 4096)
    code_chunk_size = _safe_int(phase_rag.get("code_chunk_size"), 2000)
    use_docling = phase_rag.get("use_docling", True)
    docling_do_ocr = phase_rag.get("docling_do_ocr", True)
    docling_timeout = phase_rag.get("docling_timeout") or global_rag.get(
        "docling_timeout"
    )
    ocr_prompt = phase_rag.get("ocr_prompt", rag_manager.DEFAULT_OCR_PROMPT)

    embed_model = (
        os.environ.get("ORACLE_EMBED_MODEL")
        or phase_rag.get("embed_model")
        or global_rag.get("embed_model")
        or phase_models.get("embed_model")
        or default_embed_model
    )
    embed_api_base = (
        os.environ.get("ORACLE_EMBED_API_BASE")
        or phase_rag.get("embed_api_base")
        or global_rag.get("embed_api_base")
        or endpoints.get("embed_api_base")
    )
    embed_backend = (
        os.environ.get("ORACLE_EMBED_BACKEND")
        or phase_rag.get("embed_backend")
        or global_rag.get("embed_backend")
        or ("openai" if "embedding" in embed_model.lower() else "sentence-transformers")
    )
    if (
        embed_api_base
        and embed_backend == "sentence-transformers"
        and not os.environ.get("ORACLE_EMBED_BACKEND")
    ):
        embed_backend = "openai"

    if ocr_only:
        print(
            "[oracle] --no-rag active: Files will be OCR'd to Markdown but NOT indexed into LanceDB.",
            file=sys.stderr,
        )
    else:
        print(
            f"[oracle] Running incremental ingestion (batch={batch_setting}, model={embed_model}, backend={embed_backend})...",
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
            ocr_prompt=ocr_prompt,
            overwrite=False,
            cer_threshold=cer_thresh,
            ocr_max_retries=max_retries,
            ocr_parallel=parallel,
            ocr_max_tokens=ocr_max_tokens,
            code_chunk_size=code_chunk_size,
            batch=batch_setting,
            ocr_only=ocr_only,
            use_docling=use_docling,
            docling_do_ocr=docling_do_ocr,
            docling_timeout=docling_timeout,
        )
        if success:
            print(f"[oracle] {label} completed successfully.", file=sys.stderr)
            return 0
        if empty_return_code == 0:
            print(
                f"[oracle] {label} completed but no new chunks were added or an error occurred.",
                file=sys.stderr,
            )
            return 0
        print(
            f"[oracle] {label} failed: no files were added or an error occurred.",
            file=sys.stderr,
        )
        return 1
    except Exception as e:
        print(f"[oracle] {label} failed with error: {e}", file=sys.stderr)
        return 1


def _add_maintenance(action, paths):
    """Implement --add-file and --add-table maintenance commands."""
    loaded = _load_maintenance_config()
    if loaded is None:
        return 1
    cfg, _project_dir, context_root, collection, job_dir = loaded

    print(f"[oracle] Active collection: {collection}", file=sys.stderr)
    print(f"[oracle] Collection directory: {job_dir}", file=sys.stderr)

    if not os.path.exists(job_dir):
        print("[oracle] Bootstrapping new collection directory...", file=sys.stderr)
        os.makedirs(job_dir, exist_ok=True)

    for p in paths:
        if not os.path.exists(p):
            print(f"[oracle] Error: Path does not exist: {p}", file=sys.stderr)
            return 1

        abs_p = os.path.abspath(p)
        abs_job_dir = os.path.abspath(job_dir)

        if abs_p.startswith(abs_job_dir + os.sep) or abs_p == abs_job_dir:
            print(
                f"[oracle] Path is already inside collection directory: {p}",
                file=sys.stderr,
            )
            continue

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
                for root, _dirs, files in os.walk(p):
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

    ocr_only_mode = os.environ.get("ORACLE_NO_RAG_INGEST") == "1"
    return _run_maintenance_ingest(
        cfg,
        context_root,
        collection,
        default_embed_model="gemini/text-embedding-004",
        ocr_only=ocr_only_mode,
        empty_return_code=1,
        label="Ingestion",
    )


def _add_web_maintenance(urls):
    """Implement --add-web maintenance command: fetch web content and incrementally ingest into LanceDB."""
    import rag_web

    loaded = _load_maintenance_config()
    if loaded is None:
        return 1
    cfg, project_dir, context_root, collection, job_dir = loaded
    os.makedirs(job_dir, exist_ok=True)

    expanded_urls = []
    for t in urls:
        is_explicit_file = t.startswith("--file:")
        raw_path = t[7:] if is_explicit_file else t
        resolved_path = _resolve_file_path(raw_path, project_dir)

        if is_explicit_file or (resolved_path and os.path.isfile(resolved_path)):
            if not resolved_path or not os.path.isfile(resolved_path):
                print(
                    f"[oracle] Error: URL file not found: {resolved_path or raw_path}",
                    file=sys.stderr,
                )
                return 1
            print(f"[oracle] Reading URLs from file: {resolved_path}", file=sys.stderr)
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
        workers = max(1, int(os.environ.get("ORACLE_WEB_WORKERS", "1")))
    except (ValueError, TypeError):
        workers = 1

    success_count, skipped_count = rag_web.fetch_urls_batch(
        expanded_urls, job_dir, workers=workers
    )

    print("\n[rag-web] Batch Web Download Summary:", file=sys.stderr)
    print(f"          - Successfully Ingested: {success_count} file(s)", file=sys.stderr)
    print(f"          - Skipped / Failed:        {skipped_count} file(s)", file=sys.stderr)

    if success_count == 0:
        print("[oracle] No web files were successfully fetched.", file=sys.stderr)
        return 1

    if os.environ.get("ORACLE_NO_RAG_INGEST") == "1":
        print(
            f"[oracle] --no-rag active: Saved Markdown files to '{job_dir}'. Bypassing LanceDB vector indexing.",
            file=sys.stderr,
        )
        return 0

    return _run_maintenance_ingest(
        cfg,
        context_root,
        collection,
        default_embed_model="BAAI/bge-m3",
        ocr_only=False,
        empty_return_code=0,
        label="Web ingestion",
    )
