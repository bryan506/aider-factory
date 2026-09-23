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
2. **Local / Proxy Endpoint Branch (`api_base` is present):**
   - Checks `explicit_key` -> `os.environ["ORACLE_AGENT_API_KEY"]` -> `os.environ["OPENAI_API_KEY"]`.
   - If a valid key is found (not in `DUMMY_KEYS`), returns it.
   - Otherwise defaults to `"sk-dummy"`.
3. **Cloud Endpoint Branch (`api_base` is `None` or empty):**
   - Returns `explicit_key` if non-dummy.
   - Converts `model` to lowercase and checks provider matches in `PROVIDER_ENV_KEYS`.
   - If no provider match succeeds, iterates over `ALL_PROVIDER_KEYS`.
   - Returns `None` if no valid key is present.

### Subprocess Router Key Resolution (`_router_key`)
In `orchestrate.py` and `run_workflow.py`, subprocess environment variables for local/proxy endpoints are resolved dynamically to ensure authenticated LiteLLM proxies receive valid tokens:

```python
_router_key = os.environ.get("LITELLM_API_KEY", "")
_router_key = _router_key if _router_key and not is_dummy_key(_router_key) else "sk-dummy"

if task.architect_api_base:
    env["OPENAI_API_BASE"] = task.architect_api_base
    env["OPENAI_API_KEY"] = _router_key
if task.editor_api_base:
    env["OLLAMA_API_BASE"] = task.editor_api_base
    env["LM_STUDIO_API_BASE"] = task.editor_api_base
    env["LM_STUDIO_API_KEY"] = _router_key
```

### Non-Clobbering Router Fallback (`oracle_agent.py`)
In `_ensure_oracle_config()`, `LITELLM_BASE_URL` is applied as a fallback only after parsing YAML settings. Furthermore, if `ORACLE_AGENT_MODEL` routes to a known cloud provider (`gemini/`, `anthropic/`, `groq/`), `ORACLE_AGENT_API_BASE` is preserved as `None` to prevent accidental proxy misdirection.

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

---

## 7. Appendix: Auto-Injected Oracle Variables

When `run_workflow.py` executes a phase, it dynamically compiles the YAML configuration into a strict set of environment variables. These are injected into the subprocess environment for `bash/oracle` and `bash/validate`. 

While you should **never export these manually**, they are critical for debugging validation bash scripts:

**Routing & Model:**
* `ORACLE_ARCHITECT_MODEL`: Routes the CLI debate's Architect turn.
* `ORACLE_ARCHITECT_API_BASE`: Endpoint for the Architect in a CLI debate.
* `ORACLE_AGENT_MODEL`: The Oracle RAG model (e.g., `openai/qwen3.6-27b-90k:latest`).
* `ORACLE_AGENT_API_BASE`: Endpoint for the Oracle model.
* `ORACLE_AGENT_API_KEY`: Injected as `sk-dummy` for local servers.

**Retrieval Targets:**
* `ORACLE_RAG_DB_DIR`: Absolute path to `.../lanceDB/<collection>/lancedb`.
* `ORACLE_COLLECTION`: LanceDB table to query (`*` for batch fusion, or doc stem).
* `ORACLE_TOP_K`: Number of chunks for `top_k` retrieval.
* `ORACLE_RECALL_K`: Stage 1 candidate pool depth before reranking.
* `ORACLE_RETRIEVE_MODE`: `top_k` | `no_retrieve` | `full_document`.

**Validation System (Injected during heal/apply nodes):**
* `ORACLE_REVIEW_FILE`: The generated document being validated.
* `ORACLE_SOURCE_FILE`: The OCR `<stem>.md` ground-truth source.
* `ORACLE_VALIDATION_FILE`: The failures/context report to write/read (the gate).
* `ORACLE_LEDGER_FILE`: Per-doc JSON ledger tracking the no-progress guard state.
* `ORACLE_BASELINE_LEDGER`: Debate ledger holding `quote_baseline` for the deletion guard.
* `ORACLE_VALIDATION_TAG`: Quote tag to audit (default: `evidence`).
* `VALIDATION_ATTEMPT`: Outer-loop index; resets the per-run ledger on attempt 0.
* `GROUNDING_AGENT_MODEL`: The MiniCheck entailment model (e.g., `openai/minicheck-flan-t5-large`).
* `GROUNDING_VERIFY_ALL`: If `1`, scores all claims; if `0`, scores only failing quotes.
* `GROUNDING_ENTAIL_THRESHOLD`: Probability cutoff for the entailment verifier.

**Proxy Routing & KV-Cache Stickiness:**
* `LITELLM_API_KEY`: Authentication Bearer token sent to the LiteLLM Router. Automatically mapped into `OPENAI_API_KEY`, `LM_STUDIO_API_KEY`, `ORACLE_AGENT_API_KEY`, and `GROUNDING_AGENT_API_KEY` for subprocesses.
* `LITELLM_BASE_URL`: Root URL of the LiteLLM proxy (e.g., `http://10.0.0.5:4000/v1`). Used by `probe_router()` during bootstrap and as a fallback endpoint.
* `LITELLM_SESSION_ID`: A unique UUID (`uuid.uuid4()`) generated and injected automatically by the pipeline. It is passed via `custom_headers: {"x-litellm-session-id": ...}` to ensure KV-cache stickiness across pipeline runs when routing through remote LiteLLM proxies.
