# AI Factory Helper, Terminal Assistant & Skills Framework

## 1. Executive Overview & Foundational Invariants

The `aider-helper` subsystem is the dual-mode configuration architect, interactive software engineering assistant, and skills orchestration engine of the AI Factory. Implemented primarily in `src/aider_factory/python/bootstrap.py` and exposed via the `aider-helper` CLI entrypoint in `src/aider_factory/cli.py`, it bridges raw developer requirements and automated pipeline execution.

The subsystem operates across two fundamentally bifurcated execution personas:
1. **Configuration Architect (`PERSONA_PROMPT`)**: An automated or conversational system optimization agent designed to inspect, validate, mutate, and repair multi-phase pipeline configuration files (`.env.yml`, `.env_<repo>.yml`) without corrupting inactive YAML blocks or inline comments.
2. **General Terminal Assistant (`TERMINAL_PERSONA_PROMPT` via `--terminal` / `-t`)**: An unconstrained, interactive software engineering assistant for general-purpose code explanations, shell scripting, algorithm design, and system diagnostics.

In parallel, the **Skills Framework** modularizes agent capabilities. Instead of bloating core system prompts or global conventions (`CONVENTIONS.md`), specialized tool-use instructions (such as Knowledge Oracle retrieval, SearXNG academic research, claim grounding, and headless git patch application) are encapsulated as self-contained Markdown skill programs under `src/aider_factory/markdown/skills/`. These skills are dynamically injected into the context window on demand.

### Foundational Invariants

1. **Deterministic-First Scaffolding**: Workspace initialization (`aider-helper bootstrap`) executes 100% deterministically. It executes zero LLM calls, presents zero interactive blocking prompts, and derives framework runners, model routes, and target anchors directly from filesystem markers and router endpoints.
2. **Strict Session Bifurcation**: Configuration sessions (`.helper_session.json`) and terminal assistant sessions (`.helper_terminal_session.json`) reside in distinct, non-overlapping state files under `.aider_factory/`. State, history, and system prompts from one persona never bleed into the other.
3. **Immutable Prefix & Append-Only KV Cache Invariance**: To maximize KV-cache reuse on local inference engines (vLLM, `llama-server`) and cloud providers, system prompts are strictly immutable. Reference schemas, manuals, skills, and extra context files are appended to the *user turn payload* rather than modifying system instructions. Once injected, deduplication guards prevent re-injection across subsequent turns.
4. **Pristine Working Directory Protection**: In read-only conversational mode (`--ask` / `-a`) and terminal assistant mode (`--terminal` / `-t`), `aider-helper` will never create `.aider_factory/` directories or metadata sidecars on disk if the directory does not already exist.
5. **Non-Destructive Schema Mutation**: When mutating configuration files in default mode, `aider-helper` extracts the fenced `yaml` block from the LLM response and applies minimal-delta rewrites to the target `.env.yml`, guaranteeing that external comments, phase structures, and disabled blocks remain intact.

---

## 2. System Topology & Lifecycle Flowcharts

### Subsystem Architecture & CLI Dispatch

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   AIDER-HELPER CLI DISPATCH                                 │
│                                                                                             │
│  User / Subshell Invocation:                                                                │
│  [ aider-helper <subcommand> [flags] [args] ]                                               │
│         │                                                                                   │
│         ├──► bootstrap [target_dir]                                                         │
│         │         │                                                                         │
│         │         ├──► detect_api_key() & probe_router(LITELLM_BASE_URL)                    │
│         │         ├──► _detect_framework(cwd) ──► Infer Runner & Paths                      │
│         │         ├──► _select_models() ────────► Filter 27B / Weak / Embed / Rerank        │
│         │         ├──► _discover_target_files() ─► Select Exactly 1 Anchor File             │
│         │         ├──► _discover_context_files() ► Scan README / CHANGELOG / docs           │
│         │         ├──► Regex Templating ────────► Write .aider_factory/.env_<repo>.yml      │
│         │         └──► init_user_project(cwd) ──► Scaffold Dirs & Copy Launchers            │
│         │                                                                                   │
│         └──► query "<instruction>" [options]                                                │
│                   │                                                                         │
│                   ├──► Mode Determination:                                                  │
│                   │         ├──► [-t | --terminal] ──► TERMINAL_PERSONA_PROMPT              │
│                   │         │                          Session: .helper_terminal_session.json│
│                   │         └──► [Default] ──────────► PERSONA_PROMPT                       │
│                   │                                    Session: .helper_session.json        │
│                   │                                    Target File: .env.yml                │
│                   │                                                                         │
│                   ├──► Context Expansion Engine (Turn Prefix Injection):                    │
│                   │         ├──► [-m | --master] ──► <skills_reference> + <yaml_docs>       │
│                   │         ├──► [-e | --expert] ──► <factory_service_manual>               │
│                   │         ├──► [-r | --repo-map] ─► <repository_map> (static_repo_map.md)│
│                   │         ├──► [-c | --context] ─► <extra_context_files> (Dynamic Fences) │
│                   │         └──► [Config Mode] ────► <reference_schema> + <active_config>   │
│                   │                                                                         │
│                   ├──► LiteLLM Streaming Engine:                                            │
│                   │         ├──► Header: x-litellm-session-id: _PIPELINE_SESSION_ID        │
│                   │         ├──► Rich Live Terminal Render (Markdown stream)                │
│                   │         └──► cost_tracker.py Accounting Telemetry Output               │
│                   │                                                                         │
│                   └──► Disk Persistence Gate:                                               │
│                             ├──► IF terminal_mode OR ask_mode: DO NOT WRITE DISK           │
│                             └──► IF config_mode AND NOT ask_mode:                           │
│                                       Extract ```yaml ... ``` ──► Overwrite Target YAML     │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Context Assembly & Turn Lifecycle

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                             RUN_QUERY TURN ASSEMBLY LIFECYCLE                               │
│                                                                                             │
│  Incoming User Query: "Configure Phase 2 for Rust cargo test"                                │
│                                                                                             │
│  Step 1: Check Session Cache (.helper_session.json)                                         │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Messages History = [ { "role": "system", "content": PERSONA_PROMPT }, ... ]           │  │
│  └───────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                             │
│  Step 2: Inspect Turn History for Prior Injections                                          │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Has <reference_schema> been injected?        ──► Yes: Skip. No: Append.               │  │
│  │ Has <skills_reference> been injected?        ──► Yes: Skip. No: Append.               │  │
│  │ Has <factory_service_manual> been injected?  ──► Yes: Skip. No: Append.               │  │
│  │ Has <repository_map> been injected?          ──► Yes: Skip. No: Append.               │  │
│  │ Has <active_configuration> been injected?    ──► Yes: Skip. No: Append.               │  │
│  └───────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                             │
│  Step 3: Process Ad-Hoc Extra Context (-c file1.py,docs/*.md)                                │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ For each path/glob: Expand vars ──► Deduplicate ──► Read utf-8-sig                     │  │
│  │ Compute backtick max length N ──► Dynamic fence = '`' * max(3, N + 1)                 │  │
│  │ Wrap in <extra_context_files>                                                         │  │
│  └───────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                             │
│  Step 4: Formulate Final User Payload                                                        │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ user_msg = [Persistent Additions] + "<question>\n" + instruction + "\n</question>"    │  │
│  │ messages.append({ "role": "user", "content": user_msg })                              │  │
│  └───────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                             │
│  Step 5: Dispatch to LiteLLM with KV-Cache Stickiness Header                                │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ litellm.completion(model, messages, stream=True,                                      │  │
│  │                    custom_headers={"x-litellm-session-id": _PIPELINE_SESSION_ID})      │  │
│  └───────────────────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Skills Framework Integration

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                SKILLS FRAMEWORK ARCHITECTURE                                │
│                                                                                             │
│  Source Skill Program: src/aider_factory/markdown/skills/oracle.md                          │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ # Skill: Knowledge Oracle Retrieval                                                    │  │
│  │ - Role: Side-agent RAG consultant                                                     │  │
│  │ - Invocation: /run .aider_factory/bash/oracle "<query>"                               │  │
│  │ - Invariant: Never hallucinate formulas; cite source blocks verbatim                   │  │
│  └───────────────────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                                   │
│         ├──► Autonomous Pipeline Path (run_workflow.py & orchestrate.py)                    │
│         │         │                                                                         │
│         │         ├──► Declared in YAML: phases[i].files.context_files_job                   │
│         │         ├──► Passed to Aider as immutable read-only context (--read)              │
│         │         └──► Architect uses /run command during autonomous turn                   │
│         │                                                                                   │
│         └──► Interactive Helper Path (bootstrap.py)                                         │
│                   │                                                                         │
│                   ├──► Activated via CLI: aider-helper query -m "<instruction>"              │
│                   ├──► Ingests markdown/skills/*.md into <skills_reference> block           │
│                   └──► Helper guides user on configuring tools and executing skills         │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### Mathematical Formulations

#### 1. Context Window Budgeting & Compaction Threshold
To preserve multi-hop reasoning performance and prevent attention degradation in long-context tasks, active context utilization $U_{\text{context}}$ is strictly constrained:

$$U_{\text{context}} = \frac{T_{\text{active}}}{C_{\text{window}}} \le 0.70$$

where $C_{\text{window}}$ is the maximum context length of the active model, and $T_{\text{active}}$ is decomposed as:

$$T_{\text{active}} = T_{\text{prefix}} + T_{\text{context}} + T_{\text{history}} + T_{\text{headroom}}$$

- **Prefix Overhead ($T_{\text{prefix}}$)**: Static system prompt ($5\%\text{--}10\%$).
- **Context Overhead ($T_{\text{context}}$)**: Injected reference schemas, manuals, skills, and codebases:
  $$T_{\text{context}} = T_{\text{schema}} + T_{\text{skills}} + T_{\text{manual}} + T_{\text{repomap}} + \sum_{i=1}^{K} T_{\text{file}_i}$$
- **History Overhead ($T_{\text{history}}$)**: Cumulative turns stored in `.helper_session.json` or `.helper_terminal_session.json`.
- **Generation Buffer ($T_{\text{headroom}}$)**: Reserved headroom for streaming generation ($15\%\text{--}20\%$).

When $U_{\text{context}} > 0.70$, session compaction (`--clear`) is recommended to prevent attention saturation.

#### 2. Prefix Caching Probability & KV-Cache Hit Ratio
Given a prompt serialized into token sequence $S = \langle t_1, t_2, \dots, t_N \rangle$, the KV-cache hit ratio $R_{\text{hit}}$ on an inference server supporting prefix caching is a function of the shared prefix length $k$:

$$R_{\text{hit}}(S, S') = \frac{\max \{ k \mid \forall i \le k, t_i = t_i' \}}{|S|}$$

Because `aider-helper` guarantees that the system prompt $t_1 \dots t_P$ is byte-identical and that reference contexts are deduplicated across turns:

$$S_t = S_{\text{prefix}} \mathbin{\Vert} H_{t-1} \mathbin{\Vert} \Delta_t \implies R_{\text{hit}} \approx \frac{|S_{\text{prefix}} \mathbin{\Vert} H_{t-1}|}{|S_t|}$$

yielding near-instantaneous Time-To-First-Token (TTFT) on subsequent conversational turns.

#### 3. Dynamic Code Fence Length
When arbitrary source files are loaded via `--context` / `-c`, they may contain nested markdown fences (e.g., ``` ``` ``` or ``` ``` ```). To guarantee parsing determinism without syntax truncation, the enclosing fence length $L_{\text{fence}}$ is computed dynamically:

$$L_{\text{fence}} = \max \left( 3, \, 1 + \max_{m \in M_{\text{backticks}}} |m| \right)$$

$$\text{Fence} = \underbrace{\text{"`"} \times L_{\text{fence}}}_{L_{\text{fence}} \text{ backticks}}$$

where $M_{\text{backticks}}$ is the set of all contiguous backtick matches in the target file content.

#### 4. Model Selection Scoring Function
During `run_bootstrap`, when a LiteLLM router is queried at `/v1/models`, model assignment is governed by deterministic priority functions:

$$\text{Score}_{\text{arch}}(m) = \mathbb{I}(\text{"27b"} \in m) \cdot 1000 + (100 - \text{index}(m))$$

$$\text{Score}_{\text{weak}}(m) = \mathbb{I}\left(\exists s \in \{\text{"1.5b"}, \text{"7b"}, \text{"8b"}, \text{"mini"}, \text{"flash"}, \text{"lite"}\} : s \in m\right) \cdot 1000 + (100 - \text{index}(m))$$

$$M_{\text{arch}} = \arg\max_{m \in \mathcal{M}} \text{Score}_{\text{arch}}(m), \quad M_{\text{weak}} = \arg\max_{m \in \mathcal{M}} \text{Score}_{\text{weak}}(m)$$

#### 5. Cost Tracking & Accounting
Cumulative token and financial cost accounting is handled via `cost_tracker.py`:

$$\text{Cost}_{\text{msg}} = \frac{T_{\text{sent}} \cdot R_{\text{prompt}} + T_{\text{recv}} \cdot R_{\text{completion}}}{10^6}$$

$$\text{Cost}_{\text{session}} = \text{Cost}_{\text{session}}^{\text{prior}} + \text{Cost}_{\text{msg}}$$

---

### Deep-Dive: Deterministic Workspace Scaffold (`run_bootstrap`)

The `run_bootstrap(target_dir)` routine in `src/aider_factory/python/bootstrap.py` automates workspace provisioning without human intervention. It follows five sequential stages:

#### Stage 1: API Key & Router Discovery
1. Calls `detect_api_key()` to scan for active keys in priority order:
   - Local Custom: `AIDER_HELPER_API_BASE` (bypasses auth checks with `dummy`).
   - Cloud / Router Keys: `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `AIDER_GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `OPENCODE_API_KEY`, `LITELLM_API_KEY`.
2. Inspects router environment variables:
   - `router_base = os.environ.get("LITELLM_BASE_URL") or os.environ.get("AIDER_HELPER_API_BASE")`
   - `router_key = os.environ.get("LITELLM_API_KEY")`

#### Stage 2: Test Framework Auto-Detection
Scans the current working directory (`cwd`) against filesystem markers in strict priority order:

| Framework | Filesystem Markers | Inferred Test Runner (`test_runner`) | Test Naming Convention (`test_naming_and_path`) | Prefix |
| :--- | :--- | :--- | :--- | :--- |
| **Python (`py`)** | `pytest.ini`, `setup.cfg` (with `[tool:pytest]`), or `pyproject.toml` (with `[tool.pytest]`) | `uv run --with pytest pytest` | `tests/test_{stem}.py` | `""` |
| **R (`R`)** | `DESCRIPTION` | `Rscript .aider_factory/tests/run_tests.R {file}` | `tests/testthat/test-{stem}.R` | `""` |
| **Rust (`rs`)** | `Cargo.toml` | `cargo test --test {stem}` | `tests/{stem}.rs` | `""` |
| **JavaScript (`js`)** | `package.json` | `npm test {file}` | `tests/{stem}.test.js` | `""` |
| **Go (`go`)** | `go.mod` | `go test {file}` | `tests/{stem}_test.go` | `""` |
| **Fallback** | *(No markers matched)* | `uv run --with pytest pytest` | `tests/test_{stem}.py` | `""` |

#### Stage 3: Router Model Probing & Selection
If `router_base` is accessible, invokes `env_utils.probe_router(router_base, router_key)`. The endpoint `GET {router_base}/models` is queried (timeout 2s) with `Authorization: Bearer <key>`. All returned IDs are normalized with an `openai/` prefix if bare.
- **Architect & Editor**: Selected via $\arg\max \text{Score}_{\text{arch}}(m)$ (prefers 27B models).
- **Weak Model**: Selected via $\arg\max \text{Score}_{\text{weak}}(m)$ (prefers 1.5B–8B, Flash, or Mini models).
- **Embedder**: First model containing `"embed"`. If matched, `embed_backend` is automatically switched to `"openai"`.
- **Reranker**: First model containing `"rerank"`.

#### Stage 4: Regex-Based Configuration Synthesis
Loads `src/aider_factory/default_configs/env.yml` and performs surgical regex substitutions:
1. **Project Identity**: Replaces `name:` with derived titleized repository name; normalizes `working_directory:` with forward slashes (`/`).
2. **Test Suite Parameters**: Replaces `test_command_prefix`, `test_runner`, and `test_naming_and_path`.
3. **Router Endpoints**: Sets `architect_api_base`, `editor_api`, `editor_api_fallback`, and `weak_model_api_base` to `router_base`.
   *(Crucial Invariant: RAG, OCR, ranking, and grounding endpoints remain at defaults to be resolved locally at runtime).*
4. **Model Assignments**: Sets `architect_agent`, `editor_agent`, `editor_agent_test`, `editor_agent_test_fallback`, `weak_model`, `embed_model`, `ranking_agent`, and `embed_backend`.
5. **Internal Plan Normalization**: Updates `analyze_bugs.md` template path to `src/aider_factory/markdown/internal/analyze_bugs.md`.
6. **Single-Anchor Target File Discovery**:
   - Scans repository source files matching extensions: `.py`, `.r`, `.rs`, `.go`, `.js`, `.ts`, `.jsx`, `.tsx`.
   - Excludes directories: `.git`, `.aider_factory`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `.cache`, `.pytest_cache`, `site-packages`, `.eggs`, `*.egg-info`.
   - Excludes test files via regex: `r"(?:^|[\\/])(?:tests?[\\/]|test_|conftest\.py|setup\.py|__init__\.py$)"`.
   - Selects **exactly one anchor file** (the first discovered on physical disk). If no source files exist, falls back to root documentation files.
7. **Context File Discovery**: Inspects `README.md`, `CHANGELOG.md`, and up to 15 markdown files under `docs/`, populating `context_files_job`.

#### Stage 5: Directory Provisioning & Handshake
1. Writes `.aider_factory/.env_<repo>.yml`.
2. Invokes `cli.init_user_project(cwd)` to create `.aider_factory/` subdirectories (`markdown/`, `logs/`, `sessions/`, `tests/`), unpack sample configs, and symlink bash wrappers.
3. Outputs a structured ASCII telemetry summary to `stdout`.

---

### Deep-Dive: Query Engine & State Persistence (`run_query`)

The `run_query` function handles both configuration updates and general terminal queries:

#### 1. Session Isolation Matrix
- **Configuration Mode (`terminal_mode=False`)**: State is saved to `.aider_factory/.helper_session.json`. System prompt is `PERSONA_PROMPT`.
- **Terminal Mode (`terminal_mode=True`)**: State is saved to `.aider_factory/.helper_terminal_session.json`. System prompt is `TERMINAL_PERSONA_PROMPT`.

#### 2. Deduplicated Context Injection Containers
Before appending the user query, `run_query` inspects all previous assistant and user turns in the active session. If an XML container tag has already been introduced into the history, it is omitted from subsequent turns to prevent token bloat:

- `<reference_schema>`: Injected once from `default_configs/sample_yaml_config/complete_env.yml` or `default_configs/env.yml`.
- `<yaml_documentation>`: Injected once from `markdown/docs/yaml_docs_sample.md` when `--master` or `--expert` is passed.
- `<skills_reference>`: Injected once from all Markdown files under `markdown/skills/` when `--master` or `--expert` is passed.
- `<factory_service_manual>`: Injected once from `docs/factory_service_manual.md` when `--expert` is passed.
- `<repository_map>`: Injected once from `.aider_factory/static_repo_map.md` when `--repo-map` is passed.
- `<active_configuration>`: Injected once containing the exact content of the active `.env.yml` file.
- `<extra_context_files>`: Injected per turn for paths provided via `--context` / `-c`.

#### 3. Execution & Write-Back Logic
1. **Inference Dispatch**: Calls `litellm.completion` with `stream=True` and `stream_options={"include_usage": True}`. If local endpoints are active, resolves model ID mappings (prepending `openai/` and verifying 27B preference).
2. **Rich Live Streaming**: Uses `rich.live.Live` with `rich.markdown.Markdown` refreshing at 15 Hz for smooth terminal rendering.
3. **Disk Write-Back**:
   - If `ask_mode=True` or `terminal_mode=True`: Bypasses all disk modifications.
   - If `ask_mode=False` (Default Configuration Mode): Parses the completion text for markdown code fences (```yaml ... ```). If found, writes the parsed content to the active configuration YAML (`.env.yml` or `.env_<repo>.yml`) and logs confirmation to `stdout`.

---

### Skills Framework Execution Architecture

Skills in the AI Factory are structured operational programs that teach agents how to execute specialized CLI commands.

#### Core Skills Inventory

| Skill Name | Path | Target Tool | Core Purpose |
| :--- | :--- | :--- | :--- |
| **Knowledge Oracle** | `markdown/skills/oracle.md` | `aider-oracle` (`.aider_factory/bash/oracle`) | Natural language RAG retrieval, document citation, formula lookup, and database inspection across LanceDB tables. |
| **Research Agent** | `markdown/skills/research.md` | `aider-research` (`.aider_factory/bash/research`) | Web search via SearXNG, academic paper retrieval (arXiv/Scholar), recursive XML sitemap harvesting, and link dumping. |
| **Evidence Validator** | `markdown/skills/validate.md` | `aider-validate` (`.aider_factory/bash/validate`) | Deterministic verbatim quote grounding, semantic claim audit, automated ellipsis stitching (`--autofix`), and finalization. |
| **Eval Harness** | `markdown/skills/eval_harness.md` | `eval_harness.py` | Token-level recall and IoU evaluations across chunking strategies and embedding models. |
| **Apply Agent** | `markdown/skills/apply.md` | `aider-apply` (`.aider_factory/bash/apply`) | Headless conversion of chat history specifications into atomic git commits via the `editor-diff` edit format. |

#### Skill Delivery Mechanisms
1. **Autonomous Pipeline Execution**: Delivered via `phases[i].files.context_files_job`. Orchestrate loads the skill as an immutable `--read` file, allowing the Architect model to invoke tool commands during its autonomous turn.
2. **Interactive Terminal Assistance**: Delivered via `aider-helper query -m "<query>"` or `-e`. Ingests all skills into the `<skills_reference>` XML container, enabling `aider-helper` to act as an operational tutor.

---

## 4. Exhaustive CLI & Parameter Reference

The `aider-helper` CLI supports two primary subcommands: `bootstrap` and `query`. It fully supports POSIX short-flag chaining (e.g., `aider-helper query -mta "Explain the debate KV cache strategy"`).

### Command Matrix

| Subcommand | Flag | Short | Value / Type | Default | Scope | Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `bootstrap` | `[target_dir]` | | `string` (path) | Current directory (`.`) | Setup | Scaffolds `.aider_factory/.env_<repo>.yml` deterministically without LLM calls. |
| `query` | `<instruction>` | | `string` | *(Required)* | Both | Natural language instruction or configuration request. |
| `query` | `--file` | `-f` | `string` (path) | Active `.env.yml` | Config | Explicit target configuration YAML file to read and mutate. |
| `query` | `--context` | `-c` | `string` (comma-list) | `None` | Both | Comma-separated list of extra files or glob patterns (e.g., `-c "src/*.py,docs/*.md"`). |
| `query` | `--ask` | `-a` | `boolean` (flag) | `False` | Config | Read-only conversational mode. Prevents the agent from writing YAML changes to disk. |
| `query` | `--terminal` | `-t` | `boolean` (flag) | `False` | Terminal | Switches to General AI Terminal Assistant persona and isolates session state. |
| `query` | `--clear` | | `boolean` (flag) | `False` | Both | Wipes session history file for the active persona (`.helper_session.json` or terminal). |
| `query` | `--master` | `-m` | `boolean` (flag) | `False` | Both | Injects all skills (`markdown/skills/*.md`) and YAML documentation into context. |
| `query` | `--expert` | `-e` | `boolean` (flag) | `False` | Both | Injects skills, YAML documentation, AND the complete Factory Service Manual. |
| `query` | `--repo-map` | `-r` | `boolean` (flag) | `False` | Both | Injects `.aider_factory/static_repo_map.md` into the active turn context. |

### Exit Codes

| Exit Code | Classification | Cause & Recovery |
| :--- | :--- | :--- |
| `0` | **Success** | Query executed successfully, or bootstrap completed, or `--clear` wiped session. |
| `1` | **Missing API Key** | `detect_api_key()` found no valid keys. Set cloud key or `AIDER_HELPER_API_BASE`. |
| `1` | **File Not Found** | Specified `--file` path does not exist on physical disk. |
| `1` | **Inference Failure** | LiteLLM call failed (network error, model 404, or context limit exceeded). |

### Concrete Invocations

```bash
# 1. Deterministic workspace bootstrap
aider-helper bootstrap

# 2. Bootstrap into an explicit subdirectory
aider-helper bootstrap /home/ares/projects/my_project

# 3. Conversational query about current configuration (no disk edits)
aider-helper query -a "What models are configured for Phase 1?"

# 4. Mutate configuration to add a new test pattern
aider-helper query "Update Phase 1 test_naming_and_path to tests/unit/test_{stem}.py"

# 5. General software engineering query in terminal mode
aider-helper query -t "Write a Python script to calculate Levenshtein distance"

# 6. Terminal query with chained flags: master skills, expert manual, terminal mode
aider-helper query -tem "How do I configure a custom LanceDB embedding table?"

# 7. Query with extra codebase context and repository map
aider-helper query -r -c "src/engine.py,tests/test_engine.py" "Refactor engine to support async I/O"

# 8. Clear configuration session history
aider-helper query --clear

# 9. Clear terminal assistant session history
aider-helper query -t --clear
```

---

## 5. Configuration Schema & YAML Knobs

### Environment Variable Overrides

`aider-helper` can be configured dynamically via environment variables without editing code:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `AIDER_HELPER_MODEL` | `string` | Provider-specific fallback | Overrides the model ID used by `aider-helper` (e.g., `openai/qwen2.5-coder:latest`). |
| `AIDER_HELPER_API_BASE` | `string` (URL) | `None` | Endpoint for custom local LLM server (e.g., `http://localhost:8080/v1`). |
| `LITELLM_BASE_URL` | `string` (URL) | `None` | Base URL for LiteLLM cluster router (probed during bootstrap and used as default). |
| `LITELLM_API_KEY` | `string` | `None` | Authentication key for LiteLLM cluster router. |
| `LITELLM_SESSION_ID` | `string` (UUID) | Auto-generated UUID | Session identifier passed in headers for KV-cache stickiness across turns. |
| `GEMINI_API_KEY` | `string` | `None` | Google Gemini API key. Defaults model to `gemini/gemini-3.6-flash`. |
| `ANTHROPIC_API_KEY` | `string` | `None` | Anthropic API key. Defaults model to `anthropic/claude-3-5-sonnet-20241022`. |
| `OPENAI_API_KEY` | `string` | `None` | OpenAI API key. Defaults model to `openai/gpt-4o`. |

### Scaffolded Configuration Example (`.env_<repo>.yml`)

Generated by `aider-helper bootstrap`:

```yaml
name: "My Project Pipeline"
working_directory: "/home/ares/projects/my_project"

# Global test configuration detected from filesystem
test_command_prefix: ""
test_runner: "uv run --with pytest pytest"
test_naming_and_path: "tests/test_{stem}.py"
loop_aider_test: 1
auto_lint: true

endpoints:
  architect_api_base: "http://192.168.1.100:4000/v1"
  editor_api: "http://192.168.1.100:4000/v1"
  editor_api_fallback: "http://192.168.1.100:4000/v1"
  weak_model_api_base: "http://192.168.1.100:4000/v1"
  ocr_api_base: "http://localhost:8080"
  embed_api_base: ""
  ranking_api_base: ""
  grounding_agent_api: ""

models:
  architect_agent: "openai/qwen3.6-27b-90k:LATEST"
  editor_agent: "openai/qwen3.6-27b-90k:LATEST"
  editor_agent_test: "openai/qwen3.6-27b-90k:LATEST"
  editor_agent_test_fallback: "openai/qwen3.6-27b-90k:LATEST"
  weak_model: "openai/qwen2.5-coder-7b:latest"
  embed_model: "BAAI/bge-m3"
  ranking_agent: ""

phases:
  - name: "Implementation Phase"
    enabled: true
    toggles:
      run_job_one: true
      run_job_two: false
      run_job_three: false
      iterate_test: true
      auto_test: false
      pair_programming: false
      shared_history: false
    files:
      target_files:
        - "src/core/engine.py"
      extra_editable_files: []
      test_files: []
      context_files_job:
        - "README.md"
        - "src/aider_factory/markdown/skills/oracle.md"
      context_files_test: []
    plans:
      job_one_plan: "src/aider_factory/markdown/templates/code_generate.md"
      iterate_plan: "src/aider_factory/markdown/templates/code_iterate.md"
```

---

## 6. Operational Edge Cases, Failure Modes & Telemetry

### Operational Edge Cases & Mitigations

1. **Missing Authentication Credentials**:
   - *Symptom*: Execution halts immediately with: `❌ No active LLM API key detected.`
   - *Mechanism*: `detect_api_key()` found neither cloud API keys nor `AIDER_HELPER_API_BASE`.
   - *Recovery*: Export a supported key (`export GEMINI_API_KEY="sk-..."`) or configure `AIDER_HELPER_API_BASE="http://localhost:8080/v1"`.
2. **Pristine Directory Protection**:
   - *Symptom*: Running `aider-helper query -a "help"` in an uninitialized repo does not create `.aider_factory/`.
   - *Mechanism*: In `ask_mode` or `terminal_mode`, `run_query` checks `if not ask_mode or not session_dir or os.path.exists(session_dir)` before calling `os.makedirs()`.
   - *Guarantee*: Zero accidental directory pollution on exploratory read-only queries.
3. **Missing Static Repository Map**:
   - *Symptom*: `⚠️ [aider-helper] Warning: --repo-map requested, but '.aider_factory/static_repo_map.md' not found.`
   - *Mechanism*: The `--repo-map` flag looks for `.aider_factory/static_repo_map.md`. If absent, the query continues gracefully without map injection.
   - *Recovery*: Run `aider-factory --repo-map` to generate the static AST repository map.
4. **Code Fence Collisions in Extra Context**:
   - *Symptom*: Context files containing markdown tutorials with triple backticks break LLM parsing.
   - *Mechanism*: Dynamic backtick counting counts maximum consecutive backticks in content and wraps the block in $N + 1$ backticks.
   - *Guarantee*: 100% parse fidelity for embedded code fences.
5. **YAML Block Extraction Resilience**:
   - *Symptom*: LLM emits conversational pleasantries before and after the modified YAML.
   - *Mechanism*: `run_query` checks for ``` ```yaml ``` first, splitting on fences; if not found, falls back to bare ``` ``` ``` blocks. If no code fence is found, disk write is safely bypassed to prevent file corruption.
6. **Local Server Fallback & 27B Preference**:
   - *Symptom*: Local router has 20 models loaded, but `aider-helper` picks the optimal model.
   - *Mechanism*: When `AIDER_HELPER_API_BASE` is set without an explicit model, `run_query` queries `/v1/models` and selects the first model containing `"27b"`. If none match, falls back to `openai/qwen3.6-27b-90k:LATEST`.

### Telemetry & Real-Time Cost Accounting

`aider-helper` integrates directly with `src/aider_factory/python/cost_tracker.py`:

```text
Tokens: 1.2k sent, 450 received. Cost: $0.0018 message, $0.0142 session.
```

- **Usage Retrieval**: Extracted from LiteLLM stream chunks via `chunk.usage` (`prompt_tokens`, `completion_tokens`).
- **Cost Calculation**: Calculated via `litellm.cost_calculator.cost_per_token(model, prompt_tokens, completion_tokens)`.
- **Session Accumulation**: Added to `cost_tracker._PROCESS_SESSION_COST` in memory.
- **Reporting**: Emitted directly to `sys.stderr` after response completion, preserving `stdout` for clean piping and script consumption.
