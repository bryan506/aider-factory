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

### Interactive Workspace Onboarding (`run_bootstrap`)
The `bootstrap` command initiates a terminal-based interview to capture user intent. It performs the following sequence:
1. **API Key Detection:** Scans the environment for valid provider keys (e.g., `GEMINI_API_KEY`, `OPENAI_API_KEY`) to determine the default provider.
2. **Cluster Auto-Discovery:** Queries the `LITELLM_BASE_URL` (if set) to auto-discover available models, prepending the `openai/` prefix for Aider routing.
3. **Parameter Collection:** Prompts the user for target files, context files, test frameworks, operating mode (autonomous vs. pair programming), model selection, and RAG/Oracle configuration.
4. **Deterministic Synthesis:** Reads the master `default_configs/env.yml` template, applies string replacements based on user input, and writes the final `.env_<repo>.yml` to `.aider_factory/`.

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
2. **Missing Repository Map:** If `--repo-map` (`-r`) is requested but `.aider_factory/static_repo_map.md` does not exist, the helper emits a warning to `stderr` (`Warning: --repo-map requested, but... not found`) and gracefully continues the query without the map.
3. **Cache Busting Risks:** Manually editing the `.helper_session.json` file or changing the underlying system prompt will alter the token sequence, breaking the prefix cache on the inference server and forcing a full prompt re-evaluation.
4. **YAML Parsing Failures:** In Configuration Architect mode, the agent is instructed to return ONLY the updated YAML block. If the agent hallucinates conversational text outside the markdown fences, the deterministic parser in `bootstrap.py` attempts to extract the content between ` ```yaml ` and ` ``` `. If extraction fails, the disk write is safely aborted.

### Telemetry & Diagnostics
- **Cost Accounting:** `aider-helper` queries are fully integrated into the global `cost_tracker.py` engine. It streams responses via `litellm` and calculates costs per-token. It prints `Tokens: X sent, Y received. Cost: $Z message, $W session` to `stderr` after every turn, aggregating the total session cost in memory. This means terminal assistance and configuration costs are tracked just like autonomous pipeline costs.
