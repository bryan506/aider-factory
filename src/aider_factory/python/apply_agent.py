#!/usr/bin/env python3
# apply_agent.py

import argparse
import os
import re
import subprocess
import sys
import yaml

try:
    from aider_factory.python.env_utils import load_env_files
except ImportError:
    try:
        from env_utils import load_env_files
    except ImportError:
        load_env_files = None

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
        sess_history = os.path.join(
            af_dir, "sessions", session_name, ".aider.chat.history.md"
        )
        if os.path.isfile(sess_history):
            return sess_history, session_name

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

    return "", ""


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
            editor_api_base = endpoints_cfg.get("editor_ollama_api")
        except Exception:
            pass

    return {
        "editor_model": editor_model,
        "editor_api_base": editor_api_base,
    }


def run_apply(
    files: list,
    spec_file: str = None,
    turns: int = 1,
    model: str = None,
    session_name: str = None,
    no_diff: bool = False,
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

    apply_chat_hist = os.path.join(temp_dir, ".apply.chat.history.md")
    apply_input_hist = os.path.join(temp_dir, ".apply.input.history")

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
        "--no-detect-urls",
        "--no-suggest-shell-commands",
        "--yes-always",
        "--auto-commits",
        "--no-show-model-warnings",
    ]

    if aider_conf:
        cmd.extend(["--config", aider_conf])
    if aider_settings:
        cmd.extend(["--model-settings-file", aider_settings])

    for file_path in files:
        cmd.append(file_path)

    env = os.environ.copy()
    env["AIDER_ARCHITECT"] = "false"
    if cfg["editor_api_base"]:
        env["OPENAI_API_BASE"] = cfg["editor_api_base"]
        env["OPENAI_API_KEY"] = env.get("OPENAI_API_KEY", "sk-dummy")
        env["OLLAMA_API_BASE"] = cfg["editor_api_base"]
        env["LM_STUDIO_API_BASE"] = cfg["editor_api_base"]
        env["LM_STUDIO_API_KEY"] = "sk-dummy"

    print(f"🚀 Running apply pass via {cfg['editor_model']} on files: {', '.join(files)}...")
    proc = subprocess.run(cmd, cwd=cwd, env=env)

    if proc.returncode != 0:
        print(f"❌ Error: Aider apply execution failed with exit code {proc.returncode}", file=sys.stderr)
        return False

    if not no_diff:
        print("\n" + "=" * 70)
        print("Git Diff Result (HEAD~1):")
        print("=" * 70)
        subprocess.run(["git", "--no-pager", "diff", "HEAD~1"], cwd=cwd)

    return True


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

    args = parser.parse_args()
    success = run_apply(
        files=args.files,
        spec_file=args.spec,
        turns=args.turns,
        model=args.model,
        session_name=args.session,
        no_diff=args.no_diff,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
