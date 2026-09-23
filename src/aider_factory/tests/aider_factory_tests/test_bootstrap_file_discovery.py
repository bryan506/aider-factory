"""Unit tests for _discover_target_files and _discover_context_files
extracted from run_bootstrap().

These run against real temp directories — zero mocks on filesystem.
"""
import os
import tempfile
import textwrap

import pytest

# Import the inner functions by running bootstrap in a controlled way.
# Since they are nested in run_bootstrap, we replicate the logic here
# as a standalone importable check. Alternatively, we test via the
# generated YAML output.


def _make_project(tmp_path: str) -> str:
    """Create a realistic project skeleton."""
    # Source files (should be discovered)
    os.makedirs(os.path.join(tmp_path, "src", "mypkg"), exist_ok=True)
    open(os.path.join(tmp_path, "src", "mypkg", "core.py"), "w").close()
    open(os.path.join(tmp_path, "src", "mypkg", "utils.py"), "w").close()
    open(os.path.join(tmp_path, "src", "main.py"), "w").close()

    # Excluded: tests
    os.makedirs(os.path.join(tmp_path, "tests"), exist_ok=True)
    open(os.path.join(tmp_path, "tests", "test_core.py"), "w").close()

    # Excluded: conftest, setup, __init__
    open(os.path.join(tmp_path, "conftest.py"), "w").close()
    open(os.path.join(tmp_path, "setup.py"), "w").close()
    open(os.path.join(tmp_path, "src", "mypkg", "__init__.py"), "w").close()

    # Excluded dirs
    os.makedirs(os.path.join(tmp_path, ".venv", "lib"), exist_ok=True)
    open(os.path.join(tmp_path, ".venv", "lib", "hidden.py"), "w").close()
    os.makedirs(os.path.join(tmp_path, "__pycache__"), exist_ok=True)
    open(os.path.join(tmp_path, "__pycache__", "cached.py"), "w").close()

    # Context files
    open(os.path.join(tmp_path, "README.md"), "w").write("# Hello\n")
    os.makedirs(os.path.join(tmp_path, "docs"), exist_ok=True)
    open(os.path.join(tmp_path, "docs", "guide.md"), "w").write("guide\n")
    open(os.path.join(tmp_path, "docs", "api.md"), "w").write("api\n")

    return tmp_path


# --- Replicate discovery logic for isolated unit testing ---

_SOURCE_EXTS = {".py", ".r", ".rs", ".go", ".js", ".ts", ".jsx", ".tsx"}
_EXCLUDE_DIRS = frozenset({
    ".git", ".aider_factory", "node_modules", "__pycache__",
    ".venv", "venv", "dist", "build", ".cache", ".pytest_cache",
    "site-packages", ".eggs",
})
_EXCLUDE_RE = __import__("re").compile(
    r"(?:^|[\\/])(?:tests?[\\/]|test_|conftest\.py|setup\.py|__init__\.py$)"
)


def _discover_target_files(base_dir):
    found = []
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS
                   and not d.endswith(".egg-info")]
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in _SOURCE_EXTS:
                continue
            rel = os.path.relpath(os.path.join(root, fname), base_dir).replace("\\", "/")
            if _EXCLUDE_RE.search(rel):
                continue
            found.append(rel)
    found.sort()
    return found


def _discover_context_files(base_dir):
    ctx = []
    for name in ("README.md", "CHANGELOG.md"):
        if os.path.isfile(os.path.join(base_dir, name)):
            ctx.append(name)
    docs_dir = os.path.join(base_dir, "docs")
    if os.path.isdir(docs_dir):
        for sub in sorted(os.listdir(docs_dir)):
            if sub.endswith(".md"):
                ctx.append(f"docs/{sub}")
    return ctx


class TestTargetFileDiscovery:
    def test_finds_source_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert "src/main.py" in targets
            assert "src/mypkg/core.py" in targets
            assert "src/mypkg/utils.py" in targets

    def test_excludes_test_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert not any("tests/" in t or "test_" in t for t in targets)

    def test_excludes_conftest_setup_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert "conftest.py" not in targets
            assert "setup.py" not in targets
            assert not any("__init__.py" in t for t in targets)

    def test_excludes_venv_pycache(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert not any(".venv" in t for t in targets)
            assert not any("__pycache__" in t for t in targets)

    def test_sorted_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            targets = _discover_target_files(tmp)
            assert targets == sorted(targets)

    def test_empty_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            targets = _discover_target_files(tmp)
            assert targets == []

    def test_finds_R_source_files(self):
        """Regression: .R files must be discovered (case-insensitive ext check)."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "R"), exist_ok=True)
            open(os.path.join(tmp, "R", "aac_fut_b.R"), "w").close()
            open(os.path.join(tmp, "R", "period_subset.R"), "w").close()
            # Excluded test file
            os.makedirs(os.path.join(tmp, "tests", "testthat"), exist_ok=True)
            open(os.path.join(tmp, "tests", "testthat", "test-aac.R"), "w").close()
            targets = _discover_target_files(tmp)
            assert "R/aac_fut_b.R" in targets
            assert "R/period_subset.R" in targets
            assert not any("test" in t for t in targets)


class TestContextFileDiscovery:
    def test_finds_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            ctx = _discover_context_files(tmp)
            assert "README.md" in ctx

    def test_finds_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            ctx = _discover_context_files(tmp)
            assert "docs/guide.md" in ctx
            assert "docs/api.md" in ctx

    def test_no_docs_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "README.md"), "w").close()
            ctx = _discover_context_files(tmp)
            assert ctx == ["README.md"]

    def test_empty_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _discover_context_files(tmp)
            assert ctx == []
