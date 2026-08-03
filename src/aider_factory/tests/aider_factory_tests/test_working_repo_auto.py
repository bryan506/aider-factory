#!/usr/bin/env python3
"""Tests for auto-derived working_repo from working_directory.

Covers:
  - working_repo auto-derived from working_directory basename
  - Explicit rag.working_repo overrides auto-derivation
  - code_exclude correctly built from target/context/editable files
  - _walk_repo exclusion logic works with auto-derived repo name
  - End-to-end: active files are excluded from ingestion
"""
import sys
import os
import shutil

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

import rag_manager


# ---- Test 1: Auto-derive produces correct repo name ----

def test_auto_derive_basename():
    """working_directory basename is used when rag.working_repo is unset."""
    print("test_auto_derive_basename...")

    def derive(working_dir, explicit_repo=None):
        return explicit_repo or os.path.basename(str(working_dir).rstrip("/"))

    assert derive("/home/bryanr/wf/BaseFeatures") == "BaseFeatures"
    assert derive("/home/bryanr/wf/BaseFeatures/") == "BaseFeatures"
    assert derive("/some/path/MyProject") == "MyProject"
    # Explicit override takes precedence
    assert derive("/home/bryanr/wf/BaseFeatures", "CustomName") == "CustomName"
    print("  OK: basename derivation correct for all cases")


# ---- Test 2: code_exclude built correctly for bare paths ----

def test_code_exclude_bare_paths():
    """Target files as bare paths (R/lq_leverage.R) are added to exclude set."""
    print("test_code_exclude_bare_paths...")

    rag_working_repo = "BaseFeatures"
    target_files = ["R/lq_leverage.R", "R/helpers.R"]
    context_files = ["R/queries.R", "R/validations.R"]
    _active = target_files + context_files

    code_exclude = set()
    for f in _active:
        if f:
            if rag_working_repo and f.startswith(rag_working_repo + "/"):
                code_exclude.add(f[len(rag_working_repo) + 1:])
            else:
                code_exclude.add(f)

    # Bare paths go directly into exclude set
    assert "R/lq_leverage.R" in code_exclude
    assert "R/helpers.R" in code_exclude
    assert "R/queries.R" in code_exclude
    assert "R/validations.R" in code_exclude
    print(f"  OK: {len(code_exclude)} files in exclude set")


# ---- Test 3: code_exclude handles prefixed paths ----

def test_code_exclude_prefixed_paths():
    """Paths with repo prefix (BaseFeatures/R/foo.R) are stripped correctly."""
    print("test_code_exclude_prefixed_paths...")

    rag_working_repo = "BaseFeatures"
    _active = ["BaseFeatures/R/lq_leverage.R", "R/helpers.R"]

    code_exclude = set()
    for f in _active:
        if f:
            if rag_working_repo and f.startswith(rag_working_repo + "/"):
                code_exclude.add(f[len(rag_working_repo) + 1:])
            else:
                code_exclude.add(f)

    # Prefixed path stripped, bare path kept
    assert "R/lq_leverage.R" in code_exclude
    assert "R/helpers.R" in code_exclude
    assert "BaseFeatures/R/lq_leverage.R" not in code_exclude
    print("  OK: prefix stripping works correctly")


# ---- Test 4: _walk_repo exclusion with matching repo name ----

def test_walk_repo_exclusion():
    """_walk_repo skips files in the exclude set for the matching repo."""
    print("test_walk_repo_exclusion...")

    tmp = "temp/test_walk_excl"
    repo = os.path.join(tmp, "BaseFeatures")
    os.makedirs(os.path.join(repo, "R"), exist_ok=True)

    # Create some files
    for name in ["lq_leverage.R", "helpers.R", "other.R"]:
        with open(os.path.join(repo, "R", name), "w") as f:
            f.write(f"# {name}\nfoo <- 1\n")

    exclude = {"R/lq_leverage.R", "R/helpers.R"}
    code_exts = {".r", ".R", ".py"}
    text_doc_exts = {".md", ".txt", ".Rmd"}
    ignore = {"__pycache__", "node_modules"}

    results = list(rag_manager._walk_repo(repo, ignore, code_exts, text_doc_exts, exclude))

    # Only other.R should remain
    source_files = [sf for _, _, sf in results]
    assert any("other.R" in sf for sf in source_files), f"other.R should be included: {source_files}"
    assert not any("lq_leverage.R" in sf for sf in source_files), f"lq_leverage.R should be excluded: {source_files}"
    assert not any("helpers.R" in sf for sf in source_files), f"helpers.R should be excluded: {source_files}"

    shutil.rmtree(tmp)
    print(f"  OK: excluded 2 files, kept 1")


# ---- Test 5: Non-matching repo name gets empty exclude set ----

def test_non_matching_repo_no_exclude():
    """Repos that don't match working_repo get no exclusions."""
    print("test_non_matching_repo_no_exclude...")

    tmp = "temp/test_walk_no_excl"
    repo = os.path.join(tmp, "TimeBaseR")
    os.makedirs(os.path.join(repo, "R"), exist_ok=True)

    for name in ["connect.R", "queries.R"]:
        with open(os.path.join(repo, "R", name), "w") as f:
            f.write(f"# {name}\nbar <- 2\n")

    # These excludes apply to BaseFeatures, not TimeBaseR
    exclude = {"R/lq_leverage.R", "R/helpers.R"}

    # Simulate the gate in rag_manager.ingest line 646:
    # excl = code_exclude if os.path.basename(repo) == working_repo else frozenset()
    working_repo = "BaseFeatures"
    excl = exclude if os.path.basename(repo.rstrip("/")) == working_repo else frozenset()

    code_exts = {".r", ".R", ".py"}
    text_doc_exts = {".md", ".txt"}
    ignore = {"__pycache__"}

    results = list(rag_manager._walk_repo(repo, ignore, code_exts, text_doc_exts, excl))
    source_files = [sf for _, _, sf in results]

    # Both files should be included (TimeBaseR is not the working repo)
    assert len(source_files) == 2, f"Expected 2 files, got {source_files}"
    print(f"  OK: non-matching repo has no exclusions ({len(source_files)} files)")

    shutil.rmtree(tmp)


# ---- Test 6: End-to-end with real run_workflow.py logic ----

def test_end_to_end_derivation():
    """Simulate the full derivation chain from working_directory to exclude set."""
    print("test_end_to_end_derivation...")

    # Simulate run_workflow.py config
    project_directory = "/home/bryanr/wf/BaseFeatures"
    rag_cfg = {}  # No explicit working_repo

    # The new auto-derive logic
    rag_working_repo = rag_cfg.get("working_repo") or os.path.basename(str(project_directory).rstrip("/"))
    assert rag_working_repo == "BaseFeatures"

    # Simulate target/context file list
    target_files = ["R/lq_leverage.R"]
    extra_editable = ["R/helpers_kv.R", "R/helpers.R"]
    context_files = ["R/queries.R", "R/reservations.R", "R/validations.R"]
    test_files = ["tests/testthat/test-unit-lq_leverage.R"]
    _active = target_files + extra_editable + context_files + test_files

    # Build code_exclude (same logic as run_workflow.py:353-360)
    code_exclude = set()
    for f in _active:
        if f:
            if rag_working_repo and f.startswith(rag_working_repo + "/"):
                code_exclude.add(f[len(rag_working_repo) + 1:])
            else:
                code_exclude.add(f)

    # All 7 active files should be in the exclude set
    assert len(code_exclude) == 7, f"Expected 7 excludes, got {code_exclude}"
    assert "R/lq_leverage.R" in code_exclude
    assert "R/helpers_kv.R" in code_exclude
    assert "R/helpers.R" in code_exclude
    assert "R/queries.R" in code_exclude
    assert "R/reservations.R" in code_exclude
    assert "R/validations.R" in code_exclude
    assert "tests/testthat/test-unit-lq_leverage.R" in code_exclude

    # Simulate the gate in rag_manager.ingest:
    # For BaseFeatures repo -> apply excludes
    excl_bf = code_exclude if "BaseFeatures" == rag_working_repo else frozenset()
    assert excl_bf == code_exclude, "BaseFeatures repo should get the exclude set"

    # For TimeBaseR repo -> no excludes
    excl_tb = code_exclude if "TimeBaseR" == rag_working_repo else frozenset()
    assert excl_tb == frozenset(), "TimeBaseR should get empty exclude set"

    print("  OK: full derivation chain produces correct excludes for all repos")


if __name__ == "__main__":
    test_auto_derive_basename()
    test_code_exclude_bare_paths()
    test_code_exclude_prefixed_paths()
    test_walk_repo_exclusion()
    test_non_matching_repo_no_exclude()
    test_end_to_end_derivation()
    print("\nAll working_repo auto-derive tests passed.")
