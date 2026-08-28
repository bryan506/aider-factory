---
name: aider-apply
description: Headless code modification tool that extracts diffs or task specifications from active chat history or specification files and applies them directly to target workspace files using editor-diff mode without invalidating the LLM KV cache.
---

# SKILL: Headless Code Application (`aider-apply`)

`aider-apply` is an isolated execution client that extracts code implementation specifications from active chat history (or a specification file) and applies them directly to target workspace files using Aider's `editor-diff` mode, generating clean Git commits.

---

## Operational Contract & Invariants

1. **Role Boundary & KV-Cache Insulation**: The Architect formulates technical specifications and task plans in chat. File modifications and Git commits are delegated entirely to `aider-apply`. Target files remain out of active `/read` or `/add` chat buffers to maintain immutable prefix cache stability.
2. **Turn Parsing & Artifact Stripping**: `aider-apply` parses conversation turns using token delimiter anchors (`> Tokens: ...`) while automatically stripping reasoning blocks (`<think>`, `<thinking-content-*>`), answer markers (`► **ANSWER**`), and tool noise.
3. **Session Discovery Priority**:
   - Explicit `--session <name>` flag parameter.
   - `AI_FACTORY_SESSION` environment variable.
   - Most recently modified session in `.aider_factory/sessions/`.
   - Root workspace chat history `.aider_factory/.aider.chat.history.md`.
4. **Editor Model & API Routing Resolution**:
   - `AI_FACTORY_CONFIG` environment variable override.
   - Active session configuration (`.aider_factory/sessions/<session>/session.yml`).
   - `.aider_factory/.env.yml` or `.env.yml`.
   - Explicit CLI flag `--model <str>` / `-m <str>`.
   - Fallback default model: `gemini/gemini-2.5-flash` (with `OPENAI_API_BASE` / `OLLAMA_API_BASE` / `LM_STUDIO_API_BASE` endpoint mapping if configured).
5. **Launcher Equivalence**: Callable directly via global `aider-apply` or local bash wrapper `/run .aider_factory/bash/apply`.

---

## Command Reference & Parameter Table

| Flag | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `files...` | | *(Required)* | One or more target files to modify. |
| `--turns <int>` | `-t` | `1` | Number of recent conversation turns to include in the synthesized specification. |
| `--spec <path>` | `-s` | `None` | Path to an explicit Markdown specification file (bypasses chat history). |
| `--model <str>` | `-m` | `None` | Override the editor model (e.g. `openai/qwen2.5-coder:32b`). |
| `--session <str>` | | `None` | Target session name for chat history discovery (auto-discovered if omitted). |
| `--no-diff` | | `False` | Suppress printing the resulting `git --no-pager diff HEAD~1` output to stdout. |

---

## Invocation Syntax

### From Inside an Interactive Aider Session
```bash
# Apply latest Architect turn to a single target file
/run aider-apply src/service.py

# Apply edits across multiple target files
/run aider-apply src/service.py src/utils.py

# Include prior discussion context (last N conversation turns)
/run aider-apply src/service.py --turns 3

# Apply from an explicit Markdown specification document
/run aider-apply src/service.py --spec docs/refactor_plan.md

# Override the editor model for a specific edit
/run aider-apply src/service.py --model openai/qwen2.5-coder:32b

# Target a specific named session and suppress git diff
/run .aider_factory/bash/apply src/service.py --session refactor_v2 --no-diff
```

### From Standard Terminal or Scripts
```bash
# CLI execution targeting active session
aider-apply src/service.py --turns 2

# Autonomous CI/CD execution with explicit spec and custom model
aider-apply src/service.py src/models.py --spec .aider_factory/temp/active_spec.md --no-diff
```

---

## Concrete Execution Pattern

### 1. Specification Pattern (Architect Output)
```markdown
### [Task ID: 001] - Add Healthcheck Endpoint

- **Target File**: `src/service.py`
- **Essential Elements**: `health_status()`, `/health` route
- **Tight Description**: Implement a health check handler returning JSON `{"status": "healthy", "timestamp": time.time()}`.
- **Syntax Example**:

```python
@app.route("/health", methods=["GET"])
def health_status():
    return {"status": "healthy", "timestamp": time.time()}, 200
```
```

### 2. Execution Command
```bash
/run aider-apply src/service.py --turns 1
```

---

## Execution Checklist

- [ ] Ensure Architect outputs complete specifications conforming to `### [Task ID: ...]` before calling `aider-apply`.
- [ ] Specify all affected file paths if the planned diff touches multiple files.
- [ ] Increase `--turns` if the specification spans multiple recent conversation messages.
- [ ] Verify the active session or `--spec` file path before execution.
- [ ] Inspect the returned Git diff output (`git --no-pager diff HEAD~1`) to verify clean application.
