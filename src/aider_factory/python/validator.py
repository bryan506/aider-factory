#!/usr/bin/env python3
# validator.py — evidence grounding audit for AI Factory literature reviews.
#
# Each anchor carries one short quote that must be a VERBATIM span of the OCR
# source. The anchor's tag is its state:
#   [evidence]  — authored / unverified resting state (human review if it survives).
#   [validated] — quote proven a verbatim substring of the OCR (deterministic).
#   [fixed]     — was failing; an agent healed the quote/claim to match the source.
#
# Two checks, deterministic-first:
#   1. Quote grounding (provable, no model): the normalized quote is an exact
#      substring of the normalized full OCR source. A grounded [evidence] anchor is
#      relabeled [validated] in place. No threshold, no fuzzy matching.
#   2. Region grounding (semantic, annotation): for each FAILING quote (a tripwire),
#      the surrounding REVIEW passage (its claim block + a small line margin) is
#      embedded and compared to the paper's LanceDB table (bge-small, cosine). The
#      similarity score and the retrieved SOURCE CHUNKS are written to the report so
#      the heal step (oracle + architect) can correct the quote AND the prose, and a
#      human can see which regions look hallucinated.
#
# A per-doc JSON ledger keyed on the set of tripped quotes drives a no-progress
# guard across the iterate loop. No automated step ever deletes a quote or writes
# the "Not specified in paper." sentinel.
#
#   <aider-venv-python> validator.py --file <review> --source <ocr.md> \
#       --report <out.md> [--ledger <ledger.json>] [--tag evidence] \
#       [--region-threshold 0.60] [--region-margin 2] [--top-k 5] \
#       [--db <lancedb_dir>] [--collection <table>]
#
# Run via the thin wrapper: .aider_factory/bash/validate ... (uses the aider venv).
# Exit 0 = stop (all grounded, OR no progress). Exit 1 = trips remain -> the .sh
# asks the oracle and the architect heals.

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid

# Generate session ID once per pipeline run for KV-cache stickiness
_PIPELINE_SESSION_ID = os.environ.get("LITELLM_SESSION_ID") or str(uuid.uuid4())
os.environ["LITELLM_SESSION_ID"] = _PIPELINE_SESSION_ID

# Quiet noisy ML/HTTP libs (region check loads sentence-transformers via lancedb).
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


# The template's explicit "no evidence" marker. A quote equal to this is an
# intentional terminal state (the field has no source support), NOT something to
# ground — so it is skipped by the auditor (never flagged/looped/relabeled).
_SENTINEL = "not specified in paper"

# Promotion states the validator/agent may assign. Combined with the authored tag
# (default "evidence") these form the anchor "family" the extractor recognizes.
_PROMOTED = ("validated", "fixed")
# Terminal "flagged for human" state, applied deterministically by the post-debate
# finalize step. Recognized as an anchor (counts toward the deletion guard) but never
# grounded-checked and never a failure — so the gate passes on grounded-or-[unsupported].
_FLAGGED = ("unsupported",)


def _normalize(s):
    """Collapse whitespace and unify common unicode quotes/dashes."""
    s = s.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", s).strip()


def _family(tag):
    return (tag,) + _PROMOTED + _FLAGGED


def _extract(raw_lines, tag):
    """Return [{idx, hdr, tag, quote, uncertain, raw}] for EVERY anchor in the family.

    Matches the tag anywhere on a line (bare / bullet / inline / backtick) plus an
    optional trailing `(OCR-uncertain)` marker. Uses finditer so MULTIPLE anchors on a
    single line are all returned (the debate's "split into two anchors" can leave two
    inline) — each carries `raw` (its exact matched text) so _relabel can target it
    unambiguously even when several anchors share a line. The sentinel is skipped.
    """
    fam = "|".join(re.escape(t) for t in _family(tag))
    pat = re.compile(r"`?\[(" + fam + r')\]`?\s*"([^"]+)"\s*(\(OCR-uncertain\))?')
    hdr, out = "(top)", []
    for idx, line in enumerate(raw_lines):
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            hdr = h.group(2).strip()
            continue
        for m in pat.finditer(line):
            quote = m.group(2)
            if _normalize(quote).lower().rstrip(".").strip() == _SENTINEL:
                continue
            out.append(
                {
                    "idx": idx,
                    "hdr": hdr,
                    "tag": m.group(1),
                    "quote": quote,
                    "uncertain": bool(m.group(3)),
                    "raw": m.group(0),
                }
            )
    return out


def _grounded(quote, source_norm):
    """Provable verbatim check: normalized quote is an exact substring of source."""
    return _normalize(quote) in source_norm


def _claim_block(raw_lines, idx, margin, para_margin=0):
    """The REVIEW passage around an anchor: its paragraph/bullet (bounded by a blank
    line or a heading) plus `para_margin` full paragraphs in each direction, plus
    +/- `margin` lines beyond the outermost paragraph. Headings are hard stops —
    the walk never crosses a ``## ...`` boundary even if `para_margin` is not
    exhausted."""
    n = len(raw_lines)

    def is_blank(i):
        return raw_lines[i].strip() == ""

    def is_heading(i):
        return bool(re.match(r"^#{1,6}\s", raw_lines[i].strip()))

    def boundary(i):
        return is_blank(i) or is_heading(i)

    # Step 1: find the quote's own paragraph (walk to nearest boundary).
    lo = idx
    while lo - 1 >= 0 and not boundary(lo - 1):
        lo -= 1
    hi = idx
    while hi + 1 < n and not boundary(hi + 1):
        hi += 1

    # Step 2: expand by para_margin full paragraphs in each direction.
    # A "paragraph" is a contiguous run of non-blank, non-heading lines.
    # Blank lines are consumed (skipped over); headings are hard stops.
    for _ in range(para_margin):
        # --- expand upward ---
        p = lo - 1
        # skip blank lines between paragraphs
        while p >= 0 and is_blank(p):
            p -= 1
        if p < 0 or is_heading(p):
            break  # hit top of document or a heading -> stop
        # walk through the paragraph body
        while p - 1 >= 0 and not boundary(p - 1):
            p -= 1
        lo = p

    for _ in range(para_margin):
        # --- expand downward ---
        p = hi + 1
        # skip blank lines between paragraphs
        while p < n and is_blank(p):
            p += 1
        if p >= n or is_heading(p):
            break  # hit end of document or a heading -> stop
        # walk through the paragraph body
        while p + 1 < n and not boundary(p + 1):
            p += 1
        hi = p

    # Step 3: add the fixed line margin beyond the outermost paragraph.
    lo = max(0, lo - margin)
    hi = min(n - 1, hi + margin)
    return "\n".join(raw_lines[lo : hi + 1]).strip()


def _rrf_merge(result_lists, k, c=60):
    """Reciprocal Rank Fusion across per-table hit lists -> one deterministic top-k."""
    scores, keep = {}, {}
    for rows in result_lists:
        for rank, r in enumerate(rows):
            key = (r.get("source_file", ""), (r.get("text", "") or "")[:64])
            scores[key] = scores.get(key, 0.0) + 1.0 / (c + rank)
            keep[key] = r
    ranked = sorted(scores, key=scores.get, reverse=True)[:k]
    return [keep[key] for key in ranked]


def _region(block, db_dir, collection, k):
    """Embed the review passage and compare to the paper's LanceDB table (cosine).

    Returns (similarity, [(source_file, chunk_text), ...]); similarity is None when
    the table is unavailable. stdout is muted so model-load noise never leaks."""
    if not block or not db_dir or not os.path.isdir(db_dir) or not collection:
        return None, []

    import contextlib
    import sys

    from rag_manager import embed_texts

    backend = os.environ.get("ORACLE_EMBED_BACKEND", "sentence-transformers")
    api_base = os.environ.get("ORACLE_EMBED_API_BASE")
    model = os.environ.get("ORACLE_EMBED_MODEL", "BAAI/bge-m3")

    if backend == "openai" and api_base:
        os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")
        import requests

        try:
            requests.get(f"{api_base}/models", timeout=2).raise_for_status()
        except Exception as e:
            print(
                f"[embed] endpoint unreachable at {api_base}: {e}; skipping region check.",
                file=sys.stderr,
            )
            return None, []

    per_table = []
    with contextlib.redirect_stdout(sys.stderr):
        try:
            import lancedb

            db = lancedb.connect(db_dir)
            _n = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
            all_tables = list(getattr(_n, "tables", _n))

            if collection and collection != "*":
                if collection in all_tables:
                    tables = [collection]
                else:
                    tables = [t for t in all_tables if t.startswith(collection + "_")]
            else:
                tables = list(all_tables)

            if not tables:
                return None, []

            # NO prefix (passage-to-passage comparison)
            bvec = embed_texts([block], backend, model, api_base)[0]
            
            for t in tables:
                try:
                    table = db.open_table(t)
                    per_table.append(table.search(bvec).metric("cosine").limit(k).to_list())
                except Exception:
                    continue
        except Exception:
            return None, []

    rows = _rrf_merge(per_table, k) if len(per_table) > 1 else (per_table[0] if per_table else [])
    if not rows:
        return None, []
        
    sim = 1.0 - float(rows[0].get("_distance", 1.0))
    chunks = [
        (r.get("source_file", "unknown"), (r.get("text", "") or "").strip())
        for r in rows
    ]
    return sim, chunks


# Default claim-faithfulness prompt for the grounding verifier. Generic instruct form;
# for a raw MiniCheck gguf you may prefer its native (document, claim) template — kept as a
# single constant so it's a one-line change.
_ENTAIL_PROMPT = (
    "<evidence_passages>\n{document}\n</evidence_passages>\n\n"
    "<claim_to_verify>\n{claim}\n</claim_to_verify>\n\n"
    "Is the CLAIM fully supported by the provided evidence passages? "
    "Answer only 'SUPPORTED' or 'UNSUPPORTED'."
)


def _parse_entail(reply):
    """Map a verifier reply to a support probability in [0,1] (None if unparseable).
    Handles labels (SUPPORTED/UNSUPPORTED, YES/NO, ENTAIL/CONTRADICT) and MiniCheck-style
    numeric replies (bare 1/0 or a 0.xx probability). 'unsupported' is tested first (it
    contains 'supported')."""
    if not reply:
        return None
    low = reply.strip().lower()
    if any(
        w in low for w in ("unsupported", "not support", "contradict")
    ) or low.startswith("no"):
        return 0.0
    if any(w in low for w in ("supported", "entail")) or low.startswith("yes"):
        return 1.0
    m = re.search(r"\d*\.?\d+", low)
    if m:
        try:
            v = float(m.group(0))
            if 0.0 <= v <= 1.0:
                return v
        except ValueError:
            pass
    return None


def _entail(claim, chunks, a):
    """Stateless claim-faithfulness check via a grounding verifier (e.g. MiniCheck) over the
    RETRIEVED chunks. Returns a support probability in [0,1], or None when no verifier is
    configured OR the call fails (caller then falls back to cosine). NEVER grants/denies
    GROUNDING (that stays exact-substring); this only scores the surrounding CLAIM and, at
    most, routes it to an agent. One-shot completion (no session file) -> stateless."""
    model = getattr(a, "grounding_model", None)
    if not model or not claim or not chunks:
        return None
    document = "\n\n".join(txt for _src, txt in chunks if txt).strip()
    if not document:
        return None
    prompt = _ENTAIL_PROMPT.format(document=document, claim=claim)
    import contextlib

    with contextlib.redirect_stdout(sys.stderr):  # keep any lib noise off stdout
        try:
            import litellm

            kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "custom_headers": {"x-litellm-session-id": _PIPELINE_SESSION_ID}
            }
            if getattr(a, "grounding_api_base", None):
                kwargs["api_base"] = a.grounding_api_base
            if getattr(a, "grounding_api_key", None):
                kwargs["api_key"] = a.grounding_api_key
            
            r = litellm.completion(**kwargs)
            
            try:
                from aider_factory.python.cost_tracker import response_content, litellm_cost_line
            except ImportError:
                from cost_tracker import response_content, litellm_cost_line

            reply = response_content(r)
            cost_line = litellm_cost_line(r, persist_session=False)
            print(cost_line, file=sys.stderr)
        except Exception as e:
            print(
                f"[entail] verifier failed: {e} (falling back to cosine)",
                file=sys.stderr,
            )
            return None
    return _parse_entail(reply)


def _verify(block, a):
    """Two-stage claim check: retrieve (cosine/bge, recall) THEN decide (entailment when a
    grounding model is set, else cosine — backward-compatible). Returns
    (method, score, chunks, threshold): method in {'entail','cosine'}, score in [0,1] or None."""
    sim, chunks = _region(block, a.db, a.collection, a.top_k)
    e = _entail(block, chunks, a)
    if e is not None:
        return "entail", e, chunks, a.entail_threshold
    return "cosine", sim, chunks, a.region_threshold


def _qhash(quote):
    """Stable short hash of a normalized quote (ledger / no-progress guard)."""
    return hashlib.sha1(_normalize(quote).encode("utf-8")).hexdigest()[:12]


def _ledger_load(path):
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"attempts": []}


def _ledger_save(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _relabel(raw_lines, item, new_tag, tag):
    """Relabel ONE specific anchor's tag token, preserving everything else verbatim.

    Targets the anchor by its exact matched text (`item['raw']`), so a line holding
    several anchors relabels the right one (not just the first). Order-independent: each
    anchor's `raw` carries its unique quote, so sibling anchors on the line stay findable.
    """
    fam = "|".join(re.escape(t) for t in _family(tag))
    raw = item["raw"]
    new_raw = re.sub(r"`?\[(" + fam + r")\]`?", "[" + new_tag + "]", raw, count=1)
    raw_lines[item["idx"]] = raw_lines[item["idx"]].replace(raw, new_raw, 1)


def _run(a):
    with open(a.file, encoding="utf-8") as fh:
        review = fh.read()
    with open(a.source, encoding="utf-8") as fh:
        raw_source = fh.read()
    source_norm = _normalize(raw_source)
    raw_lines = review.splitlines()
    had_nl = review.endswith("\n")
    items = _extract(raw_lines, a.tag)

    relabels = []  # [(item, new_tag)] — per-anchor (a line may hold several anchors)
    tripped = []  # ungrounded quotes needing heal (gate)
    claim_drift = []  # (c) verify_all: GROUNDED quote whose CLAIM fails entailment (annotate-only)
    warns = 0
    validated_now = 0
    fixed_ok = 0
    flagged = 0  # [unsupported] anchors: preserved + surfaced, never gate

    # B2 baseline: the pre-apply quote-hash SET the deliberation recorded. Used for
    #   (1) the deletion guard: recognized-anchor count must not drop below it (text
    #       changes/fixes keep the count; splits raise it; only a removal lowers it), and
    #   (2) tag assignment: a grounded [evidence] whose hash is NOT in the baseline was
    #       EDITED -> [fixed]; otherwise it is original -> [validated].
    # Phase 1 passes no --baseline-ledger -> empty set -> behavior unchanged (-> [validated]).
    _bl = _ledger_load(a.baseline_ledger) if a.baseline_ledger else {}
    baseline_hashes = set(_bl.get("quote_baseline") or [])
    floor_violation = bool(baseline_hashes) and len(items) < len(baseline_hashes)

    for it in items:
        if it["tag"] == "unsupported":
            flagged += 1
            continue  # flagged for human; never grounded-checked, never trips
        grounded = _grounded(it["quote"], source_norm)
        soft = it["uncertain"] or ("$" in it["quote"])
        if grounded:
            if (
                it["tag"] == a.tag
            ):  # authored [evidence] -> VALIDATOR assigns the grounded tag
                if baseline_hashes and _qhash(it["quote"]) not in baseline_hashes:
                    relabels.append((it, "fixed"))  # edited (new text) and now grounded
                    fixed_ok += 1
                else:
                    relabels.append(
                        (it, "validated")
                    )  # original text, merely confirmed
                    validated_now += 1
            elif it["tag"] == "fixed":
                fixed_ok += 1
            # already [validated] stays [validated]
            # (c) verify_all: check the surrounding CLAIM even for a grounded quote.
            # ANNOTATE-ONLY: never changes the grounding tag; never gates. (Escalation = later.)
            if getattr(a, "verify_all", False) and not soft:
                block = _claim_block(
                    raw_lines, it["idx"], a.region_margin, a.region_paragraphs
                )
                method, score, chunks, thr = _verify(block, a)
                if score is not None and score < thr:
                    claim_drift.append(
                        {
                            "hdr": it["hdr"],
                            "quote": it["quote"],
                            "block": block,
                            "method": method,
                            "score": score,
                            "thr": thr,
                            "chunks": chunks,
                        }
                    )
            continue
        if soft:
            warns += 1  # LaTeX / OCR-uncertain: reported elsewhere, never gates
            # Invariant (#5): a quote can't hold a grounding tag it can't prove. A soft-warn
            # is unverifiable verbatim, so an agent-written [fixed]/[validated] on an ungrounded
            # soft quote is bogus -> reset to the resting [evidence] tag (human review). Only
            # ever demotes; never promotes. Closes the soft-path false-grounding hole.
            if it["tag"] in _PROMOTED:
                relabels.append((it, a.tag))
            continue
        block = _claim_block(raw_lines, it["idx"], a.region_margin, a.region_paragraphs)
        method, score, chunks, thr = _verify(block, a)
        tripped.append(
            {
                "hdr": it["hdr"],
                "quote": it["quote"],
                "block": block,
                "method": method,
                "score": score,
                "thr": thr,
                "chunks": chunks,
            }
        )
        if it["tag"] == "validated":  # safety: a [validated] that no longer matches
            relabels.append((it, a.tag))

    if relabels:
        for it, new_tag in relabels:
            _relabel(raw_lines, it, new_tag, a.tag)
        with open(a.file, "w", encoding="utf-8") as f:
            f.write("\n".join(raw_lines) + ("\n" if had_nl else ""))

    # ---- ledger + no-progress guard (keyed on the tripped set) ----
    attempt = int(os.environ.get("VALIDATION_ATTEMPT", "0") or "0")
    cur = sorted(_qhash(t["quote"]) for t in tripped)
    no_progress = False
    if a.ledger:
        ledger = {"attempts": []} if attempt == 0 else _ledger_load(a.ledger)
        prev = ledger["attempts"][-1]["tripped"] if ledger["attempts"] else None
        ledger["attempts"].append(
            {
                "attempt": attempt,
                "tripped": cur,
                "validated": validated_now,
                "fixed": fixed_ok,
                "flagged": flagged,
                "warns": warns,
            }
        )
        _ledger_save(a.ledger, ledger)
        if prev is not None and prev == cur:
            no_progress = True

    total = len(items)
    if not tripped and not floor_violation and not claim_drift:
        if os.path.isfile(a.report):
            os.remove(a.report)
        print(
            f"[validate] {total} quote(s): all grounded "
            f"({validated_now} validated, {fixed_ok} fixed, {flagged} flagged, {warns} soft-warn).",
            file=sys.stderr,
        )
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
    with open(a.report, "w", encoding="utf-8") as f:
        head = "# Evidence grounding — needs healing"
        if floor_violation:
            head += " — ANCHOR COUNT DROPPED (a quote was deleted/hidden)"
        if no_progress:
            head += " — NO PROGRESS (loop stopped; manual review needed)"
        f.write(f"{head} — {os.path.basename(a.file)}\n\n")
        if floor_violation:
            f.write(
                f"> Anchor count {len(items)} is below the baseline {len(baseline_hashes)}: a quote "
                "was removed or re-tagged outside the vocabulary. Restore it (fix -> [fixed], or it "
                "will be flagged [unsupported]).\n\n"
            )
        f.write(
            f"{len(tripped)} unresolved · {validated_now} validated · {fixed_ok} fixed · "
            f"{flagged} flagged · {warns} soft-warn · {len(claim_drift)} claim-drift · "
            f"attempt {attempt}.\n"
        )
        for t in tripped:
            score, thr, method = t["score"], t["thr"], t["method"]
            score_s = "n/a" if score is None else f"{score:.2f}"
            risk = (
                ""
                if score is None
                else (
                    f"  (supported, {method})"
                    if score >= thr
                    else f"  (LOW — surrounding claim may be hallucinated, {method})"
                )
            )
            f.write(f"\n## {t['hdr']}\n")
            f.write(f"- claim support {score_s}{risk}\n")
            f.write(f'- [{a.tag}] "{t["quote"]}"\n')
            f.write("- review passage:\n\n```\n" + t["block"] + "\n```\n")
            if t["chunks"]:
                f.write("- source chunks (closest first):\n\n")
                for src, txt in t["chunks"]:
                    f.write(f"```\n[source: {src}]\n{txt}\n```\n")
        if claim_drift:  # (c) annotate-only — quotes are verbatim; the PROSE may drift
            f.write(
                f"\n---\n\n## Grounded quotes with UNSUPPORTED surrounding claims "
                f"({len(claim_drift)}) — the quote is verbatim, but the prose may misstate "
                f"the source (human review; not auto-gated)\n"
            )
            for t in claim_drift:
                f.write(f"\n### {t['hdr']}\n")
                f.write(f"- claim support {t['score']:.2f} (LOW, {t['method']})\n")
                f.write(f'- [grounded] "{t["quote"]}"\n')
                f.write("- review passage:\n\n```\n" + t["block"] + "\n```\n")
                for src, txt in t["chunks"]:
                    f.write(f"```\n[source: {src}]\n{txt}\n```\n")

    # Annotate-only claim_drift NEVER gates: exit 0 when nothing is ungrounded.
    if not tripped and not floor_violation:
        print(
            f"[validate] all quotes grounded · {len(claim_drift)} claim-drift annotation(s) "
            f"-> {a.report}",
            file=sys.stderr,
        )
        return 0
    print(
        f"[validate] {len(tripped)} unresolved / {validated_now} validated / "
        f"{total} total · attempt {attempt}"
        + (" · NO PROGRESS" if no_progress else "")
        + (" · ANCHOR DROP" if floor_violation else "")
        + f" -> {a.report}",
        file=sys.stderr,
    )
    return 0 if (no_progress and not floor_violation) else 1


# Max total inter-fragment gap (chars) for an ellipsis-spliced quote to be deterministically
# stitched back to ONE continuous source span. Splices wider than this skip text from a
# different region (a distant split) and are left untouched for the debate.
_MAX_STITCH_GAP = 200
# Matches an ellipsis splice marker: "..." (3+ dots), the unicode ellipsis "…", or spaced
# dots ". . .". A single sentence period (or "e.g.", "U.S.") never matches (needs 3 dots).
_ELLIPSIS = re.compile(r"\s*(?:\.{3,}|\u2026|\.(?:\s+\.){2,})\s*")


def _autofix(a):
    """Deterministic anchored-stitch repair (no agent, no fuzzy). For each ungrounded,
    non-soft-warn [tag]/[fixed] quote that was spliced with an ellipsis, locate every
    fragment as an EXACT substring of the source, in order and non-overlapping; if they
    resolve to ONE contiguous source span (total inter-fragment gap <= _MAX_STITCH_GAP),
    replace the quote with that exact span and relabel -> [fixed]. Every output is verbatim
    source (exact-substring verified), so it can never fabricate or mis-ground; anything that
    does not resolve cleanly (missing fragment, distant split, embedded quote) is left
    untouched for the debate. Idempotent — a second pass finds nothing left to stitch.

    Region gate: a verbatim stitch proves the QUOTE is real source, NOT that the surrounding
    REVIEW claim is faithful. Before committing, the claim block is region-checked (bge-small
    cosine vs the paper's table); if it looks hallucinated (sim < region_threshold) the stitch
    is DECLINED — the quote is left untouched ('...' intact) so the audit trips it and it
    escalates to the debate (agent judgment). The embedding never grants/denies grounding, only
    routes a suspicious claim to an agent; sim is None (no DB) -> accept (non-RAG callers)."""
    review = open(a.file, encoding="utf-8").read()
    raw_lines = review.splitlines()
    had_nl = review.endswith("\n")
    source_norm = _normalize(open(a.source, encoding="utf-8").read())
    n = 0
    held = 0  # spliced + verbatim, but weak region -> declined, left for the debate
    for it in _extract(raw_lines, a.tag):
        if it["tag"] not in (a.tag, "fixed") or it["uncertain"] or "$" in it["quote"]:
            continue  # soft-warn / wrong family: never touch formulas or promoted anchors
        q = it["quote"]
        if _grounded(q, source_norm):
            continue  # already a verbatim substring
        parts = [p for p in _ELLIPSIS.split(q) if p.strip()]
        if len(parts) < 2:
            continue  # not an ellipsis splice -> leave for the debate
        pos, spans, ok = 0, [], True
        for f in (_normalize(p) for p in parts):
            i = source_norm.find(f, pos)
            if i < 0:
                ok = False
                break
            spans.append((i, i + len(f)))
            pos = i + len(f)
        if not ok:
            continue  # a fragment isn't in the source -> not reconstructable here
        gap = (spans[-1][1] - spans[0][0]) - sum(e - s for s, e in spans)
        if gap > _MAX_STITCH_GAP:
            continue  # fragments span different regions (distant split) -> debate
        stitched = source_norm[spans[0][0] : spans[-1][1]]
        if '"' in stitched or not _grounded(stitched, source_norm):
            continue  # would break the single-line ["tag"] "..." format / paranoia check
        # Claim gate (annotation -> escalation; NOT a grounding decision): a verbatim stitch
        # proves the QUOTE text is real source, but not that the surrounding REVIEW claim
        # faithfully reflects it. Re-check the claim block via _verify (entailment when a
        # grounding model is set, else cosine); if unsupported (score < threshold) DECLINE the
        # stitch — leave the quote untouched ([tag], '...' intact) so the normal audit trips it
        # and it escalates to the debate. score is None (no verifier/DB) -> accept (no
        # regression). The verifier never grants or denies grounding, only routes to an agent.
        block = _claim_block(raw_lines, it["idx"], a.region_margin, 0)
        _method, score, _chunks, thr = _verify(
            block, a
        )  # entailment if configured, else cosine
        if score is not None and score < thr:
            held += 1
            continue  # claim not supported -> hold for the debate (do NOT strip the '...')
        # Relabel first (targets the exact anchor via it['raw']), THEN swap the quote text
        # (q is still uniquely present on the line after the tag-only relabel).
        _relabel(raw_lines, it, "fixed", a.tag)
        raw_lines[it["idx"]] = raw_lines[it["idx"]].replace(q, stitched, 1)
        n += 1
    if n:
        with open(a.file, "w", encoding="utf-8") as f:
            f.write("\n".join(raw_lines) + ("\n" if had_nl else ""))
    print(
        f"[autofix] {n} spliced quote(s) stitched -> [fixed]"
        + (f"; {held} held for region review (weak claim -> debate)" if held else ""),
        file=sys.stderr,
    )
    return n


def _finalize(a):
    """Terminal post-debate step. Two deterministic passes (no agent, no judgment), idempotent:

    1. PROMOTE (always, any debate state): the apply loop's strict gate may not have re-run
       after the final edit, leaving a now-grounded quote still tagged [<tag>]. Any grounded
       [<tag>] (not a soft-warn) is relabeled to its correct grounded tag — [fixed] if it was
       EDITED during the debate (hash not in the pre-apply baseline) else [validated]. A
       grounded quote is grounded regardless of how the debate ended.
    2. DEMOTE (only when the debate 'agreed'): any STILL-ungrounded grounding-claiming anchor
       ([<tag>] or a bogus [fixed]) -> [unsupported], PRESERVING the quote text — flagged for
       a human. deadlock/exhausted ungrounded residuals stay [<tag>] (a distinct, more-
       recoverable signal: unresolved, not provably-no-match)."""
    state = _ledger_load(a.baseline_ledger).get("state") if a.baseline_ledger else None
    baseline_hashes = (
        set(_ledger_load(a.baseline_ledger).get("quote_baseline") or [])
        if a.baseline_ledger
        else set()
    )
    review = open(a.file, encoding="utf-8").read()
    raw_lines = review.splitlines()
    had_nl = review.endswith("\n")
    source_norm = _normalize(open(a.source, encoding="utf-8").read())

    promoted = 0  # grounded [tag] -> [validated]/[fixed]
    demoted = 0  # agreed-ungrounded [tag]/[fixed] -> [unsupported]
    for it in _extract(raw_lines, a.tag):
        if it["tag"] not in (a.tag, "fixed") or it["uncertain"] or "$" in it["quote"]:
            continue
        if _grounded(it["quote"], source_norm):
            if (
                it["tag"] == a.tag
            ):  # only the authored [tag] needs promoting; [fixed] stays
                new_tag = (
                    "fixed"
                    if (baseline_hashes and _qhash(it["quote"]) not in baseline_hashes)
                    else "validated"
                )
                _relabel(raw_lines, it, new_tag, a.tag)
                promoted += 1
            continue
        # Still ungrounded: demote to [unsupported] ONLY when the debate agreed.
        if state == "agreed":
            _relabel(raw_lines, it, "unsupported", a.tag)
            demoted += 1

    if promoted or demoted:
        with open(a.file, "w", encoding="utf-8") as f:
            f.write("\n".join(raw_lines) + ("\n" if had_nl else ""))
    print(
        f"[finalize] debate state={state}; {promoted} grounded -> [validated]/[fixed], "
        f"{demoted} agreed-ungrounded -> [unsupported].",
        file=sys.stderr,
    )
    return 0


def _run_claims_only(a):
    """Validates raw text paragraphs without requiring [evidence] tags."""
    with open(a.file, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    paragraphs = []
    current_para = []
    in_code_block = False

    # Filter out code blocks, headers, and blank lines to extract clean paragraphs
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            if current_para:
                paragraphs.append("\n".join(current_para).strip())
                current_para = []
            continue

        if in_code_block:
            continue

        if stripped.startswith("#"):
            if current_para:
                paragraphs.append("\n".join(current_para).strip())
                current_para = []
            continue

        if not stripped:
            if current_para:
                paragraphs.append("\n".join(current_para).strip())
                current_para = []
            continue

        current_para.append(line)

    if current_para:
        paragraphs.append("\n".join(current_para).strip())

    tripped = []
    for i, block in enumerate(paragraphs):
        if not block:
            continue
        method, score, chunks, thr = _verify(block, a)
        if score is not None and score < thr:
            tripped.append({
                "idx": i + 1,
                "block": block,
                "method": method,
                "score": score,
                "chunks": chunks
            })

    if not tripped:
        if os.path.isfile(a.report):
            os.remove(a.report)
        msg = f"[validate] all claims grounded in {os.path.basename(a.file)}"
        if not a.no_print:
            print(msg)
        print(msg, file=sys.stderr)
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
    
    report_lines = [
        f"# Claim Verification — {os.path.basename(a.file)}\n",
        f"{len(tripped)} unsupported claims found.\n"
    ]

    for t in tripped:
        report_lines.append(f"## Paragraph {t['idx']}")
        report_lines.append(f"- claim support: {t['score']:.2f} (LOW, {t['method']})")
        report_lines.append("- review passage:\n```\n" + t['block'] + "\n```")
        if t['chunks']:
            report_lines.append("- source chunks (closest first):")
            for src, txt in t['chunks']:
                report_lines.append(f"```\n[source: {src}]\n{txt}\n```")
        report_lines.append("")

    report_text = "\n".join(report_lines)
    with open(a.report, "w", encoding="utf-8") as f:
        f.write(report_text)

    if not a.no_print:
        print(report_text)

    print(f"[validate] {len(tripped)} unresolved claims -> {a.report}", file=sys.stderr)
    return 1


def main():
    ap = argparse.ArgumentParser(description="Evidence grounding audit.")
    ap.add_argument("--file", required=True, help="generated document (review)")
    ap.add_argument("--source", required=False, help="OCR <stem>.md source of truth")
    ap.add_argument("--report", required=False, help="heal report to write")
    ap.add_argument("--claims-only", action="store_true", help="Verify raw text paragraphs without requiring [evidence] tags")
    ap.add_argument("--no-print", action="store_true", help="Suppress printing the report to stdout in claims-only mode")
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--tag", default=os.environ.get("ORACLE_VALIDATION_TAG", "evidence"))
    ap.add_argument(
        "--region-threshold", dest="region_threshold", type=float, default=float(os.environ.get("ORACLE_REGION_THRESHOLD", "0.60"))
    )
    ap.add_argument("--region-margin", dest="region_margin", type=int, default=int(os.environ.get("ORACLE_REGION_MARGIN", "2")))
    ap.add_argument(
        "--region-paragraphs", dest="region_paragraphs", type=int, default=int(os.environ.get("ORACLE_REGION_PARAGRAPHS", "0"))
    )
    ap.add_argument("--top-k", dest="top_k", type=int, default=int(os.environ.get("ORACLE_TOP_K", "5")))
    ap.add_argument("--db", default=os.environ.get("ORACLE_RAG_DB_DIR"))
    ap.add_argument("--collection", default=os.environ.get("ORACLE_COLLECTION"))
    # Deletion guard + B2 tags + finalize: debate ledger holding quote_baseline + state.
    ap.add_argument("--baseline-ledger", dest="baseline_ledger", default=None)
    # Deterministic terminal step: agreed-ungrounded [tag] quotes -> [unsupported].
    ap.add_argument(
        "--finalize-unsupported", dest="finalize_unsupported", action="store_true"
    )
    # Deterministic pre-step: stitch ellipsis-spliced quotes to a verbatim span, then audit.
    ap.add_argument("--autofix", action="store_true")
    # Grounding verifier (entailment). All default from env so EVERY caller (autofix node,
    # heal .sh, apply gate .sh, strict gate) inherits it with no flag/script changes. Unset
    # grounding-model -> cosine fallback (backward-compatible, no behavior change).
    ap.add_argument(
        "--grounding-model",
        dest="grounding_model",
        default=os.environ.get("GROUNDING_AGENT_MODEL"),
    )
    ap.add_argument(
        "--grounding-api-base",
        dest="grounding_api_base",
        default=os.environ.get("GROUNDING_AGENT_API_BASE"),
    )
    ap.add_argument(
        "--grounding-api-key",
        dest="grounding_api_key",
        default=os.environ.get("GROUNDING_AGENT_API_KEY"),
    )
    ap.add_argument(
        "--entail-threshold",
        dest="entail_threshold",
        type=float,
        default=float(os.environ.get("GROUNDING_ENTAIL_THRESHOLD", "0.5")),
    )
    ap.add_argument(
        "--verify-all",
        dest="verify_all",
        action="store_true",
        default=os.environ.get("GROUNDING_VERIFY_ALL", "0") == "1",
    )
    # Accepted for backward-compatibility (older callers / configs); ignored.
    ap.add_argument("--mode", default=None)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--context-lines", dest="context_lines", type=int, default=None)
    ap.add_argument(
        "--rescue-threshold", dest="rescue_threshold", type=float, default=None
    )
    a = ap.parse_args()

    # Auto-discover collection from YAML if missing
    if not a.collection:
        import yaml
        for yaml_path in [
            os.path.join(os.getcwd(), ".aider_factory", ".env.yml"),
            os.path.join(os.getcwd(), ".env.yml"),
        ]:
            if os.path.exists(yaml_path):
                try:
                    with open(yaml_path, "r") as f:
                        cfg = yaml.safe_load(f) or {}
                    phases = cfg.get("phases", [])
                    if phases:
                        active_phase = next((ph for ph in phases if ph.get("enabled")), phases[0])
                        rag_cfg = active_phase.get("rag", {})
                        if rag_cfg and rag_cfg.get("collection_name"):
                            a.collection = rag_cfg.get("collection_name")
                            break
                except Exception:
                    pass

    # Auto-discover DB path if missing but collection is known
    if not a.db and a.collection:
        # If the collection contains a slash, treat it as a global path
        if "/" in a.collection or "\\" in a.collection:
            abs_coll = os.path.abspath(os.path.normpath(a.collection))
            a.db = os.path.join(abs_coll, "lancedb")
            a.collection = os.path.basename(abs_coll)
        else:
            # Otherwise, treat it as a local project collection
            inferred_db = os.path.join(os.getcwd(), ".aider_factory", "markdown", "lanceDB", a.collection, "lancedb")
            if os.path.isdir(inferred_db):
                a.db = inferred_db

    if not os.path.isfile(a.file):
        print(f"[validate] missing file: {a.file} (skipping)", file=sys.stderr)
        return 0

    if a.claims_only:
        if not a.report:
            stem = os.path.splitext(os.path.basename(a.file))[0]
            a.report = os.path.join(".aider_factory", "temp", f"{stem}_claims_report.md")
        return _run_claims_only(a)

    if not a.source or not a.report:
        print("[validate] --source and --report are required unless using --claims-only", file=sys.stderr)
        return 1

    if not os.path.isfile(a.source):
        print(f"[validate] missing source: {a.source} (skipping)", file=sys.stderr)
        return 0

    if a.finalize_unsupported:
        return _finalize(a)
    if a.autofix:
        _autofix(
            a
        )  # deterministic stitch first; then the audit writes the residual report
    return _run(a)


if __name__ == "__main__":
    sys.exit(main())
