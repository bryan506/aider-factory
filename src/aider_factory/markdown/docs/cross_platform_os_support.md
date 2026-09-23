# Cross-Platform Architecture & OS Support Guide

## 1. Executive Overview & Foundational Invariants

The `aider-factory` suite is engineered to run natively across Linux (Ubuntu/Debian), macOS (Darwin), and Windows (Win32 / WSL2). Because the framework coordinates low-level operating system resources—including pseudo-terminals (PTYs), file descriptor multiplexing, process signal handling, and disk-locked vector databases—platform-specific behaviors are handled through deterministic branching rather than leaky abstractions.

### Core Cross-Platform Invariants

1. **Native Python Entrypoint Parity**: All capabilities are exposed as native Python console scripts in `pyproject.toml` (`aider-factory`, `aider-launcher`, `aider-oracle`, `aider-validate`, `aider-helper`, `aider-apply`, `aider-clean-lancedb`). On Windows, `uv` and `pip` generate executable `.exe` wrappers in `Scripts\`, eliminating any dependency on Bash wrappers for core workflows.
2. **Deterministic Stream Multiplexing**: Where POSIX kernel-level file descriptor duplication (`os.dup2` on fd 1 and 2) is supported (Linux and macOS), `OSTee` intercepts output at the kernel boundary. On Windows, where `os.dup2` on standard descriptors corrupts Python buffered I/O, output is multiplexed in user space via `_TeeWriter`.
3. **Platform-Aware PTY Emulation**: In interactive pair-programming mode (`pair_programming: true`), terminal emulation auto-selects between GNU `script -qfe` (Linux), BSD `script -q` (macOS), and direct line-buffered `subprocess.Popen` streaming (Windows).
4. **Normalized Forward-Slash Paths**: All configuration files (`.env.yml`, `session.yml`), template resolvers, active file exclusions, and LanceDB table locators normalize path separators to forward slashes (`/`), preventing backslash escape corruption across OS boundaries.
5. **NTFS File-Lock Release Before Deletion**: On Windows, open memory-mapped file handles (Arrow/LanceDB) hold locks that prevent directory cleanup. Processes explicitly release table handles and trigger Python garbage collection (`gc.collect()`) before directory removals.

---

## 2. Operating System Compatibility Matrix

| Capability / Subsystem | Linux (Ubuntu/Debian) | macOS (Apple Silicon / Intel) | Windows Native (CMD / PowerShell) | WSL 2 (Ubuntu on Windows) |
| :--- | :--- | :--- | :--- | :--- |
| **Core DAG Orchestration** | ✅ Full (`aider-factory`, `aider-launcher`) | ✅ Full (`aider-factory`, `aider-launcher`) | ✅ Full (`aider-factory`, `aider-launcher`) | ✅ Full (`aider-factory`, `aider-launcher`) |
| **Console Scripts** | ✅ Native in `~/.local/bin` | ✅ Native in `~/.local/bin` | ✅ Native in `Scripts\` | ✅ Native in `~/.local/bin` |
| **Bash Wrappers (`.aider_factory/bash/*`)** | ✅ Auto-provisioned (`+x`) | ✅ Auto-provisioned (`+x`) | ❌ Skipped by `cli.py` | ✅ Auto-provisioned (`+x`) |
| **Terminal Logging** | ✅ `OSTee` (`os.dup2` fd 1/2) | ✅ `OSTee` (`os.dup2` fd 1/2) | ⚠️ `_TeeWriter` (Stream Intercept) | ✅ `OSTee` (`os.dup2` fd 1/2) |
| **Interactive Pair Programming** | ✅ GNU `script -qfe` PTY | ✅ BSD `script -q` PTY | ⚠️ Direct `Popen` + line-tee | ✅ GNU `script -qfe` PTY |
| **Headless Apply Agent** | ✅ Native `/dev/tty` stream | ✅ Native `/dev/tty` stream | ✅ Native `CONOUT$` stream | ✅ Native `/dev/tty` stream |
| **SearXNG Auto-Provisioning** | ✅ User `systemd` + Podman/Docker | ⚠️ Manual / Docker Desktop | ⚠️ Manual / Docker Desktop | ✅ User `systemd` + Podman/Docker |
| **LanceDB Vector Database** | ✅ Native AVX-512 / Arrow | ✅ Native Accelerate / Arrow | ✅ Native PyArrow / Arrow | ✅ Native AVX-512 / Arrow |
| **Docling Multi-Format Ingestion** | ✅ `docling_runner.py` via `uv` | ✅ `docling_runner.py` via `uv` | ✅ `docling_runner.py` via `uv` | ✅ `docling_runner.py` via `uv` |
| **Verification Gate Shell Scripts (`.sh`)** | ✅ Native bash execution | ✅ Native zsh/bash execution | ⚠️ Requires Git Bash (`bash.exe`) | ✅ Native bash execution |

---

## 3. Technical Mechanics & OS-Specific Subsystems

### 3.1 Win32 Process Execution & Binary Resolution
On Windows, executable files typically carry `.exe`, `.cmd`, or `.bat` extensions. When `orchestrate.py` or `apply_agent.py` spawns Aider or Git:
1. `shutil.which("aider")` resolves the concrete executable on the system `%PATH%`.
2. If the resolved binary ends in `.cmd` or `.bat` (standard for npm or Python tool shims on Windows), the command is automatically prepended with `cmd.exe /c` to ensure reliable execution:
   ```python
   if sys.platform == "win32":
       aider_bin = shutil.which("aider") or "aider"
       cmd[0] = aider_bin
       if aider_bin.lower().endswith((".cmd", ".bat")):
           cmd = ["cmd.exe", "/c"] + cmd
   ```

### 3.2 Terminal Emulation & PTY Tri-Branch (`orchestrate.py`)
Aider's interactive user interface relies on `prompt_toolkit`, which requires a genuine TTY. When `pair_programming: true` is enabled, the orchestrator branches by OS platform:

```python
cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
if sys.platform == "win32":
    # Windows: ConPTY cannot be injected via standard script; run directly and
    # tee stdout line-by-line to the capture file for cost accounting.
    _cap_fh = open(_pair_capture, "w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        cmd, env=env, cwd=self.project_dir,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    try:
        if process.stdout:
            for _line in process.stdout:
                sys.stdout.write(_line)
                sys.stdout.flush()
                _cap_fh.write(_line)
            process.stdout.close()
    finally:
        _cap_fh.close()
elif sys.platform == "darwin":
    # macOS BSD script: positional arguments, no -e/-f flags.
    _shell = os.environ.get("SHELL", "/bin/bash")
    process = subprocess.Popen(
        ["script", "-q", _pair_capture, _shell, "-c", cmd_str],
        env=env, cwd=self.project_dir
    )
else:
    # Linux GNU script: flag-based invocation.
    process = subprocess.Popen(
        ["script", "-qfe", "-c", cmd_str, _pair_capture],
        env=env, cwd=self.project_dir
    )
```

### 3.3 Kernel-Level Multiplexing vs. Windows `_TeeWriter`
`run_workflow.py` multiplexes live terminal streaming with an unbuffered master log (`.aider_factory/logs/*.log`):
- **POSIX (Linux/macOS)**: Calls `os.dup(1)`, `os.dup(2)`, and `os.dup2(pipe_w, 1)`. All writes from C extensions, child subprocesses, and Python are captured at the file descriptor level.
- **Windows (`win32`)**: Calling `os.dup2` on standard descriptors causes unhandled access violations and buffer deadlocks with child processes. Windows branches to `_TeeWriter`, redirecting `sys.stdout` and `sys.stderr` to stream proxies that write to both the console and the log file simultaneously.

### 3.4 Headless Console Isolation (`CONOUT$` vs `/dev/tty`)
When `aider-apply` runs via Aider's `/run` directive, the parent Aider process captures `sys.stdout` as prompt tokens. To provide live visibility to the user without bloating the parent chat context:
- **POSIX**: Opens `/dev/tty` directly to write live progress lines.
- **Windows**: `/dev/tty` does not exist. `apply_agent.py` catches the platform discriminator and opens the Windows active console stream `CONOUT$`:
  ```python
  tty_path = "CONOUT$" if sys.platform == "win32" else "/dev/tty"
  tty_fh = open(tty_path, "w", encoding="utf-8", errors="replace")
  ```
  If no console is attached (e.g., headless CI runners), `open()` raises `OSError`, which is caught safely, falling back to silent buffer draining without deadlock.

### 3.5 NTFS File Locking & LanceDB Resource Teardown
Under Windows NTFS, open file handles hold strict byte locks. Attempting to delete a directory containing open `.lance` or SQLite files triggers `[WinError 32] The process cannot access the file because it is being used by another process`.
- Database maintenance routines in `oracle_agent.py` explicitly dereference open tables and connection handles (`del tbl, db`) and invoke `gc.collect()` before calling `shutil.rmtree()`.
- Test cleanup utilities employ an `onexc` / `onerror` handler that grants write permissions (`stat.S_IWRITE`) to read-only files before unlinking.

### 3.6 Windows Console UTF-8 Reconfiguration
Windows command prompts historically default to code page 1252 (ANSI Latin 1). To prevent `UnicodeEncodeError: 'charmap' codec can't encode character` when printing truecolor ANSI banners, emojis, and status logs, test runners and CLI tools reconfigure streams at launch:
```python
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
```

---

## 4. Windows Subsystem for Linux (WSL 2) Guide

For developers on Windows machines, **WSL 2 is the recommended environment** for executing complete autonomous pipelines.

### Why WSL 2 Delivers 100% Native Parity
Because WSL 2 runs a genuine Linux kernel inside a lightweight hypervisor:
1. `sys.platform` reports `"linux"`.
2. Bash validation scripts (`apply_evidence.sh`, `validations_context_check.sh`) execute natively.
3. User-level `systemd` is fully operational, enabling automatic provisioning of the rootless SearXNG service via `cli.py`.
4. True POSIX `/dev/tty` and PTY wrapping (`script -qfe`) operate without fallbacks.

### Setup Instructions for WSL 2
```bash
# 1. Open WSL terminal (Ubuntu 22.04 or 24.04 recommended)
wsl

# 2. Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# 3. Install build tools and ctags
sudo apt update && sudo apt install -y build-essential curl git universal-ctags podman

# 4. Clone and install aider-factory
git clone https://github.com/bryan506/aider-factory.git
cd aider-factory
uv pip install -e .
```

### The Performance Golden Rule for WSL 2
> **Crucial Rule:** Always clone and execute repositories inside the Linux virtual hard disk (`/home/<user>/projects/...`), **never** on the Windows mount (`/mnt/c/...`).

Accessing `/mnt/c/` crosses the 9P filesystem protocol boundary. Operating on `/mnt/c/` degrades Git operations, LanceDB vector queries, and Tree-Sitter parsing speeds by 5x to 10x. Native ext4 storage (`~`) delivers full bare-metal NVMe throughput.

---

## 5. Cross-Platform Troubleshooting Matrix

| Symptom | Operating System | Root Cause | Fix / Mitigation |
| :--- | :--- | :--- | :--- |
| `[WinError 193] %1 is not a valid Win32 application` | Windows Native | A test runner attempted to execute a `.sh` script directly via `subprocess.Popen`. | Use native test commands (`pytest`, `cargo test`, `npm test`) or run inside WSL 2. |
| `[WinError 32] The process cannot access the file` | Windows Native | LanceDB table handle held open during `shutil.rmtree()`. | Ensure table handles are closed and invoke `gc.collect()` before deleting vector directories. |
| `script: invalid option -- 'e'` | macOS | macOS uses BSD `script`, which does not accept GNU `-qfe` flags. | `orchestrate.py` automatically uses `script -q <log> <shell> -c <cmd>` on Darwin. |
| `UnicodeEncodeError: 'charmap' codec...` | Windows Native | Command Prompt / PowerShell console set to legacy cp1252 encoding. | Set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` in your environment. |
| SearXNG service does not start automatically | Windows Native / macOS | Systemd auto-provisioning is Linux-only. | Run SearXNG via Docker Desktop: `docker run -d -p 8088:8080 searxng/searxng:latest` and set `SEARXNG_BASE_URL="http://localhost:8088"`. |
| Slow file scanning or vector search | WSL 2 | Repository resides on Windows mount (`/mnt/c/...`). | Move the project to native WSL ext4 storage (`~/projects/...`). |
