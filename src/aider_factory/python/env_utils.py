#!/usr/bin/env python3
# env_utils.py — Shared environment, model routing, and endpoint utilities.

import os
import re
import subprocess
import sys
import tempfile
from typing import Optional

import yaml

def kill_proc_tree(p) -> None:
    """Terminate a process and all spawned descendants across POSIX and Windows."""
    if not p:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            import signal
            try:
                pgrp = os.getpgid(p.pid)
                if pgrp > 1 and pgrp != os.getpgrp():
                    os.killpg(pgrp, signal.SIGKILL)
                else:
                    p.kill()
            except (ProcessLookupError, OSError):
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except Exception:
                    p.kill()
            except Exception:
                p.kill()
    except Exception:
        try:
            p.kill()
        except OSError:
            pass
    try:
        p.wait(timeout=5)
    except Exception:
        pass

    for stream_name in ("stdin", "stdout", "stderr"):
        s = getattr(p, stream_name, None)
        if s:
            try:
                s.close()
            except Exception:
                pass


DUMMY_KEYS = frozenset({"sk-dummy", "dummy", "none", "null", ""})

TEST_DIR_NAMES = {
    "test",
    "tests",
    "testing",
    "testthat",
    "__tests__",
    "spec",
    "specs",
    "e2e",
    "end-to-end",
    "fixtures",
    "testdata",
    "test_fixtures",
    "benchmarks",
    "benches",
}

TEST_DELIMITED_RE = re.compile(
    r"(^|/)((tests?|specs?|unit_?tests?)[_\-\.][^/]+|.+[_\-\.](tests?|specs?|unit_?tests?)\.[^/]+)$",
    re.IGNORECASE,
)

TEST_CAMEL_RE = re.compile(
    r"(^|/)[a-zA-Z0-9_]*(Test|Tests|TestCase|Spec)\.[a-zA-Z0-9]+$"
)

EXACT_TEST_HARNESS_FILES = {
    "conftest.py",
    "tests.py",
    "tests.rs",
    "test_helper.rb",
}


DOC_EXTS = {".md", ".markdown", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml"}

def is_test_path(rel_path: str) -> bool:
    """Classify repository paths to ensure structural isolation between source code and test files."""
    clean = (rel_path or "").replace("\\", "/").strip().lstrip("./")
    if not clean:
        return False
    if os.path.isabs(clean):
        try:
            clean = os.path.relpath(clean, os.getcwd()).replace("\\", "/")
        except ValueError:
            pass
    parts = clean.split("/")
    if any(p.lower() in TEST_DIR_NAMES for p in parts[:-1]):
        return True
    filename = parts[-1]
    _, ext = os.path.splitext(filename)
    if ext.lower() in DOC_EXTS:
        return False
    if filename.lower() in EXACT_TEST_HARNESS_FILES or filename.startswith("setupTests."):
        return True
    if TEST_DELIMITED_RE.search(clean) or TEST_CAMEL_RE.search(clean):
        return True
    return False


def is_dummy_key(key: Optional[str]) -> bool:
    """Return True if key is None, empty, or a dummy string."""
    if not key:
        return True
    cleaned = key.strip().lower()
    return cleaned in DUMMY_KEYS or cleaned.startswith("sk-dummy")


def is_valid_endpoint(url: Optional[str]) -> bool:
    """Return True if url is a non-empty, non-dummy HTTP/HTTPS URL and not a template placeholder."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if is_dummy_key(u):
        return False
    if "<" in u or ">" in u or "your-router-host" in u:
        return False
    return u.startswith(("http://", "https://"))


def is_local_model(model_name: Optional[str]) -> bool:
    """Return True if model_name represents a local or custom endpoint model."""
    if not model_name or not isinstance(model_name, str):
        return True
    m = model_name.strip().lower()
    cloud_prefixes = (
        "gemini/",
        "google/",
        "anthropic/",
        "claude/",
        "openrouter/",
        "groq/",
        "deepseek/",
        "mistral/",
        "cohere/",
        "bedrock/",
        "vertex_ai/",
        "azure/",
    )
    if any(m.startswith(p) for p in cloud_prefixes):
        return False

    # Bare cloud model prefixes without provider prefix
    bare_cloud = (
        "claude-",
        "command-",
        "deepseek-",
        "mistral-",
    )
    if any(m.startswith(p) for p in bare_cloud):
        return False

    # OpenAI cloud models (with or without 'openai/' prefix)
    bare = m[7:] if m.startswith("openai/") else m
    openai_cloud_prefixes = (
        "gpt-",
        "o1",
        "o3",
        "chatgpt",
        "text-embedding",
        "dall-e",
        "tts-",
        "whisper-",
        "babbage",
        "davinci",
    )
    if any(bare.startswith(p) for p in openai_cloud_prefixes):
        return False

    return True


def get_model_settings(model_name: str, cwd: Optional[str] = None) -> dict:
    """Read .aider.model.settings.yml and return configuration dict for model_name."""
    if not model_name or not isinstance(model_name, str):
        return {}
    base_dir = cwd or os.getcwd()
    candidates = []
    env_settings = os.environ.get("AIDER_MODEL_SETTINGS_FILE")
    if env_settings:
        candidates.append(env_settings if os.path.isabs(env_settings) else os.path.join(base_dir, env_settings))
    session_id = os.environ.get("AI_FACTORY_SESSION")
    if session_id:
        candidates.append(os.path.join(base_dir, ".aider_factory", "sessions", session_id, ".aider.model.settings.yml"))
    candidates.append(os.path.join(base_dir, ".aider_factory", ".aider.model.settings.yml"))
    candidates.append(os.path.join(base_dir, ".aider.model.settings.yml"))

    settings_file = next((c for c in candidates if os.path.isfile(c)), None)
    if not settings_file:
        return {}

    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            entries = yaml.safe_load(f)
        if not isinstance(entries, list):
            return {}

        raw = model_name.strip().lower()
        bare = raw.split("/")[-1]
        target_names = {raw, bare, raw.split(":")[0], bare.split(":")[0]}
        if raw.startswith("openai/"):
            target_names.add(raw[7:])
            target_names.add(raw[7:].split(":")[0])
        else:
            target_names.add(f"openai/{raw}")
            target_names.add(f"openai/{raw.split(':')[0]}")

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            e_name = str(entry.get("name", "")).strip().lower()
            e_bare = e_name.split("/")[-1]
            e_variants = {e_name, e_bare, e_name.split(":")[0], e_bare.split(":")[0]}
            if target_names.intersection(e_variants):
                return dict(entry)
    except Exception:
        pass
    return {}


def ensure_model_settings(
    target_path: str,
    models_to_configure: list[dict],
    base_settings_path: Optional[str] = None,
) -> str:
    """Non-destructively upsert model endpoint definitions into an Aider model settings YAML file."""
    settings_dict = {}
    if base_settings_path and os.path.exists(base_settings_path):
        try:
            with open(base_settings_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and "name" in item:
                            settings_dict[item["name"]] = dict(item)
        except Exception:
            pass

    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and "name" in item:
                            settings_dict[item["name"]] = dict(item)
        except Exception:
            pass

    settings_list = list(settings_dict.values())
    for cfg in models_to_configure:
        name = cfg.get("name")
        api_base = cfg.get("api_base")
        api_key = cfg.get("api_key") or "sk-dummy"
        if not name or not is_valid_endpoint(api_base):
            continue

        names = [name]
        if "/" not in name:
            names.append(f"openai/{name}")
        elif name.startswith("openai/"):
            names.append(name[7:])
        elif "/" in name:
            bare = name.split("/", 1)[1]
            names.append(bare)
            names.append(f"openai/{bare}")
            leaf = name.split("/")[-1]
            if leaf not in names:
                names.append(leaf)

        for n in dict.fromkeys(names):
            existing = next((entry for entry in settings_list if entry.get("name") == n), None)
            if existing is not None:
                extra = existing.get("extra_params")
                if not isinstance(extra, dict):
                    extra = {}
                    existing["extra_params"] = extra
                extra["api_base"] = api_base
                extra["api_key"] = api_key
            else:
                settings_list.append({
                    "name": n,
                    "extra_params": {
                        "api_base": api_base,
                        "api_key": api_key,
                    },
                })

    target_dir = os.path.dirname(os.path.abspath(target_path))
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    os.close(fd)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(settings_list, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
    return target_path


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


def probe_router(base_url: str, api_key: Optional[str] = None, timeout: int = 2) -> Optional[list]:
    """Query LiteLLM Router GET /v1/models. Returns sorted list of model ID strings or None on failure.

    Prepends 'openai/' to any bare model ID. Never raises.
    """
    if not is_valid_endpoint(base_url):
        return None
    import requests

    try:
        headers = {}
        if api_key and not is_dummy_key(api_key):
            headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.get(
            f"{base_url.rstrip('/')}/models", headers=headers, timeout=timeout
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", [])
        return sorted(
            m["id"] if "/" in m["id"] else f"openai/{m['id']}"
            for m in data
            if isinstance(m, dict) and "id" in m
        )
    except Exception:
        return None


def resolve_api_key(
    model: str = "", api_base: Optional[str] = None, explicit_key: Optional[str] = None
) -> Optional[str]:
    """Resolve active API key prioritizing explicit overrides, provider-specific env vars, and filtering dummy keys."""
    if api_base:
        if explicit_key and not is_dummy_key(explicit_key):
            return explicit_key
        for env_var in ("LITELLM_API_KEY", "ORACLE_AGENT_API_KEY", "OPENAI_API_KEY"):
            val = os.environ.get(env_var)
            if val and not is_dummy_key(val):
                return val
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
