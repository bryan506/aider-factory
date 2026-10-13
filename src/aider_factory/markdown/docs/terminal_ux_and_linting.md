# Terminal UX, Privacy Controls & Automated Linting

## 1. Executive Overview & Foundational Invariants

The `aider-factory` pipeline enforces strict invariants regarding terminal ergonomics, user privacy, air-gapped security, and automated code quality assurance. In high-throughput, automated, or air-gapped environments, unhandled network telemetry, browser popups, and syntax errors introduced by LLM code edits disrupt workflow continuity.

### The Five Foundational Invariants

1. **Air-Gapped Telemetry & Network Silencing Invariant**: Upstream Aider contacts remote PyPI repositories for update checks, emits telemetry pings to PostHog, and spawns local browser windows to display release history (`https://aider.chat/HISTORY.html`). `aider-factory` permanently silences all outgoing analytics, update checks, desktop alerts, and browser launches at both the configuration level (`.aider.conf.yml`) and CLI invocation level (`--no-analytics`, `--no-check-update`, `--no-show-release-notes`, `--no-notifications`).
2. **Offline Cost & Token Accounting Guarantee**: Blocking telemetry (`analytics: false`) does **NOT** degrade or disable pipeline cost tracking. Token usage (`prompt_tokens`, `completion_tokens`) and financial expenditure ($USD$) are computed 100% offline and locally by reading API response usage metadata in `cost_tracker.py` and aggregating run logs via `aggregate_costs.py` without external network dependency.
3. **Automated Post-Edit Self-Healing Invariant**: Code edits performed by the Editor or Architect agents are immediately passed through automated linting and syntax validation hooks prior to git commit. Non-zero exit codes (syntax violations, linter errors) are captured via standard streams and injected directly into the LLM context, triggering an automated repair cycle capped by `max_aider_loops`.
4. **Stream Isolation & Outer/Inner Aider Protection**: When sub-agents or headless tools (such as `apply_agent.py`) execute within an outer Aider session, noisy terminal output (40–120k tokens of thinking blocks, file echoes, and linter traces) is routed to `/dev/tty` or `CONOUT$` for human visibility while restricting standard stdout to clean git diffs (~3–4k tokens), preventing context window blowup in the outer session.
5. **Cross-Platform Process Lifecycle & Clean Termination**: Subprocess trees (linters, test suites, Aider sessions) are isolated in dedicated process groups (`start_new_session=True`). Timeouts monitored by background watchdog timers trigger recursive tree termination (`kill_proc_tree`) via `os.killpg(pgrp, SIGKILL)` on POSIX and `taskkill /F /T /PID` on Windows, preventing orphaned processes.

---

## 2. System Topology & Lifecycle Flowcharts

### 2.1 Telemetry Isolation & Offline Cost Tracking Topology

```mermaid
graph TD
    A[Aider Engine Launch] --> B{Configuration & CLI Ingestion}
    B --> C[Privacy & Telemetry Silencing Engine]
    
    subgraph Network Isolation Boundary (Air-Gapped)
        C -->|check-update: false / --no-check-update| D[PyPI Update Checks BLOCKED]
        C -->|analytics: false / --no-analytics| E[PostHog Telemetry BLOCKED]
        C -->|show-release-notes: false / --no-show-release-notes| F[Browser Popups BLOCKED]
        C -->|notifications: false / --no-notifications| G[OS Desktop Alerts BLOCKED]
    end

    A --> H[Model Inference API Response]
    
    subgraph Offline Local Cost Accounting Engine
        H -->|Usage Metadata Object| I[cost_tracker.py: litellm_cost_line]
        I -->|Atomic File Dump| J[.oracle_session.json.costs.json]
        I -->|sys.stderr Telemetry Line| K[Timestamped Run Log: .aider_factory/logs/*.log]
        K -->|Post-Run Aggregate Pass| L[aggregate_costs.py: aggregate_log]
        L --> M[Cost Analysis Report: Terminal USD Summary]
    end
```

### 2.2 Post-Edit Automated Linting & Self-Healing Lifecycle

```mermaid
graph TD
    A[Editor Agent Applies Code Edit] --> B{auto_lint Enabled?}
    B -->|false| C[Git Auto-Commit: Commit Changes]
    B -->|true| D{lint_cmd Configured?}
    
    D -->|null / Default| E[Resolve Default Linter via File Extension]
    D -->|Custom String| F[Substitute {file} Parameter]
    
    E --> G[Spawn Linter Subprocess with Watchdog]
    F --> G
    
    G --> H{Linter Exit Code == 0?}
    H -->|Yes: 0 Clean| C
    H -->|No: != 0 Errors| I[Capture Combined stdout & stderr]
    I --> J{Attempt < max_aider_loops?}
    J -->|Yes| K[Wrap Errors in Repair Prompt Context]
    K --> L[Architect/Editor Self-Healing Correction Pass]
    L --> G
    J -->|No: Exhausted| M[Halt Loop & Log Persistent Error]
    M --> N[Defer to Escalation Debate or Human Review]
```

### 2.3 Cross-Platform Stream Redirection & PTY Capture Topology

```mermaid
graph TD
    subgraph Stream Routing Engine
        A1[run_workflow.py / factory_launcher.py] --> B1{Operating System}
        B1 -->|Linux / macOS| C1[OSTee: os.pipe + os.dup2 on fd 1/2]
        B1 -->|Windows| D1[_TeeWriter: Threading RLock Wrapping sys.stdout/stderr]
        C1 --> E1[Live Terminal stdout]
        C1 --> F1[Run Log File: .aider_factory/logs/*.log]
        D1 --> E1
        D1 --> F1
    end

    subgraph Interactive Pair-Programming PTY Capture
        A2[Task: pair_programming=True] --> B2{Platform Dispatch}
        B2 -->|Linux GNU| C2[script -qfe -c cmd .pair_capture.log]
        B2 -->|macOS BSD| D2[script -q .pair_capture.log $SHELL -c cmd]
        B2 -->|Windows| E2[Direct Popen + Python Buffer Tee]
        C2 --> F2[Terminal Interactivity + File Cost Parsing]
        D2 --> F2
        E2 --> F2
    end

    subgraph Outer/Inner Aider Context Isolation
        A3[apply_agent.py] --> B3[Inner Aider Execution: 40-120k Tokens]
        B3 -->|Streaming Mode| C3[/dev/tty or CONOUT$: User Terminal Visibility]
        B3 -->|Final Clean Diff| D3[stdout: Git Diff HEAD~1 HEAD ~3-4k Tokens]
        D3 --> E3[Outer Aider Context Window Preserved]
    end
```

---

## 3. Technical Mechanics & Deep-Dive Logic

### 3.1 Mathematical Formulations & Accounting Metrics

#### Offline Message & Session Cost Formulation
The inference cost of each completion response is derived offline using token usage counts and model pricing tables:
$$\text{Cost}_{\text{message}} = \left( T_{\text{prompt}} \times R_{\text{input}} \right) + \left( T_{\text{completion}} \times R_{\text{output}} \right)$$

Where $T_{\text{prompt}}$ is the count of prompt tokens, $T_{\text{completion}}$ is the count of completion tokens, and $R_{\text{input}}, R_{\text{output}}$ represent the unit rates per token in USD.

Cumulative session cost across $M$ turns is defined as:
$$\text{Cost}_{\text{session}} = \sum_{m=1}^{M} \text{Cost}_{\text{message}, m}$$

#### Total Pipeline Run Cost Aggregation
When `factory_launcher.py` completes execution, `aggregate_costs.py` scans the captured run log using regular expressions, calculating the exact sum across $N$ recorded entries:
$$\text{Cost}_{\text{run}} = \sum_{i=1}^{N} \text{Cost}_{\text{msg}, i}, \quad T_{\text{total\_sent}} = \sum_{i=1}^{N} T_{\text{sent}, i}, \quad T_{\text{total\_recv}} = \sum_{i=1}^{N} T_{\text{recv}, i}$$

#### Metric Token Count Normalization
Token counts in log files and terminal footers are normalized to metric representations via the function $f_{\text{fmt}}(n)$:
$$f_{\text{fmt}}(n) = \begin{cases} 
\left\lfloor \frac{n}{10^6} \right\rfloor \text{M} & \text{if } n \ge 10^7 \\
\frac{n}{10^6} \text{M} & \text{if } 10^6 \le n < 10^7 \\
\left\lfloor \frac{n}{10^3} \right\rfloor \text{k} & \text{if } 10^4 \le n < 10^6 \\
\frac{n}{10^3} \text{k} & \text{if } 10^3 \le n < 10^4 \\
n & \text{if } n < 10^3 
\end{cases}$$

#### 24-Bit ANSI Truecolor Conversion
Hexadecimal color codes defined in YAML are converted to 24-bit Truecolor terminal escape sequences:
$$\text{Hex } \#R_1R_2G_1G_2B_1B_2 \longrightarrow \backslash 033[38;2;R;G;Bm$$
$$\text{where } R = 16 R_1 + R_2, \quad G = 16 G_1 + G_2, \quad B = 16 B_1 + B_2$$

---

### 3.2 Air-Gapped Telemetry Silencing Mechanics

Upstream Aider includes telemetry instrumentation that contacts remote endpoints upon startup and after code edits. `aider-factory` permanently disables these mechanisms:

1. **Configuration Layer**: `.aider.conf.yml` establishes baseline defaults:
   - `check-update: false`: Suppresses HTTP GET calls to PyPI checking for newer package releases.
   - `analytics: false`: Blocks event emission to PostHog analytics servers.
   - `show-release-notes: false`: Prevents invocation of `webbrowser.open()` to display online changelogs.
   - `notifications: false`: Disables notifications via `notify-send` (Linux), `osascript` (macOS), or Windows balloon toasts.
2. **Subprocess Enforcement Layer**: In `orchestrate.py` and `apply_agent.py`, the CLI arguments passed to `subprocess.Popen` explicitly include:
   ```python
   cmd = [
       "aider",
       "--no-check-model-accepts-settings",
       "--no-show-model-warnings",
       "--no-check-update",
       "--no-show-release-notes",
       "--no-notifications",
       "--no-analytics",
       ...
   ]
   ```
3. **Library Silencing Layer**: In `rag_manager.py`, `oracle_agent.py`, and `validator.py`, noisy telemetry and progress bars from downstream ML and HTTP libraries are suppressed prior to import:
   ```python
   os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
   os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
   os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
   os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
   for _n in ("httpx", "urllib3"):
       logging.getLogger(_n).setLevel(logging.WARNING)
   ```

---

### 3.3 Dual-Stream Terminal Teeing Engine (`OSTee` & `factory_launcher.py`)

To ensure real-time terminal monitoring while preserving an identical, unbuffered log file, `run_workflow.py` and `factory_launcher.py` implement dual-stream teeing mechanisms.

#### POSIX Pipe Duplication (`OSTee`)
On Linux and macOS, `OSTee` intercepts output at the operating system file descriptor level (fd 1 for stdout, fd 2 for stderr):
1. Allocates pipe via `os.pipe()` returning read and write file descriptors `(pipe_r, pipe_w)`.
2. Duplicates original stdout and stderr via `os.dup(1)` and `os.dup(2)`.
3. Replaces fd 1 and fd 2 with `pipe_w` using `os.dup2(pipe_w, 1)` and `os.dup2(pipe_w, 2)`.
4. Spawns a background thread reading 4096-byte chunks from `pipe_r`. Each chunk is written directly to the duplicated original terminal fd via `os.write(orig_stdout_fd, data)` and decoded lossy UTF-8 to the log file.

#### Windows `_TeeWriter` Thread-Safe Wrapper
On Windows, where file descriptor duplication on C standard streams is unstable, `OSTee` wraps `sys.stdout` and `sys.stderr` in `_TeeWriter` instances protected by `threading.RLock()`. Every call to `write()` simultaneously writes to the terminal stream and the log file handle followed by `flush()`.

#### Preserving ANSI Colors Across Pipes
When stdout is redirected to a pipe, terminal libraries (such as `rich` used by Aider) default to stripping ANSI escape codes. `factory_launcher.py` explicitly exports:
```python
env["FORCE_COLOR"] = "1"
```
This forces the emitting processes to retain 24-bit Truecolor codes in both the live terminal stream and the written log file.

---

### 3.4 Automated Linting Hook Execution (`auto_lint` & `lint_cmd`)

When an editing task completes, Aider intercepts the modified target files prior to creating a git commit:

1. **Configuration Compilation**: In `orchestrate.py`, `Task.auto_lint` and `Task.lint_cmd` are written into the session-specific `.aider.conf.yml` and exported to the subprocess environment as `AIDER_AUTO_LINT` and `AIDER_LINT_CMD`.
2. **Command Resolution**:
   - If `lint_cmd` is a custom string (e.g. `"ruff check --fix {file}"`), `{file}` is resolved to the relative path of the modified file.
   - If `lint_cmd` is `null`, Aider maps the file extension to the system default linter binary.
3. **Execution & Exit Code Verification**:
   - **Exit Code `0`**: Linter succeeds without error. Aider proceeds directly to git auto-commit.
   - **Exit Code `!= 0`**: Linter reports syntax or formatting errors. Aider aborts the commit, captures stdout and stderr, wraps the trace in a repair block, and prompts the LLM to resolve the errors in an immediate follow-up turn.

#### Supported Language Defaults (`lint_cmd: null`)
| Extension | Detected Language | Default Invoked Linter Binary |
| :--- | :--- | :--- |
| `.py` | Python | `ruff check` $\rightarrow$ `flake8` $\rightarrow$ `black --check` |
| `.js`, `.ts`, `.jsx`, `.tsx` | JavaScript / TypeScript | `eslint` / `prettier --check` |
| `.rs` | Rust | `cargo check` / `cargo clippy` |
| `.go` | Go | `go vet` |
| `.R`, `.rmd` | R | `Rscript -e 'lintr::lint("{file}")'` |

---

### 3.5 Context Isolation in Headless Execution (`apply_agent.py`)

When `apply_agent.py` is invoked inside an active Aider session (via `/run aider-apply <target_file>`), the outer Aider process captures all stdout and stderr from the child process as conversational command output.

If the inner Aider's full conversational trace (file listings, reasoning streams, thinking blocks, ANSI formatting) were written to stdout, **40,000 to 120,000 tokens** would be injected into the outer Aider's context window, degrading reasoning capacity and causing context compaction.

#### The Stream Isolation Solution
1. **Streaming Mode (`--stream`)**: Inner Aider writes verbose output directly to `/dev/tty` (POSIX) or `CONOUT$` (Windows). The user watches the live edit stream in the terminal, but the outer Aider process captures zero tokens.
2. **Stdout Isolation**: Inner Aider's standard output is suppressed. Upon completion, `apply_agent.py` executes:
   ```bash
   git diff --no-color --no-ext-diff HEAD~1 HEAD
   ```
   Only the final unified diff (~3,000–4,000 tokens) is written to stdout. The outer Aider receives the clean diff without token bloat.

---

### 3.6 Cross-Platform Process Tree Termination (`kill_proc_tree`)

When child processes (linters, test suites, or Aider sessions) exceed execution timeouts, standard Python `proc.kill()` terminates only the top-level process or shell, leaving orphaned child or grandchild processes executing in the background.

`env_utils.kill_proc_tree(p)` implements guaranteed recursive termination across POSIX and Windows:
- **POSIX Systems**: Subprocesses are spawned with `start_new_session=True`, creating a dedicated process group. When terminating, `kill_proc_tree` queries the group via `os.getpgid(p.pid)` and sends `signal.SIGKILL` to the entire process group via `os.killpg(pgrp, signal.SIGKILL)`.
- **Windows Systems**: Spawns an external task termination command `taskkill /F /T /PID <pid>`, where `/F` forces termination and `/T` terminates all child processes in the process tree.
- **Resource Cleanup**: Closes all associated standard stream handles (`stdin`, `stdout`, `stderr`) to prevent leaked file descriptors.

---

## 4. Exhaustive CLI & Parameter Reference

### 4.1 Upstream Aider Privacy, Telemetry & Ergonomics Flags

| Flag / Option | Argument Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `--check-update` / `--no-check-update` | Boolean | `--no-check-update` | Toggles PyPI update check at startup. Hardcoded false in pipeline. |
| `--analytics` / `--no-analytics` | Boolean | `--no-analytics` | Toggles PostHog analytics reporting. Hardcoded false in pipeline. |
| `--show-release-notes` / `--no-show-release-notes` | Boolean | `--no-show-release-notes` | Toggles browser launch to online release notes. Hardcoded false in pipeline. |
| `--notifications` / `--no-notifications` | Boolean | `--no-notifications` | Toggles OS desktop notifications. Hardcoded false in pipeline. |
| `--auto-lint` / `--no-auto-lint` | Boolean | `--auto-lint` | Toggles automated linting after code edits. Controlled via `auto_lint`. |
| `--lint-cmd` | String | `null` | Custom shell command for linting. Requires `{file}` placeholder. |
| `--auto-commits` / `--no-auto-commits` | Boolean | `--auto-commits` | Toggles automatic git commits after applying code edits. |
| `--auto-accept-architect` / `--no-auto-accept-architect` | Boolean | `--auto-accept-architect` | Automatically accepts Architect proposals in autonomous mode. |
| `--yes-always` | Boolean | `false` | Automatically answers 'yes' to all interactive confirmation prompts. |
| `--fancy-input` / `--no-fancy-input` | Boolean | `--fancy-input` | Enables prompt-toolkit autocompletion, history, and syntax styling. |
| `--multiline` / `--no-multiline` | Boolean | `--no-multiline` | Toggles multiline input. When false, Enter submits prompt immediately. |
| `--pretty` / `--no-pretty` | Boolean | `--pretty` | Toggles colorized ANSI Markdown output formatting in terminal. |
| `--user-input-color` | Hex String | `#d97706` | Sets 24-bit Truecolor for user prompt headers and commands. |
| `--assistant-output-color` | Hex String | `#38bdf8` | Sets 24-bit Truecolor for assistant response text. |

### 4.2 Pipeline Launcher (`aider-launcher` / `factory_launcher.py`)

| Flag / Argument | Argument Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `[session_name]` | String (Positional) | Auto-generated timestamp | Explicit session identifier for logging and state isolation. |
| `[config_file.yml]` | String (Positional) | `.aider_factory/.env.yml` | Path to pipeline YAML configuration file. |
| `-h`, `--help` | Flag | N/A | Prints help message and usage instructions. |
| `-s`, `--session <name>` | String | N/A | Explicit flag alternative for specifying session identifier. |

### 4.3 Headless Application Agent (`aider-apply` / `apply_agent.py`)

| Flag / Option | Argument Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `files` | List[String] | (Required) | Target files to edit with the generated specification. |
| `--spec`, `-s` | Path | `null` | Explicit path to markdown specification file. |
| `--turns`, `-t` | Integer | `1` | Number of chat history turns to parse from active history file. |
| `--model`, `-m` | String | `null` | Model override for the Editor agent. |
| `--session` | String | `null` | Target session identifier for resolving chat history. |
| `--no-diff` | Flag | `false` | Suppresses git diff output following code modification. |
| `--stream` | Flag | `false` | Streams inner Aider terminal output directly to `/dev/tty` / `CONOUT$`. |

### 4.4 Cost Aggregation Utility (`aggregate_costs.py`)

| Argument | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `<log_path>` | File Path (Positional) | (Required) | Path to pipeline run log file to parse and aggregate. |

### 4.5 Standard Exit Codes

| Exit Code | Meaning | System Behavior |
| :--- | :--- | :--- |
| `0` | Success | Operation completed cleanly; all linter checks and tests passed. |
| `1` | General Error / Linter Failure | Unhandled exception, syntax failure, or test assertion failure. |
| `2` | CLI Usage Error | Invalid command-line arguments, missing paths, or bad parameters. |
| `130` | SIGINT (Ctrl+C) | Process interrupted by user; clean shutdown of child processes. |
| `137` | SIGKILL (Watchdog Timeout) | Process tree forcefully terminated after exceeding execution timeout. |

---

## 5. Configuration Schema & YAML Knobs

### 5.1 Base Privacy & Terminal Ergonomics (`.aider.conf.yml`)

```yaml
# ==============================================================================
# Global Privacy & Telemetry Silencing (.aider.conf.yml)
# ==============================================================================
check-update: false             # Block PyPI update checks on startup (type: bool)
show-release-notes: false       # Block browser opening to release notes (type: bool)
notifications: false            # Disable desktop notification daemons (type: bool)
analytics: false                # Block PostHog telemetry event emission (type: bool)
no-show-model-warnings: true    # Suppress model capabilities warnings (type: bool)

# ==============================================================================
# Terminal Input & Truecolor Ergonomics (.aider.conf.yml)
# ==============================================================================
fancy-input: true               # Enable prompt autocompletion & history (type: bool)
multiline: false                # Single-line Enter submission (type: bool)
user-input-color: "#d97706"     # Dark Orange user prompt styling (type: hex string)
assistant-output-color: "#38bdf8" # Sky Blue assistant streaming text (type: hex string)
pretty: true                    # Enable colorized ANSI Markdown output (type: bool)
```

### 5.2 Pipeline Linting & Subprocess Toggles (`.env.yml`)

```yaml
# ==============================================================================
# Pipeline-Level Automated Linting Configuration (.env.yml)
# ==============================================================================
auto_lint: true                 # Global toggle for post-edit automated linting (type: bool)
lint_cmd: null                  # Global custom linter command string (type: string | null)

# ==============================================================================
# Terminal Color Palette (.env.yml)
# ==============================================================================
colors:
  architect_debate: "#38bdf8"   # Sky Blue ANSI Truecolor for Architect debate turns
  oracle_debate: "#d3869b"      # Soft Rose ANSI Truecolor for Oracle debate turns
  user_input: "#d97706"         # Dark Orange for interactive user prompts
  assistant_output: "#38bdf8"   # Sky Blue for assistant generation text

# ==============================================================================
# Per-Phase Toggles & Overrides (.env.yml)
# ==============================================================================
phases:
  - name: "Phase_0_Implementation"
    enabled: true
    toggles:
      auto_lint: true           # Phase override for automated linting (type: bool)
      lint_cmd: "ruff check --fix {file}" # Phase-specific linter command (type: string)
      auto_commits: true        # Auto-commit clean edits (type: bool)
      auto_accept_architect: true # Bypass confirmation for Architect proposals (type: bool)
      yes_always: true          # Auto-confirm destructive file operations (type: bool)
      suggest_shell_commands: true # Allow Architect to suggest shell executions (type: bool)
      detect_urls: false        # Suppress web URL detection and scraping (type: bool)
      disable_playwright: true  # Suppress headless browser scraping (type: bool)
```

### 5.3 Session-Scoped Compilation Dynamics in `orchestrate.py`

During runtime, `orchestrate.py` resolves phase toggles and dynamically synthesizes a temporary session-scoped configuration file at:
```text
.aider_factory/sessions/<session_name>/.aider.conf.yml
```

The synthesizer dynamically strips ambient history keys (`chat-history-file`, `input-history-file`, `llm-history-file`, `restore-chat-history`) to ensure CLI flags remain the sole authority. It then writes the merged runtime dictionary and passes `--config .aider_factory/sessions/<session_name>/.aider.conf.yml` to the child Aider process.

---

## 6. Telemetry, Diagnostics & Operational Edge Cases

### 6.1 Linter Loop Oscillation & Exhaustion
- **Symptom**: The Editor applies a code diff, the linter reports a formatting/syntax error, the Editor attempts a fix that introduces a different error, creating an infinite repair loop.
- **Root Cause Mechanism**: Cyclic linter rules (e.g. conflicting line-length and docstring formatting rules) or ambiguous imports.
- **Remediation**: The linting loop respects the `max_aider_loops` ceiling in `orchestrate.py`. Once exhausted, the pipeline logs the failure to `.aider_factory/logs/`, marks the task as failed or soft-exhausted, and defers the change to human review or escalation debate without corrupting git history.

### 6.2 Missing Linter Binaries in PATH
- **Symptom**: `auto_lint: true` is enabled with `lint_cmd: null`, but the language default binary (e.g. `ruff`, `eslint`, `cargo`) is not installed in the active environment.
- **Root Cause Mechanism**: Missing virtualenv tools or incomplete host toolchains.
- **Remediation**: Aider logs a non-fatal warning (`Linter binary not found`), bypasses the linting hook, and proceeds to git commit. To enforce a specific binary, configure an absolute path in `lint_cmd` (e.g., `lint_cmd: "/home/user/.cargo/bin/cargo clippy --quiet"`).

### 6.3 TTY Pipe Buffering & ANSI Stripping
- **Symptom**: Running the pipeline under CI/CD or through `tee` causes ANSI escape codes to either disappear entirely or display as raw unescaped characters (`\033[38;2;56;189;248m`).
- **Root Cause Mechanism**: Standard C runtime libraries detect that stdout is not a TTY and disable ANSI formatting or switch to full block buffering (4096 bytes).
- **Remediation**: `factory_launcher.py` exports `FORCE_COLOR=1` prior to spawning child processes. When invoking custom bash wrappers, prefix with `export FORCE_COLOR=1`.

### 6.4 Windows Console Codepage 1252 Crashes
- **Symptom**: `UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'` on Windows command prompts.
- **Root Cause Mechanism**: Windows console streams default to legacy code page 1252 instead of UTF-8.
- **Remediation**: All entrypoints reconfigure standard streams at initialization:
  ```python
  if hasattr(sys.stdout, "reconfigure"):
      sys.stdout.reconfigure(encoding="utf-8", errors="replace")
  if hasattr(sys.stderr, "reconfigure"):
      sys.stderr.reconfigure(encoding="utf-8", errors="replace")
  ```
  Set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` in the environment.

### 6.5 Platform-Specific PTY Invocation Discrepancies
- **Symptom**: Interactive pair-programming fails to launch or crashes with invalid argument errors on macOS or Windows.
- **Root Cause Mechanism**: The UNIX `script` command has incompatible syntax across BSD (macOS) and GNU (Linux), while Windows lacks a native PTY command.
- **Remediation**: `orchestrate.py` dispatches execution based on `sys.platform`:
  - **Linux (GNU)**: `script -qfe -c "<cmd>" <capture_log>`
  - **macOS (BSD)**: `script -q <capture_log> $SHELL -c "<cmd>"`
  - **Windows**: Executes direct `subprocess.Popen` with a background thread teeing stdout to the capture file.

### 6.6 Outer Aider Context Window Pollution
- **Symptom**: Using `/run aider-apply` inside an interactive session rapidly consumes 50k+ tokens, degrading reasoning.
- **Root Cause Mechanism**: Standard stdout of child processes is captured into the parent Aider's conversation context.
- **Remediation**: Run `aider-apply` with `--stream`, which writes verbose execution traces to `/dev/tty` / `CONOUT$` and emits only the clean git diff to stdout.

### 6.7 Process Tree Timeouts & Zombie Subprocesses
- **Symptom**: A stuck linter or test suite hangs the pipeline indefinitely; standard `proc.kill()` leaves orphaned child processes running.
- **Root Cause Mechanism**: Standard process termination signals only kill the direct parent shell, leaving grandchild processes running.
- **Remediation**: The pipeline spawns all processes with `start_new_session=True` and applies recursive tree termination via `env_utils.kill_proc_tree(p)`:
  ```python
  def kill_proc_tree(p) -> None:
      if sys.platform == "win32":
          subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], check=False)
      else:
          pgrp = os.getpgid(p.pid)
          os.killpg(pgrp, signal.SIGKILL)
  ```
