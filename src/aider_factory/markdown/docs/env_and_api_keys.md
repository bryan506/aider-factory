# Environment Variables & Multi-Provider API Key Resolution (`env_utils.py`)

`env_utils.py` provides centralized environment loading, provider alias normalization, and intelligent API key resolution across all AI Factory components (`oracle_agent.py`, `validator.py`, `bootstrap.py`, `rag_manager.py`, `apply_agent.py`, and `cli.py`).

---

## 1. Multi-Tier File Loading (`load_env_files`)

The environment loader automatically scans and loads environment files in the following precedence order:
1. `<working_directory>/.env`
2. `<working_directory>/.env.local`
3. `<working_directory>/.aider_factory/.env`
4. `<working_directory>/.aider_factory/.env.local`

### Syntax Parsing Features
* **`export` statement stripping**: Handles standard `export KEY=val` syntax cleanly.
* **Quote un-wrapping**: Strips matching single (`'`) and double (`"`) quotes.
* **Inline comment stripping**: Safely ignores trailing comments (`KEY=value # comment`).
* **Non-destructive injection**: Only populates `os.environ[k]` if the variable is not already set in the active process environment.

---

## 2. Dummy Key Filtering (`is_dummy_key`)

Local inference endpoints (such as `llama-server`, vLLM, LM Studio, Ollama) do not require real API keys, but upstream client libraries (like LiteLLM and OpenAI SDK) throw validation errors if `api_key` is `None` or missing. Conversely, passing `"sk-dummy"` to cloud providers (e.g. Gemini, Anthropic) triggers `401 Unauthorized` errors.

`is_dummy_key(key)` identifies placeholder values:
```python
DUMMY_KEYS = frozenset({"sk-dummy", "dummy", "none", "null", ""})
```

---

## 3. Intelligent Key Resolution (`resolve_api_key`)

The `resolve_api_key(model, api_base, explicit_key)` function resolves the appropriate authentication key following strict routing rules:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   API KEY RESOLUTION FLOW                                       │
│                                                                                                 │
│  [Call: resolve_api_key(model, api_base, explicit_key)]                                        │
│                            │                                                                    │
│                            ├──── Is api_base set? (Local Server / Proxy)                        │
│                            │     ├── 1. Return explicit_key if not dummy                        │
│                            │     ├── 2. Return ORACLE_AGENT_API_KEY if not dummy                │
│                            │     ├── 3. Return OPENAI_API_KEY if not dummy                      │
│                            │     └── 4. Fallback to "sk-dummy"                                  │
│                            │                                                                    │
│                            └──── api_base is None (Direct Cloud Model Routing)                  │
│                                  ├── 1. Return explicit_key if not dummy                        │
│                                  ├── 2. Match model prefix against PROVIDER_ENV_KEYS            │
│                                  │      (e.g. "gemini/" -> GEMINI_API_KEY, GOOGLE_API_KEY)      │
│                                  ├── 3. Scan ALL_PROVIDER_KEYS fallback list                    │
│                                  └── 4. Return None (let client library handle auth)             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Supported Provider Key Aliases
| Provider | Recognized Environment Variables (Checked in Order) |
| :--- | :--- |
| **Gemini / Google** | `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `AIDER_GEMINI_API_KEY`, `GOOGLE_GEMINI_API_KEY` |
| **Anthropic / Claude** | `ANTHROPIC_API_KEY`, `AIDER_ANTHROPIC_API_KEY` |
| **OpenAI** | `OPENAI_API_KEY`, `AIDER_OPENAI_API_KEY` |
| **OpenRouter** | `OPENROUTER_API_KEY`, `AIDER_OPENROUTER_API_KEY` |
| **Groq** | `GROQ_API_KEY`, `AIDER_GROQ_API_KEY` |
| **DeepSeek** | `DEEPSEEK_API_KEY`, `AIDER_DEEPSEEK_API_KEY` |
| **Mistral** | `MISTRAL_API_KEY`, `AIDER_MISTRAL_API_KEY` |

---

## 4. Usage in Code

```python
from aider_factory.python.env_utils import resolve_api_key, load_env_files

# 1. Load active .env files
load_env_files()

# 2. Resolve key for a cloud Gemini call (automatically omits sk-dummy)
api_key = resolve_api_key(model="gemini/gemini-2.5-flash", api_base=None)

# 3. Resolve key for a local inference server
api_key = resolve_api_key(model="openai/qwen3-32b", api_base="http://localhost:8080/v1")
# Returns "sk-dummy" if no real key is exported
```
