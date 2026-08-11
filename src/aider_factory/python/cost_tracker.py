import os
import sys
import json
import logging

_DEFAULT_SESSION_FILE = os.path.join(".aider_factory", ".oracle_session.json")
_PROCESS_SESSION_COST = 0.0

def _session_file():
    """Return the active session file path. Overridable via ORACLE_SESSION_FILE."""
    return os.environ.get("ORACLE_SESSION_FILE", _DEFAULT_SESSION_FILE)

def _session_cost_file():
    """Sidecar for cumulative session cost (Aider-style 'session' total)."""
    return _session_file() + ".costs.json"

def load_session_cost():
    cf = _session_cost_file()
    if os.path.exists(cf):
        try:
            with open(cf, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            return float(data.get("session_cost", 0.0) or 0.0)
        except Exception:
            pass
    return 0.0

def save_session_cost(total_cost):
    cf = _session_cost_file()
    os.makedirs(os.path.dirname(cf), exist_ok=True)
    with open(cf, "w", encoding="utf-8") as f:
        json.dump({"session_cost": float(total_cost)}, f, ensure_ascii=False, indent=2)

def clear_session():
    """Wipes the LLM KV cache and the human-readable transcript."""
    TRANSCRIPT_FILE = os.path.join(".aider_factory", ".oracle_chat.history.md")
    for f in [_session_file(), _session_cost_file(), TRANSCRIPT_FILE]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass
    print("[oracle] 🧹 Session cleared.", file=sys.stderr)

def fmt_token_count(n):
    try:
        n = int(n or 0)
    except Exception:
        n = 0
    if n >= 1_000_000:
        v = n / 1_000_000.0
        return f"{v:.0f}M" if v >= 10 else f"{v:.1f}M".replace(".0M", "M")
    if n >= 10_000:
        return f"{n / 1000.0:.0f}k"
    if n >= 1000:
        return f"{n / 1000.0:.1f}k".replace(".0k", "k")
    return str(n)

def fmt_cost_usd(cost):
    try:
        cost = float(cost or 0.0)
    except Exception:
        cost = 0.0
    if cost <= 0:
        return "0.00"
    return f"{cost:.4f}" if cost < 0.01 else f"{cost:.2f}"

def response_usage(resp):
    usage = getattr(resp, "usage", None)
    if isinstance(resp, dict):
        usage = resp.get("usage")
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif hasattr(usage, "dict"):
        usage = usage.dict()
    return usage or {}

def response_content(resp):
    try:
        return resp["choices"][0]["message"]["content"]
    except Exception:
        return resp.choices[0].message.content

def litellm_cost_line(resp, *, persist_session=False):
    """Format Aider-style token/cost output for one LiteLLM completion response."""
    global _PROCESS_SESSION_COST

    usage = response_usage(resp)
    sent = usage.get("prompt_tokens", 0) or 0
    received = usage.get("completion_tokens", 0) or 0

    msg_cost = 0.0
    try:
        import litellm
        msg_cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
    except Exception:
        msg_cost = 0.0

    if persist_session:
        session_cost = load_session_cost() + msg_cost
        save_session_cost(session_cost)
    else:
        _PROCESS_SESSION_COST += msg_cost
        session_cost = _PROCESS_SESSION_COST

    return (
        f"Tokens: {fmt_token_count(sent)} sent, "
        f"{fmt_token_count(received)} received. "
        f"Cost: ${fmt_cost_usd(msg_cost)} message, "
        f"${fmt_cost_usd(session_cost)} session."
    )
