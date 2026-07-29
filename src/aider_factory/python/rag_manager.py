#!/usr/bin/env python3
# rag_manager.py — multi-format OCR -> LanceDB ingestion for the AI Factory.
#
#   <aider-venv-python> rag_manager.py [path/to/.env.yml]
#   (also called once per RAG phase by orchestrate.py via Task.ocr_ingest)
#
# A "job/collection" is one folder you assemble by hand:
#   .aider_factory/markdown/lanceDB/<collection_name>/   <- you create + drop docs in
#       <doc>.pdf | .epub | .png | ...   (mixed formats OK)
#       images/        <- pipeline writes rasterized page PNGs
#       <doc>.md       <- pipeline writes OCR markdown
#       lancedb/       <- one DB for the whole job (table name = <collection_name>)
#
# overwrite=false -> if the table already exists, the whole job is skipped (cache hit).

import base64
import logging
import os
import re
import sys
import time

# Quiet noisy ML/HTTP libraries so the pipeline log stays readable.
# (env vars must be set before transformers/huggingface_hub import)
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
for _n in ("httpx", "urllib3"):
    logging.getLogger(_n).setLevel(logging.WARNING)
for _n in ("huggingface_hub", "sentence_transformers", "transformers"):
    logging.getLogger(_n).setLevel(logging.ERROR)

import re

import Levenshtein

log = logging.getLogger("rag_manager")

DEFAULT_OCR_PROMPT = (
    "Extract the text, tables, and mathematical formulas from this page into clean "
    "Markdown. Preserve all structural integrity."
)

_ST_CACHE = {}


def embed_texts(texts, backend, model, api_base, batch_size=8):
    """Return list[list[float]] for `texts`. The ONLY embedding entrypoint.
    openai backend with api_base set -> direct HTTP to local llama-server.
    openai backend with api_base empty/None -> cloud model via litellm
    (set embed_api_base to "" in the YAML and use a prefixed model name
    like 'gemini/text-embedding-004').
    sentence-transformers -> local model (unchanged)."""
    if not texts:
        return []
    out = []
    if backend == "openai":
        if api_base:
            # Local endpoint: direct HTTP (llama-server, etc.)
            import requests as _req

            for i in range(0, len(texts), batch_size):
                r = _req.post(
                    f"{api_base.rstrip('/')}/embeddings",
                    json={"input": texts[i : i + batch_size], "model": model},
                    headers={
                        "Authorization": "Bearer sk-dummy",
                        "Content-Type": "application/json",
                    },
                    timeout=(10, None),  # 10s connect; unlimited read
                )
                r.raise_for_status()
                out.extend(d["embedding"] for d in r.json()["data"])
        else:
            # Cloud model: route through litellm (gemini/, openai/, etc.)
            import litellm

            for i in range(0, len(texts), batch_size):
                r = litellm.embedding(model=model, input=texts[i : i + batch_size])
                out.extend(d["embedding"] for d in r["data"])
    elif backend == "sentence-transformers":
        from sentence_transformers import SentenceTransformer

        st = _ST_CACHE.get(model) or _ST_CACHE.setdefault(
            model, SentenceTransformer(model)
        )
        out = [v.tolist() for v in st.encode(texts, normalize_embeddings=True)]
    else:
        raise ValueError(f"unknown embed_backend: {backend}")
    return out


def _calculate_cer(reference: str, hypothesis: str) -> float:
    """Calculates Normalized Edit Distance (CER) on purely alphanumeric strings."""
    # Lowercase and strip ALL non-alphanumeric chars (punctuation, spaces, #, |, *, etc.)
    ref_norm = re.sub(r"[^a-z0-9]", "", reference.lower())
    hyp_norm = re.sub(r"[^a-z0-9]", "", hypothesis.lower())

    # If the text layer is completely empty (e.g., scanned image), validation automatically passes
    if not ref_norm:
        return 0.0

    distance = Levenshtein.distance(ref_norm, hyp_norm)
    return distance / len(ref_norm)


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif"}
DOC_EXTS = {".pdf", ".xps", ".oxps", ".epub", ".mobi", ".fb2", ".cbz", ".svg", ".txt"}

CODE_EXTS_DEFAULT = {
    ".r",
    ".py",
    ".js",
    ".ts",
    ".cpp",
    ".cc",
    ".c",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".sh",
    ".sql",
}
TEXT_DOC_EXTS_DEFAULT = {".md", ".rmd", ".txt", ".rst"}
IGNORE_DEFAULT = {
    ".git",
    "renv",
    "packrat",
    "node_modules",
    "__pycache__",
    ".venv",
    "build",
    "dist",
    "data",
    ".rproj.user",
}

_LANG_BY_EXT = {
    ".r": "r",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".h": "cpp",
    ".hpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".sh": "bash",
    ".sql": "sql",
}

_FENCE_RE = re.compile(r"(```.*?```|~~~.*?~~~)", re.DOTALL)


def _lang_for_ext(ext):
    return _LANG_BY_EXT.get(ext.lower())


# batch=True flush cadence: write buffered chunks to the table once this many are
# queued (checked at document boundaries). Bounds peak memory on large first builds
# and persists partial progress so a crash mid-corpus loses only unflushed docs.
FLUSH_CHUNK_THRESHOLD = 2000

# Auto-create an ANN index once a table crosses this row count (below it, flat KNN
# is fast and exact). Params are auto-selected by LanceDB to avoid dimension-divisor
# pitfalls. Tuning + eval-gating are deferred (roadmap item 3).
IVF_PQ_MIN_ROWS = 50000


def _maybe_create_index(table, table_name):
    """Create an ANN index once a table is large enough. Never fatal — a failed
    index just means we keep exact flat search. Row-count gate = IVF_PQ_MIN_ROWS."""
    try:
        if hasattr(table, "count_rows") and table.count_rows() > IVF_PQ_MIN_ROWS:
            log.info(
                f"[RAG] table '{table_name}' > {IVF_PQ_MIN_ROWS} rows -> building ANN index."
            )
            table.create_index(
                metric="cosine"
            )  # LanceDB auto-selects partitions/sub-vectors
    except Exception as e:
        log.warning(f"[RAG] ANN index skipped for '{table_name}': {e}")


def _get_parser(lang):
    try:
        from tree_sitter_language_pack import get_parser

        return get_parser(lang)
    except Exception as e:
        log.warning(
            f"[RAG] Tree-sitter grammar for {lang} not found: {e}. Hard skipping code file."
        )
        return None


def _text_split_fallback(text, max_chars, overlap_lines=3):
    """Split oversized text at line boundaries when AST cannot subdivide further.
    If the text has no line breaks (single long line), falls back to character-level
    splitting with ~20% overlap so no chunk exceeds max_chars."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return []
    # Single long line with no breaks: split at character boundaries
    if len(lines) == 1 and len(lines[0]) > max_chars:
        chunks = []
        t = lines[0]
        overlap_chars = min(max_chars // 5, 200)
        i = 0
        while i < len(t):
            end = min(i + max_chars, len(t))
            chunks.append(t[i:end])
            i = end - overlap_chars if end < len(t) else end
        return chunks
    # Multi-line: split at line boundaries with line-level overlap
    chunks, buf, n = [], [], 0
    for line in lines:
        # If a single line exceeds max_chars, split it at char boundaries first
        if len(line) > max_chars:
            if buf:
                chunks.append("".join(buf))
                buf, n = [], 0
            overlap_chars = min(max_chars // 5, 200)
            i = 0
            while i < len(line):
                end = min(i + max_chars, len(line))
                chunks.append(line[i:end])
                i = end - overlap_chars if end < len(line) else end
            continue
        if n + len(line) > max_chars and buf:
            chunks.append("".join(buf))
            # keep last overlap_lines as context for next chunk
            buf = buf[-overlap_lines:] if overlap_lines else []
            n = sum(len(l) for l in buf)
        buf.append(line)
        n += len(line)
    if buf:
        chunks.append("".join(buf))
    return chunks


def _ast_chunk(source, language, max_chars=2000):
    src = source.encode("utf-8")
    parser = _get_parser(language)
    if not parser:
        return []

    try:
        tree = parser.parse(src)
    except Exception:
        return []

    def txt(n):
        return src[n.start_byte : n.end_byte].decode("utf-8", "ignore")

    def symbol(n):
        for c in n.children:
            if c.type in ("identifier", "name"):
                return txt(c)
        return ""

    chunks = []

    def flush(buf, s, e, sym):
        t = "\n".join(buf).strip("\n")
        if t.strip():
            chunks.append((t, s, e, sym))

    def recurse(node):
        buf, s, e = [], None, None
        for ch in node.children:
            ctext = txt(ch)
            if len(ctext) > max_chars and ch.child_count:
                if buf:
                    flush(buf, s, e, symbol(node))
                    buf, s = [], None
                recurse(ch)
            elif len(ctext) > max_chars:
                # Oversized leaf: fall back to line-level text splitting
                if buf:
                    flush(buf, s, e, symbol(node))
                    buf, s = [], None
                sym = symbol(node)
                ls = ch.start_point[0] + 1
                le = ch.end_point[0] + 1
                for sub in _text_split_fallback(ctext, max_chars):
                    chunks.append((sub, ls, le, sym))
            else:
                if s is None:
                    s = ch.start_point[0] + 1
                buf.append(ctext)
                e = ch.end_point[0] + 1
                if sum(len(x) for x in buf) >= max_chars:
                    flush(buf, s, e, symbol(node))
                    buf, s = [], None
        if buf:
            flush(buf, s, e, symbol(node))

    root = tree.root_node
    if root.children:
        recurse(root)
    if not chunks:
        return []
    return chunks


def _classify(path, code_exts, text_doc_exts):
    ext = os.path.splitext(path)[1].lower()
    if ext in code_exts:
        return "code"
    if ext in text_doc_exts:
        return "text_doc"
    if ext in (IMAGE_EXTS | DOC_EXTS):
        return "ocr_doc"
    return None


def _walk_repo(repo_dir, ignore, code_exts, text_doc_exts, exclude_rel=frozenset()):
    repo_name = os.path.basename(repo_dir.rstrip("/"))
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [
            d
            for d in dirs
            if d.lower() not in ignore
            and d not in ("lancedb", "images")
            and not d.startswith(".")
        ]

        ocr_stems = {
            os.path.splitext(f)[0]
            for f in files
            if _classify(os.path.join(root, f), code_exts, text_doc_exts) == "ocr_doc"
        }

        for f in sorted(files):
            p = os.path.join(root, f)
            ext = os.path.splitext(f)[1].lower()
            stem = os.path.splitext(f)[0]

            if ext in text_doc_exts and stem in ocr_stems:
                continue

            kind = _classify(p, code_exts, text_doc_exts)
            if not kind:
                continue

            rel = os.path.relpath(p, repo_dir)
            if rel in exclude_rel:
                log.info(f"[RAG] exclude active file: {repo_name}/{rel}")
                continue
            yield p, kind, f"{repo_name}/{rel}"


def _collection_sources(job_dir, code_exts, text_doc_exts):
    subdirs, top_files = [], []
    for name in sorted(os.listdir(job_dir)):
        p = os.path.join(job_dir, name)
        if name in ("images", "lancedb") or name.startswith("."):
            continue
        if os.path.isdir(p):
            subdirs.append(p)
        elif os.path.isfile(p) and _classify(p, code_exts, text_doc_exts):
            top_files.append(p)
    return subdirs, top_files


def table_name_for(doc_or_stem):
    """Deterministic LanceDB table name for a document (used in batch=False mode).

    LanceDB only allows letters, digits, '.', '-', '_' in table names, so any other
    character (notably spaces) is collapsed to '_'. This is the SINGLE source of truth
    for the per-document table name: rag_manager creates the table with it and
    run_workflow sets ORACLE_COLLECTION with it, guaranteeing they always match.
    """
    stem = os.path.splitext(os.path.basename(str(doc_or_stem)))[0]
    name = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("_")
    return name or "doc"


def _rasterize(src_path, out_dir, dpi=150):
    """Return a list of tuples: (PNG_path, raw_pdf_text)."""
    ext = os.path.splitext(src_path)[1].lower()
    stem = os.path.splitext(os.path.basename(src_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    pages = []
    if ext in IMAGE_EXTS:
        from PIL import Image

        png = os.path.join(out_dir, f"{stem}_0001.png")
        Image.open(src_path).convert("RGB").save(png)
        pages.append((png, ""))  # Images have no text layer
    else:
        try:
            import fitz  # PyMuPDF: pdf/xps/epub/mobi/fb2/cbz/svg/txt

            doc = fitz.open(src_path)
        except Exception as e:
            log.warning(
                f"[RAG] skip {os.path.basename(src_path)}: unsupported ({e}); convert to PDF first."
            )
            return pages
        for i, page in enumerate(doc):
            png = os.path.join(out_dir, f"{stem}_{i + 1:04d}.png")
            page.get_pixmap(dpi=dpi).save(png)
            raw_text = page.get_text("text")
            pages.append((png, raw_text))
    return pages


def _ocr_image(png_path, model_id, api_base, prompt_text, max_tokens=2048, timeout=300, retries=1):
    """OCR a single page. Routes to a local endpoint (api_base set) or a cloud
    model via litellm (api_base empty/None).  Omit ocr_api_base in the YAML
    (or set to "") and set ocr_agent to a cloud model (e.g.
    'gemini/gemini-2.5-flash') to use cloud OCR instead of a local vision
    server."""
    with open(png_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("utf-8")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ],
        }
    ]
    last_err = None
    for attempt in range(retries + 1):
        try:
            if api_base:
                # Local endpoint: direct HTTP (llama-server, ollama, etc.)
                import requests as _req

                payload = {"model": model_id, "messages": messages}
                if max_tokens:
                    payload["max_tokens"] = max_tokens

                r = _req.post(
                    f"{api_base}/chat/completions",
                    json=payload,
                    timeout=timeout,
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            else:
                # Cloud model: route through litellm (gemini/, openai/, etc.)
                import litellm

                kwargs = {"model": model_id, "messages": messages}
                if max_tokens:
                    kwargs["max_tokens"] = max_tokens
                r = litellm.completion(**kwargs)
                return r["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last_err


def _chunk(markdown_text, chunk_size_chars=800, chunk_overlap_chars=100):
    """Header-aware, then size-capped — but fenced code blocks are atomic (never split
    mid-block), so code inside vignettes/READMEs/papers stays intact."""
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    sections = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")]
    ).split_text(markdown_text)
    sizer = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size_chars, chunk_overlap=chunk_overlap_chars
    )
    out = []
    for s in sections:
        for seg in _FENCE_RE.split(s.page_content):
            if not seg.strip():
                continue
            if seg.lstrip().startswith(("```", "~~~")):
                if len(seg) <= chunk_size_chars * 2:
                    out.append(seg)
                else:
                    fm = re.match(r"^(```\w*|~~~)", seg.lstrip())
                    f_head = fm.group(1) if fm else "```"
                    f_foot = "```" if "```" in f_head else "~~~"

                    buf, n = [f_head + "\n"], len(f_head) + 1
                    for line in seg.strip().splitlines(keepends=True)[1:-1]:
                        buf.append(line)
                        n += len(line)
                        if n >= chunk_size_chars:
                            buf.append(f_foot + "\n")
                            out.append("".join(buf))
                            buf, n = [f_head + "\n"], len(f_head) + 1
                    if len(buf) > 1:
                        buf.append(f_foot + "\n")
                        out.append("".join(buf))
            else:
                out.extend(sizer.split_text(seg))
    return out


def _ocr_one_page(
    pi,
    p,
    raw_text,
    npages,
    model_id,
    ocr_api_base,
    ocr_prompt,
    cer_threshold,
    ocr_max_retries,
    ocr_max_tokens=2048,
):
    """OCR a single page with CER-gated retries. Returns (page_index, best_md)."""
    best_md = ""
    best_cer = float("inf")

    for attempt in range(ocr_max_retries + 1):
        try:
            md_text = _ocr_image(
                p,
                model_id,
                ocr_api_base,
                ocr_prompt,
                max_tokens=ocr_max_tokens,
            )
        except Exception as e:
            log.error(f"\n[RAG]    page {pi}/{npages} OCR failed: {e}")
            continue

        if not raw_text.strip():
            best_md = md_text
            break

        cer = _calculate_cer(raw_text, md_text)
        if cer < best_cer:
            best_cer = cer
            best_md = md_text

        if cer <= cer_threshold:
            break

    # Safety fallback for digital PDFs: if OCR produced high CER (> 0.4) or garbage
    # and clean embedded PDF text layer exists, fall back to the native text layer.
    if raw_text.strip() and (len(raw_text.strip()) > 50) and best_cer > 0.4:
        best_md = raw_text.strip()

    return pi, best_md


def ingest(
    context_root,
    collection_name,
    embed_model,
    embed_backend="sentence-transformers",
    embed_api_base=None,
    chunk_size_chars=800,
    chunk_overlap_chars=100,
    ocr_api_base=None,
    ocr_agent=None,
    ocr_prompt=DEFAULT_OCR_PROMPT,
    overwrite=False,
    code_chunk_size=2000,
    working_repo=None,
    code_exclude=frozenset(),
    code_exts=None,
    text_doc_exts=None,
    ignore=None,
    cer_threshold=0.05,
    ocr_max_retries=2,
    ocr_parallel=1,
    batch=True,
    **kwargs,
):
    import lancedb
    from lancedb.pydantic import LanceModel, Vector

    job_dir = os.path.join(context_root, collection_name)
    if not os.path.isdir(job_dir):
        log.warning(
            f"[RAG] job folder not found: {job_dir} -> create it and add documents."
        )
        return False

    db = lancedb.connect(os.path.join(job_dir, "lancedb"))

    code_exts = set(code_exts or CODE_EXTS_DEFAULT)
    text_doc_exts = set(text_doc_exts or TEXT_DOC_EXTS_DEFAULT)
    ignore = set(x.lower() for x in (ignore or IGNORE_DEFAULT))

    try:
        _names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        existing_names = list(getattr(_names, "tables", _names))
    except Exception:
        existing_names = []

    try:
        _dim = len(
            embed_texts(
                ["dimension probe"], embed_backend, embed_model, embed_api_base
            )[0]
        )
    except Exception as e:
        log.error(f"[RAG] Failed to probe embedding model '{embed_model}': {e}")
        return False

    class RAGChunk(LanceModel):
        text: str
        vector: Vector(_dim)  # type: ignore
        source_file: str
        source_type: str  # "code" | "doc"
        language: str = ""
        symbol: str = ""
        line_start: int = 0
        line_end: int = 0

    # For cloud models (e.g. gemini/gemini-2.5-flash), keep the full name
    # so litellm can route by prefix.  For local models (ocr_api_base set),
    # strip the prefix as before (llama-server uses bare model names).
    _raw_agent = ocr_agent or ""
    model_id = _raw_agent if not ocr_api_base else _raw_agent.split("/", 1)[-1]
    img_dir = os.path.join(job_dir, "images")
    ocr_max_tokens = int(kwargs.get("ocr_max_tokens", 2048))
    cfg = dict(
        embed_backend=embed_backend,
        embed_model=embed_model,
        embed_api_base=embed_api_base,
        chunk_size_chars=chunk_size_chars,
        chunk_overlap_chars=chunk_overlap_chars,
        code_chunk_size=code_chunk_size,
        img_dir=img_dir,
        model_id=model_id,
        ocr_api_base=ocr_api_base,
        ocr_prompt=ocr_prompt,
        cer_threshold=cer_threshold,
        ocr_max_retries=ocr_max_retries,
        ocr_parallel=max(1, int(ocr_parallel)),
        ocr_max_tokens=ocr_max_tokens,
        _dim=_dim,
    )

    def _ocr_to_markdown(
        doc_path,
        img_dir,
        model_id,
        ocr_api_base,
        ocr_prompt,
        cer_threshold,
        ocr_max_retries,
        ocr_parallel=1,
        ocr_max_tokens=2048,
    ):
        md_path = os.path.join(
            os.path.dirname(doc_path),
            os.path.splitext(os.path.basename(doc_path))[0] + ".md",
        )
        if not overwrite and os.path.exists(md_path) and os.path.getsize(md_path) > 0:
            log.info(
                f"[RAG] Reusing existing OCR markdown for {os.path.basename(doc_path)}"
            )
            with open(md_path, "r", encoding="utf-8") as f:
                return f.read()

        pages = _rasterize(doc_path, img_dir)
        if not pages:
            log.warning(f"[RAG] {doc_path}: nothing to rasterize, skipping.")
            return ""

        npages = len(pages)
        results = {}  # {page_index: md_text}

        if ocr_parallel > 1:
            # Parallel OCR: use thread pool to process multiple pages concurrently.
            # Set ocr_parallel to match llama-server --parallel N or cloud rate limits.
            from concurrent.futures import ThreadPoolExecutor, as_completed

            sys.stderr.write(f"       OCR {npages} pages ({ocr_parallel} workers)\n")
            sys.stderr.flush()
            with ThreadPoolExecutor(max_workers=ocr_parallel) as pool:
                futures = {
                    pool.submit(
                        _ocr_one_page,
                        pi,
                        p,
                        raw,
                        npages,
                        model_id,
                        ocr_api_base,
                        ocr_prompt,
                        cer_threshold,
                        ocr_max_retries,
                        ocr_max_tokens,
                    ): pi
                    for pi, (p, raw) in enumerate(pages, 1)
                }
                for fut in as_completed(futures):
                    pi, md = fut.result()
                    results[pi] = md
                    sys.stderr.write(f"\r       page {pi}/{npages} done ")
                    sys.stderr.flush()
        else:
            # Sequential OCR (default): one page at a time with progress output.
            for pi, (p, raw_text) in enumerate(pages, 1):
                sys.stderr.write(f"\r       page {pi}/{npages} ")
                sys.stderr.flush()
                _, md = _ocr_one_page(
                    pi,
                    p,
                    raw_text,
                    npages,
                    model_id,
                    ocr_api_base,
                    ocr_prompt,
                    cer_threshold,
                    ocr_max_retries,
                    ocr_max_tokens,
                )
                results[pi] = md

        sys.stderr.write("\r" + " " * 45 + "\r")
        sys.stderr.flush()

        # Reassemble pages in order
        parts = [results[pi] for pi in sorted(results) if results[pi]]

        md_text = "\n\n".join(parts)
        with open(
            os.path.join(
                os.path.dirname(doc_path),
                os.path.splitext(os.path.basename(doc_path))[0] + ".md",
            ),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(md_text)
        return md_text

    def _rows_for(path, kind, source_file, language, cfg):
        if kind == "code":
            with open(path, encoding="utf-8", errors="ignore") as fh:
                src = fh.read()
            if language:
                pieces = _ast_chunk(src, language, cfg["code_chunk_size"])
                if not pieces:
                    log.warning(
                        f"[RAG] Skipping '{source_file}' - No valid chunks produced by AST."
                    )
                    return []
            else:
                log.warning(
                    f"[RAG] Skipping '{source_file}' - No grammar available for code chunks."
                )
                return []
            return [
                {
                    "text": t,
                    "source_file": source_file,
                    "source_type": "code",
                    "language": language or "",
                    "symbol": sym,
                    "line_start": ls,
                    "line_end": le,
                }
                for (t, ls, le, sym) in pieces
            ]

        if kind == "text_doc":
            with open(path, encoding="utf-8", errors="ignore") as fh:
                text_all = fh.read()
            chunks = _chunk(
                text_all, cfg["chunk_size_chars"], cfg["chunk_overlap_chars"]
            )
        else:  # ocr_doc
            md = _ocr_to_markdown(
                path,
                cfg["img_dir"],
                cfg["model_id"],
                cfg["ocr_api_base"],
                cfg["ocr_prompt"],
                cfg["cer_threshold"],
                cfg["ocr_max_retries"],
                cfg["ocr_parallel"],
                cfg["ocr_max_tokens"],
            )
            chunks = _chunk(md, cfg["chunk_size_chars"], cfg["chunk_overlap_chars"])

        return [
            {
                "text": c,
                "source_file": source_file,
                "source_type": "doc",
                "language": "",
                "symbol": "",
                "line_start": 0,
                "line_end": 0,
            }
            for c in chunks
        ]

    def _build_table(db, existing_names, table_name, entries, schema, cfg, overwrite):
        has = table_name in existing_names
        table = None
        existing_files = set()

        if has and not overwrite:
            try:
                table = db.open_table(table_name)
                schema_names = set(table.schema.names)
                existing_files = {
                    r["source_file"]
                    for r in table.search().select(["source_file"]).to_list()
                }
            except Exception as e:
                log.error(
                    f"[RAG] cannot read '{table_name}': {e}; abort (avoid duplication)."
                )
                return False
            if "source_type" not in schema_names or "language" not in schema_names:
                log.error(
                    f"[RAG] old-schema table '{table_name}' (pre-metadata); rebuild with `overwrite: true`."
                )
                return False
            if table.schema.field("vector").type.list_size != cfg["_dim"]:
                log.error(f"[RAG] dim mismatch on '{table_name}'; rebuild required.")
                return False
        elif has and overwrite:
            db.drop_table(table_name)
            has = False

        pending, appended = [], 0

        def flush():
            nonlocal table, appended
            if not pending:
                return
            vecs = embed_texts(
                [r["text"] for r in pending],
                cfg["embed_backend"],
                cfg["embed_model"],
                cfg["embed_api_base"],
            )
            for r, v in zip(pending, vecs):
                r["vector"] = v
            if table is None:
                table = db.create_table(table_name, schema=schema)
            table.add(pending)
            appended += len(pending)
            pending.clear()

        for abs_path, kind, sf in entries:
            if sf in existing_files and not overwrite:
                log.info(f"[RAG] skip embedded: {sf}")
                continue

            lang = (
                _lang_for_ext(os.path.splitext(abs_path)[1]) if kind == "code" else ""
            )
            rows = _rows_for(abs_path, kind, sf, lang, cfg)
            pending.extend(rows)

            if len(pending) >= FLUSH_CHUNK_THRESHOLD:
                flush()

        flush()
        if table is not None:
            _maybe_create_index(table, table_name)
        log.info(f"[RAG] table '{table_name}': +{appended} chunk(s)")
        return appended > 0 or bool(existing_files)

    subdirs, top_files = _collection_sources(job_dir, code_exts, text_doc_exts)
    jobs = []

    for repo in subdirs:
        repo_name = table_name_for(os.path.basename(repo))
        excl = (
            code_exclude
            if os.path.basename(repo.rstrip("/")) == working_repo
            else frozenset()
        )
        code_entries, doc_entries = [], []
        for p, kind, sf in _walk_repo(repo, ignore, code_exts, text_doc_exts, excl):
            (code_entries if kind == "code" else doc_entries).append((p, kind, sf))
        if code_entries:
            jobs.append((f"{collection_name}_{repo_name}_code", code_entries))
        if doc_entries:
            jobs.append((f"{collection_name}_{repo_name}_docs", doc_entries))

    if top_files:
        if batch:
            # Dedup generated .md sidecars from top-level files
            ocr_stems = {
                os.path.splitext(f)[0]
                for f in top_files
                if _classify(f, code_exts, text_doc_exts) == "ocr_doc"
            }
            entries = []
            for p in top_files:
                if (
                    os.path.splitext(p)[1].lower() in text_doc_exts
                    and os.path.splitext(p)[0] in ocr_stems
                ):
                    continue
                entries.append(
                    (p, _classify(p, code_exts, text_doc_exts), os.path.basename(p))
                )
            if entries:
                jobs.append((f"{collection_name}_docs", entries))
        else:
            ocr_stems = {
                os.path.splitext(f)[0]
                for f in top_files
                if _classify(f, code_exts, text_doc_exts) == "ocr_doc"
            }
            for p in top_files:
                if (
                    os.path.splitext(p)[1].lower() in text_doc_exts
                    and os.path.splitext(p)[0] in ocr_stems
                ):
                    continue
                jobs.append(
                    (
                        table_name_for(p),
                        [
                            (
                                p,
                                _classify(p, code_exts, text_doc_exts),
                                os.path.basename(p),
                            )
                        ],
                    )
                )

    if not jobs:
        log.warning(f"[RAG] no ingestable sources in {job_dir}")
        return False

    ok, failed = False, []
    for table_name, entries in jobs:
        try:
            ok = (
                _build_table(
                    db, existing_names, table_name, entries, RAGChunk, cfg, overwrite
                )
                or ok
            )
        except Exception as e:
            log.error(
                f"[RAG] table '{table_name}' failed: {e}; continuing with remaining jobs."
            )
            failed.append(table_name)

    if failed:
        log.warning(
            f"[RAG] '{collection_name}' DONE with {len(failed)} failure(s): {failed}"
        )
    else:
        log.info(f"[RAG] '{collection_name}' DONE: {len(jobs)} table(s)")
    return ok


def _from_config(yaml_path):
    import yaml

    with open(yaml_path, "r") as f:
        cfg = yaml.safe_load(f) or {}
    project_dir = str(cfg.get("working_directory", os.getcwd()))
    rag = cfg.get("rag", {}) or {}
    return ingest(
        context_root=os.path.join(project_dir, ".aider_factory", "markdown", "lanceDB"),
        collection_name=rag.get("collection_name", "knowledge"),
        embed_model=rag.get("embed_model", "BAAI/bge-m3"),
        ocr_api_base=cfg.get("ocr_api_base"),
        ocr_agent=rag.get("ocr_agent", ""),
        ocr_prompt=rag.get("ocr_prompt", DEFAULT_OCR_PROMPT),
        overwrite=bool(rag.get("overwrite", False)),
        cer_threshold=float(rag.get("cer_threshold", 0.05)),
        ocr_max_retries=int(rag.get("ocr_max_retries", 2)),
        ocr_parallel=int(rag.get("ocr_parallel", 1)),
        batch=bool(rag.get("batch", True)),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sd = os.path.dirname(os.path.abspath(__file__))
    _from_config(
        sys.argv[1] if len(sys.argv) > 1 else os.path.join(sd, "..", ".env.yml")
    )
