# `aider-apply` — Headless Code Application & KV-Cache Preservation Engine

`aider-apply` is a specialized, headless execution client that bridges high-reasoning conversational planning (Architect) and surgical code editing (Editor) without invalidating local LLM KV caches (Prefix Caches).

It extracts implementation specifications directly from your active session's chat history (or a standalone spec file), spins up an isolated, headless Aider instance to apply SEARCH/REPLACE diffs to target files, commits changes to Git, and streams the resulting `git diff` back to your terminal or Architect session.

---

## 1. The Core Problem: KV-Cache Invalidation in Aider

Aider is inherently **disk-aware**. Every turn, Aider scans all files currently loaded via `/add` or `/read`. If any loaded file is modified on disk:
1. Aider re-reads the file from disk and places the updated content into the prompt context.
2. Because the prompt text changes near the top of the context window, the **prefix hash changes completely**.
3. On local inference servers (e.g. `llama-server`, vLLM, SGLang), this causes a **total KV cache bust**. The server must re-evaluate the entire context (often 10,000 to 50,000+ tokens), turning a 1-second conversational turn into a 2-minute GPU stall.

### The Golden Rule of KV-Cache Preservation
* **Immutable Reference Files**: Can safely stay loaded in `/read` because they never mutate.
* **Mutable Target Files**: Should **never** be loaded in `/read` or `/add` during the Architect's reasoning phase. Instead, mutable files should be introduced via the **append-only chat stream** (e.g. `/run cat src/target.py` or through the turn extraction spec).
* **Edits**: Must be offloaded to a separate, headless Editor process (`aider-apply`), allowing the Architect's context prefix to remain 100% byte-identical and warm in GPU VRAM.

---

## 2. Architecture & Execution Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   AIDER-APPLY DATA FLOW                                         │
│                                                                                                 │
│  [Node 1: Architect Session]                                                                    │
│  • Runs interactively in /ask mode (AIDER_ARCHITECT=false, edit_format=ask)                     │
│  • Discusses, refines, and formats SEARCH/REPLACE blocks                                       │
│  • Appends turns to: .aider_factory/sessions/<name>/.aider.chat.history.md                      │
│                                                                                                 │
│                                           │                                                     │
│                                           ▼                                                     │
│  [Turn Extraction & Spec Synthesis: apply_agent.py]                                             │
│  1. Scans .aider.chat.history.md using TOKEN_ANCHOR_RE                                          │
│  2. Filters out tool invocations (/run, /add, /read) and strips thinking tokens (<think>)      │
│  3. Formats the last N turns into: .aider_factory/temp/active_spec.md                           │
│  4. Resolves editor configuration from paired session.yml                                       │
│                                                                                                 │
│                                           │                                                     │
│                                           ▼                                                     │
│  [Node 2: Headless Editor Pass]                                                                 │
│  • Spawns: aider --message-file active_spec.md --edit-format editor-diff <target_files>          │
│  • Redirects chat history to: .aider_factory/temp/.apply.chat.history.md                        │
│  • Modifies target files on disk & creates Git commit                                           │
│                                                                                                 │
│                                           │                                                     │
│                                           ▼                                                     │
│  [Diff Telemetry Stream]                                                                        │
│  • Runs: git --no-pager diff HEAD~1                                                             │
│  • Prints git diff to terminal or streams back into Architect's context                         │
│  • Node 1 Architect resumes with 100% KV-cache reuse (<1.2s prompt eval)!                       │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Key Subsystems

### 3.1 Dual-Anchor Turn Extraction Algorithm (`parse_chat_history`)
Chat history files generated by Aider contain user messages (`#### <prompt>`), assistant answers (`► ANSWER ...`), tool outputs (`> Added ...`), and token usage footers (`> Tokens: ...`). 

`apply_agent.py` uses a resilient **Dual-Anchor Token Parser**:
1. **Primary Anchor**: Locates message boundaries by matching `TOKEN_ANCHOR_RE` (`(?m)^>\s*Tokens:\s*[\d\.]+[kKMG]?\s*sent,\s*[\d\.]+[kKMG]?\s*received.*$`).
2. **Slash-Command Filtering**: Strips out interactive commands like `/add`, `/run`, `/read`, `/drop`, `/model`, and `/clear` while preserving `/ask` prompts.
3. **Thinking Token Stripping**: Regex-cleans `<thinking-content-...>`, `<think>...</think>`, and Aider UI banners (`► ANSWER`), extracting only the actionable specification.
4. **Single vs. Multi-Turn Formatting**:
   - For `turns=1` (default): Synthesizes a clean `# Directive` and `# Specification & Implementation Plan`.
   - For `turns > 1`: Organizes prior discussion chronologically under `## Prior Context Turn N` headers, culminating in the `## Active Directive`.

### 3.2 Paired Session & Config Resolution (`resolve_editor_config`)
`aider-apply` automatically discovers which model and API endpoint to use following a strict precedence hierarchy:
1. Explicit `--model <model_id>` CLI override.
2. `AI_FACTORY_CONFIG` environment variable.
3. Paired session configuration: `.aider_factory/sessions/<session_name>/session.yml`.
4. Workspace configuration: `.aider_factory/.env.yml` or `.env.yml`.
5. Default fallback (`gemini/gemini-2.5-flash`).

It automatically maps `editor_ollama_api` or local endpoints into `OPENAI_API_BASE`, `OLLAMA_API_BASE`, and `LM_STUDIO_API_BASE` for the subprocess.

### 3.3 Session Isolation & Zero History Pollution
To prevent headless editor output from corrupting the active interactive session:
* The subprocess runs with `--no-restore-chat-history`.
* Chat and input history are redirected to ephemeral sandboxes:
  - `.aider_factory/temp/.apply.chat.history.md`
  - `.aider_factory/temp/.apply.input.history`
* The active Architect session's `.aider.chat.history.md` remains clean and unpolluted.

---

## 4. CLI Reference

`aider-apply` is available globally via the terminal or inside an interactive Aider session via `/run aider-apply` (or `/run .aider_factory/bash/apply`).

```bash
aider-apply <files...> [options]
```

### Positional Arguments
* `files` — One or more relative or absolute paths to target files that need to be edited.

### Optional Flags
| Flag | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--spec` | `-s` | `None` | Path to an explicit Markdown specification file (bypasses chat history parsing). |
| `--turns` | `-t` | `1` | Number of recent Architect turns to extract from chat history (e.g. `-t 3` for multi-turn context). |
| `--model` | `-m` | `None` | Override the editor model (e.g. `openai/qwen3.6-27b-90k:LATEST`). |
| `--session` | | `None` | Explicit session name to resolve chat history and `session.yml` from. If omitted, auto-discovers active session by `mtime`. |
| `--no-diff` | | `False` | Suppress printing the `git --no-pager diff HEAD~1` output to stdout after execution. |

---

## 5. Usage Workflows & Examples

### Scenario A: Standard Pair-Programming Handoff
1. Open an interactive session:
   ```bash
   aider-factory my_feature
   ```
2. Discuss the design with the Architect in chat. In Turn 1 and 2, explore the architecture. In Turn 3, ask:
   > *"Output the exact SEARCH/REPLACE blocks to implement `calculate_tax` in `src/calculator.py`."*
3. Apply the spec immediately without leaving the session:
   ```bash
   /run aider-apply src/calculator.py
   ```
4. `aider-apply` executes in ~15 seconds, commits the edit, and prints the git diff.
5. Resume chatting with the Architect. Because `src/calculator.py` was never in `/read`, the Architect evaluates **only the ~400 token delta** in ~1.1 seconds with 100% KV cache hit rate!

### Scenario B: Multi-Turn Context Extraction (`--turns`)
If the implementation details are spread across the last 3 turns of your conversation:
```bash
aider-apply src/math_service.py --turns 3
```

### Scenario C: Standalone Spec File Application
If you have an offline specification or design document (`specs/auth_refactor.md`):
```bash
aider-apply src/auth.py src/user.py --spec specs/auth_refactor.md
```

### Scenario D: Cross-Session Application
Apply edits from a specific background worker session:
```bash
aider-apply src/service.py --session worker_session_2
```
