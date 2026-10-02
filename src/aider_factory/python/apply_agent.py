#!/usr/bin/env python3
# apply_agent.py

import argparse
import os
import re
import shutil
import subprocess
import sys
import yaml

try:
    from aider_factory.python.env_utils import (
        load_env_files,
        is_dummy_key,
        is_local_model,
        ensure_model_settings,
        is_valid_endpoint,
        is_test_path,
        kill_proc_tree,
    )
except ImportError:
    try:
        from env_utils import (
            load_env_files,
            is_dummy_key,
            is_local_model,
            ensure_model_settings,
            is_valid_endpoint,
            is_test_path,
            kill_proc_tree,
        )
    except ImportError:
        load_env_files = None
        is_dummy_key = lambda k: not k
        is_local_model = lambda m: True
        ensure_model_settings = lambda p, m, b=None: p
        is_valid_endpoint = lambda u: bool(u and u.startswith(("http://", "https://")))
        is_test_path = lambda p: any(x in (p or "").lower() for x in ("test", "spec"))
        kill_proc_tree = lambda p: getattr(p, "kill", lambda: None)()

if load_env_files:
    load_env_files()

TOKEN_ANCHOR_RE = re.compile(
    r"(?m)^>\s*Tokens:\s*[\d\.]+[kKMG]?\s*sent,\s*[\d\.]+[kKMG]?\s*received.*$"
)
SLASH_CMD_RE = re.compile(
    r"^/(add|run|read|drop|model|clear|exit|undo|diff|load|help)\b"
)


def parse_chat_history(chat_path: str, turns: int = 1) -> str:
    """Parse chat history and extract spec/directive for the last N turns."""
    if not os.path.isfile(chat_path):
        return ""
    with open(chat_path, "r", encoding="utf-8") as f:
        content = f.read()

    matches = list(TOKEN_ANCHOR_RE.finditer(content))
    if not matches:
        return ""

    parsed_turns = []
    prev_end = 0
    for m in matches:
        start_idx = m.start()
        block = content[prev_end:start_idx].strip()
        prev_end = m.end()

        lines = block.splitlines()
        user_lines = []
        asst_lines = []
        user_done = False

        for line in lines:
            if not user_done:
                if line.startswith("####"):
                    raw_user = re.sub(r"^####\s*", "", line)
                    if not SLASH_CMD_RE.match(raw_user.strip()):
                        clean_cmd = re.sub(r"^/ask\s*", "", raw_user)
                        user_lines.append(clean_cmd)
                else:
                    user_done = True
                    asst_lines.append(line)
            else:
                asst_lines.append(line)

        user_text = "\n".join(user_lines).strip()
        asst_text = "\n".join(asst_lines).strip()

        # Clean thinking content and answer markers
        asst_text = re.sub(
            r"<thinking-content-[0-9a-fA-F]+>[\s\S]*?</thinking-content-[0-9a-fA-F]+>",
            "",
            asst_text,
        )
        asst_text = re.sub(r"<think>[\s\S]*?</think>", "", asst_text)
        asst_text = re.sub(r"►\s*\*{0,2}ANSWER\*{0,2}", "", asst_text).strip()

        # Clean tool artifacts
        asst_clean = "\n".join(
            ln
            for ln in asst_text.splitlines()
            if not re.match(r"^>\s*(Added|Moved|No files|Tokens).*", ln)
        ).strip()

        if asst_clean:
            parsed_turns.append((user_text, asst_clean))

    if not parsed_turns:
        return ""

    selected = parsed_turns[-turns:]
    if len(selected) == 1:
        u, a = selected[0]
        header = f"# Directive\n{u}\n\n" if u else ""
        return f"{header}# Specification & Implementation Plan\n{a}\n"

    out = []
    for idx, (u, a) in enumerate(selected, 1):
        is_last = idx == len(selected)
        tag = "Active Directive" if is_last else f"Prior Context Turn {idx}"
        out.append(
            f"## {tag}\n### User Request:\n{u}\n\n### Architect Specification:\n{a}\n"
        )
    return "\n".join(out)


def find_active_session_chat_history(
    cwd: str, session_name: str = None
) -> tuple[str, str]:
    """Find the chat history markdown file and resolved session name."""
    af_dir = os.path.join(cwd, ".aider_factory")
    if not session_name:
        session_name = os.environ.get("AI_FACTORY_SESSION")

    if session_name:
        sess_dir = os.path.join(af_dir, "sessions", session_name)
        sess_history = os.path.join(sess_dir, ".aider.chat.history.md")
        if os.path.isfile(sess_history):
            return sess_history, session_name

        vault_dir = os.path.join(sess_dir, "chat_history")
        if os.path.isdir(vault_dir):
            stem_histories = [
                os.path.join(vault_dir, f)
                for f in os.listdir(vault_dir)
                if f.startswith(".aider.chat.history_") and f.endswith(".md")
            ]
            if stem_histories:
                stem_histories.sort(key=os.path.getmtime, reverse=True)
                return stem_histories[0], session_name

    sess_root = os.path.join(af_dir, "sessions")
    if os.path.isdir(sess_root):
        candidates = []
        for s in os.listdir(sess_root):
            h_path = os.path.join(sess_root, s, ".aider.chat.history.md")
            if os.path.isfile(h_path):
                candidates.append((os.path.getmtime(h_path), s, h_path))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][2], candidates[0][1]

    root_history = os.path.join(af_dir, ".aider.chat.history.md")
    if os.path.isfile(root_history):
        return root_history, ""

    return "", session_name or ""


def resolve_editor_config(
    cwd: str, session_name: str = None, explicit_model: str = None
) -> dict:
    """Extract editor model and endpoint configurations from active session or env YAML."""
    candidates = []
    env_config = os.environ.get("AI_FACTORY_CONFIG")
    if env_config:
        candidates.append(env_config if os.path.isabs(env_config) else os.path.join(cwd, env_config))
    if session_name:
        candidates.append(os.path.join(cwd, ".aider_factory", "sessions", session_name, "session.yml"))
    candidates.append(os.path.join(cwd, ".aider_factory", ".env.yml"))
    candidates.append(os.path.join(cwd, ".env.yml"))

    config_path = next((p for p in candidates if os.path.isfile(p)), None)

    editor_model = explicit_model or "gemini/gemini-2.5-flash"
    editor_api_base = None
    weak_model = os.environ.get("AIDER_WEAK_MODEL") or os.environ.get("WEAK_MODEL")
    raw_weak_api_base = (
        os.environ.get("WEAK_MODEL_API_BASE")
        or os.environ.get("AIDER_WEAK_MODEL_API_BASE")
    )

    if config_path:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            models_cfg = cfg.get("models", {}) or {}
            phases = cfg.get("phases", []) or []
            phase_models = phases[0].get("models", {}) if phases and isinstance(phases[0], dict) else {}

            merged_models = {**models_cfg, **phase_models}
            if not explicit_model and merged_models.get("editor_agent"):
                editor_model = merged_models["editor_agent"]

            endpoints_cfg = cfg.get("endpoints", {}) or {}
            editor_api_base = endpoints_cfg.get("editor_api")

            weak_model = (
                merged_models.get("weak_model")
                or merged_models.get("weak_agent")
                or weak_model
            )
            raw_weak_api_base = (
                endpoints_cfg.get("weak_model_api_base")
                or endpoints_cfg.get("weak_model_api")
                or endpoints_cfg.get("weak_api_base")
                or raw_weak_api_base
            )
        except Exception:
            pass

    if is_valid_endpoint(editor_api_base):
        editor_api_base = editor_api_base
    else:
        editor_api_base = None

    if weak_model and not is_local_model(weak_model):
        weak_model_api_base = None
    elif is_valid_endpoint(raw_weak_api_base):
        weak_model_api_base = raw_weak_api_base
    elif weak_model and is_local_model(weak_model) and is_valid_endpoint(editor_api_base):
        weak_model_api_base = editor_api_base
    else:
        weak_model_api_base = None

    return {
        "editor_model": editor_model,
        "editor_api_base": editor_api_base,
        "weak_model": weak_model,
        "weak_model_api_base": weak_model_api_base,
    }


def run_apply(
    files: list,
    spec_file: str = None,
    turns: int = 1,
    model: str = None,
    session_name: str = None,
    no_diff: bool = False,
    stream: bool = False,
    cwd: str = None,
) -> bool:
    """Execute headless Aider application pass and stream git diff."""
    if not cwd:
        cwd = os.getcwd()

    if spec_file and os.path.isfile(spec_file):
        with open(spec_file, "r", encoding="utf-8") as f:
            spec_content = f.read()
    else:
        chat_path, resolved_session = find_active_session_chat_history(cwd, session_name)
        if not chat_path:
            print("❌ Error: No chat history found to parse spec from.", file=sys.stderr)
            return False
        if not session_name:
            session_name = resolved_session
        spec_content = parse_chat_history(chat_path, turns=turns)

    if not spec_content.strip():
        print("❌ Error: Could not parse a valid specification from chat history.", file=sys.stderr)
        return False

    EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    temp_cleanup_files = []
    try:
        temp_dir = os.path.join(cwd, ".aider_factory", "temp")
        os.makedirs(temp_dir, exist_ok=True)
        active_spec_path = os.path.join(temp_dir, "active_spec.md")
        with open(active_spec_path, "w", encoding="utf-8") as f:
            f.write(spec_content)

        cfg = resolve_editor_config(cwd, session_name=session_name, explicit_model=model)

        local_conf = os.path.join(cwd, ".aider_factory", ".aider.conf.yml")
        root_conf = os.path.join(cwd, ".aider.conf.yml")
        aider_conf = local_conf if os.path.exists(local_conf) else (root_conf if os.path.exists(root_conf) else None)

        local_settings = os.path.join(cwd, ".aider_factory", ".aider.model.settings.yml")
        root_settings = os.path.join(cwd, ".aider.model.settings.yml")
        aider_settings = local_settings if os.path.exists(local_settings) else (root_settings if os.path.exists(root_settings) else None)

        resolved_weak_model = cfg.get("weak_model")
        resolved_weak_api_base = cfg.get("weak_model_api_base")
        if resolved_weak_model and not is_local_model(resolved_weak_model):
            resolved_weak_api_base = None
        elif not is_valid_endpoint(resolved_weak_api_base):
            resolved_weak_api_base = None

        _litellm_key = os.environ.get("LITELLM_API_KEY", "")
        _openai_key = os.environ.get("OPENAI_API_KEY", "")
        _router_key = (
            _litellm_key if (_litellm_key and not is_dummy_key(_litellm_key))
            else (_openai_key if (_openai_key and not is_dummy_key(_openai_key)) else "sk-dummy")
        )

        if resolved_weak_model and resolved_weak_api_base:
            apply_settings = os.path.join(temp_dir, ".apply.aider.model.settings.yml")
            ensure_model_settings(
                target_path=apply_settings,
                models_to_configure=[
                    {
                        "name": resolved_weak_model,
                        "api_base": resolved_weak_api_base,
                        "api_key": _router_key,
                    }
                ],
                base_settings_path=aider_settings,
            )
            aider_settings = apply_settings

        # Sanitize aider_conf to prevent ambient read-only files (e.g. repo maps) from leaking into apply
        sanitized_conf = None
        if aider_conf:
            try:
                with open(aider_conf, "r", encoding="utf-8") as f:
                    raw_cfg = yaml.safe_load(f) or {}
                cleaned_cfg = {k: v for k, v in raw_cfg.items() if k not in ("read", "files")}
                cleaned_cfg["architect"] = False
                sanitized_conf = os.path.join(temp_dir, ".apply.aider.conf.yml")
                with open(sanitized_conf, "w", encoding="utf-8") as f:
                    yaml.safe_dump(cleaned_cfg, f)
            except Exception:
                sanitized_conf = aider_conf

        apply_chat_hist = os.path.join(temp_dir, f".apply.chat.history_{os.getpid()}.md")
        apply_input_hist = os.path.join(temp_dir, f".apply.input.history_{os.getpid()}")
        temp_cleanup_files.extend([apply_chat_hist, apply_input_hist])

        cmd = [
            "aider",
            "--model",
            cfg["editor_model"],
            "--editor-model",
            cfg["editor_model"],
            "--edit-format",
            "editor-diff",
            "--message-file",
            active_spec_path,
            "--no-restore-chat-history",
            "--chat-history-file",
            apply_chat_hist,
            "--input-history-file",
            apply_input_hist,
            "--map-tokens",
            "0",
            "--map-refresh",
            "manual",
            "--map-multiplier-no-files",
            "0",
            "--max-chat-history-tokens",
            "100000",
            "--no-check-update",
            "--no-show-release-notes",
            "--no-notifications",
            "--no-analytics",
            "--no-detect-urls",
            "--no-suggest-shell-commands",
            "--exit",
            "--auto-commits",
            "--no-show-model-warnings",
        ]

        if resolved_weak_model:
            cmd.extend(["--weak-model", resolved_weak_model])
        if sanitized_conf:
            cmd.extend(["--config", sanitized_conf])
        if aider_settings:
            cmd.extend(["--model-settings-file", aider_settings])

        for file_path in files:
            cmd.append(file_path)

        env = os.environ.copy()
        env["AIDER_ARCHITECT"] = "false"
        if cfg["editor_api_base"]:
            env["OPENAI_API_BASE"] = cfg["editor_api_base"]
            if _router_key and not is_dummy_key(_router_key):
                env["OPENAI_API_KEY"] = _router_key
            elif "OPENAI_API_KEY" not in env:
                env["OPENAI_API_KEY"] = "sk-dummy"
            env["OLLAMA_API_BASE"] = cfg["editor_api_base"]
            env["LM_STUDIO_API_BASE"] = cfg["editor_api_base"]
            if _router_key and not is_dummy_key(_router_key):
                env["LM_STUDIO_API_KEY"] = _router_key
            elif "LM_STUDIO_API_KEY" not in env:
                env["LM_STUDIO_API_KEY"] = "sk-dummy"
        if resolved_weak_api_base and is_valid_endpoint(resolved_weak_api_base):
            env["WEAK_MODEL_API_BASE"] = resolved_weak_api_base
            env["AIDER_WEAK_MODEL_API_BASE"] = resolved_weak_api_base
            if is_local_model(cfg.get("editor_model")) and not cfg["editor_api_base"] and "OPENAI_API_BASE" not in env:
                env["OPENAI_API_BASE"] = resolved_weak_api_base
                env["OPENAI_API_KEY"] = _router_key

        # --- Output isolation: /dev/tty for visibility, stdout for outer aider ---
        #
        # When aider-apply is invoked via aider's /run, the outer aider captures
        # our stdout (and stderr) as "command output" tokens. The inner aider
        # emits 40–120k raw bytes (file echoes, thinking blocks, ANSI codes,
        # commit confirmations). Streaming those to /dev/tty gives the user live
        # terminal visibility WITHOUT polluting the outer aider's context window.
        # Only the git diff (~3–4k tokens) is written to stdout.
        #
        # In pipeline mode (orchestrate.py), there is no outer aider capturing
        # stdout, so _aider_ask_turn streams to sys.stdout directly. See the
        # NOTE in orchestrate.py._aider_ask_turn for the inverse pattern.
        #
        # Default (stream=False): inner aider output is silently discarded.
        # Only the git diff at the end reaches stdout. Use --stream to watch.
        print(
            f"🚀 Running apply pass via {cfg['editor_model']} on files: {', '.join(files)}...",
            file=sys.stderr,
        )

        if sys.platform == "win32":
            try:
                aider_bin = shutil.which("aider") or "aider"
            except Exception:
                aider_bin = "aider"
            cmd[0] = aider_bin
            if aider_bin.lower().endswith((".cmd", ".bat")):
                comspec = os.environ.get("COMSPEC", "cmd.exe")
                cmd = [comspec, "/c"] + cmd

        popen_kwargs = {"start_new_session": True} if sys.platform != "win32" else {}
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            **popen_kwargs,
        )

        import threading
        try:
            timeout_secs = float(os.environ.get("AIDER_STREAM_TIMEOUT", "300"))
            if timeout_secs <= 0.0:
                timeout_secs = 300.0
        except (ValueError, TypeError):
            timeout_secs = 300.0

        timed_out = threading.Event()
        def _on_timeout():
            timed_out.set()
            kill_proc_tree(proc)

        watchdog = threading.Timer(timeout_secs, _on_timeout)
        watchdog.daemon = True
        watchdog.start()
        try:
            if stream:
                try:
                    if proc.stdin:
                        proc.stdin.write("n\n" * 50)
                        proc.stdin.flush()
                        proc.stdin.close()
                except Exception:
                    pass

                tty_fh = None
                try:
                    tty_path = "CONOUT$" if sys.platform == "win32" else "/dev/tty"
                    tty_fh = open(tty_path, "w", encoding="utf-8", errors="replace")
                except OSError:
                    pass

                try:
                    if proc.stdout:
                        while True:
                            try:
                                line = proc.stdout.readline()
                            except (ValueError, OSError):
                                break
                            if not line and proc.poll() is not None:
                                break
                            if line and tty_fh:
                                tty_fh.write(line)
                                tty_fh.flush()
                        try:
                            proc.stdout.close()
                        except Exception:
                            pass
                    proc.wait()
                finally:
                    if tty_fh:
                        tty_fh.close()
            else:
                try:
                    proc.communicate(input="n\n" * 50, timeout=timeout_secs)
                except subprocess.TimeoutExpired:
                    timed_out.set()
                    kill_proc_tree(proc)
                except Exception as e:
                    print(f"❌ Error: Aider apply execution failed with unexpected exception: {e}", file=sys.stderr)
                    kill_proc_tree(proc)
                    return False
        except KeyboardInterrupt:
            kill_proc_tree(proc)
            raise
        finally:
            watchdog.cancel()

        if timed_out.is_set():
            print(f"❌ Error: Aider apply execution timed out after {timeout_secs}s. Terminating process tree.", file=sys.stderr)
            return False

        if proc.returncode != 0:
            print(
                f"❌ Error: Aider apply execution failed with exit code {proc.returncode}",
                file=sys.stderr,
            )
            return False

        if not no_diff:
            print("\n" + "=" * 70)
            print("Git Diff Result:")
            print("=" * 70)
            try:
                git_bin = shutil.which("git") or "git"
            except Exception:
                git_bin = "git"
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

            git_cmd = [git_bin, "--no-pager", "diff", "--no-color", "--no-ext-diff", git_target, "HEAD"]
            if sys.platform == "win32" and git_bin.lower().endswith((".cmd", ".bat")):
                git_cmd = ["cmd.exe", "/c"] + git_cmd
            try:
                subprocess.run(git_cmd, cwd=cwd, timeout=30)
            except Exception as e:
                print(f"⚠️ Warning: Git diff execution failed or timed out: {e}", file=sys.stderr)

        return True
    finally:
        for p in temp_cleanup_files:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


def main():
    parser = argparse.ArgumentParser(
        description="aider-apply: Execute headless Aider code edit from chat history specs or spec files."
    )
    parser.add_argument("files", nargs="+", help="Target file(s) to edit.")
    parser.add_argument("--spec", "-s", default=None, help="Explicit spec file path.")
    parser.add_argument("--turns", "-t", type=int, default=1, help="Number of chat history turns to include in spec (default: 1).")
    parser.add_argument("--model", "-m", default=None, help="Override editor model.")
    parser.add_argument("--session", default=None, help="Target session name.")
    parser.add_argument("--no-diff", action="store_true", help="Suppress git diff output after apply.")
    parser.add_argument("--stream", action="store_true", help="Stream inner aider output to terminal (default: silent).")

    args = parser.parse_args()
    success = run_apply(
        files=args.files,
        spec_file=args.spec,
        turns=args.turns,
        model=args.model,
        session_name=args.session,
        no_diff=args.no_diff,
        stream=args.stream,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
