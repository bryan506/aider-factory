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
import math
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
for _n in ("huggingface_hub", "huggingface_hub.utils._http", "sentence_transformers", "transformers"):
    logging.getLogger(_n).setLevel(logging.ERROR)

import Levenshtein

log = logging.getLogger("rag_manager")

DEFAULT_OCR_PROMPT = (
    "Extract the text, tables, and mathematical formulas from this page into clean "
    "Markdown. Preserve all structural integrity."
)

_ST_CACHE = {}


try:
    from aider_factory.python.env_utils import resolve_api_key
except ImportError:
    from env_utils import resolve_api_key

_resolve_api_key = resolve_api_key


def _sanitize_for_embed(s: str) -> str:
    if not s:
        return "."
    s = re.sub(r"<\|([^|>]*)\|>", r"< \1 >", s)
    s = s.replace("<|", "< ").replace("|>", " >")
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]", " ", s)
    return s.strip() or "."


def _is_valid_vec(vec) -> bool:
    return (
        isinstance(vec, list)
        and len(vec) > 0
        and all(
            isinstance(x, (int, float))
            and not isinstance(x, bool)
            and math.isfinite(x)
            for x in vec
        )
    )


def _mean_pool_vecs(valid_vecs: list[list[float]]) -> list[float]:
    dim = len(valid_vecs[0])
    acc = [0.0] * dim
    for v in valid_vecs:
        for i, val in enumerate(v):
            acc[i] += float(val)
    norm = math.sqrt(sum(x * x for x in acc))
    norm = norm if norm > 1e-9 else 1.0
    return [x / norm for x in acc]


def embed_texts(texts, backend, model, api_base, batch_size=8, max_batch_chars=7000):
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

            url = f"{api_base.rstrip('/')}/embeddings"
            headers = {
                "Authorization": "Bearer sk-dummy",
                "Content-Type": "application/json",
            }

            def _embed_single_safe(text_item: str, chunk_idx: int = -1):
                clean_cand = _sanitize_for_embed(text_item)
                print(
                    f"      [warn] chunk {chunk_idx} (len={len(clean_cand)}) returned NaN; flushing slot & entering recovery...",
                    file=sys.stderr,
                )

                # 6,000-char clean flush payload to overwrite poisoned KV/compute buffer past len(clean_cand)
                flush_pad = " ".join(f"item_{i}" for i in range(850))

                # Tier 1: Flush poisoned slot, then try 2-sequence halves [first_half, second_half]
                if len(clean_cand) >= 256:
                    half_len = len(clean_cand) // 2
                    first_half = clean_cand[:half_len].strip()
                    second_half = clean_cand[half_len:].strip()
                    if first_half and second_half:
                        try:
                            _req.post(
                                url,
                                json={"input": [flush_pad, "ok"], "model": model},
                                headers=headers,
                                timeout=(10, 60),
                            )
                            r_halves = _req.post(
                                url,
                                json={"input": [first_half, second_half], "model": model},
                                headers=headers,
                                timeout=(10, 60),
                            )
                            r_halves.raise_for_status()
                            half_data = r_halves.json().get("data", [])
                            if (
                                len(half_data) == 2
                                and all(_is_valid_vec(d.get("embedding")) for d in half_data)
                                and len(half_data[0]["embedding"]) == len(half_data[1]["embedding"])
                            ):
                                print(
                                    f"      [recovery] chunk {chunk_idx} (len={len(clean_cand)}) recovered via "
                                    f"slot-flush + 2-seq halves pool",
                                    file=sys.stderr,
                                )
                                return _mean_pool_vecs(
                                    [half_data[0]["embedding"], half_data[1]["embedding"]]
                                )
                        except _req.exceptions.ConnectionError as e:
                            print(
                                f"      [warn] chunk {chunk_idx} Tier 1 connection failed ({e}); aborting recovery.",
                                file=sys.stderr,
                            )
                            return None
                        except Exception as e:
                            print(
                                f"      [warn] chunk {chunk_idx} Tier 1 halves recovery failed: {e}",
                                file=sys.stderr,
                            )

                # Tier 2: Language-neutral deduplicated identifier distillation
                words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", clean_cand)
                unique_words = list(dict.fromkeys(words))
                distilled_text = (
                    ("code symbols: " + " ".join(unique_words))[:3000].strip() or "code"
                )

                for attempt in range(1, 4):
                    try:
                        _req.post(
                            url,
                            json={"input": [flush_pad, "ok"], "model": model},
                            headers=headers,
                            timeout=(10, 60),
                        )
                        r_rec = _req.post(
                            url,
                            json={"input": [distilled_text, "ok"], "model": model},
                            headers=headers,
                            timeout=(10, 60),
                        )
                        r_rec.raise_for_status()
                        rec_data = r_rec.json().get("data", [])
                        if rec_data and _is_valid_vec(rec_data[0].get("embedding")):
                            print(
                                f"      [recovery] chunk {chunk_idx} (len={len(clean_cand)}) recovered on attempt {attempt} "
                                f"via slot-flush + deduplicated identifiers (len={len(distilled_text)}, words={len(unique_words)})",
                                file=sys.stderr,
                            )
                            return rec_data[0]["embedding"]
                    except _req.exceptions.ConnectionError as e:
                        print(
                            f"      [warn] chunk {chunk_idx} Tier 2 connection failed ({e}); aborting recovery.",
                            file=sys.stderr,
                        )
                        return None
                    except Exception as e:
                        print(
                            f"      [warn] chunk {chunk_idx} Tier 2 attempt {attempt} failed: {e}",
                            file=sys.stderr,
                        )
                return None

            sanitized_texts = [_sanitize_for_embed(t) for t in texts]
            idx = 0
            while idx < len(sanitized_texts):
                batch_slice = []
                batch_indices = []
                batch_chars = 0
                while idx < len(sanitized_texts) and len(batch_slice) < batch_size:
                    nxt = sanitized_texts[idx]
                    if batch_slice and (batch_chars + len(nxt) > max_batch_chars):
                        break
                    batch_slice.append(nxt)
                    batch_indices.append(idx)
                    batch_chars += len(nxt)
                    idx += 1

                try:
                    r = _req.post(
                        url,
                        json={"input": batch_slice, "model": model},
                        headers=headers,
                        timeout=(10, None),  # 10s connect; unlimited read
                    )
                    r.raise_for_status()
                    batch_data = r.json().get("data") or []
                    batch_vecs = [
                        batch_data[i].get("embedding")
                        if i < len(batch_data) and isinstance(batch_data[i], dict)
                        else None
                        for i in range(len(batch_slice))
                    ]
                except _req.exceptions.ConnectionError as e:
                    print(
                        f"      [warn] Batch POST connection failed ({e}); skipping recovery for disconnected batch.",
                        file=sys.stderr,
                    )
                    out.extend([None] * len(batch_slice))
                    continue
                except Exception as e:
                    print(
                        f"      [warn] Batch POST failed ({e}); falling back to safe item-by-item recovery...",
                        file=sys.stderr,
                    )
                    batch_vecs = [None] * len(batch_slice)
                for c_idx, t_item, vec in zip(batch_indices, batch_slice, batch_vecs):
                    if _is_valid_vec(vec):
                        out.append(vec)
                    else:
                        out.append(_embed_single_safe(t_item, chunk_idx=c_idx))
        else:
            # Cloud model: route through litellm (gemini/, openai/, etc.)
            import litellm
            # Removed redundant local sys import

            try:
                from aider_factory.python.cost_tracker import fmt_token_count, fmt_cost_usd, _PROCESS_SESSION_COST
                import aider_factory.python.cost_tracker as ct
            except ImportError:
                from cost_tracker import fmt_token_count, fmt_cost_usd, _PROCESS_SESSION_COST
                import cost_tracker as ct

            total_sent = 0
            total_cost = 0.0

            emb_key = _resolve_api_key(model, None)

            for i in range(0, len(texts), batch_size):
                batch_input = texts[i : i + batch_size]
                emb_kwargs = {"model": model, "input": batch_input, "timeout": 60}
                if emb_key:
                    emb_kwargs["api_key"] = emb_key

                retries = 3
                last_err = None
                r = None
                for attempt in range(retries + 1):
                    try:
                        r = litellm.embedding(**emb_kwargs)
                        break
                    except Exception as e:
                        last_err = e
                        if attempt < retries:
                            time.sleep(2 * (attempt + 1))
                if r is None:
                    raise last_err

                out.extend(d["embedding"] for d in r["data"])
                
                try:
                    usage = r.get("usage", {})
                    if hasattr(usage, "model_dump"): usage = usage.model_dump()
                    elif hasattr(usage, "dict"): usage = usage.dict()
                    elif not isinstance(usage, dict): usage = vars(usage) if hasattr(usage, "__dict__") else {}
                    total_sent += usage.get("prompt_tokens", 0)
                except Exception:
                    pass

                try:
                    total_cost += float(litellm.completion_cost(completion_response=r) or 0.0)
                except Exception:
                    pass
            
            if total_sent > 0 or total_cost > 0:
                ct._PROCESS_SESSION_COST += total_cost
                session_cost = ct._PROCESS_SESSION_COST
                print(
                    f"Tokens: {fmt_token_count(total_sent)} sent, 0 received. "
                    f"Cost: ${fmt_cost_usd(total_cost)} message, "
                    f"${fmt_cost_usd(session_cost)} session.",
                    file=sys.stderr
                )
    elif backend == "sentence-transformers":
        from sentence_transformers import SentenceTransformer

        if model not in _ST_CACHE:
            try:
                # Offline-first: load directly from local cache (zero network calls)
                _ST_CACHE[model] = SentenceTransformer(model, local_files_only=True)
            except Exception:
                # Cold-start fallback: download once if not present in local cache
                _ST_CACHE[model] = SentenceTransformer(model, local_files_only=False)
        st = _ST_CACHE[model]
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
DOC_EXTS = {
    ".pdf",
    ".xps",
    ".oxps",
    ".epub",
    ".mobi",
    ".fb2",
    ".cbz",
    ".svg",
    ".txt",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".asciidoc",
}

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
    ".aider_factory",
    "renv",
    "packrat",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "target",
    "out",
    "coverage",
    "htmlcov",
    "site",
    "_site",
    "data",
    "temp",
    "tmp",
    "tempfiles",
    "logs",
    "log",
    "secrets",
    "credentials",
    "vendor",
    "third_party",
    "ai-agent-config",
    "cursor-skills",
    "skeleton",
    ".rproj.user",
}

AGENT_HARNESS_FILES = {
    "agents.md",
    "claude.md",
    "gemini.md",
    "conventions.md",
    "readme.skeleton.md",
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


_DEF_NODE_TYPES = {
    "function_definition",
    "class_definition",
    "decorated_definition",
    "method_definition",
    "function_declaration",
    "class_declaration",
    "method_declaration",
    "struct_item",
    "impl_item",
    "trait_item",
    "function_item",
    "method",
    "singleton_method",
}


def _text_split_fallback(text, max_chars, overlap_lines=3):
    """Split oversized text at line boundaries when AST cannot subdivide further.
    If the text has no line breaks (single long line), falls back to character-level
    splitting with ~20% overlap so no chunk exceeds max_chars."""
    max_chars = max(1, int(max_chars))
    overlap_lines = max(0, int(overlap_lines or 0))
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
            while buf and n + len(line) > max_chars:
                removed = buf.pop(0)
                n -= len(removed)
        buf.append(line)
        n += len(line)
    if buf:
        chunks.append("".join(buf))
    return chunks


def _ast_chunk(source, language, max_chars=6000):
    if not source or not source.strip():
        return []
    src = source.encode("utf-8")
    parser = _get_parser(language)
    if not parser:
        return []

    try:
        tree = parser.parse(src)
    except Exception:
        return []

    def txt_bytes(start_b: int, end_b: int) -> str:
        return src[start_b:end_b].decode("utf-8", "ignore")

    def extract_def_symbol(n) -> str:
        target = n
        if n.type == "decorated_definition":
            for c in n.children:
                if c.type in _DEF_NODE_TYPES and c.type != "decorated_definition":
                    target = c
                    break
        if target.type in ("binary_operator", "left_assignment", "equals_assignment"):
            if (
                any(c.type == "function_definition" for c in target.children)
                and target.children
            ):
                first_c = target.children[0]
                if first_c.type in ("identifier", "name"):
                    return txt_bytes(first_c.start_byte, first_c.end_byte).strip()
            return ""
        if target.type not in _DEF_NODE_TYPES:
            return ""
        name_node = (
            target.child_by_field_name("name")
            if hasattr(target, "child_by_field_name")
            else None
        )
        if name_node is not None:
            cand = txt_bytes(name_node.start_byte, name_node.end_byte).strip()
            return "" if cand in ("function", "def", "class", "fn", "func") else cand
        for c in target.children:
            if c.type in (
                "identifier",
                "name",
                "type_identifier",
                "property_identifier",
                "word",
            ):
                cand = txt_bytes(c.start_byte, c.end_byte).strip()
                if cand and cand not in ("function", "def", "class", "fn", "func"):
                    return cand
        return ""

    # Stage 1: Decompose AST into in-order spans <= max_chars
    spans = []  # (start_byte | None, end_byte_or_text, line_start, line_end, sym)

    def collect_spans(node, scope: str = ""):
        node_sym = extract_def_symbol(node)
        last_seg = scope.split(".")[-1] if scope else ""
        if node_sym and node_sym != last_seg:
            cur_scope = f"{scope}.{node_sym}" if scope else node_sym
        else:
            cur_scope = scope
        byte_len = node.end_byte - node.start_byte

        if byte_len <= max_chars:
            if byte_len > 0:
                spans.append(
                    (
                        node.start_byte,
                        node.end_byte,
                        node.start_point[0] + 1,
                        node.end_point[0] + 1,
                        cur_scope,
                    )
                )
            return

        if node.child_count > 0:
            for ch in node.children:
                collect_spans(ch, cur_scope)
            return

        leaf_text = txt_bytes(node.start_byte, node.end_byte)
        ls = node.start_point[0] + 1
        le = node.end_point[0] + 1
        leaf_budget = max(256, max_chars - 200)
        for sub in _text_split_fallback(leaf_text, leaf_budget):
            if sub.strip():
                spans.append((None, sub.strip("\n"), ls, max(le, ls + 1), cur_scope))

    root = tree.root_node
    if root.children:
        for child in root.children:
            collect_spans(child, "")

    if not spans:
        return []

    # Stage 2: Greedily merge contiguous byte spans up to max_chars
    raw_chunks = []
    win_sb = win_eb = win_ls = win_le = None
    win_sym = ""

    def emit_split_text(text_val: str, base_ls: int, base_le: int, sym: str):
        subs = [
            s.strip("\n")
            for s in _text_split_fallback(text_val, max_chars)
            if s.strip()
        ]
        cur_line = base_ls
        for sub in subs:
            n_lines = max(1, len(sub.splitlines()))
            sub_le = (
                min(base_le, cur_line + n_lines - 1)
                if base_le > cur_line
                else cur_line + n_lines - 1
            )
            raw_chunks.append((sub, cur_line, sub_le, sym))
            cur_line = sub_le

    def flush_win():
        nonlocal win_sb, win_eb, win_ls, win_le, win_sym
        if win_sb is None or win_eb is None:
            return
        t = txt_bytes(win_sb, win_eb).strip("\n")
        if t.strip():
            if len(t) <= max_chars:
                raw_chunks.append((t, win_ls, win_le, win_sym))
            else:
                emit_split_text(t, win_ls, win_le, win_sym)
        win_sb = win_eb = win_ls = win_le = None
        win_sym = ""

    for sb, eb_or_text, ls, le, sym in spans:
        if sb is None:
            if win_sb is not None and (win_ls == win_le or (win_eb - win_sb) < 160):
                hdr_t = txt_bytes(win_sb, win_eb).strip("\n")
                combined = f"{hdr_t}\n{eb_or_text}" if hdr_t else eb_or_text
                comb_ls = win_ls
                comb_sym = win_sym or sym
                win_sb = win_eb = win_ls = win_le = None
                win_sym = ""
                emit_split_text(combined, comb_ls, le, comb_sym)
            else:
                flush_win()
                raw_chunks.append((eb_or_text, ls, le, sym))
            continue

        if win_sb is not None:
            if (eb_or_text - win_sb) <= max_chars:
                win_eb = eb_or_text
                win_le = le
                if sym and (not win_sym or ("." in sym and "." not in win_sym)):
                    win_sym = sym
                continue
            if win_ls == win_le or (win_eb - win_sb) < 160:
                combined_text = txt_bytes(win_sb, eb_or_text).strip("\n")
                comb_ls = win_ls
                comb_sym = sym if (sym and ("." in sym or not win_sym)) else win_sym
                win_sb = win_eb = win_ls = win_le = None
                win_sym = ""
                emit_split_text(combined_text, comb_ls, le, comb_sym)
                continue

        flush_win()
        win_sb = sb
        win_eb = eb_or_text
        win_ls = ls
        win_le = le
        win_sym = sym

    flush_win()

    # Final pass: eliminate any remaining 1-line orphan chunks by merging or borrowing context lines
    merged = []
    for t, ls, le, sym in raw_chunks:
        is_one_line = (ls == le) or (len(t.splitlines()) == 1)
        if merged and is_one_line:
            pt, pls, ple, psym = merged[-1]
            if len(pt) + 1 + len(t) <= max_chars:
                merged[-1] = (f"{pt}\n{t}", pls, max(ple, le, pls + 1), psym or sym)
                continue
            prev_lines = pt.splitlines()
            if len(prev_lines) > 4:
                borrow = prev_lines[-3:]
                kept = "\n".join(prev_lines[:-3])
                rebalanced = "\n".join(borrow) + "\n" + t
                if len(rebalanced) <= max_chars:
                    merged[-1] = (kept, pls, max(pls + 1, ple - 3), psym)
                    merged.append(
                        (rebalanced, max(1, ls - 3), max(le, ls + 1), sym or psym)
                    )
                    continue
        merged.append((t, ls, le, sym))

    if len(merged) > 1 and (
        merged[0][1] == merged[0][2] or len(merged[0][0].splitlines()) == 1
    ):
        t0, ls0, _le0, sym0 = merged[0]
        t1, _ls1, le1, sym1 = merged[1]
        if len(t0) + 1 + len(t1) <= max_chars:
            merged[1] = (f"{t0}\n{t1}", ls0, max(_le0, le1, ls0 + 1), sym0 or sym1)
            merged.pop(0)

    return merged


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
    repo_name = os.path.basename(str(repo_dir).rstrip("/\\"))
    effective_ignore = IGNORE_DEFAULT | {x.lower() for x in (ignore or ())}
    exclude_normalized = {e.replace("\\", "/") for e in (exclude_rel or set())}
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [
            d
            for d in dirs
            if d.lower() not in effective_ignore
            and d not in ("lancedb", "images")
            and not d.startswith(".")
        ]

        ocr_stems = {
            os.path.splitext(f)[0]
            for f in files
            if not f.startswith(".")
            and os.path.splitext(f)[1].lower() != ".html"
            and _classify(os.path.join(root, f), code_exts, text_doc_exts) == "ocr_doc"
        }
        text_doc_stems = {
            os.path.splitext(f)[0]
            for f in files
            if not f.startswith(".")
            and os.path.splitext(f)[1].lower() in text_doc_exts
        }

        for f in sorted(files):
            if f.startswith(".") or f.lower() in AGENT_HARNESS_FILES:
                continue
            p = os.path.join(root, f)
            ext = os.path.splitext(f)[1].lower()
            stem = os.path.splitext(f)[0]

            if ext == ".md" and stem in ocr_stems:
                continue
            if ext == ".html" and stem in text_doc_stems:
                continue

            kind = _classify(p, code_exts, text_doc_exts)
            if not kind:
                continue

            rel = os.path.relpath(p, repo_dir).replace("\\", "/")
            if rel in exclude_normalized:
                log.info(f"[RAG] exclude active file: {repo_name}/{rel}")
                continue
            yield p, kind, f"{repo_name}/{rel}"


def _collection_sources(job_dir, code_exts, text_doc_exts, ignore=None):
    subdirs, top_files = [], []
    effective_ignore = IGNORE_DEFAULT | {x.lower() for x in (ignore or ())}
    for name in sorted(os.listdir(job_dir)):
        p = os.path.join(job_dir, name)
        if (
            name in ("images", "lancedb")
            or name.startswith(".")
            or name.lower() in AGENT_HARNESS_FILES
        ):
            continue
        if os.path.isdir(p):
            if name.lower() not in effective_ignore:
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
                try:
                    from aider_factory.python.cost_tracker import response_content, litellm_cost_line
                except ImportError:
                    from cost_tracker import response_content, litellm_cost_line

                kwargs = {"model": model_id, "messages": messages}
                if max_tokens:
                    kwargs["max_tokens"] = max_tokens
                ocr_key = _resolve_api_key(model_id, None)
                if ocr_key:
                    kwargs["api_key"] = ocr_key
                r = litellm.completion(**kwargs)
                
                cost_line = litellm_cost_line(r, persist_session=False)
                import sys
                print(cost_line, file=sys.stderr)
                
                return response_content(r)
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last_err


def _chunk(markdown_text, chunk_size_chars=1500, chunk_overlap_chars=300):
    """Header-aware, then size-capped — but fenced code blocks are atomic (never split
    mid-block), so code inside vignettes/READMEs/papers stays intact."""
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    sections = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")],
        strip_headers=False,
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
    chunk_size_chars=1500,
    chunk_overlap_chars=300,
    ocr_api_base=None,
    ocr_agent=None,
    ocr_prompt=DEFAULT_OCR_PROMPT,
    overwrite=False,
    code_chunk_size=6000,
    working_repo=None,
    code_exclude=frozenset(),
    code_exts=None,
    text_doc_exts=None,
    ignore=None,
    cer_threshold=0.05,
    ocr_max_retries=2,
    ocr_parallel=1,
    batch=True,
    ocr_only=False,
    use_docling=True,
    docling_do_ocr=True,
    docling_timeout=None,
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
    ignore = IGNORE_DEFAULT | {x.lower() for x in (ignore or ())}

    try:
        _names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
        existing_names = list(getattr(_names, "tables", _names))
    except Exception:
        existing_names = []

    _dim = 1536  # Safe dummy value for ocr_only mode
    if not ocr_only:
        try:
            probe_vecs = embed_texts(
                ["dimension probe"], embed_backend, embed_model, embed_api_base
            )
            if not probe_vecs or not _is_valid_vec(probe_vecs[0]):
                raise RuntimeError("embedding dimension probe returned invalid/null vector")
            _dim = len(probe_vecs[0])
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
        ocr_only=ocr_only,
        use_docling=use_docling,
        docling_do_ocr=docling_do_ocr,
        docling_timeout=docling_timeout,
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
        use_docling=True,
        docling_do_ocr=True,
        docling_timeout=None,
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

        ext = os.path.splitext(doc_path)[1].lower()
        
        # Smart Routing: Skip raw images. Try Docling for digital PDFs and other docs when use_docling is True.
        if use_docling and ext not in IMAGE_EXTS:
            should_try_docling = True
            
            # Deterministic check for PDFs: only bypass Docling for scans if native OCR is disabled
            if ext == ".pdf" and not docling_do_ocr:
                should_try_docling = False
                try:
                    import fitz
                    doc = fitz.open(doc_path)
                    text_length = 0
                    for page in doc:
                        text_length += len(page.get_text("text").strip())
                        if text_length > 100:
                            should_try_docling = True
                            break
                except Exception:
                    pass

            if should_try_docling:
                sys.stderr.write(f"       [Docling] Attempting native parse for {os.path.basename(doc_path)}...\n")
                sys.stderr.flush()

                runner_script = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "docling_runner.py")
                )
                import subprocess
                try:
                    do_ocr_arg = "true" if docling_do_ocr else "false"
                    
                    # Pass the host's HF_HOME to the uv environment so Docling can use cached weights
                    env = os.environ.copy()
                    if "HF_HOME" not in env:
                        env["HF_HOME"] = os.path.expanduser("~/.cache/huggingface")
                    
                    result = subprocess.run(
                        ["uv", "run", "--with", "docling>=2.0.0", "python", runner_script, doc_path, md_path, do_ocr_arg],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=docling_timeout,
                        env=env,
                    )
                    if result.returncode == 0:
                        sys.stderr.write("       [Docling] Success! Extracted natively.\n")
                        sys.stderr.flush()
                        with open(md_path, "r", encoding="utf-8") as f:
                            return f.read()
                    else:
                        sys.stderr.write(f"       [Docling] Native parse failed (code {result.returncode}). Falling back to Vision OCR.\n")
                        if result.stderr:
                            sys.stderr.write(f"       [Docling Error] {result.stderr.strip()}\n")
                        sys.stderr.flush()
                except Exception as e:
                    sys.stderr.write(f"       [Docling] Subprocess failed: {e}. Falling back to Vision OCR.\n")
                    sys.stderr.flush()

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
                use_docling=cfg.get("use_docling", True),
                docling_do_ocr=cfg.get("docling_do_ocr", True),
                docling_timeout=cfg.get("docling_timeout"),
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
            valid_rows = []
            for r, v in zip(pending, vecs):
                if v is None:
                    log.warning(
                        f"[RAG] Skipping un-embeddable chunk (NaN/null vector) in "
                        f"'{r.get('source_file')}:{r.get('line_start')}-{r.get('line_end')}'"
                    )
                    continue
                r["vector"] = v
                valid_rows.append(r)
            if valid_rows:
                if table is None:
                    table = db.create_table(table_name, schema=schema)
                table.add(valid_rows)
                appended += len(valid_rows)
            pending.clear()

        for abs_path, kind, sf in entries:
            if sf in existing_files and not overwrite:
                log.info(f"[RAG] skip embedded: {sf}")
                continue

            lang = (
                _lang_for_ext(os.path.splitext(abs_path)[1]) if kind == "code" else ""
            )
            rows = _rows_for(abs_path, kind, sf, lang, cfg)
            
            if cfg.get("ocr_only"):
                continue
                
            pending.extend(rows)

            if len(pending) >= FLUSH_CHUNK_THRESHOLD:
                flush()

        flush()
        if table is not None:
            try:
                table.optimize()
            except Exception:
                pass
            _maybe_create_index(table, table_name)
        log.info(f"[RAG] table '{table_name}': +{appended} chunk(s)")
        return appended > 0 or bool(existing_files)

    subdirs, top_files = _collection_sources(job_dir, code_exts, text_doc_exts, ignore)
    jobs = []

    for repo in subdirs:
        repo_name = table_name_for(os.path.basename(repo))
        excl = (
            code_exclude
            if os.path.basename(repo.rstrip("/\\")) == working_repo
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
        ocr_stems = {
            os.path.splitext(f)[0]
            for f in top_files
            if os.path.splitext(f)[1].lower() != ".html"
            and _classify(f, code_exts, text_doc_exts) == "ocr_doc"
        }
        text_doc_stems = {
            os.path.splitext(f)[0]
            for f in top_files
            if os.path.splitext(f)[1].lower() in text_doc_exts
        }
        filtered_top_files = [
            p
            for p in top_files
            if not (
                (
                    os.path.splitext(p)[1].lower() == ".md"
                    and os.path.splitext(p)[0] in ocr_stems
                )
                or (
                    os.path.splitext(p)[1].lower() == ".html"
                    and os.path.splitext(p)[0] in text_doc_stems
                )
            )
        ]
        if batch:
            entries = [
                (p, _classify(p, code_exts, text_doc_exts), os.path.basename(p))
                for p in filtered_top_files
            ]
            if entries:
                jobs.append((f"{collection_name}_docs", entries))
        else:
            for p in filtered_top_files:
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

    with open(yaml_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    project_dir = str(cfg.get("working_directory", os.getcwd()))
    endpoints = cfg.get("endpoints", {}) or {}

    phases = cfg.get("phases", []) or []
    active_phase = (
        next((ph for ph in phases if ph.get("enabled", True)), {}) if phases else {}
    )
    phase_models = active_phase.get("models", {}) or {}
    phase_rag = active_phase.get("rag", {}) or {}
    global_rag = cfg.get("rag", {}) or {}
    collection_name = (
        phase_rag.get("collection_name")
        or global_rag.get("collection_name")
        or "knowledge"
    )
    embed_model = (
        phase_models.get("embed_model")
        or phase_rag.get("embed_model")
        or global_rag.get("embed_model")
        or "BAAI/bge-m3"
    )
    embed_api_base = endpoints.get("embed_api_base")
    embed_backend = (
        phase_rag.get("embed_backend")
        or global_rag.get("embed_backend")
        or phase_models.get("embed_backend")
        or "sentence-transformers"
    )

    if embed_api_base and embed_backend == "sentence-transformers":
        embed_backend = "openai"

    working_repo = (
        phase_rag.get("working_repo")
        or global_rag.get("working_repo")
        or os.path.basename(project_dir.replace("\\", "/").rstrip("/"))
    )
    code_exts = phase_rag.get("code_exts") or global_rag.get("code_exts")
    text_doc_exts = phase_rag.get("text_doc_exts") or global_rag.get("text_doc_exts")
    ignore = phase_rag.get("ignore") or global_rag.get("ignore")
    code_chunk_size = int(
        phase_rag.get("code_chunk_size")
        or global_rag.get("code_chunk_size")
        or 6000
    )

    return ingest(
        context_root=os.path.join(project_dir, ".aider_factory", "markdown", "lanceDB"),
        collection_name=collection_name,
        embed_model=embed_model,
        embed_backend=embed_backend,
        embed_api_base=embed_api_base,
        ocr_api_base=endpoints.get("ocr_api_base"),
        ocr_agent=phase_models.get("ocr_agent", ""),
        ocr_prompt=phase_rag.get("ocr_prompt", DEFAULT_OCR_PROMPT),
        overwrite=phase_rag.get("vectordb_overwrite", False),
        code_chunk_size=code_chunk_size,
        working_repo=working_repo,
        code_exts=code_exts,
        text_doc_exts=text_doc_exts,
        ignore=ignore,
        cer_threshold=0.05,
        ocr_max_retries=2,
        ocr_parallel=1,
        batch=True,
        use_docling=phase_rag.get("use_docling", True),
        docling_do_ocr=phase_rag.get("docling_do_ocr", True),
        docling_timeout=phase_rag.get("docling_timeout") or global_rag.get("docling_timeout", None),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sd = os.path.dirname(os.path.abspath(__file__))
    _from_config(
        sys.argv[1] if len(sys.argv) > 1 else os.path.join(sd, "..", ".env.yml")
    )
