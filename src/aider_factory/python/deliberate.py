#!/usr/bin/env python3
# deliberate.py — deterministic referee for two-party Oracle<->Architect debates.
#
# Pure logic: parse the agents' structured end-lines, hash the architect's position,
# decide the termination state, render the verdict, and gate the downstream edit.
# No model calls. Reuses validator's tiny shared helpers to stay DRY.
#
# Termination (observable signals only — no comprehension):
#   'agreed'    - the oracle's last verdict is AGREE,
#   'deadlock'  - the architect repeated the same proposal AND the oracle still OBJECTs,
#   'exhausted' - the loop cap was hit (decided by the caller),
#   'continue'  - keep debating.
#
# The DEBATE never consults the deterministic gate; agreement (or stalemate) is the
# only stop. The gate is a SEPARATE truth check applied AFTER the edit (Node B). A
# verdict is "actionable" only when an agreed debate is backed by a gate.

import hashlib
import os
import re
import sys
from typing import Optional

from validator import _ledger_save, _normalize  # shared, dependency-free helpers

_STATUS = "STATUS:"
_GATE = "GATE:"

EVALUATION_CONTRACT = (
    "\n\n<evaluation_contract>\n"
    "Critically evaluate the Architect's proposal in accordance with your persona guidelines. "
    "Structure your response exactly as follows:\n"
    "<critique>\n"
    "[Step-by-step analysis of edge cases, logic flaws, and RAG grounding]\n"
    "</critique>\n"
    "VERDICT: [AGREE | REVISE | OBJECT - <reason>]\n"
    "</evaluation_contract>"
)

PROPOSAL_TERMINAL_ANCHOR = (
    "Conclude your response with EXACTLY this terminal line:\n"
    "PROPOSAL: <one-line summary of resolution>"
)


def proposal_hash(text):
    """Hash the architect's proposal, combining PROPOSAL lines with sanitized specification body."""
    props = re.findall(
        r"(?im)^[\s*>#*_`\-]*PROPOSAL[\s*_`]*[:\-]?[\s*_`]*(.+)$", text or ""
    )
    cleaned = sanitize_proposal_text(text)
    if props and cleaned:
        basis = " ".join(props) + "\n" + cleaned
    elif props:
        basis = " ".join(props)
    elif cleaned:
        basis = cleaned
    else:
        basis = text or ""
    return hashlib.sha1(_normalize(basis).encode("utf-8")).hexdigest()[:12]


def oracle_verdict(text):
    """'agree' | 'object' | 'revise' | None from the oracle's 'VERDICT: AGREE|OBJECT|REVISE' line."""
    clean = text or ""
    clean = re.sub(r"(?m)^```[a-zA-Z0-9_-]*\s*$", "", clean)
    clean = re.sub(r"(?is)<critique>.*?</critique>", "", clean)
    if re.search(r"(?i)<critique>", clean) and not re.search(r"(?i)</critique>", clean):
        clean = re.sub(
            r"(?ism)<critique>.*?(?=(?:^[\s*>#*_`\-]*VERDICT[\s*_`]*[:\-]?[\s*_`\[]*(?:AGREE|OBJECT|REVISE|DISAGREE|REJECT)\b)|\Z)",
            "",
            clean,
        )
    clean = re.sub(r"(?i)</?evaluation_contract>", "", clean)
    filtered_lines = [
        line for line in clean.splitlines()
        if not re.search(r"(?i)VERDICT.*?(?:AGREE|OBJECT|REVISE|DISAGREE|REJECT)\s*\|", line)
    ]
    clean = "\n".join(filtered_lines)
    m = re.findall(
        r"(?im)^[\s*>#*_`\-]*VERDICT[\s*_`]*[:\-]?[\s*_`\[]*(AGREE|OBJECT|REVISE|DISAGREE|REJECT)\b",
        clean,
    )
    if not m:
        return None
    raw_verdict = m[-1].lower()
    if raw_verdict in ("disagree", "reject"):
        return "object"
    return raw_verdict


def count_tasks(text: str) -> int:
    """Count discrete task definitions (### [Task ID: ...) in text."""
    if not text:
        return 0
    return len(re.findall(r"(?im)^[\s*>#*_`\-]*###\s*\[?Task\s+ID:", text))


def update_high_watermark_proposal(current_text: str, previous_proposal: str) -> str:
    """Preserve the most comprehensive proposal, preventing brief closing turns
    or delta responses from eclipsing an earlier cumulative task specification."""
    if not current_text or not current_text.strip():
        return previous_proposal or ""
    current_tasks = count_tasks(current_text)
    prev_tasks = count_tasks(previous_proposal)
    if current_tasks >= prev_tasks or prev_tasks == 0:
        return current_text
    return previous_proposal


def sanitize_proposal_text(raw: str) -> str:
    """Sanitize architect proposal text through 3-tier cleanup.
    Tier 1: Anchors to the earliest recognized specification header.
    Tier 2: Strips leading startup noise lines sequentially.
    Tier 3: Returns non-empty candidate or raw text fallback.
    """
    if not raw or not raw.strip():
        return ""

    text = raw.strip()

    # Tier 1: Search for earliest recognized specification header
    header_patterns = [
        r"(?im)^##\s+Scope\s+Analysis\b",
        r"(?im)^##\s+Implementation\s+Plan\b",
        r"(?im)^##\s+Remediation\s+Plan\b",
        r"(?im)^##\s+Problem\s+Diagnosis\b",
        r"(?im)^##\s+Root\s+Cause\b",
        r"(?im)^##\s+Executive\s+Summary\b",
        r"(?im)^##\s+Architectural\s+Specification\b",
        r"(?im)^###\s*\[?Task\s+ID:\b",
    ]

    earliest_pos = None
    for pattern in header_patterns:
        m = re.search(pattern, text)
        if m:
            if earliest_pos is None or m.start() < earliest_pos:
                earliest_pos = m.start()

    if earliest_pos is not None:
        return text[earliest_pos:].strip()

    # Tier 2: Line-by-line sequential stripping of known startup noise
    noise_prefixes = (
        "aider v",
        "main model:",
        "editor model:",
        "weak model:",
        "git repo:",
        "repo-map:",
        "added ",
        "tokens:",
        "cost:",
        "warning:",
        "scraping",
        "for more info",
        "use /help",
        "commit",
        "committing",
        "restored previous",
        "chat (read-only)",
        "to the chat (read-only)",
        "► thinking",
        "▸ thinking",
        "─",
        "►",
        "▸",
    )

    cleaned_lines = []
    past_header_noise = False
    for line in text.splitlines():
        line_stripped = line.strip().lower()
        if not past_header_noise:
            if not line_stripped:
                continue
            if any(line_stripped.startswith(p) for p in noise_prefixes) or "to the chat (read-only)" in line_stripped:
                continue
            past_header_noise = True
        cleaned_lines.append(line)

    candidate = "\n".join(cleaned_lines).strip()

    # Tier 3: Non-empty candidate or clean empty return for pure noise
    if candidate:
        return candidate
    return ""


def proposal_line(text):
    """The architect's last PROPOSAL: line (for clean ledger excerpts + live logs)."""
    m = re.findall(
        r"(?im)^[\s*>#*_`\-]*PROPOSAL[\s*_`]*[:\-]?[\s*_`]*(.+)$", text or ""
    )
    return m[-1].strip() if m else ""


def new_ledger(issue_id):
    return {"issue": issue_id, "turns": [], "state": "continue"}


def record_turn(ledger, turn, role, excerpt, **extra):
    ledger.setdefault("turns", []).append(
        {"turn": turn, "role": role, "excerpt": (excerpt or "")[:280], **extra}
    )


def consensus_state(ledger):
    """Return 'agreed' | 'deadlock' | 'continue' from the debate ledger so far."""
    turns = ledger.get("turns", [])
    arch = [t for t in turns if t["role"] == "architect"]
    orc = [t for t in turns if t["role"] == "oracle"]
    if not orc:
        return "continue"
    last = (orc[-1].get("verdict") or "").lower()
    if last == "agree":
        return "agreed"
    empty_hash = proposal_hash("")
    last_hash = arch[-1].get("proposal_hash") if arch else None
    stable = (
        len(arch) >= 2
        and bool(last_hash)
        and last_hash != empty_hash
        and last_hash == arch[-2].get("proposal_hash")
    )
    orc_verdicts = [(t.get("verdict") or "").lower() for t in orc if t.get("verdict")]
    prior_objected = len(orc_verdicts) >= 2 and orc_verdicts[-2] in ("object", "revise")
    if last in ("object", "revise") and stable and prior_objected:
        return "deadlock"
    return "continue"


def write_verdict(
    path, state, gate_present, proposal, draft_mode=False, oracle_response=None
):
    """Write the verdict Node B self-gates on. Returns True iff ACTIONABLE.

    Actionable = an 'agreed' debate backed by a gate. The apply step fixes what it can
    ([fixed]); a separate deterministic finalize flags the rest [unsupported] (only when
    the debate 'agreed'). 'clean' = the gate was already green. 'deadlock'/'exhausted' =
    no agreement -> held for a human (residuals stay [evidence]).
    If draft_mode is True, the verdict is actionable iff state is agreed.
    oracle_response: the oracle's last reply (evidence citations + VERDICT line). Appended
    to the verdict file so downstream consumers see both sides of the debate.
    """
    gate_token = "present" if gate_present else ("draft" if draft_mode else "none")
    actionable = (state == "agreed") if draft_mode else (state == "agreed" and gate_present)
    clean_proposal = sanitize_proposal_text(proposal)
    if not path:
        return actionable
    import tempfile
    target_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    os.close(fd)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(
                f"{_STATUS} {state}\n{_GATE} {gate_token}\n\n"
            )
            if state == "clean":
                f.write("> Already grounded; nothing to apply.\n\n")
            elif not actionable:
                f.write(
                    "> HELD FOR HUMAN REVIEW — no agreement reached (deadlock/exhausted). "
                    "Leave quotes as [evidence]; do NOT delete, re-tag, or fabricate.\n\n"
                )
            f.write("# Resolution\n\n" + (clean_proposal or "").strip() + "\n")
            if oracle_response:
                f.write("\n---\n\n# Oracle Assessment\n\n" + oracle_response.strip() + "\n")
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
    return actionable


def _read_header(path):
    status = gate = None
    if not path or not os.path.isfile(path):
        return status, gate
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith(_STATUS):
                    status = line[len(_STATUS) :].strip()
                elif line.startswith(_GATE):
                    gate = line[len(_GATE) :].strip()
                if status is not None and gate is not None:
                    break
    except OSError:
        return None, None
    return status, gate


def verdict_status(path):
    """The STATUS token of a verdict file (or None)."""
    return _read_header(path)[0]


def verdict_is_actionable(path):
    """True iff the verdict is an agreed, gate-backed, or agreed-draft applicable resolution."""
    status, gate = _read_header(path)
    return status == "agreed" and gate in ("present", "draft")


def save_ledger(path, data):
    if not path:
        return
    _ledger_save(path, data)


def load_persona_or_instruct_files(
    raw_val,
    project_dir: Optional[str] = None,
    resolve_fn=None,
    label: str = "Persona",
    strict: bool = False,
) -> Optional[list[str]]:
    """Resolve and load persona or instruction markdown files across debate rounds.

    When strict=True (CLI debate), a missing file prints an error to stderr and returns None.
    When strict=False (orchestrator), missing files are skipped.
    """
    if not raw_val:
        return []
    items = (
        [str(f).strip() for f in raw_val if f is not None and str(f).strip()]
        if isinstance(raw_val, (list, tuple))
        else [f.strip() for f in str(raw_val).split(",") if f.strip()]
    )
    base_dir = str(project_dir) if project_dir else os.getcwd()

    def _default_resolve(entry: str):
        expanded = os.path.expanduser(entry)
        cand_direct = (
            expanded if os.path.isabs(expanded) else os.path.join(base_dir, expanded)
        )
        if os.path.isfile(cand_direct):
            return os.path.normpath(cand_direct)
        try:
            try:
                from run_workflow import resolve_template_path
            except ImportError:
                from aider_factory.python.run_workflow import resolve_template_path
            cand = resolve_template_path(entry, project_directory=base_dir)
            if cand and os.path.isfile(cand):
                return cand
        except Exception:
            pass
        return os.path.normpath(cand_direct)

    resolver = resolve_fn or _default_resolve
    contents = []
    for entry in items:
        resolved = resolver(entry)
        if not resolved or not os.path.isfile(resolved):
            if strict:
                print(
                    f"[oracle] Error: {label} file not found: {entry}", file=sys.stderr
                )
                return None
            continue
        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                contents.append(f.read().strip())
        except Exception:
            if strict:
                print(
                    f"[oracle] Error: {label} file not found: {entry}", file=sys.stderr
                )
                return None
    return contents


def has_remaining_round_configs(round_idx: int, *configs) -> bool:
    """Return True if any multi-round configuration has entries beyond round_idx."""
    for raw_val in configs:
        if not raw_val:
            continue
        if isinstance(raw_val, (list, tuple)):
            if len(raw_val) > round_idx:
                return True
        elif isinstance(raw_val, str) and "," in raw_val:
            parts = [p.strip() for p in raw_val.split(",") if p.strip()]
            if len(parts) > round_idx:
                return True
    return False
