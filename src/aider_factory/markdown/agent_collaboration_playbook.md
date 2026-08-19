# Agent Collaboration Playbook — Deterministic-First Change Protocol

A repeatable protocol for high-success agent-driven code changes. Works for any codebase/task, not just this pipeline. The goal: **never hand back a broken, out-of-spec result.**

## 0. Why this works (the one-line thesis)
Front-load *understanding and agreement*, gate *implementation* behind an explicit spec approval, and prove correctness with checks **independent of the code you changed** — plus always preserve the codebase's load-bearing invariants ("the foundation").

---

## 1. The Six Pillars of Mission-Critical Engineering

Every agent session, harness extension, or pipeline change must honor these six institutional standards:

1. **Strict Process & State Isolation (Zero Blast Radius)**:
   - No task, experiment, or agent turn may bleed state, prompt history, or scratch artifacts into adjacent execution contexts or root directories.
   - Namespacing and explicit parameter passing must enforce zero cross-talk across sessions, branches, or concurrent workers.

2. **Deterministic Reproducibility & Paired Configuration**:
   - Code transformations, agent reasoning, and test executions must be fully replayable.
   - Every execution context must freeze and pair its active configuration, model parameters, and environment state with its generated outputs so any result can be reconstructed.

3. **Immutable Auditability & Dual-Stream Telemetry**:
   - Every decision, LLM call, token expenditure, and subprocess execution must be captured in durable, timestamped audit logs.
   - Raw output streams (stdout/stderr) must be preserved at the OS level without dropping stack traces, buffering latency, or losing runtime diagnostics.

4. **Compute & Context Efficiency (KV-Cache Preservation)**:
   - Context windows and GPU compute are scarce, high-value assets. Prompts must be structured with immutable byte-parity prefixes, append-only delta injection, and deterministic serialization to lock KV-cache reuse.

5. **Air-Gapped Privacy & Local-First Execution**:
   - Proprietary logic, internal data, and code must default to zero external leakage.
   - Systems must be built local-first, seamlessly routing across on-prem, self-hosted, or air-gapped endpoints before ever escalating to external third-party services.

6. **Fail-Closed Verification & Zero Repository Pollution**:
   - Verification must rely on objective, deterministic proof (exit codes, exact substring checks, test suites), never on model self-assessment or fuzzy assumptions.
   - Read-only queries, evaluations, and diagnostic checks must execute in-memory with zero uncommitted repository clutter or disk side effects.
   - End-to-end (E2E) and integration tests must execute physical reality: real subprocesses, live filesystem fixtures, and real OS exit codes. Mocking the system under test in E2E suites is strictly banned.

---

## 2. The contract (establish once, honor always)
- **Find and write down the invariants first.** Every codebase has load-bearing rules ("the car foundation"). Extract them from docs, code comments, and the user. Nothing you add may break them. If none are written, ask the user to confirm the ones you infer.
- **Deterministic-first.** Do with code what code can prove; use an agent/LLM only for genuine judgment. Cheap, provable checks before expensive, fuzzy ones.
- **Minimal-delta, isolation.** Change only what the task needs; gate new behavior so existing paths are provably untouched (mode flags, feature toggles).
- **Objectivity over agreement.** Push back with reasoning when a request is suboptimal or based on a wrong assumption; surface tradeoffs instead of silently complying.

---

## 3. The lifecycle (7 phases)

**Phase 1 — Understand (read before touching).**
- Read the relevant code, the docs, AND the *actual on-disk / runtime state* (not just what docs claim).
- Confirm current behavior with an **independent observation** (e.g., re-derive the truth with different logic than the code uses).
- Restate your understanding back to the user; correct mismatches early.

**Phase 2 — Diagnose root cause (not symptoms).**
- Trace the failure end-to-end to the actual mechanism (e.g., "the critic gets no context," "the loop never re-tests its last edit"), not the surface message.
- Prove the diagnosis (logs, a trace, or a minimal reproduction) before proposing a fix.

**Phase 3 — Spec (propose, don't assume).**
- Present: root cause → proposed design → **tradeoffs** → **explicit open questions**.
- List options (A/B/C) with a recommendation and *why*.
- Enumerate **edge cases** proactively; ask the user to rule on the ambiguous ones.
- Keep a running "loose ends" list; drive it to zero before implementing.

**Phase 4 — Approval gate (hard stop).**
- Draft the **actual diffs + new files in chat** for review *before* writing anything.
- Do not implement until the user approves the spec and the loose ends are closed.

**Phase 5 — Implement (surgical).**
- Make the smallest change that satisfies the approved spec.
- Isolate new behavior behind a discriminator/flag so untouched paths can't regress.
- Prefer reusing existing machinery over adding new subsystems/nodes.

**Phase 6 — Cross-validate (see §4 — the heart of it).**
- Run the full matrix. If any check fails, fix and re-run the *whole* matrix, not just the failed check.

**Phase 7 — Document truthfully (Separation of Concerns).**
- Maintain a strict **Separation of Concerns** in technical documentation:
  - **Master Feature Manuals (`src/aider_factory/markdown/docs/`)**: Every major engine, standalone CLI tool, or protocol (`aider_apply.md`, `terminal_ux_and_linting.md`, etc.) must have its own dedicated, in-depth reference manual.
  - **High-Level Service Manual (`factory_service_manual.md`)**: Preserves global orchestration topology, systemd setup, and cross-cutting invariants.
  - **Agent Skills (`skills/`)**: Concise, agent-facing invocation references.
- Remove/flag obsolete claims; add new knobs. **No hallucinated features** — every documented behavior must map to shipped code.

---

## 4. Validation & testing playbook (how we avoided a broken hand-off)

Run these after **every** change. The theme: **verify with logic independent of the code under test.**

1. **Compile / typecheck everything touched + its dependents.**
   `py_compile` (or the language's build) on all edited files *and* files that import them.

2. **Dry-run the build graph without executing it.**
   If work is expressed as a graph/plan (DAG, task list, migration set), construct it in-memory and *inspect* it (nodes, dependencies, flags) without running side effects. (We import the builder module — it builds at import, real execution is `__main__`-guarded.)

3. **Independent audit of real artifacts.**
   Re-implement the correctness check a *different way* than production code (we parsed anchors with `finditer` when the bug was a `search` blind spot). Assert the invariant holds (e.g., "0 false-positives"). Never verify a bug-fix with code that shares the bug's assumption.

4. **Unit testing (narrow isolation only) vs. End-to-End (strict zero-mock mandate)**:
   - **Unit Tests (Narrow Isolation Only)**: Use monkeypatching strictly for deterministic internal parser checks or hard-to-reach branch logic where external processes cannot run.
   - **End-to-End & Integration Tests (Strict Zero-Mock Mandate)**: NEVER mock the system under test (`subprocess.Popen`, `subprocess.run`, `open`, or CLI entrypoints). E2E tests must execute the real binary/script entry point in temporary directory sandboxes (`tempfile`), stream real telemetry to stdout/stderr, assert on physical on-disk file transformations, and verify real OS return codes (`0`). A test that passes by asserting on mock call counts is a fake pass that hides deadlocks, pipe blocking, and filesystem leakage.

5. **Backward-compatibility matrix.**
   Re-run *every* prior configuration/variant and assert **unchanged** results (task counts, no feature "leakage," identical outputs). A refactor is only safe if the old paths are byte/shape-identical.

6. **Real-artifact smoke test of generated commands.**
   If the code emits a command/query/SQL, run the *actual generated string* once against real data (read-only where possible) to confirm it's well-formed and exits as expected.

7. **Dangling-reference sweep.**
   After a refactor, grep for removed symbols/vars/config keys across the whole repo (and docs) to catch orphans.

8. **Isolation proof.**
   Explicitly assert the untouched mode/path did NOT change (e.g., "review path: flag absent, extra call NOT made").

9. **Secure the test artifacts.**
   When implementing Python logic within a broader orchestration system, extract the functions (e.g., via `ast.parse` or isolated module imports) and build programmatic tests. Maintain these inside a dedicated suite (e.g., `.aider_factory/tests/aider_factory_tests/`) to permanently lock in the invariants. Tests must pass locally before the agent signals completion.

---

## 5. Cross-validation matrix template (fill in per task)

| Check | Command / method | Expected | Result |
|---|---|---|---|
| Compile (edited + dependents) | `<build/compile>` | clean | |
| Graph/plan dry-run (new path) | build-only, inspect | expected nodes/deps/flags | |
| Graph/plan dry-run (each legacy path) | build-only | **unchanged** counts/shape | |
| Independent artifact audit | reimplemented check | invariant holds (0 violations) | |
| Targeted unit test (hard branch) | monkeypatch capture/force | correct output per branch | |
| Isolation proof (untouched path) | monkeypatch spy | no new call / no change | |
| Generated-command smoke test | run the real emitted cmd | exit 0 / well-formed | |
| Dangling refs | grep removed symbols | none | |
| Docs match code | grep old claims | none stale | |
| Secure test artifacts | Add to dedicated suite (e.g. `tests/`) | Suite passes | |

---

## 6. Interaction protocol (what raised the success rate)
- **Clarify before assuming.** When intent is ambiguous, ask — with options and a recommendation, not open-ended.
- **Name the loose ends explicitly** and get a ruling on each; don't bury a decision in an assumption.
- **Show diffs before writing.** The approval gate is where misunderstandings die cheaply.
- **Report honestly and specifically.** State what passed, what changed, what's a known limitation/tradeoff, and what's out of scope. Correct your own earlier overstatements (we downgraded a "correctness fix" to "efficiency" when analysis showed it).
- **Keep the user's mental model intact.** Use their vocabulary; when correcting it, explain the distinction plainly.

---

## 7. Anti-patterns (each one nearly bit us)
- **Mocking the system under test in E2E suites (The "Fake Pass" Trap)**: Replacing real subprocesses, file I/O, or CLI executions with mocks in end-to-end tests only tests your own assumptions. It hides real runtime deadlocks (e.g., non-TTY terminal hangs), silent stream swallowing, and filesystem leakage.
- **Fixing symptoms, not causes** (would've "increased loops" instead of fixing the untested-last-edit).
- **Bolting on a parallel structure** instead of extending the foundation (the reason we removed the redundant `deliberate:` block and unified the escalation).
- **Verifying a fix with the buggy assumption** (the `search` vs `finditer` blind spot).
- **Adding fuzzy/threshold logic** where a provable check exists (precision over recall).
- **Silent behavior changes to shared engines** (we isolated code-mode behavior behind a flag so the review path was provably unaffected).
- **Implementing before the spec is approved / loose ends closed.**
- **Documenting aspirational features** — docs must map to shipped code only.

---

## 8. One-screen checklist
```
[ ] Read code + docs + real runtime state; restate understanding
[ ] Extract/confirm invariants (the foundation)
[ ] Diagnose root cause; prove it
[ ] Write spec: design + tradeoffs + edge cases + open questions
[ ] Drive loose ends to zero; get explicit approval
[ ] Draft diffs/new files in chat BEFORE writing
[ ] Implement minimal-delta, behind an isolation flag
[ ] Cross-validate: compile · dry-run · independent audit · unit(narrow) · zero-mock E2E
    · backward-compat matrix · smoke test · dangling-ref sweep · isolation proof
[ ] Secure test artifacts: embed unit tests into the permanent project suite
[ ] Any failure → fix → re-run WHOLE matrix
[ ] Update docs truthfully (modular docs in markdown/docs/ per separation of concerns); no hallucinated features
[ ] Report: what changed, verified how, known limits, out of scope
```

---




