# Agent Collaboration Playbook — Deterministic-First Change Protocol

A repeatable protocol for high-success agent-driven code changes. Works for any codebase/task, not just this pipeline. The goal: **never hand back a broken, out-of-spec result.**

## 0. Why this works (the one-line thesis)
Front-load *understanding and agreement*, gate *implementation* behind an explicit spec approval, and prove correctness with checks **independent of the code you changed** — plus always preserve the codebase's load-bearing invariants ("the foundation").

---

## 1. The contract (establish once, honor always)
- **Find and write down the invariants first.** Every codebase has load-bearing rules ("the car foundation"). Extract them from docs, code comments, and the user. Nothing you add may break them. If none are written, ask the user to confirm the ones you infer.
- **Deterministic-first.** Do with code what code can prove; use an agent/LLM only for genuine judgment. Cheap, provable checks before expensive, fuzzy ones.
- **Minimal-delta, isolation.** Change only what the task needs; gate new behavior so existing paths are provably untouched (mode flags, feature toggles).
- **Objectivity over agreement.** Push back with reasoning when a request is suboptimal or based on a wrong assumption; surface tradeoffs instead of silently complying.

---

## 2. The lifecycle (7 phases)

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

**Phase 6 — Cross-validate (see §3 — the heart of it).**
- Run the full matrix. If any check fails, fix and re-run the *whole* matrix, not just the failed check.

**Phase 7 — Document truthfully.**
- Update the user-facing config reference and the operator manual to match reality.
- Remove/flag obsolete claims; add new knobs. **No hallucinated features** — every documented behavior must map to shipped code.

---

## 3. Validation & testing playbook (how we avoided a broken hand-off)

Run these after **every** change. The theme: **verify with logic independent of the code under test.**

1. **Compile / typecheck everything touched + its dependents.**
   `py_compile` (or the language's build) on all edited files *and* files that import them.

2. **Dry-run the build graph without executing it.**
   If work is expressed as a graph/plan (DAG, task list, migration set), construct it in-memory and *inspect* it (nodes, dependencies, flags) without running side effects. (We import the builder module — it builds at import, real execution is `__main__`-guarded.)

3. **Independent audit of real artifacts.**
   Re-implement the correctness check a *different way* than production code (we parsed anchors with `finditer` when the bug was a `search` blind spot). Assert the invariant holds (e.g., "0 false-positives"). Never verify a bug-fix with code that shares the bug's assumption.

4. **Targeted unit tests via monkeypatch** for hard-to-reach paths.
   Replace external calls (`subprocess.run`/`Popen`, network, model calls) with fakes to (a) capture what the code *would* send (prompt/args contain X), and (b) force specific branches (final-check pass → SUCCESS; fail → FAILED). Cheap, deterministic, no live models.

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

## 4. Cross-validation matrix template (fill in per task)

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

## 5. Interaction protocol (what raised the success rate)
- **Clarify before assuming.** When intent is ambiguous, ask — with options and a recommendation, not open-ended.
- **Name the loose ends explicitly** and get a ruling on each; don't bury a decision in an assumption.
- **Show diffs before writing.** The approval gate is where misunderstandings die cheaply.
- **Report honestly and specifically.** State what passed, what changed, what's a known limitation/tradeoff, and what's out of scope. Correct your own earlier overstatements (we downgraded a "correctness fix" to "efficiency" when analysis showed it).
- **Keep the user's mental model intact.** Use their vocabulary; when correcting it, explain the distinction plainly.

---

## 6. Anti-patterns (each one nearly bit us)
- **Fixing symptoms, not causes** (would've "increased loops" instead of fixing the untested-last-edit).
- **Bolting on a parallel structure** instead of extending the foundation (the reason we removed the redundant `deliberate:` block and unified the escalation).
- **Verifying a fix with the buggy assumption** (the `search` vs `finditer` blind spot).
- **Adding fuzzy/threshold logic** where a provable check exists (precision over recall).
- **Silent behavior changes to shared engines** (we isolated code-mode behavior behind a flag so the review path was provably unaffected).
- **Implementing before the spec is approved / loose ends closed.**
- **Documenting aspirational features** — docs must map to shipped code only.

---

## 7. One-screen checklist
```
[ ] Read code + docs + real runtime state; restate understanding
[ ] Extract/confirm invariants (the foundation)
[ ] Diagnose root cause; prove it
[ ] Write spec: design + tradeoffs + edge cases + open questions
[ ] Drive loose ends to zero; get explicit approval
[ ] Draft diffs/new files in chat BEFORE writing
[ ] Implement minimal-delta, behind an isolation flag
[ ] Cross-validate: compile · dry-run · independent audit · unit(monkeypatch)
    · backward-compat matrix · smoke test · dangling-ref sweep · isolation proof
[ ] Secure test artifacts: embed unit tests into the permanent project suite
[ ] Any failure → fix → re-run WHOLE matrix
[ ] Update docs truthfully; no hallucinated features
[ ] Report: what changed, verified how, known limits, out of scope
```

---




