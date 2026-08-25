# Environment Variables & Multi-Provider API Key Resolution (`env_utils.py`)

## 1. Executive Overview & Foundational Invariants

The `env_utils.py` module serves as the centralized environment loader, provider alias normalizer, and intelligent API key resolver across all AI Factory components (`oracle_agent.py`, `validator.py`, `bootstrap.py`, `rag_manager.py`, `apply_agent.py`, and `cli.py`). Its primary purpose is to decouple authentication logic from downstream agents, ensuring seamless transitions between local inference servers (which require dummy keys) and cloud providers (which require specific cryptographic keys).

### Foundational Invariants
1. **Non-Destructive Injection:** The loader only populates `os.environ[k]` if the variable is not already set in the active process environment, allowing CLI overrides to take precedence over `.env` files.
2. **Dummy Key Safety:** Cloud endpoints strictly reject dummy keys (preventing `401 Unauthorized` crashes), while local endpoints automatically inject `"sk-dummy"` to satisfy upstream SDK validation requirements (e.g., LiteLLM, OpenAI SDK).
3. **Multi-Tier Precedence:** Environment variables are loaded in a strict precedence order, allowing workspace-specific `.env.local` files to override global repository `.env` files.
4. **Deterministic Dummy Filtering:** Any key matching `DUMMY_KEYS` (`sk-dummy`, `dummy`, `none`, `null`, or empty string) is treated as unconfigured for cloud provider resolution.

---

## 2. System Topology & Lifecycle Flowcharts

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   API KEY RESOLUTION FLOW                                       │
│                                                                                                 │
│  [Call: resolve_api_key(model, api_base, explicit_key)]                                         │
│                            │                                                                    │
│                            ├── Is explicit_key valid (non-dummy)? ──► YES ──► Return explicit_key
│                            │                                                                    │
│                            ├──── Is api_base set? (Local Server / Proxy)                        │
│                            │     ├── 1. Return explicit_key if not dummy                        │
│                            │     ├── 2. Return ORACLE_AGENT_API_KEY if not dummy                │
│                            │     ├── 3. Return OPENAI_API_KEY if not dummy                      │
│                            │     └── 4. Fallback to "sk-dummy"                                  │
│                            │                                                                    │
│                            └──── api_base is None / Empty (Direct Cloud Model Routing)          │
│                                  ├── 1. Match model prefix in PROVIDER_ENV_KEYS                 │
│                                  │      (e.g., "gemini" -> GEMINI_API_KEY, GOOGLE_API_KEY)     │
│                                  ├── 2. Scan ALL_PROVIDER_KEYS fallback list                    │
│                                  └── 3. Return None (let client SDK raise/handle auth)          │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### Dummy Key Filtering (`is_dummy_key`)
`is_dummy_key(key: Optional[str]) -> bool` returns `True` if a key is `None`, empty, or matches the set of placeholders:
```python
DUMMY_KEYS = frozenset({"sk-dummy", "dummy", "none", "null", ""})
```

### Multi-Tier File Loading (`load_env_files`)
`load_env_files(cwd: Optional[str] = None)` automatically scans and loads environment files in two directories (`cwd` or `os.getcwd()`, and `<base_dir>/.aider_factory`):
1. `<base_dir>/.env`
2. `<base_dir>/.env.local`
3. `<base_dir>/.aider_factory/.env`
4. `<base_dir>/.aider_factory/.env.local`

**Syntax Parsing Mechanics:**
* **`export` statement stripping:** Strips `export ` prefixes (`export KEY=val` -> `KEY=val`).
* **Quote un-wrapping:** Strips matching surrounding single (`'`) and double (`"`) quotes.
* **Inline comment stripping:** Truncates on `" #"` and strips whitespace.
* **Non-destructive assignment:** Only assigns `os.environ[k] = v` if `k` is not already present in `os.environ`.

### Intelligent Key Resolution (`resolve_api_key`)
`resolve_api_key(model: str = "", api_base: Optional[str] = None, explicit_key: Optional[str] = None) -> Optional[str]`
1. Triggers `load_env_files()`.
2. **Local Endpoint Branch (`api_base` is present):**
   - Checks `explicit_key` -> `os.environ["ORACLE_AGENT_API_KEY"]` -> `os.environ["OPENAI_API_KEY"]`.
   - If none are set or non-dummy, defaults to `"sk-dummy"`.
3. **Cloud Endpoint Branch (`api_base` is `None` or empty):**
   - Returns `explicit_key` if non-dummy.
   - Converts `model` to lowercase and checks provider matches in `PROVIDER_ENV_KEYS`.
   - If no provider match succeeds, iterates over `ALL_PROVIDER_KEYS`.
   - Returns `None` if no valid key is present.

---

## 4. Exhaustive CLI & Parameter Reference

While `env_utils.py` is an internal utility module, its mapping configuration dictates how API keys are resolved for all AI Factory components (`aider-oracle`, `aider-validate`, `aider-factory`, `aider-helper`).

### Provider Key Mapping Matrix (`PROVIDER_ENV_KEYS`)
| Provider Key Alias | Checked Environment Variables (in Order) |
| :--- | :--- |
| `gemini` / `google` | `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `AIDER_GEMINI_API_KEY`, `GOOGLE_GEMINI_API_KEY` |
| `anthropic` / `claude` | `ANTHROPIC_API_KEY`, `AIDER_ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY`, `AIDER_OPENAI_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY`, `AIDER_OPENROUTER_API_KEY` |
| `groq` | `GROQ_API_KEY`, `AIDER_GROQ_API_KEY` |
| `deepseek` | `DEEPSEEK_API_KEY`, `AIDER_DEEPSEEK_API_KEY` |
| `mistral` | `MISTRAL_API_KEY`, `AIDER_MISTRAL_API_KEY` |

### Fallback Keys Order (`ALL_PROVIDER_KEYS`)
If a model string does not match any provider key in `PROVIDER_ENV_KEYS`, `resolve_api_key` scans:
1. `GEMINI_API_KEY`
2. `GOOGLE_API_KEY`
3. `AIDER_GEMINI_API_KEY`
4. `ANTHROPIC_API_KEY`
5. `OPENAI_API_KEY`
6. `OPENROUTER_API_KEY`
7. `GROQ_API_KEY`
8. `DEEPSEEK_API_KEY`
9. `MISTRAL_API_KEY`

---

## 5. Configuration Schema & YAML Knobs

The YAML pipeline configuration (`.env.yml`) supplies `model` strings and `endpoints` URLs which are passed directly to `resolve_api_key`.

```yaml
endpoints:
  # Local inference endpoint: resolve_api_key defaults to "sk-dummy" if no explicit key is set
  architect_api_base: "http://192.168.100.2:8080/v1"
  # Cloud endpoint: set to empty string or omit so resolve_api_key routes to GEMINI_API_KEY
  editor_api: ""

models:
  # Routes to local endpoint via architect_api_base
  architect_agent: "openai/qwen3.5-122b-a10b-90k:latest"
  # Direct cloud model: matches "gemini" in PROVIDER_ENV_KEYS
  editor_agent: "gemini/gemini-2.5-flash"
```

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### Failure Modes & Edge Cases
1. **Silent File Reading Exceptions:** `load_env_files` wraps `.env` parsing in `try/except Exception: pass`. If an environment file is unreadable or malformed, execution continues without throwing errors.
2. **Cloud Authentication Rejection:** If a cloud model (e.g. `gemini/gemini-2.5-flash`) is invoked without setting a valid API key, `resolve_api_key` returns `None`. Downstream client libraries (e.g., `litellm`) will raise an explicit authentication error (`401 Unauthorized` / `APIKeyMissingError`).
3. **Protected Local Endpoints:** If a local server requires a real Bearer token (e.g., a secured LiteLLM proxy), pass the real token via `OPENAI_API_KEY` or `ORACLE_AGENT_API_KEY`. Because `resolve_api_key` checks these variables before falling back to `"sk-dummy"`, valid keys are preserved.
