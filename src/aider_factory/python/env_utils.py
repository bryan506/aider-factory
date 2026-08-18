import os
from typing import Optional

DUMMY_KEYS = frozenset({"sk-dummy", "dummy", "none", "null", ""})


def is_dummy_key(key: Optional[str]) -> bool:
    """Return True if key is None, empty, or a dummy string."""
    if not key:
        return True
    return key.strip().lower() in DUMMY_KEYS


def load_env_files(cwd: Optional[str] = None) -> None:
    """Load key-value pairs from .env and .env.local into os.environ if not already set.

    Parses export statements, quoted values, and strips inline comments.
    """
    base_dir = cwd or os.getcwd()
    for d in [base_dir, os.path.join(base_dir, ".aider_factory")]:
        for fname in (".env", ".env.local"):
            efile = os.path.join(d, fname)
            if os.path.isfile(efile):
                try:
                    with open(efile, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            if line.startswith("export "):
                                line = line[7:].strip()
                            if "=" not in line:
                                continue
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip()
                            if v and v[0] in ("'", '"') and len(v) >= 2 and v[-1] == v[0]:
                                v = v[1:-1]
                            elif " #" in v:
                                v = v.split(" #", 1)[0].strip()
                            v = v.strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
                except Exception:
                    pass


PROVIDER_ENV_KEYS = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AIDER_GEMINI_API_KEY", "GOOGLE_GEMINI_API_KEY"),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AIDER_GEMINI_API_KEY", "GOOGLE_GEMINI_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY", "AIDER_ANTHROPIC_API_KEY"),
    "claude": ("ANTHROPIC_API_KEY", "AIDER_ANTHROPIC_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY", "AIDER_OPENROUTER_API_KEY"),
    "groq": ("GROQ_API_KEY", "AIDER_GROQ_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY", "AIDER_DEEPSEEK_API_KEY"),
    "mistral": ("MISTRAL_API_KEY", "AIDER_MISTRAL_API_KEY"),
    "openai": ("OPENAI_API_KEY", "AIDER_OPENAI_API_KEY"),
}

ALL_PROVIDER_KEYS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "AIDER_GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY",
)


def resolve_api_key(
    model: str = "", api_base: Optional[str] = None, explicit_key: Optional[str] = None
) -> Optional[str]:
    """Resolve active API key prioritizing explicit overrides, provider-specific env vars, and filtering dummy keys."""
    load_env_files()

    if api_base:
        if explicit_key and not is_dummy_key(explicit_key):
            return explicit_key
        e_key = os.environ.get("ORACLE_AGENT_API_KEY")
        if e_key and not is_dummy_key(e_key):
            return e_key
        o_key = os.environ.get("OPENAI_API_KEY")
        if o_key and not is_dummy_key(o_key):
            return o_key
        return "sk-dummy"

    if explicit_key and not is_dummy_key(explicit_key):
        return explicit_key

    m_lower = (model or "").lower()
    for provider, env_keys in PROVIDER_ENV_KEYS.items():
        if provider in m_lower:
            for k in env_keys:
                val = os.environ.get(k)
                if val and not is_dummy_key(val):
                    return val

    for k in ALL_PROVIDER_KEYS:
        val = os.environ.get(k)
        if val and not is_dummy_key(val):
            return val

    return None
