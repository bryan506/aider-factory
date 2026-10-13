# `aider-apply` — Headless Code Application & KV-Cache Preservation Engine

## 1. Executive Overview & Foundational Invariants

`aider-apply` is an autonomous, headless code application engine within the AI Factory pipeline. It decouples high-reasoning conversational planning (Architect) from surgical repository mutation (Editor) without invalidating local Large Language Model Key-Value caches (Prefix Caches / Prompt Caching).

In modern software development pipelines powered by large parameter local models (e.g., Qwen 2.5 32B/72B, DeepSeek-Coder, Llama 3.3 70B running on `llama-server`, vLLM, or SGLang), prompt evaluation time scales linearly with the length of uncached tokens. `aider-apply` eliminates prefix cache eviction by enforcing an append-only conversational model: the Architect plans the implementation in an interactive conversational session (`--edit-format ask`), and `aider-apply` extracts the concrete `SEARCH/REPLACE` specification from the chat history and executes it in an isolated, headless subprocess. The physical codebase is mutated on disk, committed to Git, and a compact plain-text Git diff is streamed back into the terminal and the Architect's context.

### The Core Problem: KV-Cache Invalidation in Aider

Standard Aider operation is **disk-aware**. At every conversational turn, Aider inspects the filesystem timestamp and hash of all files currently tracked in its context via `/add` or `/read`. When any tracked file is edited on disk:
1. Aider reads the updated content from disk and reconstructs the system/context block near the beginning of the prompt.
2. The byte sequence of the prompt shifts starting at the position of the modified file.
3. Because autoregressive transformers compute Key-Value tensors sequentially, changing token $k$ invalidates all KV cache entries from position $k$ through context length $L_{\text{prompt}}$.
4. On local inference servers, this triggers a **complete KV-cache bust**, forcing full prompt re-evaluation across 10,000 to 60,000+ tokens and stalling the GPU for 60 to 180 seconds per turn.

### Mathematical Foundations of KV-Cache Preservation

In autoregressive transformer models, the prompt prefill latency $T_{\text{eval}}$ is governed by matrix-vector operations across the uncached prompt tokens:

$$T_{\text{eval}} = \alpha \cdot L_{\text{uncached}} + \beta$$

where $\alpha$ represents the hardware-dependent compute time per token (governed by memory bandwidth and FLOP capability), $\beta$ is fixed kernel dispatch overhead, and $L_{\text{uncached}}$ is the length of prompt tokens lacking pre-computed Key-Value representations in GPU VRAM.

When mutable target files reside in Aider's `/read` or `/add` context, an on-disk file edit invalidates the cache starting at token index $k$, where $k$ is the offset of the modified file in the prompt. The effective KV-cache prefix hit ratio $H_{\text{KV}}$ degrades to:

$$H_{\text{KV}} = \frac{|\mathcal{P}_{\text{shared}}|}{|\mathcal{P}_{\text{total}}|} = \frac{k}{L_{\text{prompt}}}$$

Because file representations are injected high up in Aider's system prompt topology ($k \ll L_{\text{prompt}}$), $H_{\text{KV}} \to 0$, inducing cold evaluation:

$$T_{\text{cold}} = \alpha \cdot L_{\text{prompt}} + \beta$$

By contrast, `aider-apply` guarantees that mutable target files are **never** loaded into the Architect's `/read` or `/add` table. Instead, target file snippets enter the Architect's context strictly through the append-only conversation tail $\Delta L_{\text{turn}}$. The prompt prefix remains 100% byte-identical across successive turns:

$$H_{\text{KV}} = \frac{|\mathcal{P}_{\text{shared}}|}{|\mathcal{P}_{\text{total}}|} = \frac{L_{\text{prompt}} - \Delta L_{\text{turn}}}{L_{\text{prompt}}} \approx 1.0 \quad (\text{as } \Delta L_{\text{turn}} \ll L_{\text{prompt}})$$

Under this regime, prompt prefill latency on local inference engines operates in warm mode:

$$T_{\text{warm}} = \alpha \cdot \Delta L_{\text{turn}} + \beta$$

The theoretical and empirical speedup factor $\mathcal{S}$ is:

$$\mathcal{S} = \frac{T_{\text{cold}}}{T_{\text{warm}}} = \frac{\alpha \cdot L_{\text{prompt}} + \beta}{\alpha \cdot \Delta L_{\text{turn}} + \beta}$$

For typical workloads where $L_{\text{prompt}} = 35{,}000$ tokens and $\Delta L_{\text{turn}} = 450$ tokens:

$$\mathcal{S} \approx \frac{35{,}000}{450} \approx 77.7\times$$

Transforming a 120-second GPU stall into a sub-1.5-second turn.

Furthermore, folding the resulting plain-text Git diff back into the Architect's conversation rather than re-reading the entire file provides a substantial token transmission reduction ratio $\Delta_{\text{tokens}}$:

$$\Delta_{\text{tokens}} = 1 - \frac{|\text{Tokens}(\text{UnifiedDiff})|}{|\text{Tokens}(\text{FullFileContent})|}$$

where $|\text{Tokens}(\text{UnifiedDiff})| \ll |\text{Tokens}(\text{FullFileContent})|$, saving $75\%$ to $95\%$ of context consumption per iterative editing cycle.

### Foundational Invariants

1. **Immutable Reference Files**: Reference documents (e.g., specifications, schemas, `CONVENTIONS.md`) loaded via `--read` or `/read` must never mutate during a session. Their byte-identical presence preserves the KV-cache prefix.
2. **Mutable Target Files**: Files targeted for code modification must **never** be loaded via `/add` or `/read` in the Architect's session. They are introduced strictly via the append-only chat stream (e.g., `/run cat <target_file>` or diff telemetry).
3. **Headless Execution Decoupling**: All physical disk modifications, syntax transformations, and Git commits are offloaded to an ephemeral, headless Editor process (`apply_agent.py`), running `--edit-format editor-diff` with independent chat history files.
4. **Zero Blast Radius**: Ephemeral artifacts (`active_spec.md`, `.apply.chat.history_*`, `.apply.input.history_*`, temporary settings) are written to isolated scratch directories (`.aider_factory/temp/`) and cleanly purged upon process exit.
5. **Deterministic Git Telemetry**: Every successful mutation pass must terminate by outputting a standard unified Git diff against `HEAD~1` (or `EMPTY_TREE_SHA` on root commits) formatted with `--no-color` and `--no-ext-diff`.

---

## 2. System Topology & Lifecycle Flowcharts

### System Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 AIDER-APPLY TOPOLOGY & DATA FLOW                                │
│                                                                                                 │
│  [Node 1: Interactive Architect Session]                                                        │
│  • Running interactively in terminal (/ask mode, AIDER_ARCHITECT=false)                         │
│  • Static context: CONVENTIONS.md, specs in /read (Never target files!)                         │
│  • Appends turns to: .aider_factory/sessions/<name>/.aider.chat.history.md                      │
│                                                                                                 │
│                                           │                                                     │
│                                           ▼                                                     │
│  [apply_agent.py: Extraction & Configuration Subsystem]                                         │
│  1. Locates active history: find_active_session_chat_history()                                  │
│  2. Dual-anchor parser: parse_chat_history(chat_path, turns=N)                                  │
│     - Slices turns via TOKEN_ANCHOR_RE                                                          │
│     - Strips interactive commands via SLASH_CMD_RE                                              │
│     - Cleans thinking blocks (<think>, <thinking-content-*>) & tool noise                       │
│  3. Writes isolated spec: .aider_factory/temp/active_spec.md                                     │
│  4. Resolves editor config: resolve_editor_config() from paired session.yml / .env.yml          │
│  5. Sanitizes configuration: strips ambient 'read' and 'files' to prevent context leakage       │
│  6. Upserts weak model endpoints into temporary .aider.model.settings.yml                       │
│                                                                                                 │
│                                           │                                                     │
│                                           ▼                                                     │
│  [Node 2: Headless Editor Process (Isolated Subprocess)]                                        │
│  • Invokes: aider --model <editor_model> --edit-format editor-diff                              │
│                   --message-file active_spec.md --no-restore-chat-history                       │
│                   --chat-history-file .apply.chat.history_<pid>.md                              │
│                   --map-tokens 0 --exit --auto-commits <target_files...>                        │
│  • Stdin primed with: b"n\n" * 50 (auto-reject interactive prompts)                             │
│  • Watchdog thread: AIDER_STREAM_TIMEOUT (default: 300s) -> kill_proc_tree()                    │
│  • Stream isolation: progress piped to /dev/tty or CONOUT$ (zero stdout pollution)              │
│  • Mutates target files on disk & creates standard Git commit                                   │
│                                                                                                 │
│                                           │                                                     │
│                                           ▼                                                     │
│  [Git Diff Telemetry & Ephemeral Cleanup]                                                       │
│  1. Verifies git revision: git rev-parse --verify HEAD~1 (fallback: EMPTY_TREE_SHA)              │
│  2. Emits diff: git --no-pager diff --no-color --no-ext-diff <target> HEAD                      │
│  3. Unlinks temporary files: active_spec.md, .apply.chat.history_<pid>.md                       │
│  4. Node 1 Architect reads clean diff from stdout with 100% KV-cache hit rate!                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Complete Lifecycle State Machine Flowchart

```text
    ┌─────────────────────────┐
    │          IDLE           │
    └────────────┬────────────┘
                 │ Invoked via CLI, /run, or Script
                 ▼
    ┌─────────────────────────┐
    │     SPEC_EXTRACTION     │◄─────────────────────────────────────────────┐
    └────────────┬────────────┘                                              │
                 │ Chat history parsed or explicit --spec loaded             │
                 ├───────────────────────────────┐                           │
                 │ Success                       │ Spec empty or file missing│
                 ▼                               ▼                           │
    ┌─────────────────────────┐     ┌────────────────────────┐               │
    │    CONFIG_RESOLUTION    │     │      HALT_FAILURE      │               │
    └────────────┬────────────┘     │      (Exit Code 1)     │               │
                 │ Precedence resolved (CLI > env > session > .env.yml)      │
                 ▼                  └────────────────────────┘               │
    ┌─────────────────────────┐                                              │
    │     SETTINGS_UPSERT     │                                              │
    └────────────┬────────────┘                                              │
                 │ Weak model settings mapped; config sanitized (strip read) │
                 ▼                                                           │
    ┌─────────────────────────┐                                              │
    │    SUBPROCESS_SPAWN     │                                              │
    └────────────┬────────────┘                                              │
                 │ Popen: stdin primed (b"n\n" * 50); watchdog started       │
                 ▼                                                           │
    ┌─────────────────────────┐                                              │
    │   WATCHDOG_EXECUTION    │                                              │
    └────────────┬────────────┘                                              │
                 │ Stream isolation: progress to /dev/tty or CONOUT$         │
                 ├───────────────────────────────┐                           │
                 │ Returncode == 0               │ Non-zero exit or Timeout  │
                 ▼                               ▼                           │
    ┌─────────────────────────┐     ┌────────────────────────┐               │
    │     DIFF_EXTRACTION     │     │     KILL_PROC_TREE     │───────────────┘
    └────────────┬────────────┘     │      (Exit Code 1)     │
                 │ Verify HEAD~1 (fallback to EMPTY_TREE_SHA); emit diff     │
                 ▼                  └────────────────────────┘
    ┌─────────────────────────┐
    │    EPHEMERAL_CLEANUP    │
    └────────────┬────────────┘
                 │ Temp files unlinked in finally block
                 ▼
    ┌─────────────────────────┐
    │      HALT_SUCCESS       │
    │      (Exit Code 0)      │
    └─────────────────────────┘
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### The Dual-Anchor Regex Extraction Engine

Aider chat history files (`.aider.chat.history.md`) interleave user prompts, assistant answers, tool outputs, and token summaries. `apply_agent.py` implements a dual-anchor parser to extract clean, unambiguous specifications.

```python
TOKEN_ANCHOR_RE = re.compile(
    r"(?m)^>\s*Tokens:\s*[\d\.]+[kKMG]?\s*sent,\s*[\d\.]+[kKMG]?\s*received.*$"
)
SLASH_CMD_RE = re.compile(
    r"^/(add|run|read|drop|model|clear|exit|undo|diff|load|help)\b"
)
```

#### Step-by-Step Parsing Logic (`parse_chat_history`)

1. **Anchor Slicing**:
   - `TOKEN_ANCHOR_RE` identifies the terminal line of each conversation turn generated by Aider.
   - Slices the file text backwards from each match index, isolating turn blocks between `prev_end` and `start_idx`.
2. **User Directive Extraction**:
   - Identifies user prompt lines prefixed with `#### `.
   - Evaluates lines against `SLASH_CMD_RE`. If a command matches `/add`, `/run`, `/read`, `/drop`, `/model`, `/clear`, `/exit`, `/undo`, `/diff`, `/load`, or `/help`, it is discarded.
   - `/ask` prefixes are stripped via `re.sub(r"^/ask\s*", "", raw_user)`, preserving conversational user directives.
3. **Artifact & Reasoning Sanitization**:
   - Assistant text is sanitized of internal chain-of-thought blocks:
     ```python
     asst_text = re.sub(
         r"<thinking-content-[0-9a-fA-F]+>[\s\S]*?</thinking-content-[0-9a-fA-F]+>",
         "",
         asst_text,
     )
     asst_text = re.sub(r"<think>[\s\S]*?</think>", "", asst_text)
     asst_text = re.sub(r"►\s*\*{0,2}ANSWER\*{0,2}", "", asst_text).strip()
     ```
   - Tool execution lines matching `^>\s*(Added|Moved|No files|Tokens).*` are discarded.
4. **Header Synthesis & Multi-Turn Structuring**:
   - If `turns == 1` (default):
     - Emits `# Directive\n<user_text>\n\n# Specification & Implementation Plan\n<asst_text>\n`.
   - If `turns > 1`:
     - Emits prior turns chronologically under `## Prior Context Turn <idx>\n### User Request:\n...\n### Architect Specification:\n...`.
     - Emits the final active turn under `## Active Directive\n### User Request:\n...\n### Architect Specification:\n...`.

### Active Chat History Discovery (`find_active_session_chat_history`)

The active chat history file is discovered across four hierarchical tiers:

```python
def find_active_session_chat_history(cwd: str, session_name: str = None) -> tuple[str, str]:
```

1. **Target Session Root**: If `session_name` is explicitly passed or found in `AI_FACTORY_SESSION`:
   - Checks `.aider_factory/sessions/<session_name>/.aider.chat.history.md`.
2. **Target Session History Vault**:
   - Checks `.aider_factory/sessions/<session_name>/chat_history/.aider.chat.history_*.md`.
   - Sorts candidates by modification time (`os.path.getmtime`) descending; selects the most recent file.
3. **Global Sessions Sweep**:
   - Scans `.aider_factory/sessions/*/` for `.aider.chat.history.md`.
   - Selects the session directory with the latest `mtime`.
4. **Workspace Root Fallback**:
   - Checks `.aider_factory/.aider.chat.history.md`.
   - Returns `("", session_name)` if no history file is found.

### Editor Configuration Discovery (`resolve_editor_config`)

The editor configuration is dynamically resolved across four candidate paths:
1. File path specified by `AI_FACTORY_CONFIG`.
2. Session-specific YAML: `.aider_factory/sessions/<session_name>/session.yml`.
3. Workspace configuration: `.aider_factory/.env.yml`.
4. Workspace root configuration: `.env.yml`.

From the matched YAML file, `apply_agent.py`:
- Extracts `models.editor_agent` or phase 0 `models.editor_agent` (falls back to `gemini/gemini-2.5-flash` if unspecified).
- Extracts `endpoints.editor_api`.
- Extracts `weak_model` and `weak_model_api_base`.
- Validates endpoints via `is_valid_endpoint(url)` to reject dummy or template values.
- Enforces strict cloud/local isolation: if `weak_model` is a cloud model (`gemini/*`, `anthropic/*`, `openai/*`), `weak_model_api_base` is forced to `None` to prevent cloud traffic from leaking to local inference servers.

### Configuration Sanitization & Model Settings Upsert

To ensure the headless editor operates with zero ambient state leakage:

1. **Configuration Sanitization**:
   - Loads the active `.aider.conf.yml`.
   - Strips `read` and `files` keys so ambient repository maps or reference manuals are not loaded into the editor context.
   - Forces `architect: false`.
   - Writes the sanitized configuration to `.aider_factory/temp/.apply.aider.conf.yml`.
2. **Model Settings Upsert (`ensure_model_settings`)**:
   - If `weak_model` and `weak_model_api_base` are configured, upserts model definitions into a temporary `.aider_factory/temp/.apply.aider.model.settings.yml`.
   - Resolves the API key in priority order: `LITELLM_API_KEY` $\to$ `OPENAI_API_KEY` $\to$ `"sk-dummy"`.

### Subprocess Watchdog & Process Tree Termination

`aider-apply` protects against hanging editor passes using an isolated watchdog thread:

```python
import threading

timeout_secs = float(os.environ.get("AIDER_STREAM_TIMEOUT", "300"))
watchdog = threading.Timer(timeout_secs, _on_timeout)
watchdog.daemon = True
watchdog.start()
```

If execution exceeds `AIDER_STREAM_TIMEOUT` (default: 300 seconds), the watchdog triggers `kill_proc_tree(proc)`:
- **Windows**: Executes `taskkill /F /T /PID <pid>` to terminate the entire process hierarchy.
- **POSIX**: Retrieves the process group ID via `os.getpgid(proc.pid)` and sends `signal.SIGKILL` across the process group (`os.killpg(pgrp, signal.SIGKILL)`).
- Closes `stdin`, `stdout`, and `stderr` streams cleanly.

---

## 4. Exhaustive CLI & Parameter Reference

### Entrypoints

`aider-apply` can be invoked through four distinct interfaces:

| Interface | Invocations | Scope & Use Case |
| :--- | :--- | :--- |
| **Global CLI Entrypoint** | `aider-apply <files...> [options]` | Terminal execution from anywhere within the repository workspace. |
| **Workspace Script** | `.aider_factory/bash/apply <files...> [options]` | Shell wrapper utilizing the repository virtual environment. |
| **Python Module Execution** | `python -m aider_factory.python.apply_agent <files...> [options]` | Direct execution under an explicit Python interpreter. |
| **Interactive Aider Slash Command** | `/run aider-apply <files...> [options]`<br>`/run .aider_factory/bash/apply <files...>` | Executed directly from the Architect chat prompt without leaving Aider. |

### Command Parameter Matrix

```bash
aider-apply <files...> [--spec <path>] [--turns <N>] [--model <id>] [--session <name>] [--no-diff] [--stream]
```

| Parameter | Short | Type | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `files` | *(none)* | `list[str]` | *(Required)* | One or more paths to target files to be modified. Relative or absolute. |
| `--spec` | `-s` | `str` | `None` | Path to an explicit Markdown specification file. Bypasses chat history extraction. |
| `--turns` | `-t` | `int` | `1` | Number of recent conversation turns to extract from chat history. |
| `--model` | `-m` | `str` | `None` | Overrides the editor model configured in `session.yml` or `.env.yml`. |
| `--session` | *(none)* | `str` | `None` | Explicit session identifier to resolve history and config from. Auto-discovered if omitted. |
| `--no-diff` | *(none)* | `flag` | `False` | Suppresses Git diff output to `stdout` following successful application. |
| `--stream` | *(none)* | `flag` | `False` | Streams inner Aider editor output to console (`/dev/tty` or `CONOUT$`) without polluting `stdout`. |
| `--help` | `-h` | `flag` | `False` | Displays the standard CLI help message and parameter reference. |

### Process Exit Codes

| Exit Code | Classification | Cause & System State |
| :---: | :--- | :--- |
| **`0`** | **SUCCESS** | Spec extracted, headless editor applied changes cleanly, Git commit created, and diff emitted. |
| **`1`** | **FAILURE: Missing History** | No `.aider.chat.history.md` found in session directory, vault, or repository root. |
| **`1`** | **FAILURE: Empty Spec** | Chat history parsed successfully, but no actionable user directives or specifications were found. |
| **`1`** | **FAILURE: Subprocess Error** | The underlying `aider` editor process terminated with a non-zero exit code. |
| **`1`** | **FAILURE: Watchdog Timeout** | Editor execution exceeded `AIDER_STREAM_TIMEOUT` (300s default) and process tree was terminated. |
| **`1`** | **FAILURE: Exception** | Unhandled I/O error, invalid CLI arguments, or environment configuration exception. |

---

## 5. Configuration Schema & YAML Knobs

`aider-apply` inherits settings from the pipeline configuration schema defined in `.aider_factory/.env.yml` or `.aider_factory/sessions/<name>/session.yml`.

### YAML Schema Definition

```yaml
# ==============================================================================
# AIDER-APPLY RUNTIME CONFIGURATION SCHEMA
# ==============================================================================

# Network Endpoints for Inference Servers
endpoints:
  # Base URL for Editor LLM (Ollama, vLLM, llama-server, LiteLLM router)
  # Injected as OPENAI_API_BASE, OLLAMA_API_BASE, and LM_STUDIO_API_BASE
  editor_api: "http://127.0.0.1:8080/v1" # string (URL) | null

  # Base URL for Weak Model (summaries, linting, commit messages)
  weak_model_api_base: "http://127.0.0.1:8081/v1" # string (URL) | null

# Model Identifiers
models:
  # Primary Editor agent responsible for applying SEARCH/REPLACE diffs
  # Prefixed with provider: 'openai/', 'gemini/', 'anthropic/'
  editor_agent: "openai/qwen2.5-coder-32b-instruct" # string (Model ID)

  # Lightweight model for commit messages and auxiliary editing tasks
  weak_model: "openai/qwen2.5-coder-7b-instruct" # string (Model ID) | null
```

### Environment Variable Matrix

The following environment variables govern `aider-apply` runtime execution:

| Variable | Scope | Type | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `AIDER_STREAM_TIMEOUT` | Host | `float` | `300.0` | Watchdog timeout in seconds before terminating the editor process tree. |
| `AI_FACTORY_SESSION` | Host | `str` | `None` | Active session identifier for scoping history and config lookups. |
| `AI_FACTORY_CONFIG` | Host | `str` | `None` | Explicit path to active YAML configuration file. |
| `LITELLM_API_KEY` | Host | `str` | `None` | Primary router API key. Filtered against dummy values; falls back to `sk-dummy`. |
| `OPENAI_API_KEY` | Host | `str` | `None` | Secondary API key. Fallback for `LITELLM_API_KEY`. |
| `OPENAI_API_BASE` | Subprocess | `str` | `editor_api` | Injected into the headless Aider subprocess. |
| `OLLAMA_API_BASE` | Subprocess | `str` | `editor_api` | Injected into the headless Aider subprocess. |
| `LM_STUDIO_API_BASE` | Subprocess | `str` | `editor_api` | Injected into the headless Aider subprocess. |
| `LM_STUDIO_API_KEY` | Subprocess | `str` | Router Key | Authentication key for LM Studio endpoints. |
| `WEAK_MODEL_API_BASE` | Subprocess | `str` | Weak Base | Injected into subprocess if weak model is local. |
| `AIDER_WEAK_MODEL_API_BASE`| Subprocess | `str` | Weak Base | Alternate weak model endpoint variable for Aider. |
| `AIDER_ARCHITECT` | Subprocess | `str` | `"false"` | Explicitly disables Architect mode in the editor subprocess. |

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### The Initial Commit Edge Case (`EMPTY_TREE_SHA`)

When `aider-apply` operates in a newly initialized Git repository with only a single commit (or during initial repository bootstrapping), checking `HEAD~1` causes `git rev-parse` to fail:

```text
fatal: ambiguous argument 'HEAD~1': unknown revision or path not in the working tree.
```

`apply_agent.py` intercepts this condition deterministically by verifying `HEAD~1` before diff calculation and falling back to Git's universal empty tree hash:

$$\text{SHA}_{\text{empty}} = \texttt{4b825dc642cb6eb9a060e54bf8d69288fbee4904}$$

```python
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
git_target = "HEAD~1"
try:
    rev_check = subprocess.run(
        [git_bin, "rev-parse", "--verify", "HEAD~1"],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    if rev_check.returncode != 0:
        git_target = EMPTY_TREE_SHA
except Exception:
    git_target = EMPTY_TREE_SHA
```

This guarantees that `git --no-pager diff --no-color --no-ext-diff <git_target> HEAD` succeeds even on the initial commit of a repository.

### Cross-Platform Windows Execution Mechanics

On Windows platforms, `aider` is frequently installed as a batch or command wrapper (`aider.bat` or `aider.cmd`). Attempting to execute batch files directly via `subprocess.Popen` without a command shell triggers `OSError: [WinError 193] %1 is not a valid Win32 application`.

`apply_agent.py` resolves this via binary inspection:

```python
if sys.platform == "win32":
    try:
        aider_bin = shutil.which("aider") or "aider"
    except Exception:
        aider_bin = "aider"
    cmd[0] = aider_bin
    if aider_bin.lower().endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        cmd = [comspec, "/c"] + cmd
```

Similarly, when invoking Git commands on Windows, if `git_bin` resolves to a batch script, execution is prefixed with `["cmd.exe", "/c"]`.

### Stream Isolation via Console Devices (`/dev/tty` vs `CONOUT$`)

When `aider-apply` is executed from within an active Aider session using `/run aider-apply <files>`, the outer Aider process captures all data written to `stdout` and `stderr` as "command output" and injects it into the Architect's context window.

A standard Aider editing pass outputs 40,000 to 120,000 raw tokens consisting of file content echoes, intermediate thinking blocks, and UI progress markers. If allowed on `stdout`, this would instantly overwhelm the Architect's context window.

To prevent context pollution while preserving real-time terminal visibility for the developer, `aider-apply --stream` routes output directly to the operating system's raw console device:
- **POSIX (Linux, macOS)**: `/dev/tty`
- **Windows**: `CONOUT$`

```python
tty_path = "CONOUT$" if sys.platform == "win32" else "/dev/tty"
tty_fh = open(tty_path, "w", encoding="utf-8", errors="replace")
# Progress lines written to tty_fh bypass stdout entirely
```

Only the clean unified diff is written to `sys.stdout` upon completion.

### Non-Interactive Stdin Priming

Headless Aider instances occasionally encounter unexpected user confirmation prompts (e.g., file creation confirmations, git repo warnings, large file warnings).

To prevent the headless process from blocking indefinitely on an unattached stdin stream, `apply_agent.py` primes the standard input pipe with automated negative responses:

```python
proc.stdin.write(b"n\n" * 50)
proc.stdin.flush()
proc.stdin.close()
```

This guarantees deterministic non-blocking execution across automated DAG pipelines.

### Token Economy & ANSI Strip Rationale

The diff emitted by `aider-apply` is generated using:

```bash
git --no-pager diff --no-color --no-ext-diff HEAD~1 HEAD
```

1. `--no-pager`: Disables interactive pagers (`less`, `more`) that hang headless automation.
2. `--no-color`: Strips 24-bit ANSI color escape sequences (`\033[32m`, `\033[0m`). ANSI escape sequences inflate token counts by **30% to 40%** and cause byte-pair tokenizers to split identifiers across punctuation boundaries.
3. `--no-ext-diff`: Disables custom user diff drivers (e.g., `difftastic`), enforcing standard unified diff formatting across all workstations and CI runners.

### Concrete Diagnostic Workflows

#### Workflow 1: Standard Interactive Pair-Programming Handoff
1. Launch an interactive session:
   ```bash
   aider-factory my_feature
   ```
2. Discuss design with the Architect in `/ask` mode. Explore alternatives across Turns 1 and 2.
3. At Turn 3, instruct the Architect:
   > *"Output the exact SEARCH/REPLACE blocks to implement `verify_token` in `src/auth.py`."*
4. Apply the specification immediately without leaving the session:
   ```bash
   /run aider-apply src/auth.py
   ```
5. `aider-apply` parses Turn 3, executes the headless editor, commits the edit, and prints the unified diff.
6. The Architect receives the diff with 100% KV-cache hit rate (<1.2s prefill time).

#### Workflow 2: Multi-Turn Context Extraction (`--turns N`)
When architectural decisions and code blocks are distributed across multiple preceding turns:
```bash
aider-apply src/pipeline.py src/utils.py --turns 3
```
`apply_agent.py` formats Turns $T-2$ and $T-1$ as `## Prior Context Turn` blocks and Turn $T$ as `## Active Directive`, giving the editor full context.

#### Workflow 3: Offline Specification Application (`--spec`)
To apply an offline specification document or design plan directly:
```bash
aider-apply src/database.py --spec .aider_factory/markdown/plans/db_refactor.md
```

#### Workflow 4: Cross-Session State Recovery (`--session`)
To extract the specification from an asynchronous background session:
```bash
aider-apply src/worker.py --session worker_job_20260408
```

#### Workflow 5: Diagnosing Empty Spec Failures
If `aider-apply` exits with `❌ Error: Could not parse a valid specification from chat history.`:
1. Inspect the chat history:
   ```bash
   tail -n 100 .aider_factory/sessions/<name>/.aider.chat.history.md
   ```
2. Verify that the turn ends with a standard token usage footer matching `TOKEN_ANCHOR_RE` (`> Tokens: ... sent, ... received`).
3. Ensure the Architect was not interrupted mid-stream before the usage footer was written. If interrupted, send a brief confirmation prompt (e.g., `/ask confirm spec`) to flush the token footer.

#### Workflow 6: Diagnosing Subprocess Timeouts
If `aider-apply` terminates with `❌ Error: Aider apply execution timed out after 300.0s`:
1. Check inference server utilization and logs to verify whether the editor model hung during generation.
2. If working with massive files (>2,000 lines), increase the timeout threshold:
   ```bash
   export AIDER_STREAM_TIMEOUT=600
   aider-apply src/large_file.py
   ```
3. Run with `--stream` to monitor real-time generation output on `/dev/tty` or `CONOUT$`:
   ```bash
   aider-apply src/large_file.py --stream
   ```
