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

from validator import _ledger_save, _normalize  # shared, dependency-free helpers

_STATUS = "STATUS:"
_GATE = "GATE:"


def proposal_hash(text):
    """Hash the architect's PROPOSAL line(s); fall back to the whole turn."""
    props = re.findall(
        r"(?im)^[\s*>#*_`\-]*PROPOSAL[\s*_`]*[:\-]?[\s*_`]*(.+)$", text or ""
    )
    basis = " ".join(props) if props else (text or "")
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
    If draft_mode is True, the verdict is always considered actionable and no warning is added.
    oracle_response: the oracle's last reply (evidence citations + VERDICT line). Appended
    to the verdict file so downstream consumers see both sides of the debate.
    """
    actionable = (state == "agreed" and gate_present) or draft_mode
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
                f"{_STATUS} {state}\n{_GATE} {'present' if gate_present else 'none'}\n\n"
            )
            if state == "clean":
                f.write("> Already grounded; nothing to apply.\n\n")
            elif not actionable:
                f.write(
                    "> HELD FOR HUMAN REVIEW — no agreement reached (deadlock/exhausted). "
                    "Leave quotes as [evidence]; do NOT delete, re-tag, or fabricate.\n\n"
                )
            f.write("# Resolution\n\n" + (proposal or "").strip() + "\n")
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
    """True iff the verdict is an agreed, gate-backed, applicable resolution."""
    status, gate = _read_header(path)
    return status == "agreed" and gate == "present"


def save_ledger(path, data):
    if not path:
        return
    _ledger_save(path, data)
