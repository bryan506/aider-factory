#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "minicheck @ git+https://github.com/Liyan06/MiniCheck.git@main",
#   "accelerate",
#   "sentencepiece",
#   "protobuf",
#   "fastapi",
#   "uvicorn",
# ]
# ///
# minicheck_server.py — OpenAI-compatible MiniCheck grounding verifier (Option 1).
#
# WHY: MiniCheck-Flan-T5-Large is a seq2seq CLASSIFIER, not a chat model. Its score is a
# calibrated probability read from the decoder's class logits by the official `minicheck`
# package (MiniCheck-Model(document, claim) -> {0,1} with raw_prob). A llama.cpp/gguf chat
# endpoint CANNOT reproduce it (chat template corrupts the T5 input; free generation ignores
# the logit). This shim runs the model the real way (HF weights, auto-downloaded — the gguf is
# NOT used) and exposes it over OpenAI /v1/chat/completions so the pipeline reaches it via
# litellm with zero validator changes.
#
# CONTRACT with validator._ENTAIL_PROMPT:
#   "DOCUMENT:\n{document}\n\nCLAIM:\n{claim}\n\nIs the CLAIM fully supported by the
#    DOCUMENT? Answer only 'SUPPORTED' or 'UNSUPPORTED'."
# We parse DOCUMENT + CLAIM out of that content, split the CLAIM into sentences (MiniCheck is
# a sentence-level checker), score each against the DOCUMENT, and return the MINIMUM support
# probability as the assistant message content (e.g. "0.9805"). validator._parse_entail reads
# that float. A scoring failure returns "0.0000" (reads as unsupported -> the pipeline
# escalates, the safe default). If BOTH change, keep the delimiter contract in sync.
#
# DEPLOY (uv, PEP 723 — no manual venv/pip):
#   uv run --locked minicheck_server.py        # first run downloads HF weights (~1GB) to cache
#   (systemd ExecStart points at `uv run --locked .../minicheck_server.py`; see the
#    AI Factory service manual, section 7.12.)
import os
import re
import time

from fastapi import FastAPI
from minicheck.minicheck import MiniCheck

# HF checkpoint alias understood by the minicheck package: 'flan-t5-large' | 'roberta-large'
# | 'deberta-v3-large' | 'Bespoke-MiniCheck-7B'. Default = the sub-1B Flan-T5 (CPU-friendly).
MODEL_NAME = os.environ.get("MINICHECK_MODEL", "flan-t5-large")
CACHE_DIR = os.environ.get("MINICHECK_CACHE", "./ckpts")
SERVED_ID = os.environ.get("MINICHECK_SERVED_ID", "minicheck-flan-t5-large")
PORT = int(os.environ.get("MINICHECK_PORT", "8090"))
# Drop sentence fragments shorter than this (markers, stray tokens) so trivial bits don't
# drag the min score down.
MIN_SENT_LEN = int(os.environ.get("MINICHECK_MIN_SENT_LEN", "8"))

app = FastAPI()
_scorer = MiniCheck(model_name=MODEL_NAME, cache_dir=CACHE_DIR)  # loads once at startup

# Anchor the CLAIM end on the fixed prompt trailer so blank lines INSIDE the document or the
# claim block don't truncate the parse (DOTALL, non-greedy).
_PARSE = re.compile(
    r"DOCUMENT:\s*(?P<doc>.*?)\n\nCLAIM:\s*(?P<claim>.*?)\n\nIs the CLAIM fully supported",
    re.DOTALL,
)


def _parse(content: str):
    """Extract (document, claim) from the validator's entailment prompt. Falls back to a
    plain CLAIM: split, then to treating the whole content as the claim."""
    m = _PARSE.search(content or "")
    if m:
        return m.group("doc").strip(), m.group("claim").strip()
    if "CLAIM:" in (content or ""):
        doc, _, claim = content.partition("CLAIM:")
        return doc.replace("DOCUMENT:", "").strip(), claim.strip()
    return "", (content or "").strip()


def _sentences(claim: str):
    """Split a (possibly multi-sentence) claim into sentences; MiniCheck checks sentence
    granularity. Keeps at least the whole claim if nothing splits out."""
    parts = re.split(r"(?<=[.!?])\s+", claim.strip())
    sents = [p.strip() for p in parts if len(p.strip()) >= MIN_SENT_LEN]
    return sents or [claim.strip()]


@app.post("/v1/chat/completions")
def chat(body: dict):
    msgs = body.get("messages", []) or []
    content = msgs[-1].get("content", "") if msgs else ""
    doc, claim = _parse(content)
    sents = _sentences(claim)
    try:
        _labels, probs, _, _ = _scorer.score(docs=[doc] * len(sents), claims=sents)
        # MINIMUM: the least-supported sentence governs (conservative — any unsupported
        # sentence flags the whole claim as drifted/ungrounded).
        score = float(min(probs)) if probs else 0.0
    except Exception:
        score = (
            0.0  # scoring failed -> read as unsupported -> pipeline escalates (safe)
        )
    return {
        "id": f"minicheck-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", SERVED_ID),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": f"{score:.4f}"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/v1/models")
def models():
    return {
        "object": "list",
        "data": [{"id": SERVED_ID, "object": "model", "owned_by": "minicheck"}],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
