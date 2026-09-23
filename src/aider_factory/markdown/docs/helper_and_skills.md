# AI Factory Helper, Terminal Assistant & Skills Framework

## 1. Executive Overview & Foundational Invariants

The `aider-helper` CLI is the primary interactive configuration architect and general terminal assistant for the AI Factory. It operates via two distinct personas: a **Configuration Architect** for deterministic YAML mutation, and a **General AI Terminal Assistant** (`--terminal`) for unrestricted software engineering queries. The **Skills Framework** modularizes agent capabilities by injecting tool-specific instructions into the context window on demand.

### Foundational Invariants
1. **Append-Only KV Cache:** Context (manuals, repository maps, skills) is appended to the session history on the current turn. The system prompt remains static to guarantee 100% prefix cache hits on local inference servers (e.g., `llama-server`, vLLM).
2. **Strict Session Isolation:** Configuration sessions (`.helper_session.json`) and terminal sessions (`.helper_terminal_session.json`) are strictly bifurcated. Context from one persona never bleeds into the other.
3. **Non-Destructive Mutation:** In configuration mode, the helper applies minimal-delta edits to `.env.yml` while preserving inline comments and inactive blocks.
4. **Zero-Clutter Onboarding:** The `bootstrap` command auto-discovers endpoints, provisions default configurations, and generates a tailored `.env_<repo>.yml` without requiring manual file copying.

---

## 2. System Topology & Lifecycle Flowcharts

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                            AIDER-HELPER INVOCATION ROUTING                                  │
│                                                                                             │
│  [Call: aider-helper <command>]                                                             │
│         │                                                                                   │
│         ├─► bootstrap ──► Interactive Interview ──► Generates .env_<repo>.yml               │
│         │                                                                                   │
│         └─► query ──┬──► --terminal (-t) ──► Loads TERMINAL_PERSONA_PROMPT                  │
│                     │                        (Uses .helper_terminal_session.json)           │
│                     │                        (Bypasses YAML config parsing)                 │
│                     │                                                                       │
│                     └──► (Default) ────────► Loads PERSONA_PROMPT                           │
│                                              (Uses .helper_session.json)                    │
│                                              Parses & Updates active .env.yml               │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### Deterministic Workspace Scaffold (`run_bootstrap`)
The `bootstrap` command provisions a workspace completely deterministically. No interview prompts. No LLM calls. It executes in 5 automated steps:

1. **Detect Keys & Router**: Scans environment variables for `LITELLM_API_KEY`, `LITELLM_BASE_URL`, and provider keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`, etc.).
2. **Detect Test Framework**: Scans the filesystem in priority order:
   - `pytest.ini`, `setup.cfg`, or `pyproject.toml` with `[tool.pytest]` $\rightarrow$ Python (`uv run --with pytest pytest`)
   - `DESCRIPTION` $\rightarrow$ R (`Rscript .aider_factory/tests/run_tests.R {file}`)
   - `Cargo.toml` $\rightarrow$ Rust (`cargo test --test {stem}`)
   - `package.json` $\rightarrow$ JavaScript (`npm test {file}`)
   - `go.mod` $\rightarrow$ Go (`go test {file}`)
3. **Query Router for Models**: If `LITELLM_BASE_URL` is reachable, queries `/v1/models` and selects models:
   - **Architect & Editor**: Prefers models with `"27b"` in their name, else the first available model.
   - **Embed**: First model containing `"embed"`. Automatically flips `embed_backend` to `"openai"`.
   - **Reranker**: First model containing `"rerank"`.
   - Bare IDs receive the `openai/` prefix automatically.
4. **Scaffold Configuration & Auto-Discover Files**:
   - Performs regex substitution on `default_configs/env.yml`, normalizing all paths to forward slashes (`/`).
   - Scopes router endpoint substitution strictly to `architect_api_base`, `editor_api`, and `editor_api_fallback`.
   - **Target File Discovery**: Scans the codebase for source files (`.py`, `.r`, `.rs`, `.go`, `.js`, `.ts`), excluding test files and virtual environments, and selects **exactly one real anchor file** for `target_files` (since pipelines process one file per session).
   - **Context File Discovery**: Populates `context_files_job` with `README.md`, `CHANGELOG.md`, and up to 15 markdown files from `docs/`.
5. **Provision & Report**: Creates `.aider_factory/`, writes `.env_<repo>.yml`, provisions bash launchers (on Linux/macOS), and prints a structured summary.

### Append-Only KV Cache Mechanics (`run_query`)
To maximize GPU VRAM efficiency and minimize Time-To-First-Token (TTFT), `aider-helper` utilizes an append-only memory architecture. 
When heavy documents are requested via flags (`--master`, `--expert`, `--repo-map`, `--context`), they are wrapped in XML tags (e.g., `<skills_reference>`, `<factory_service_manual>`) and prepended to the *user's current question turn*, rather than modifying the system prompt.
Because the beginning of the conversation history remains mathematically identical across subsequent queries, the inference server achieves a 100% prefix cache hit.

### Skills Injection Architecture
Skills are prompt programs written in Markdown, located in `.aider_factory/markdown/skills/` (e.g., `oracle.md`, `research.md`). They teach agents how to invoke specific CLI tools (like `/run .aider_factory/bash/oracle`). 
Instead of bloating the global `CONVENTIONS.md`, skills are modular. They are delivered to the Architect agent on a per-phase basis by adding the skill file path to the `files.context_files_job` array in the YAML configuration.

---

## 4. Exhaustive CLI Invocations & Command Matrix

The `aider-helper` CLI exposes two primary subcommands: `bootstrap` and `query`.

### Command Matrix

| Command / Flag | Alias | Description | Persona / Mode |
| :--- | :--- | :--- | :--- |
| `bootstrap` | | Initiates the interactive workspace onboarding interview. | Setup |
| `query <instruction>` | | Executes a query against the active persona. | Config / Terminal |
| `--file <path>` | `-f` | Target a specific configuration YAML file for editing. | Config |
| `--context <paths>` | `-c` | Comma-separated list of extra context files to load. | Both |
| `--ask` | `-a` | Conversational mode; prevents the agent from writing to disk. | Config |
| `--terminal` | `-t` | Switches to the General AI Terminal Assistant persona. | Terminal |
| `--clear` | | Wipes the active session history (respects `-t` flag isolation). | Both |
| `--master` | `-m` | Injects all skill reference documents (`markdown/skills/*.md`). | Both |
| `--expert` | `-e` | Injects the full Factory Service Manual (`factory_service_manual.md`). | Both |
| `--repo-map` | `-r` | Injects the static repository map (`static_repo_map.md`). | Both |

*Note: POSIX short-flag combining is fully supported (e.g., `aider-helper query -mta "Explain the debate KV cache strategy"`).*

---

## 5. Configuration Schema & YAML Knobs

### Environment Variable Overrides
The helper model and endpoint can be overridden dynamically, independently of the main pipeline configuration:

```bash
# For local endpoints (e.g., llama.cpp / LM Studio):
export AIDER_HELPER_MODEL="openai/qwen2.5-coder:latest"
export AIDER_HELPER_API_BASE="http://192.168.100.1:8080/v1"
export OPENAI_API_KEY="sk-dummy"

# For cloud providers:
export AIDER_HELPER_MODEL="anthropic/claude-3-5-sonnet-20241022"
export ANTHROPIC_API_KEY="your-key"
```

### Skills Injection via YAML
To equip an agent with a specific skill during a pipeline run, append the skill document to the phase's context files:

```yaml
phases:
  - name: "Implementation Phase"
    files:
      context_files_job:
        - "src/aider_factory/markdown/skills/oracle.md"
        - "src/aider_factory/markdown/skills/research.md"
```

---

## 6. Operational Edge Cases, Failure Modes & Telemetry

### Failure Modes & Edge Cases

1. **Missing API Keys:** If no valid API key is detected in the environment (and `AIDER_HELPER_API_BASE` is unset), the CLI intercepts the execution, calls `print_key_help_and_exit()`, and outputs instructions for exporting keys to `~/.bashrc`.
2. **Pristine Directory Protection (Ask/Terminal Mode):** In conversational (`--ask`) or terminal assistant (`--terminal`) mode, `run_query` never creates a `.aider_factory/` folder on disk if one does not already exist, keeping uninitialized directories completely clean.
3. **Missing Repository Map:** If `--repo-map` (`-r`) is requested but `.aider_factory/static_repo_map.md` does not exist, the helper emits a warning to `stderr` and gracefully continues the query without the map.
4. **Cache Busting Risks:** Manually editing the `.helper_session.json` file or changing the underlying system prompt will alter the token sequence, breaking the prefix cache on the inference server and forcing a full prompt re-evaluation.
5. **YAML Parsing Failures:** In Configuration Architect mode, the agent is instructed to return ONLY the updated YAML block. If the agent hallucinates conversational text outside the markdown fences, the deterministic parser in `bootstrap.py` attempts to extract the content between ` ```yaml ` and ` ``` `. If extraction fails, the disk write is safely aborted.

### Telemetry & Diagnostics
- **Cost Accounting:** `aider-helper` queries are fully integrated into the global `cost_tracker.py` engine. It streams responses via `litellm` and calculates costs per-token. It prints `Tokens: X sent, Y received. Cost: $Z message, $W session` to `stderr` after every turn, aggregating the total session cost in memory. This means terminal assistance and configuration costs are tracked just like autonomous pipeline costs.
