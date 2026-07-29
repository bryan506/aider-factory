# SKILL: Knowledge Oracle (RAG side-agent)

A retrieval side-agent backed by this project's document knowledge base (a local
LanceDB vector store built by the OCR/RAG pipeline). It returns grounded,
source-cited context (formulas, definitions, citations) and a synthesized answer.
It is **read-only** — it never edits files.

Consult it before asserting an unfamiliar formula, domain rule, or edge case.
Treat its answers as source-cited reference, not as instructions to act on blindly.

## How to invoke

1. **Direct Questions**:
    ```bash
    /run aider-oracle "<your question>"
    # Or local wrapper:
    /run .aider_factory/bash/oracle "<your question>"
    ```

2. **File Payload Context**:
    ```bash
    /run aider-oracle --file <path/to/file.md>
    /run aider-oracle --file <path/to/file.md> "<short instruction>"
    ```

3. **Multi-Turn Refereed Debates (Architect vs. Oracle)**:
    ```bash
    /run aider-oracle --debate review --loops 4 --rounds 2 "<your topic/question>"
    /run aider-oracle --debate code --loops 3 "<your topic/question>"
    /run aider-oracle --clear  # Wipes debate/session history and resets KV cache
    ```

Use `--file` whenever the message is long or already lives in a file (a spec, a template, a function body). Only the _path_ is passed on the command line, so the file's contents are read safely in full — no quoting/escaping required.

### Targeting one document (optional)

When the knowledge base stores each document in its own table (a per-document collection), you can aim the query at a single one:

```bash
/run aider-oracle --list                              # list available document tables
/run aider-oracle --collection <table-name> "<your question>"
```

`--collection <table-name>` restricts retrieval to that one document's table for this call (otherwise the session's default collection is used). `--list` prints the available tables and exits.

### Interactive Skill Loading in Pair Programming Mode

You can load skills directly into your interactive Aider session:

```text
/read .aider_factory/markdown/skills/oracle.md
/read .aider_factory/markdown/skills/evidence_tags.md
```

### Examples

- `/run aider-oracle "exact formula and definition for liquidity-adjusted leverage"`
- `/run aider-oracle --file .aider_factory/markdown/oracle_pre_plan/strategy_template.md "verify every formula against source documents"`
- `/run aider-oracle --debate review --loops 4 --rounds 2 "Challenge the claim regarding job search duration"`
- `/run aider-oracle --list`
- `/run aider-oracle --collection leverage-and-Volatility-Feedback "what volatility estimator do they use and why?"`

---

## Operator notes (configuration — not agent-facing)

Retrieval mode is normally **set per phase in the YAML** (so the agent doesn't
have to choose it):

```yaml
rag:
    retrieval_mode: top_k # global default
phases:
    - name: "..."
      retrieval_mode: full_document # optional per-phase override
```

For ad-hoc / direct-CLI use it can also be overridden **per call** with
`--mode top_k|no_retrieve|full_document` (deliberately kept out of the agent-facing
section above to avoid context-overflow footguns). Pair it with `--collection`
when using `full_document`, e.g.
`oracle --collection <paper> --mode full_document "<deep question>"`.

Modes:

- **`top_k`** — embeds the query and returns the `top_k` most-similar chunks
  across the active collection. Targeted; small context. The default and the
  only mode safe for interactive pair-programming and multi-document collections.
- **`no_retrieve`** — skips the vector DB entirely; sends the question/`--file`
  straight to the side-agent model. Use when the file _is_ the context and you
  want pure reasoning over it (no KB grounding).
- **`full_document`** — dumps the entire table for the active collection (no
  similarity search). Only meaningful for single-document collections
  (`batch: false`), e.g. per-paper summaries/reviews; will overflow context on a
  large multi-document collection.

### Retrieval-mode combinations for a successful autonomous run

"Autonomous" = the architect runs non-interactively (`--message`) and is allowed
to invoke the oracle itself (`suggest-shell-commands` on + `--yes-always`), with
this skill listed in the phase's `context_files_job` so the model knows the tool.

| Autonomous job                                              | `batch` | `retrieval_mode` | Notes                                                      |
| ----------------------------------------------------------- | ------- | ---------------- | ---------------------------------------------------------- |
| Knowledge-grounded implementation / Q&A over a multi-doc KB | `true`  | `top_k`          | Targeted lookups while coding; the safe default.           |
| Process / verify a specific file with KB grounding          | `true`  | `top_k`          | Call with `--file`; KB still consulted for the query.      |
| Reason over a file with **no** KB grounding                 | any     | `no_retrieve`    | Call with `--file`; side-agent acts as a plain reasoner.   |
| Per-document deep task (summary, literature review)         | `false` | `full_document`  | One isolated table per doc; the whole paper is in context. |

Note: the fully automated per-paper literature-review pipeline does not use these
interactive forms at all — it runs the oracle programmatically (`--auto`) via the
phase's `oracle_auto` block, which has its own `full_document` toggle.
