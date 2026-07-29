#!/usr/bin/env python3
# orchestrate.py

import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Terminal colors for debate turns (24-bit truecolor). Configurable via the pipeline
# YAML `colors:` block; run_workflow.py sets the env vars at startup. Hardcoded
# defaults match the original values: architect teal #38bdf8, oracle rose #d3869b.
_ARCH_COLOR = os.environ.get("PIPELINE_COLOR_ARCHITECT", "\033[38;2;56;189;248m")
_ORACLE_COLOR = os.environ.get("PIPELINE_COLOR_ORACLE", "\033[38;2;211;134;155m")
_RESET = "\033[0m"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    message_file: Optional[str] = None
    iterate_file: Optional[str] = None
    files: list[str] = field(default_factory=list)
    read_files: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)

    # Model Routing
    model: str = "openai/minimax-179b-80k:latest"
    editor_model: str = "ollama/qwen3-coder-64k:latest"
    fallback_editor_model: Optional[str] = None  # Escalation model for attempt > 0
    architect_api_base: Optional[str] = "http://localhost:11435/v1"
    editor_api_base: Optional[str] = "http://localhost:11434"

    status: TaskStatus = TaskStatus.PENDING
    test_cmd: Optional[str] = None
    iterate_test: bool = False
    max_aider_loops: int = 1
    auto_test: bool = False  # Toggle to leverage Aider's 3-loop default behavior
    pair_programming: bool = False  # Interactive mode
    rag_env: dict = field(default_factory=dict)  # Extra env for /run oracle (ORACLE_*)
    ocr_ingest: Optional[dict] = (
        None  # If set, run rag_manager.ingest(**ocr_ingest) first
    )
    oracle: Optional[dict] = (
        None  # If set, run oracle_agent --auto (no Aider): {template, out, full_document}
    )
    validate: Optional[dict] = (
        None  # If set, run Tier-1 evidence audit (no Aider): {review, source, report, tag, threshold}
    )
    skip_aider: bool = (
        False  # Setup-only node (ingest / oracle programmatic job); never launch Aider
    )
    deliberate: Optional[dict] = (
        None  # If set, run a two-party Oracle<->Architect debate (ask mode, no edits)
    )
    verdict_gate: Optional[str] = (
        None  # Edit node self-gate: act only if this verdict file is actionable
    )
    soft_fail: bool = False  # Apply node: loop exhaustion is a soft success (a downstream finalize is the authority)
    final_check: bool = False  # Code apply: after the iterate loop, re-run test_cmd ONCE and return its true pass/fail (the loop never verifies its own last edit; code mode has no finalize authority)


class AiderFactory:
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.tasks: dict[str, Task] = {}
        self.last_test_result: dict[str, bool] = {}

    def add_task(self, task: Task):
        self.tasks[task.id] = task

    def dependencies_met(self, task: Task) -> bool:
        # Allow the pipeline to continue even if a previous phase/job for this file failed.
        # This ensures the "Factory" attempts every configured job in the YAML sequence.
        return all(
            self.tasks[dep].status in [TaskStatus.SUCCESS, TaskStatus.FAILED]
            for dep in task.depends_on
        )

    def _run_oracle_job(self, task: Task) -> bool:
        """Run oracle_agent.py in programmatic job mode via the bash wrapper (which uses
        the aider venv interpreter that has litellm/lancedb). Failure is non-fatal so the
        remaining per-document jobs still run; the task is just marked FAILED."""
        job = task.oracle or {}
        oracle = os.path.join(self.project_dir, ".aider_factory", "bash", "oracle")
        if not os.path.exists(oracle):
            oracle = "aider-oracle"

        # Reuse an existing output instead of re-running the oracle job (e.g.
        # when iterating on the downstream validation/fix loop only). No model call
        # if the file already exists.
        _out = job.get("out")
        if (
            not job.get("redo", True)
            and _out
            and os.path.isfile(_out)
            and os.path.getsize(_out) > 0
        ):
            log.info(
                f"♻️  ORACLE JOB [{task.id}] reuse existing {_out} "
                f"(redo_oracle_job=false); skipping model call."
            )
            return True

        # Merge: real environment + the phase's ORACLE_* routing + the programmatic job vars.
        env = os.environ.copy()
        if task.rag_env:
            env.update(task.rag_env)
        env["ORACLE_JOB"] = "1"
        if job.get("template"):
            env["ORACLE_JOB_TEMPLATE"] = str(job["template"])
        if job.get("out"):
            env["ORACLE_JOB_OUT"] = str(job["out"])
        if job.get("read_files"):
            env["ORACLE_JOB_READ_FILES"] = "\x1e".join(
                job["read_files"]
            )  # use record separator to be safe with spaces
        env["ORACLE_JOB_FULLDOC"] = "1" if job.get("full_document", True) else "0"

        log.info(
            f"🔮 ORACLE JOB [{task.id}] -> collection "
            f"'{env.get('ORACLE_COLLECTION')}' -> {job.get('out')}"
        )
        try:
            proc = subprocess.run([oracle], env=env, cwd=self.project_dir)
        except Exception as e:
            log.error(f"❌ ORACLE JOB EXCEPTION [{task.id}]: {e} (continuing)")
            return False
        if proc.returncode == 0:
            log.info(f"✅ TASK SUCCESS [{task.id}] (oracle job)")
            return True
        log.error(
            f"⚠️  ORACLE JOB failed [{task.id}] (rc={proc.returncode}) (continuing)"
        )
        return False

    def _run_validate(self, task: "Task") -> bool:
        """Evidence grounding audit (deterministic, no Aider). Runs the auditor via
        the bash/validate wrapper. The audit always SUCCEEDS
        as a DAG node — any ungrounded quotes are recorded in the report, which the
        Tier-2 (post_validate) task keys off. Non-fatal on error."""
        v = task.validate or {}
        validate = os.path.join(self.project_dir, ".aider_factory", "bash", "validate")
        if not os.path.exists(validate):
            validate = "aider-validate"
        env = os.environ.copy()
        if task.rag_env:
            env.update(task.rag_env)
        cmd = [
            validate,
            "--file",
            str(v.get("review", "")),
            "--source",
            str(v.get("source", "")),
            "--report",
            str(v.get("report", "")),
            "--tag",
            str(v.get("tag", "evidence")),
        ]
        if v.get("finalize"):
            # Deterministic terminal step: agreed-ungrounded [tag] -> [unsupported].
            cmd.append("--finalize-unsupported")
            if v.get("baseline_ledger"):
                cmd += ["--baseline-ledger", str(v["baseline_ledger"])]
        elif v.get("autofix"):
            # Deterministic anchored-stitch repair, then write the strict residual report.
            cmd.append("--autofix")
            if v.get("db"):
                cmd += ["--db", str(v["db"])]
            if v.get("collection"):
                cmd += ["--collection", str(v["collection"])]
            if v.get("region_threshold") is not None:
                cmd += ["--region-threshold", str(v["region_threshold"])]
            if v.get("region_margin") is not None:
                cmd += ["--region-margin", str(v["region_margin"])]
            if v.get("top_k") is not None:
                cmd += ["--top-k", str(v["top_k"])]
        else:
            cmd += ["--threshold", str(v.get("threshold", 0.90))]
        _label = (
            "🏁 FINALIZE"
            if v.get("finalize")
            else "🪡 AUTOFIX"
            if v.get("autofix")
            else "🔎 EVIDENCE AUDIT"
        )
        _dest = (
            v.get("review")
            if (v.get("finalize") or v.get("autofix"))
            else v.get("report")
        )
        log.info(f"{_label} [{task.id}] -> {_dest}")
        try:
            subprocess.run(cmd, env=env, cwd=self.project_dir)
            log.info(f"✅ TASK SUCCESS [{task.id}] (evidence audit)")
        except Exception as e:
            # The auditor couldn't run (missing/non-exec wrapper, etc.). Still
            # non-fatal for the DAG, but don't claim SUCCESS — log it honestly.
            log.error(f"⚠️  EVIDENCE AUDIT error [{task.id}]: {e} (continuing)")
        # Audit is always a 'done' DAG node: any ungrounded quotes live in the
        # report, which the Tier-2 task keys off. A crash leaves no report (no gate).
        return True

    # ---- Two-party deliberation (Oracle <-> Architect debate, refereed) ---------

    def _extract_assistant_text(self, raw: str) -> str:
        """Strip aider's banner/footer chrome from captured stdout. The PROPOSAL /
        VERDICT lines are parsed from the full text regardless, so this is cosmetic."""
        if not raw:
            return ""
        noise = (
            "Aider v",
            "Main model:",
            "Editor model:",
            "Weak model:",
            "Git repo:",
            "Repo-map:",
            "Added",
            "Tokens:",
            "Cost:",
            "Warning:",
            "Scraping",
            "For more info",
            "Use /help",
            "Commit",
            "Committing",
            "─",
            "►",
            "▸",
        )
        keep = [
            ln
            for ln in raw.splitlines()
            if not any(ln.strip().startswith(p) for p in noise)
        ]
        return "\n".join(keep).strip()

    def _strip_thinking(self, text: str) -> str:
        """Remove the model's reasoning/thinking block from CAPTURED text (so the oracle
        and the transcript don't pay for it). Live streaming still shows it on-screen.

        aider's reasoning tag is the fixed string thinking-content-<hash>; its close is
        usually RENDERED as the '► **ANSWER**' marker rather than a literal tag, so we cut
        on that marker (everything after it is the answer, which carries the PROPOSAL).
        Safe: if there's no reasoning marker, the text is returned unchanged."""
        if not text:
            return text
        try:
            from aider.reasoning_tags import REASONING_TAG, remove_reasoning_content

            text = remove_reasoning_content(
                text, REASONING_TAG
            )  # literal <tag>...</tag> cases
        except Exception:
            pass
        # Rendered boundary: keep everything AFTER the ANSWER marker (the answer + PROPOSAL).
        m = re.search(r"►\s*\*{0,2}ANSWER\*{0,2}", text)
        if m:
            text = text[m.end() :]
        # Drop any leftover opening reasoning-tag line.
        text = re.sub(r"(?m)^.*<thinking-content-[0-9a-fA-F]+>.*$", "", text)
        return text.strip()

    def _aider_ask_turn(
        self,
        task: "Task",
        message: str,
        read_files: list,
        label: str = "",
        history_file: str = None,
    ) -> str:
        """One architect turn in ASK mode: no edits, no shell, no commits. STREAMS the
        turn live to the terminal while capturing it. The global config's architect:true
        is overridden per-invocation via AIDER_ARCHITECT=false + --edit-format ask.

        Streaming is stdout-only (observability); it is NOT added to any model context."""
        root = str(self.project_dir)

        # Resolve config paths: prioritize .aider_factory/ then fall back to root
        local_aider_factory_conf = os.path.join(root, ".aider_factory", ".aider.conf.yml")
        aider_conf = (
            local_aider_factory_conf
            if os.path.exists(local_aider_factory_conf)
            else os.path.join(root, ".aider.conf.yml")
        )

        local_aider_factory_settings = os.path.join(
            root, ".aider_factory", ".aider.model.settings.yml"
        )
        aider_settings = (
            local_aider_factory_settings
            if os.path.exists(local_aider_factory_settings)
            else os.path.join(root, ".aider.model.settings.yml")
        )

        cmd = [
            "aider",
            "--config",
            aider_conf,
            "--model-settings-file",
            aider_settings,
            "--no-check-model-accepts-settings",
            "--no-show-model-warnings",
            "--model",
            task.model,
            "--edit-format",
            "ask",  # ask coder: cannot edit or run shell
            "--no-auto-commits",
            "--no-pretty",
            "--no-suggest-shell-commands",
            "--no-detect-urls",
            "--yes-always",
            "--auto-accept-architect",
            "--map-tokens",
            "0",
            "--map-refresh",
            "manual",
            "--map-multiplier-no-files",
            "0",
            "--max-chat-history-tokens",
            "1000000",
            "--message",
            message,
        ]
        if history_file:
            cmd.extend(["--restore-chat-history", "--chat-history-file", history_file])

        for rf in read_files or []:
            if not rf:
                continue
            full = rf if os.path.isabs(rf) else os.path.join(self.project_dir, rf)
            if os.path.exists(full):
                cmd.extend(["--read", rf])
        env = os.environ.copy()
        env["AIDER_ARCHITECT"] = "false"  # override config architect:true for this turn
        env["PYTHONHASHSEED"] = (
            "0"  # Ensure deterministic set iteration for perfect prefix caching
        )
        if task.architect_api_base:
            env["OPENAI_API_BASE"] = task.architect_api_base
            env["OPENAI_API_KEY"] = "sk-dummy"
        if task.editor_api_base:
            env["OLLAMA_API_BASE"] = task.editor_api_base
            env["LM_STUDIO_API_BASE"] = task.editor_api_base
            env["LM_STUDIO_API_KEY"] = "sk-dummy"
        print(f"\n{_ARCH_COLOR}┌── architect {label} ──", flush=True)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=self.project_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            print(f"└──{_RESET}", flush=True)
            return f"PROPOSAL: (architect turn failed: {e})"
        chars = []
        try:
            if proc.stdout:
                while True:
                    ch = proc.stdout.read(1)
                    if not ch and proc.poll() is not None:
                        break
                    if ch:
                        # Color escapes are print-only; never appended to `chars`, so the
                        # captured value (parsing/_strip_thinking) stays byte-identical.
                        print(ch, end="", flush=True)
                        chars.append(ch)
                proc.stdout.close()
            proc.wait()
            print(f"\n└──{_RESET}", flush=True)
        finally:
            # Belt-and-suspenders: never leave the terminal stuck in the architect color.
            print(_RESET, end="", flush=True)
        # Live stream showed the raw turn; the CAPTURED value drops the reasoning block
        # (saves oracle tokens + keeps the transcript clean) while preserving the PROPOSAL.
        return self._extract_assistant_text(self._strip_thinking("".join(chars)))

    def _gate_run(self, task: "Task", gate_cmd: str):
        """Run the deterministic gate; return (passed, combined_output)."""
        env = {**os.environ, **(task.rag_env or {})}
        try:
            p = subprocess.run(
                gate_cmd,
                shell=True,
                cwd=self.project_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            passed = (p.returncode == 0)
            self.last_test_result[gate_cmd] = passed
            return passed, p.stdout or ""
        except Exception as e:
            self.last_test_result[gate_cmd] = False
            return False, f"(gate error: {e})"

    def _oracle_turn(
        self,
        task: "Task",
        d: dict,
        arch_text: str,
        turn: int,
        label: str = "",
        pre_assess_prompt: str = None,
    ) -> str:
        """One oracle turn via the existing client. Ends with a VERDICT line. The reply is
        printed live to the terminal (observability only; not added to any model context)."""
        oracle = os.path.join(self.project_dir, ".aider_factory", "bash", "oracle")
        if not os.path.exists(oracle):
            oracle = "aider-oracle"
        env = {**os.environ, **(task.rag_env or {})}
        # Route the oracle to a debate-specific session file (survives apply-phase cleanup).
        _sf = d.get("oracle_session_file")
        if _sf:
            env["ORACLE_SESSION_FILE"] = _sf
        # Prevent re-retrieving the LanceDB chunks after turn 0 to save tokens, since
        # the session state carries the context forward.
        mode = d.get("retrieve_mode", "no_retrieve") if turn == 0 else "no_retrieve"

        # The oracle's judging role differs by debate mode: grounding cites verbatim source
        # for quotes; code cites reference code/patterns for a fix. Both end with a VERDICT line.
        if pre_assess_prompt:
            prompt = pre_assess_prompt
            # Code mode: append the full file contents to the pre-assessment
            # prompt so the oracle sees the same source files the architect
            # reads via --read.  Without this, the pre_assess_prompt branch
            # short-circuits the code-mode elif below, where file injection
            # normally lives (gated by `if not turn`).  Regression was
            # introduced when the generalized pre_assess_prompt parameter
            # was added above the code-mode branch.
            if d.get("mode") == "code" and not turn:
                for _rf in d.get("read_files") or []:
                    _full = (
                        _rf
                        if os.path.isabs(_rf)
                        else os.path.join(self.project_dir, _rf)
                    )
                    if os.path.isfile(_full):
                        try:
                            with open(_full, encoding="utf-8") as _fh:
                                prompt += (
                                    "\n\n## " + _rf + "\n```\n" + _fh.read() + "\n```"
                                )
                        except Exception:
                            pass
        elif d.get("mode") == "code":
            # Build code context block: failure log + full file contents.
            _ctx = []
            _fl = d.get("failure_log")
            if _fl:
                _ctx.append("## Failing test output\n```\n" + _fl[-4000:] + "\n```")

            # Pass the full file contents ONLY on Turn 1 to warm up Oracle's KV cache.
            if not turn:
                for _rf in d.get("read_files") or []:
                    _full = (
                        _rf
                        if os.path.isabs(_rf)
                        else os.path.join(self.project_dir, _rf)
                    )
                    if os.path.isfile(_full):
                        try:
                            with open(_full, encoding="utf-8") as _fh:
                                _ctx.append(f"## {_rf}\n```\n{_fh.read()}\n```")
                        except Exception:
                            pass
            _ctx_block = ("\n\n" + "\n\n".join(_ctx)) if _ctx else ""

            prompt = (
                "You are the Knowledge Oracle advising the Architect agent. "
                "Judge the Architect's PROPOSAL against the provided context "
                "and files below. Cite exact evidence (file + snippet) that "
                "supports or refutes the proposal; do not endorse APIs or "
                "patterns absent from the provided code or references. "
                "End with EXACTLY one line: 'VERDICT: AGREE' if the proposal "
                "is sound and grounded, or 'VERDICT: OBJECT - <specific reason>' "
                "if not."
                + _ctx_block
                + "\n\n## Architect's analysis and PROPOSAL\n"
                + (arch_text or "")
            )
        else:
            _file_ctx = []
            if not turn:
                for _rf in d.get("read_files") or []:
                    _full = (
                        _rf
                        if os.path.isabs(_rf)
                        else os.path.join(self.project_dir, _rf)
                    )
                    if os.path.isfile(_full):
                        try:
                            with open(_full, encoding="utf-8") as _fh:
                                _file_ctx.append(f"## {_rf}\n```\n{_fh.read()}\n```")
                        except Exception:
                            pass
            _file_block = ("\n\n" + "\n\n".join(_file_ctx)) if _file_ctx else ""

            prompt = (
                "You are the Knowledge Oracle reviewing the Architect's analysis "
                "and PROPOSAL below. Judge it against the knowledge base and "
                "provided context. Cite exact evidence from the source material "
                "to support or refute the proposal. "
                "End with EXACTLY one line: 'VERDICT: AGREE' if you concur, "
                "or 'VERDICT: OBJECT - <specific reason>' if not."
                + _file_block
                + "\n\n"
                + (arch_text or "")
            )

        # Write prompt to a temp file instead of passing as a CLI arg to avoid
        # E2BIG (Argument list too long) when code files are large.
        import tempfile

        prompt_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            dir=os.path.join(self.project_dir, ".aider_factory"),
            prefix=".oracle_prompt_",
            delete=False,
        )
        prompt_file.write(prompt)
        prompt_file.close()

        args = [oracle, "--mode", mode]
        coll = (task.rag_env or {}).get("ORACLE_COLLECTION")
        if coll and mode != "no_retrieve":
            args += ["--collection", coll]
        args.extend(["--file", prompt_file.name])

        try:
            p = subprocess.run(
                args,
                cwd=self.project_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as e:
            log.warning(f"⚠️  oracle call failed [{task.id}]: {e}")
            return f"VERDICT: OBJECT - oracle error: {e}"
        finally:
            # Clean up the temp file after the oracle has read it
            try:
                os.unlink(prompt_file.name)
            except OSError:
                pass
        out = re.sub(r"\033\[[0-9;]*m", "", (p.stdout or "")).strip()
        # Surface the oracle's retrieval status from stderr (always, not just on failure).
        # The oracle prints "[oracle] N source chunk(s) ..." to stderr on every call.
        _stderr = (p.stderr or "").strip()
        _rag_line = ""
        _cost_line = ""
        for _sl in _stderr.splitlines():
            if "[oracle]" in _sl and "source chunk" in _sl:
                _rag_line = _sl.strip()
            if "Cost:" in _sl and "message," in _sl:
                _cost_line = _sl.strip()
        print(f"\n{_ORACLE_COLOR}┌── oracle {label} ──", flush=True)
        if _rag_line:
            print(f"  {_rag_line}", flush=True)
        print(out or "(no output)", flush=True)
        if _cost_line:
            print(f"  {_cost_line}", flush=True)
        print(f"└──{_RESET}", flush=True)
        if not out:
            tail = " | ".join(_stderr.splitlines()[-3:])
            log.warning(
                f"⚠️  oracle returned NO output [{task.id}] (rc={p.returncode}); stderr: {tail}"
            )
        return out

    def _run_deliberation(self, task: "Task") -> bool:
        """Two-party debate refereed by the ledger. Writes a verdict + debate ledger.
        Never edits — a downstream (verdict_gate) task applies an actionable verdict."""
        import deliberate

        d = task.deliberate or {}

        # Early exit: if the previous round already reached agreement, skip this round.
        # The DAG statically pre-builds all rounds at parse time; this runtime check
        # prevents wasted rounds after consensus (mirrors the CLI debate's early exit).
        prior_verdict_path = d.get("prior_verdict")
        if prior_verdict_path and os.path.isfile(prior_verdict_path):
            prior_state = deliberate.verdict_status(prior_verdict_path)
            if prior_state in ("agreed", "clean"):
                # Copy the prior verdict to this round's path so the downstream
                # task (which references this round's verdict) finds the content.
                verdict_path = d.get("verdict")
                if verdict_path:
                    import shutil

                    os.makedirs(
                        os.path.dirname(os.path.abspath(verdict_path)), exist_ok=True
                    )
                    shutil.copy(prior_verdict_path, verdict_path)
                log.info(
                    f"⏩ DELIBERATION [{task.id}] skipped — prior round already agreed or clean."
                )
                return True

        template, issue = d.get("template"), d.get("issue")
        verdict_path, ledger_path = d.get("verdict"), d.get("ledger")
        gate_cmd, max_turns = d.get("gate_cmd"), int(d.get("loops", 3))
        review_path, source_path, tag = (
            d.get("review"),
            d.get("source"),
            d.get("tag", "evidence"),
        )

        seed = ""
        for p in (template, issue):
            if p and os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    seed += f.read() + "\n\n"

        # If a prior round's ledger was passed, extract its final agreed resolution to seed this round.
        # This gives Round 2 knowledge of what Round 1 just attempted.
        prior_ledger_path = d.get("prior_ledger")
        if prior_ledger_path and os.path.isfile(prior_ledger_path):
            try:
                import json

                with open(prior_ledger_path, "r", encoding="utf-8") as pf:
                    _pl = json.load(pf)
                    _pturns = _pl.get("turns", [])
                    if _pturns and _pl.get("state") == "agreed":
                        # The architect's proposal that triggered the 'AGREE' is the second to last turn
                        if len(_pturns) >= 2 and _pturns[-2]["role"] == "architect":
                            _prior_fix = _pturns[-2].get("excerpt", "")
                            seed += f"## Context: The PREVIOUS escalation round agreed to attempt this fix:\n{_prior_fix}\n\n"
            except Exception as e:
                log.warning(f"⚠️  Could not parse prior ledger {prior_ledger_path}: {e}")

        # B2 baseline: the pre-apply quote-hash SET (deletion guard + [validated]/[fixed]
        # distinction) + the actual ungrounded quotes (for context-symmetry retrieval).
        import validator

        quote_baseline, ungrounded = [], []
        if review_path and os.path.isfile(review_path):
            _rl = open(review_path, encoding="utf-8").read().splitlines()
            _items = validator._extract(_rl, tag)
            quote_baseline = sorted(validator._qhash(it["quote"]) for it in _items)
            if source_path and os.path.isfile(source_path):
                _sn = validator._normalize(open(source_path, encoding="utf-8").read())
                ungrounded = [
                    it["quote"]
                    for it in _items
                    if it["tag"] == tag and not validator._grounded(it["quote"], _sn)
                ]

        # Context symmetry: hand the architect the SAME source chunks the oracle sees,
        # keyed on the actual failing quotes (top_k from ORACLE_TOP_K).
        if ungrounded and d.get("retrieve_mode", "no_retrieve") != "no_retrieve":
            _db = (task.rag_env or {}).get("ORACLE_RAG_DB_DIR")
            _coll = (task.rag_env or {}).get("ORACLE_COLLECTION")
            try:
                _k = int((task.rag_env or {}).get("ORACLE_TOP_K", "30"))
            except ValueError:
                _k = 30
            _, _chunks = validator._region(" ".join(ungrounded)[:2000], _db, _coll, _k)
            if _chunks:
                seed += (
                    "\n\n## Source evidence (retrieved from the paper)\n"
                    + "\n".join(f"```\n[source: {s}]\n{t}\n```" for s, t in _chunks)
                    + "\n"
                )

        issue_id = os.path.basename(issue or task.id)
        gate_present = bool(gate_cmd)

        # Ensure a stale ledger from a previous run doesn't poison the gate's deletion guard
        if os.path.exists(ledger_path):
            try:
                os.remove(ledger_path)
            except OSError:
                pass

        # Seed with the real failure; short-circuit if the gate is already green.
        if gate_present:
            if self.last_test_result.get(gate_cmd) is True:
                ok = True
                gate_out = "Gate already passed in preceding task."
            else:
                ok, gate_out = self._gate_run(task, gate_cmd)
            if ok:
                led = deliberate.new_ledger(issue_id)
                led["state"] = "clean"
                led["quote_baseline"] = quote_baseline
                deliberate.save_ledger(ledger_path, led)
                deliberate.write_verdict(
                    verdict_path,
                    "clean",
                    True,
                    "Gate already passes; no change required.",
                )
                log.info(
                    f"🗣️  DELIBERATION [{task.id}] -> gate already green; nothing to do."
                )
                return True
            seed += f"## Current failure (gate output)\n```\n{gate_out[-4000:]}\n```\n"
            # Code/test mode: hand the oracle the same failure log the architect sees so it
            # can judge against real evidence (the debate is ASK-mode, so the log is stable).
            if d.get("mode") == "code":
                d["failure_log"] = gate_out
            # Code/test mode: no grounded quotes to key retrieval on -> retrieve corpus
            # chunks (other repos + literature) keyed on the failure, so the architect and
            # oracle both reason from vetted reference material (the code "grounding").
            if (
                not ungrounded
                and d.get("retrieve_mode", "no_retrieve") != "no_retrieve"
            ):
                _db = (task.rag_env or {}).get("ORACLE_RAG_DB_DIR")
                _coll = (task.rag_env or {}).get("ORACLE_COLLECTION")
                try:
                    _k = int((task.rag_env or {}).get("ORACLE_TOP_K", "30"))
                except ValueError:
                    _k = 30
                _, _chunks = validator._region((gate_out or "")[:2000], _db, _coll, _k)
                if _chunks:
                    seed += (
                        "\n\n## Reference evidence (retrieved from the corpus)\n"
                        + "\n".join(f"```\n[source: {s}]\n{t}\n```" for s, t in _chunks)
                        + "\n"
                    )

        ledger = deliberate.new_ledger(issue_id)
        last_proposal, state = "", "continue"
        transcript = [f"# Deliberation transcript — {issue_id}\n"]
        # Accumulated debate memory fed to EVERY architect turn (each architect turn is a
        # fresh process with no chat memory). Architect side = its PROPOSAL line only (the
        # reasoning path is low-value/noisy); oracle side = its FULL reply (carries the
        # verbatim citations the architect must reuse to converge).
        history = ""

        # Debate-specific session file: separate from the main .oracle_session.json
        # so the apply phase's cleanup does not destroy cross-round oracle context.
        oracle_debate_session = os.path.join(
            self.project_dir, ".aider_factory", ".oracle_debate_session.json"
        )
        d["oracle_session_file"] = oracle_debate_session
        oracle_debate_cost_sidecar = oracle_debate_session + ".costs.json"

        debate_aider_history = os.path.join(
            self.project_dir, ".aider_factory", ".debate_aider_history.md"
        )

        # Clear debate context: always on round 1 (fresh sequence), or every round
        # when pass_round_history is off (each cluster of loops gets a clean slate).
        _first_round = d.get("round_idx", 1) == 1
        _clear = not d.get("pass_round_history", False) or _first_round
        if _clear:
            for _f in [
                oracle_debate_session,
                oracle_debate_cost_sidecar,
                debate_aider_history,
            ]:
                if os.path.exists(_f):
                    try:
                        os.remove(_f)
                    except OSError:
                        pass

        log.info(f"🗣️  DELIBERATION [{task.id}] -> up to {max_turns} turn(s)")
        _reads = d.get("read_files") or ([issue] if issue else [])

        # --- Oracle turn 0: pre-assessment before the architect speaks ---
        _orc0_prompt = (
            "You are the Knowledge Oracle. Assess the following using the "
            "provided context, evidence, and any retrieved reference material. "
            "Provide your expert analysis before the Architect responds."
            "\n\n" + seed
        )
        last_oracle = self._oracle_turn(
            task,
            d,
            "",
            turn=0,
            label="turn 0 (pre-assessment)",
            pre_assess_prompt=_orc0_prompt,
        )
        deliberate.record_turn(ledger, -1, "oracle", last_oracle, verdict=None)
        transcript.append(
            f"\n## Turn 0 — Oracle (pre-assessment)\n\n{(last_oracle or '').strip()}\n"
        )

        for turn in range(max_turns):
            if turn == 0:
                arch_msg = (
                    seed + f"\n\n## Oracle Pre-Assessment\n{last_oracle}\n\n"
                    "Address the issue above. The Oracle has provided an initial "
                    "assessment — build on it or counter it with evidence. "
                    "End with EXACTLY one line:\n"
                    "PROPOSAL: <one-line concrete resolution>"
                )
            else:
                # Delta-only prompts: we only pass objections and metadata!
                arch_msg = (
                    f"The Oracle reviewed your proposal and responded:\n\n"
                    f"{last_oracle}\n\n"
                    f"Please address the Oracle's objections and refine your proposal. "
                    f"End with EXACTLY one line:\n"
                    f"PROPOSAL: <one-line concrete resolution>"
                )

            # Send prompt using our robust, non-interactive Ask turn with history restoration
            arch_text = self._aider_ask_turn(
                task,
                arch_msg,
                _reads,
                label=f"turn {turn + 1}/{max_turns}",
                history_file=debate_aider_history,
            )

            last_proposal = arch_text or last_proposal
            pline = deliberate.proposal_line(arch_text) or "(no PROPOSAL line)"
            log.info(f"   turn {turn + 1} architect → {pline[:160]}")
            deliberate.record_turn(
                ledger,
                turn,
                "architect",
                pline,
                proposal_hash=deliberate.proposal_hash(arch_text),
            )
            transcript.append(
                f"\n## Turn {turn + 1} — Architect\n\n{(arch_text or '').strip()}\n"
            )

            # Oracle Turn (turn variable is passed so it knows whether to skip file loading)
            last_oracle = self._oracle_turn(
                task, d, arch_text, turn + 1, label=f"turn {turn + 1}/{max_turns}"
            )
            verdict = deliberate.oracle_verdict(last_oracle)
            log.info(
                f"   turn {turn + 1} oracle → VERDICT: {(verdict or 'none').upper()}"
            )
            deliberate.record_turn(ledger, turn, "oracle", last_oracle, verdict=verdict)
            transcript.append(
                f"\n## Turn {turn + 1} — Oracle\n\n{(last_oracle or '').strip()}\n"
            )

            # Grow the shared memory transcript
            history += (
                f"\n### Turn {turn + 1} — Architect proposed\n{pline}\n"
                f"### Turn {turn + 1} — Oracle replied\n{(last_oracle or '').strip()}\n"
            )

            state = deliberate.consensus_state(ledger)
            log.info(f"   turn {turn + 1}/{max_turns}: {state}")
            if state != "continue":
                break

        if state == "continue":
            state = "exhausted"
        ledger["state"] = state
        ledger["quote_baseline"] = quote_baseline
        deliberate.save_ledger(ledger_path, ledger)
        actionable = deliberate.write_verdict(
            verdict_path,
            state,
            gate_present,
            last_proposal,
            draft_mode=d.get("draft_mode", False),
            oracle_response=last_oracle,
        )

        # Human-readable transcript of the full back-and-forth (observability only;
        # never fed into any aider session context).
        transcript_path = os.path.splitext(ledger_path)[0] + ".md"  # <stem>.debate.md
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(transcript_path)), exist_ok=True
            )
            with open(transcript_path, "w", encoding="utf-8") as tf:
                tf.write("\n".join(transcript))
        except Exception:
            pass

        # Archive the oracle transcript before the next aider task deletes it.
        # The aider session setup (line 780) removes .oracle_chat.history.md, so
        # if we don't archive here, the debate's retrieved chunks are lost.
        _ot = os.path.join(self.project_dir, ".aider_factory", ".oracle_chat.history.md")
        if os.path.exists(_ot):
            import datetime
            import shutil

            _stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            _rhd = os.path.join(
                self.project_dir, ".aider_factory", "logs", "oracle_history"
            )
            os.makedirs(_rhd, exist_ok=True)
            try:
                shutil.copy(_ot, os.path.join(_rhd, f"{_stamp}_{task.id}.md"))
            except Exception:
                pass

        # Clean up debate working files — but preserve them when
        # pass_round_history is True so the next round's oracle and architect
        # can resume from the prior round's accumulated context.
        if not d.get("pass_round_history", False):
            for _df in [
                oracle_debate_session,
                oracle_debate_cost_sidecar,
                debate_aider_history,
            ]:
                if os.path.exists(_df):
                    try:
                        os.remove(_df)
                    except OSError:
                        pass

        log.info(
            f"🗣️  DELIBERATION [{task.id}] -> {state} "
            f"({'ACTIONABLE' if actionable else 'held for human'}) -> {verdict_path}"
        )
        return True

    def run_task(self, task: Task) -> bool:
        # Edit-node self-gate: a task that applies a deliberation verdict runs only when
        # that verdict is an agreed, gate-backed resolution; otherwise hold for a human.
        if task.verdict_gate:
            import deliberate

            if not deliberate.verdict_is_actionable(task.verdict_gate):
                st = deliberate.verdict_status(task.verdict_gate)
                if st == "clean":
                    log.info(
                        f"✅ TASK SUCCESS [{task.id}]: already grounded; nothing to apply."
                    )
                else:
                    log.info(
                        f"⏸️  HELD FOR HUMAN [{task.id}]: verdict '{st}' "
                        f"(not auto-applied; quotes left as [evidence])."
                    )
                return True
        # Per-phase RAG/OCR ingestion (movable DAG node). Runs once, in DAG order,
        # before this task's session. Non-fatal: a missing job folder just skips.
        if task.ocr_ingest:
            try:
                import rag_manager

                log.info(
                    f"📚 RAG INGEST [{task.id}] -> collection "
                    f"'{task.ocr_ingest.get('collection_name')}'"
                )
                rag_manager.ingest(**task.ocr_ingest)
            except Exception as e:
                log.error(f"⚠️  RAG ingest failed [{task.id}]: {e} (continuing)")

        # Programmatic side-agent job (no Aider): the oracle reads a template, pulls
        # this collection's knowledge, and writes the synthesized output to disk.
        if task.oracle:
            return self._run_oracle_job(task)

        # Evidence grounding audit (no Aider): exact-substring match of [tag]
        # quotes against the OCR source; writes a heal report. (Legacy Task.validate
        # path; the current heal loop runs the auditor via the test script instead.)
        if task.validate:
            return self._run_validate(task)

        # Two-party deliberation (no Aider edits): ask-mode architect turns + oracle
        # turns, refereed by the ledger; writes a verdict for a downstream edit node.
        if task.deliberate:
            return self._run_deliberation(task)

        # Setup-only node (e.g. ingest-only): nothing left to do, never launch Aider.
        if task.skip_aider:
            log.info(f"✅ TASK SUCCESS [{task.id}] (setup-only; Aider bypassed).")
            return True

        max_outer_loops = task.max_aider_loops if task.iterate_test else 1
        if task.pair_programming:
            max_outer_loops = 1

        for attempt in range(max_outer_loops):
            # Wipe Aider's history files to ensure a 100% clean directory between loops
            chat_hist = os.path.join(
                self.project_dir, ".aider_factory", ".aider.chat.history.md"
            )
            input_hist = os.path.join(
                self.project_dir, ".aider_factory", ".aider.input.history"
            )
            oracle_session = os.path.join(
                self.project_dir, ".aider_factory", ".oracle_session.json"
            )
            oracle_cost_sidecar = os.path.join(
                self.project_dir, ".aider_factory", ".oracle_session.json.costs.json"
            )
            oracle_debate_session = os.path.join(
                self.project_dir, ".aider_factory", ".oracle_debate_session.json"
            )
            debate_aider_history = os.path.join(
                self.project_dir, ".aider_factory", ".debate_aider_history.md"
            )
            oracle_transcript = os.path.join(
                self.project_dir, ".aider_factory", ".oracle_chat.history.md"
            )
            _pair_capture = os.path.join(
                self.project_dir, ".aider_factory", ".pair_capture.log"
            )
            for f in [
                chat_hist,
                input_hist,
                oracle_session,
                oracle_cost_sidecar,
                oracle_debate_session,
                debate_aider_history,
                oracle_transcript,
                _pair_capture,
            ]:
                if os.path.exists(f):
                    os.remove(f)

            root = str(self.project_dir)

            # Resolve config paths: prioritize .aider_factory/ then fall back to root
            local_aider_factory_conf = os.path.join(root, ".aider_factory", ".aider.conf.yml")
            aider_conf = (
                local_aider_factory_conf
                if os.path.exists(local_aider_factory_conf)
                else os.path.join(root, ".aider.conf.yml")
            )

            local_aider_factory_settings = os.path.join(
                root, ".aider_factory", ".aider.model.settings.yml"
            )
            aider_settings = (
                local_aider_factory_settings
                if os.path.exists(local_aider_factory_settings)
                else os.path.join(root, ".aider.model.settings.yml")
            )

            cmd = [
                "aider",
                "--config",
                aider_conf,
                "--no-check-model-accepts-settings",
                "--no-show-model-warnings",
                "--model-settings-file",
                aider_settings,
                "--model",
                task.model,
                "--editor-model",
                # Escalate to fallback_editor_model on attempt > 0 if configured
                task.fallback_editor_model
                if (attempt > 0 and task.fallback_editor_model)
                else task.editor_model,
            ]

            # Determine if we should use the message file or check test failures.
            # We use the plan (message_file) only on the first attempt.
            # Subsequent outer loops in iterative mode will check the current test baseline.
            use_plan = task.message_file and attempt == 0

            if (
                not use_plan
                and task.iterate_test
                and task.test_cmd
                and not task.pair_programming
            ):
                # Run the test manually in Python to get the failure output
                log.info(
                    f"⚙️ Running initial test suite to check baseline for [{task.id}] (Loop {attempt + 1}/{max_outer_loops})..."
                )

                # Stream output to console while capturing it
                test_proc = subprocess.Popen(
                    task.test_cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # Combine stderr into stdout
                    text=True,
                    bufsize=1,  # Line-buffered
                    cwd=self.project_dir,
                    # Side-agent (ORACLE_*) + per-doc validation vars, so a test
                    # command that shells out to the oracle/validator is configured.
                    # VALIDATION_ATTEMPT lets the contextual validator reset its
                    # per-run ledger (no-progress guard) on the first attempt.
                    env={
                        **os.environ,
                        **(task.rag_env or {}),
                        "VALIDATION_ATTEMPT": str(attempt),
                    },
                )

                output_lines = []
                if test_proc.stdout:
                    while True:
                        char = test_proc.stdout.read(1)
                        if not char and test_proc.poll() is not None:
                            break
                        if char:
                            print(char, end="", flush=True)
                            output_lines.append(char)
                    test_proc.stdout.close()

                test_proc.wait()  # Wait for the process to finish
                out = "".join(output_lines)
                self.last_test_result[task.test_cmd] = (test_proc.returncode == 0)

                if test_proc.returncode == 0:
                    log.info(
                        f"✅ Tests already pass for [{task.id}]. Skipping Aider execution."
                    )
                    # if os.path.exists(history_file):
                    #     os.remove(history_file)
                    return True

                log.info(
                    "❌ Initial tests failed. Pushing output to Architect model..."
                )

                if task.iterate_file and os.path.isfile(task.iterate_file):
                    with open(task.iterate_file, "r", encoding="utf-8") as f:
                        FIX_CONSTRAINTS = f"\n{f.read()}\n"
                else:
                    FIX_CONSTRAINTS = (
                        "\nCONSTRAINTS FOR THIS FIX:\n"
                        "- You may edit the source file and the test file to ensure the tests pass and the logic is mathematically sound.\n"
                        "- Make targeted, minimal edits to the source code. Do not attempt to rewrite massive blocks of code to fix a single-line bug.\n"
                        "- Do not create new files\n"
                        "- Do not delete existing passing tests\n"
                        "- Your SEARCH blocks must exactly match current file content\n"
                    )

                msg = (
                    "The test suite failed. Review errors and resolve.\n"
                    + FIX_CONSTRAINTS
                    + "\n\n```log\n"
                    + out
                    + "\n```"
                )
                cmd.extend(["--message", msg])

            elif task.message_file and os.path.isfile(task.message_file):
                if task.pair_programming:
                    # In pair programming mode skip --message so Aider drops
                    # straight to the interactive prompt. Plan is loaded as
                    # read-only context and the user drives the conversation.
                    cmd.extend(["--read", task.message_file])
                else:
                    cmd.extend(
                        [
                            "--message",
                            f"Please execute the instructions found in {task.message_file}.",
                            "--read",
                            task.message_file,
                        ]
                    )
            unique_read_files = []
            for f in task.read_files:
                if f not in task.files and f not in unique_read_files:
                    unique_read_files.append(f)

            for file in unique_read_files:
                cmd.extend(["--read", file])

            # Add target files (ensure no duplicates)
            for file in dict.fromkeys(task.files):
                cmd.extend([file])

            if task.test_cmd:
                cmd.extend(["--test-cmd", task.test_cmd])
                # Optional: Use Aider's built-in 3-loop iteration
                # When auto_test=true, the architect gets input every 3 attempts
                # When auto_test=false, the architect gets input on every attempt
                if task.iterate_test and task.auto_test:
                    cmd.append("--auto-test")

            current_editor = (
                task.fallback_editor_model
                if (attempt > 0 and task.fallback_editor_model)
                else task.editor_model
            )
            log.info(
                f"🚀 STARTING TASK [{task.id}] (attempt {attempt + 1}/{max_outer_loops}) -> Arch: {task.architect_api_base} | Ed: {current_editor}"
            )

            # Inject the correct endpoints for the specific machine (Strix vs 7900XT)
            env = os.environ.copy()
            if task.architect_api_base:
                env["OPENAI_API_BASE"] = task.architect_api_base
                env["OPENAI_API_KEY"] = "sk-dummy"
            if task.editor_api_base:
                env["OLLAMA_API_BASE"] = task.editor_api_base
                env["LM_STUDIO_API_BASE"] = task.editor_api_base
                env["LM_STUDIO_API_KEY"] = "sk-dummy"
            # Side-agent (ORACLE_*) config, visible to /run child processes
            if task.rag_env:
                env.update(task.rag_env)
            # env["AIDER_EDITOR_TEMPERATURE"] = "0.2"  # Force deterministic execution

            try:
                if task.pair_programming:
                    log.info(
                        f"🤝 STARTING INTERACTIVE PAIR-PROGRAMMING [{task.id}] -> Arch: {task.architect_api_base} | Ed: {current_editor}"
                    )
                    # Wrap Aider in `script` so prompt_toolkit sees a real PTY
                    # while all output (stdout + stderr) is captured to a file.
                    # The finally block parses the capture for cost lines and
                    # emits them to stdout (-> tee -> log -> aggregate_costs.py).
                    # This captures every cost source: main session, /run
                    # debates, and oracle turns — no sidecars or chat history.
                    cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
                    process = subprocess.Popen(
                        ["script", "-qfe", "-c", cmd_str, _pair_capture],
                        env=env,
                        cwd=self.project_dir,
                    )
                    while True:
                        try:
                            process.wait()
                            break
                        except KeyboardInterrupt:
                            print(
                                "\n⏸️  [Pipeline] Ctrl+C caught! Letting Aider handle interrupt and returning to chat..."
                            )
                            continue
                    return process.returncode == 0

                # Start Aider, streaming to terminal
                cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
                process = subprocess.Popen(
                    cmd_str,
                    shell=True,
                    cwd=self.project_dir,
                    env=env,
                )

                # Wait for Aider to finish
                process.wait()

                if process.returncode != 0:
                    if not task.iterate_test:
                        log.error(
                            f"❌ TASK FAILED OR KILLED [{task.id}] (Exit code: {process.returncode})"
                        )
                        return False
                    else:
                        # Aider exhausted its 3 loops. Continue Python outer loop!
                        continue

                if not task.iterate_test:
                    log.info(f"✅ TASK SUCCESS [{task.id}]")
                    return True
                else:
                    # Aider exited cleanly (tests might be fixed). Continue Python loop to verify.
                    continue

            except KeyboardInterrupt:
                log.warning(f"⏸️  TASK CANCELLED BY USER [{task.id}]")
                return False
            except Exception as e:
                log.error(f"❌ TASK EXCEPTION [{task.id}]: {str(e)}")
                return False
            finally:
                # Archive chat history before cleanup
                if os.path.exists(chat_hist):
                    import datetime
                    import shutil

                    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    history_dir = os.path.join(
                        self.project_dir, ".aider_factory", "logs", "chat_history"
                    )
                    os.makedirs(history_dir, exist_ok=True)

                    archive_name = f"{stamp}_{task.id}.md"
                    shutil.copy(chat_hist, os.path.join(history_dir, archive_name))

                # Archive the Oracle side-agent transcript before cleanup
                if os.path.exists(oracle_transcript):
                    import datetime
                    import shutil

                    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    rag_hist_dir = os.path.join(
                        self.project_dir,
                        ".aider_factory",
                        "logs",
                        "oracle_history",
                    )
                    os.makedirs(rag_hist_dir, exist_ok=True)
                    shutil.copy(
                        oracle_transcript,
                        os.path.join(rag_hist_dir, f"{stamp}_{task.id}.md"),
                    )

                # Final cleanup
                for f in [
                    chat_hist,
                    input_hist,
                    oracle_session,
                    oracle_cost_sidecar,
                    oracle_debate_session,
                    debate_aider_history,
                    oracle_transcript,
                    _pair_capture,
                ]:
                    if os.path.exists(f):
                        os.remove(f)

        # The iterate loop verifies edit N via the test-check at the START of attempt N+1,
        # so the FINAL attempt's edit is never re-tested -> exhaustion can't tell "still
        # broken" from "the last edit just fixed it." Code mode has no finalize authority,
        # so a final_check node re-runs test_cmd ONCE here (reusing the same subprocess the
        # loop already uses; no agent, no new node) and returns its true pass/fail.
        if task.final_check and task.test_cmd:
            log.info(
                f"🔁 FINAL CHECK [{task.id}]: re-running the test suite once to verify the "
                "last edit (loop never re-tests its own final edit)..."
            )
            try:
                p = subprocess.run(
                    task.test_cmd,
                    shell=True,
                    cwd=self.project_dir,
                    env={**os.environ, **(task.rag_env or {})},
                )
                self.last_test_result[task.test_cmd] = (p.returncode == 0)
                if p.returncode == 0:
                    log.info(f"✅ TASK SUCCESS [{task.id}]: final test check passed.")
                    return True
                log.error(
                    f"❌ TASK FAILED [{task.id}]: final test check still failing "
                    f"(rc={p.returncode}) after {max_outer_loops} attempt(s)."
                )
                return False
            except Exception as e:
                log.error(f"❌ TASK FAILED [{task.id}]: final test check errored: {e}")
                return False

        # An apply node's strict gate may not have run after the final edit, so the loop can
        # exhaust even when the document is actually grounded. The downstream finalize step is
        # the terminal authority (it promotes grounded quotes and flags real residuals), so a
        # soft_fail apply node treats exhaustion as success and defers the verdict to finalize.
        if task.soft_fail:
            log.info(
                f"ℹ️  TASK SOFT-EXHAUSTED [{task.id}]: used all {max_outer_loops} attempt(s); "
                "deferring to the downstream authority."
            )
            return True
        log.error(
            f"❌ TASK FAILED [{task.id}]: Exhausted all {max_outer_loops} test attempts."
        )
        # if os.path.exists(history_file):
        #     os.remove(history_file)
        return False

    def execute_pipeline(self) -> None:
        pending = [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]

        while pending:
            progress = False
            for task in pending:
                if self.dependencies_met(task):
                    task.status = TaskStatus.RUNNING
                    success = self.run_task(task)
                    task.status = TaskStatus.SUCCESS if success else TaskStatus.FAILED
                    progress = True
                    break

            if not progress:
                log.error(
                    "Pipeline suddenly stopped. Check dependencies or failed tasks."
                )
                break

            pending = [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]
