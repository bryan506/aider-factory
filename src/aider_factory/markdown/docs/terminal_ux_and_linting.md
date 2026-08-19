# Terminal UX, Privacy Controls & Automated Linting

This guide documents the configuration options in `.aider.conf.yml` and `.env.yml` governing terminal ergonomics, privacy, telemetry silencing, and automated linting hooks.

---

## 1. Privacy, Telemetry & Browser Popup Silencing

By default, upstream Aider contacts remote PyPI repositories to check for updates and spawns external browser windows with release notes. In air-gapped, high-throughput, or automated environments, these network pings and popups interrupt workflows.

`aider-factory` configures a complete silencing baseline in `src/aider_factory/default_configs/aider.conf.yml`:

```yaml
# Global Automation & Silence Settings
check-update: false             # Disable network calls to PyPI on launch
show-release-notes: false       # Permanently block browser popups to https://aider.chat/HISTORY.html
notifications: false            # Disable OS-level desktop notification pings
analytics: false                # Block anonymous PostHog telemetry pings to external servers
no-show-model-warnings: true    # Suppress verbose terminal warnings on non-standard model prefixes
```

### Why Disabling Telemetry Does NOT Affect Costs or Token Counts
Setting `analytics: false` only blocks external HTTP pings to PostHog. All token counting and financial cost metrics are computed **100% locally and offline**:
* **Token Usages**: Read directly from LiteLLM and model API response objects (`resp.usage.prompt_tokens` / `completion_tokens`).
* **Cost Accounting**: Handled offline by `cost_tracker.py` and `aggregate_costs.py`.
* **Auditability**: Complete request histories are logged locally to `.aider_factory/logs/` and `.aider.llm.history`.

---

## 2. Terminal Input Ergonomics

Configure input behavior under `.aider.conf.yml`:

```yaml
fancy-input: true               # Enable rich prompt formatting, command auto-completion, and history scrolling
multiline: false                # When false, hitting Enter submits immediately; Esc+Enter creates a new line
user-input-color: "#d97706"     # Changes user prompt text, file listings, and command prompts (Dark Orange)
assistant-output-color: "#38bdf8" # Streaming model text color (Sky Blue)
pretty: true                    # Enable colorized ANSI Markdown output
```

### Multiline Input Controls
* `multiline: false` (Recommended): Pressing `Enter` sends the prompt. To insert a newline, press `Esc` then `Enter`, or paste multiline text directly.
* `multiline: true`: Pressing `Enter` adds a newline; pressing `Meta+Enter` (or `Alt+Enter`) submits the message.

---

## 3. Automated Linting Integration (`auto_lint` & `lint_cmd`)

`aider-factory` supports native post-edit linting and formatting hooks. When enabled, Aider automatically runs your linter immediately after applying code edits, injecting any syntax or linting errors back into the context so the model can heal them before committing.

### Configuration in `.env.yml`
```yaml
# Top-level settings in .env.yml
auto_lint: true                 # Automatically execute linting after edits
lint_cmd: null                  # Custom linter command; null uses language defaults
```

### Supported Language Defaults
When `lint_cmd` is `null` and `auto_lint: true`, Aider invokes standard linters based on the modified file types:
* **Python**: `flake8`, `black --check`, or `ruff`
* **JavaScript / TypeScript**: `eslint`, `prettier`
* **Rust**: `cargo check`
* **Go**: `go vet`
* **R**: `styler`, `lintr`

### Custom Linter Examples
```yaml
# Python with Ruff
lint_cmd: "ruff check --fix {file}"

# R with lintr
lint_cmd: "Rscript -e 'lintr::lint(\"{file}\")'"

# Rust
lint_cmd: "cargo clippy --quiet"
```
