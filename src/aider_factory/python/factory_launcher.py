#!/usr/bin/env python3
"""factory_launcher.py — Cross-platform Python equivalent of bash/factory.

Launches run_workflow.py, tees all output to a timestamped log file,
then runs aggregate_costs.py on the log. Preserves the workflow exit code.

Usage:
    aider-launcher [options] [session_name] [config_file.yml]
    python factory_launcher.py [options] [session_name] [config_file.yml]
"""

import datetime
import os
import subprocess
import sys
import threading


def _resolve_config(argv):
    """Find the config file path from argv or default locations.

    Scans argv for the first positional argument ending in .yml/.yaml.
    If none found, falls back to .aider_factory/.env.yml then .env.yml
    in the current working directory.

    Returns the config path string, or None if nothing found.
    """
    for arg in argv:
        if arg.startswith("-"):
            continue
        if arg.endswith((".yml", ".yaml")):
            if os.path.isabs(arg):
                return arg
            candidate = os.path.join(os.getcwd(), arg)
            if os.path.isfile(candidate):
                return candidate
            return arg  # pass through even if missing; workflow will error
    cwd = os.getcwd()
    default = os.path.join(cwd, ".aider_factory", ".env.yml")
    if os.path.isfile(default):
        return default
    fallback = os.path.join(cwd, ".env.yml")
    if os.path.isfile(fallback):
        return fallback
    return None


def _derive_log_path(config_path):
    """Derive a timestamped log file path from the config file stem.

    Creates the logs directory if it does not exist.
    Returns the absolute path to the log file.
    """
    cwd = os.getcwd()
    logs_dir = os.path.join(cwd, ".aider_factory", "logs")
    os.makedirs(logs_dir, exist_ok=True)
    if config_path:
        stem = os.path.splitext(os.path.basename(config_path))[0].lstrip(".")
    else:
        stem = "env"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(logs_dir, f"{stem}_run_{timestamp}.log")


def main():
    """Entry point: launch workflow, tee output, aggregate costs, exit."""
    # Handle --help early
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(
            "aider-launcher: Cross-platform AI Factory pipeline launcher.\n"
            "\n"
            "Usage:\n"
            "  aider-launcher [options] [session_name] [config_file.yml]\n"
            "\n"
            "Equivalent to bash/factory but works on Linux, macOS, and Windows.\n"
            "Launches run_workflow.py, tees output to a log file, then runs\n"
            "aggregate_costs.py on the log. Preserves the workflow exit code.\n"
            "\n"
            "Options:\n"
            "  -h, --help            Show this help message and exit.\n"
            "  -s, --session <name>  Explicit session identifier.\n"
        )
        sys.exit(0)

    config_path = _resolve_config(sys.argv[1:])
    log_path = _derive_log_path(config_path)

    workflow_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "run_workflow.py"
    )
    if not os.path.isfile(workflow_script):
        print(
            f"❌ Error: run_workflow.py not found at {workflow_script}",
            file=sys.stderr,
        )
        sys.exit(1)

    print("=" * 70)
    print("Starting AI Factory Pipeline")
    print(f"   Config: {config_path or '(auto-detect)'}")
    print(f"   Log:    {log_path}")
    print("=" * 70)

    env = os.environ.copy()
    # FORCE_COLOR=1 tells rich (Aider's terminal library) to emit ANSI colors
    # even when stdout is a pipe. The log file captures raw ANSI codes.
    env["FORCE_COLOR"] = "1"

    cmd = [sys.executable, workflow_script] + sys.argv[1:]

    log_fh = open(log_path, "w", encoding="utf-8", errors="replace")

    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    def _pump():
        """Read subprocess output and write to both terminal and log file."""
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                # Write raw bytes to terminal (preserves ANSI colors)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                # Decode for the log file (lossy on invalid UTF-8)
                log_fh.write(chunk.decode("utf-8", errors="replace"))
                log_fh.flush()
        except Exception:
            pass

    pump_thread = threading.Thread(target=_pump, daemon=True)
    pump_thread.start()
    proc.wait()
    pump_thread.join(timeout=5.0)
    log_fh.close()

    exit_code = proc.returncode

    # Cost aggregation (same as bash/factory step 4)
    print()
    print("=" * 70)
    print("Run Completed. Aggregating Costs...")
    print("=" * 70)

    agg_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "aggregate_costs.py"
    )
    if os.path.isfile(agg_script):
        subprocess.run([sys.executable, agg_script, log_path], check=False)
    else:
        print(
            f"⚠️  aggregate_costs.py not found at {agg_script}; skipping.",
            file=sys.stderr,
        )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
