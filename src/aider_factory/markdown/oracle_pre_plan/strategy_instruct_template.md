# Phase-0 Plan — Build the Strategy Template from the Knowledge Base

You are the **architect** in an interactive RAG session. A local vector knowledge
base (LanceDB) has already been built from the documents in this phase's collection.

## Your tool: the Knowledge Oracle

Query it with a shell command (it prints grounded snippets + a synthesized answer):

```
/run .aider_factory/bash/oracle "<your question>"
```

Examples:

- `/run .aider_factory/bash/oracle "exact formula and definition for liquidity-adjusted leverage"`
- `/run .aider_factory/bash/oracle "edge cases and input ranges for the leverage feature"`

The oracle is grounded **only** in the ingested documents and cites the source file.
Consult it before asserting any formula or domain rule.

## Objective

Produce a single, self-contained **source-of-truth template** at
`.aider_factory/markdown/oracle_pre_plan/strategy_template.md` that downstream implementation phases
will read automatically (via `sticky_context`). It must contain:

1. **Scope** — what is being implemented/refactored and why.
2. **Definitions & formulas** — exact, oracle-sourced, with the source file cited.
3. **Inputs / outputs** — names, types, units, valid ranges.
4. **Edge cases & constraints** — boundary behavior, error handling expectations.
5. **Acceptance criteria** — concise, testable statements.

## Workflow

1. Ask the oracle targeted questions to extract the formulas/rules you need.
2. Draft `strategy_template.md` from the oracle's grounded answers (no hallucinated math).
3. Keep it tight and factual — this is a blueprint, not prose.
4. When satisfied, exit the session (`/exit` or Ctrl-C) to advance to the next phase.
