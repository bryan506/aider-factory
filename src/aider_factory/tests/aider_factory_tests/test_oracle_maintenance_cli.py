#!/usr/bin/env python3
# test_oracle_maintenance_cli.py — Unit, integration, and E2E tests for LanceDB maintenance CLI.

import os
import shutil
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "../../python"))

import lancedb
from lancedb.pydantic import LanceModel, Vector
import oracle_agent
from oracle_agent import (
    _add_maintenance,
    _extract_overrides,
    _list_files,
    _remove_db,
    _remove_file,
    _remove_table,
)

print("Starting Oracle Maintenance CLI Tests...\n")


def test_maintenance_flags_parsing():
    # Test --list-files
    args = ["--list-files"]
    out, do_list, did_clear, action, target = _extract_overrides(args)
    assert action == "list-files", f'Expected action "list-files", got {action}'
    assert target is None

    # Test --rm-table
    args = ["--rm-table", "test_table_name"]
    out, do_list, did_clear, action, target = _extract_overrides(args)
    assert action == "rm-table"
    assert target == "test_table_name"

    # Test --rm-file
    args = ["--rm-file", "my_code.R"]
    out, do_list, did_clear, action, target = _extract_overrides(args)
    assert action == "rm-file"
    assert target == "my_code.R"

    # Test --rm-db
    args = ["--rm-db"]
    out, do_list, did_clear, action, target = _extract_overrides(args)
    assert action == "rm-db"
    assert target is None

    print("  [Unit] CLI maintenance flags parsed correctly.")


def test_add_flags_parsing():
    # Test --add-file with single file
    args = ["--add-file", "my_file.pdf"]
    out, do_list, did_clear, action, target = _extract_overrides(args)
    assert action == "add-file", f'Expected action "add-file", got {action}'
    assert target == ["my_file.pdf"], f"Expected ['my_file.pdf'], got {target}"

    # Test --add-file with multiple files (stacking)
    args = ["--add-file", "file1.pdf", "file2.txt", "file3.py"]
    out, do_list, did_clear, action, target = _extract_overrides(args)
    assert action == "add-file"
    assert target == ["file1.pdf", "file2.txt", "file3.py"]

    # Test --add-table with single path
    args = ["--add-table", "my_folder"]
    out, do_list, did_clear, action, target = _extract_overrides(args)
    assert action == "add-table"
    assert target == ["my_folder"]

    # Test --add-table with multiple paths (stacking)
    args = ["--add-table", "folder1", "folder2", "file.pdf"]
    out, do_list, did_clear, action, target = _extract_overrides(args)
    assert action == "add-table"
    assert target == ["folder1", "folder2", "file.pdf"]

    print("  [Unit] CLI add maintenance flags parsed correctly.")


def test_lancedb_operations():
    # Set up a temporary database in temp/
    temp_db_dir = os.path.join(script_dir, "../../temp/test_maint_lancedb")
    if os.path.exists(temp_db_dir):
        shutil.rmtree(temp_db_dir)
    os.makedirs(temp_db_dir, exist_ok=True)

    # Configure environment overrides
    os.environ["ORACLE_RAG_DB_DIR"] = temp_db_dir
    os.environ["ORACLE_COLLECTION"] = "test_col"

    db = lancedb.connect(temp_db_dir)

    # Create test schemas
    class TestChunk(LanceModel):
        text: str
        vector: Vector(1536)
        source_file: str

    # Create tables
    t1_name = "test_col_code"
    t2_name = "test_col_docs"
    t3_name = "other_col_code"  # Should be ignored when filtering by test_col

    tbl1 = db.create_table(t1_name, schema=TestChunk, mode="overwrite")
    tbl2 = db.create_table(t2_name, schema=TestChunk, mode="overwrite")
    tbl3 = db.create_table(t3_name, schema=TestChunk, mode="overwrite")

    # Insert data
    tbl1.add(
        [
            {"text": "chunk1", "vector": [0.1] * 1536, "source_file": "R/aac.R"},
            {"text": "chunk2", "vector": [0.2] * 1536, "source_file": "R/helpers.R"},
        ]
    )
    tbl2.add([{"text": "chunk3", "vector": [0.3] * 1536, "source_file": "README.md"}])
    tbl3.add([{"text": "chunk4", "vector": [0.4] * 1536, "source_file": "R/aac.R"}])

    print("  [Integration] Temporary mock tables created.")

    # 1. Test listing files
    rc = _list_files()
    assert rc == 0, f"Expected 0, got {rc}"

    # 2. Test surgical file delete (exact match)
    rc = _remove_file("R/helpers.R")
    assert rc == 0
    # Verify R/helpers.R is gone from tbl1 (reopen to see updated MVCC snapshot)
    tbl1 = db.open_table(t1_name)
    rows = tbl1.to_arrow().to_pylist()
    print("ROWS AFTER DELETE:", rows)
    assert len(rows) == 1
    assert rows[0]["source_file"] == "R/aac.R"
    print("  [Integration] Surgical file delete (exact match) verified.")

    # 3. Test surgical file delete (suffix match)
    rc = _remove_file("aac.R")
    assert rc == 0
    # Since tbl1 became empty, it should have been dropped
    assert t1_name not in db.table_names()
    print(
        "  [Integration] Surgical file delete (suffix match) and empty table drop verified."
    )

    # Verify tbl3 (other_col_code) was NOT touched because it belongs to 'other_col'
    assert t3_name in db.table_names()
    tbl3_opened = db.open_table(t3_name)
    assert tbl3_opened.count_rows() == 1
    print(
        "  [Integration] Collection isolation verified (other collections untouched)."
    )

    # 4. Test removing a specific table
    rc = _remove_table(t2_name)
    assert rc == 0
    assert t2_name not in db.table_names()
    print("  [Integration] Table drop verified.")

    # 5. Test removing the entire database
    rc = _remove_db()
    assert rc == 0
    assert not os.path.exists(temp_db_dir)
    print("  [Integration] Database wipe verified.")


def test_add_operations():
    import os
    import shutil

    import rag_manager

    print("  [Integration] Starting --add-file and --add-table operation tests...")

    # Set up temporary paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))

    test_collection = "test_maint_add_col"
    context_root = os.path.join(os.getcwd(), ".aider_factory", "markdown", "lanceDB")
    job_dir = os.path.join(context_root, test_collection)

    # Clean up any leftover test directories
    if os.path.exists(job_dir):
        shutil.rmtree(job_dir)

    # Create external test file
    external_file = os.path.join(project_dir, "temp", "test_external_file.txt")
    os.makedirs(os.path.dirname(external_file), exist_ok=True)
    with open(external_file, "w", encoding="utf-8") as f:
        f.write("mock content for testing add-file")

    # Create external test directory
    external_dir = os.path.join(project_dir, "temp", "test_external_dir")
    if os.path.exists(external_dir):
        shutil.rmtree(external_dir)
    os.makedirs(external_dir, exist_ok=True)
    with open(
        os.path.join(external_dir, "file_in_dir.txt"), "w", encoding="utf-8"
    ) as f:
        f.write("mock content for file inside directory")

    # Mock rag_manager.ingest
    ingest_calls = []

    def mock_ingest(*args, **kwargs):
        ingest_calls.append((args, kwargs))
        return True

    orig_ingest = rag_manager.ingest
    rag_manager.ingest = mock_ingest

    orig_rag_root = getattr(oracle_agent, "rag_context_root", None)
    oracle_agent.rag_context_root = context_root

    try:
        # Set environment override for collection
        os.environ["ORACLE_COLLECTION"] = test_collection
        os.environ["ORACLE_EXPLICIT_COLLECTION"] = "1"

        # 1. Test adding a file
        rc = _add_maintenance("file", [external_file])
        assert rc == 0, f"Expected 0, got {rc}"

        # Verify that collection directory was bootstrapped
        assert os.path.exists(job_dir), "Collection directory was not created"

        # Verify that file was copied into collection directory
        copied_file = os.path.join(job_dir, "test_external_file.txt")
        assert os.path.exists(copied_file), (
            "File was not copied to collection directory"
        )
        with open(copied_file, "r", encoding="utf-8") as f:
            assert f.read() == "mock content for testing add-file"

        # Verify that rag_manager.ingest was called with correct collection and overwrite=False
        assert len(ingest_calls) == 1, (
            f"Expected 1 ingest call, got {len(ingest_calls)}"
        )
        _, kwargs = ingest_calls[0]
        assert kwargs["collection_name"] == test_collection
        assert kwargs["overwrite"] is False

        # 2. Test adding a directory (table)
        rc = _add_maintenance("table", [external_dir])
        assert rc == 0, f"Expected 0, got {rc}"

        # Verify that directory was copied recursively
        copied_dir = os.path.join(job_dir, "test_external_dir")
        assert os.path.exists(copied_dir), (
            "Directory was not copied to collection directory"
        )
        copied_file_in_dir = os.path.join(copied_dir, "file_in_dir.txt")
        assert os.path.exists(copied_file_in_dir), (
            "File inside directory was not copied"
        )
        with open(copied_file_in_dir, "r", encoding="utf-8") as f:
            assert f.read() == "mock content for file inside directory"

        # Verify that rag_manager.ingest was called again
        assert len(ingest_calls) == 2, (
            f"Expected 2 ingest calls, got {len(ingest_calls)}"
        )

        # 3. Test self-containment (adding a file that is already inside the collection directory)
        # It should skip copying but still run ingestion
        rc = _add_maintenance("file", [copied_file])
        assert rc == 0
        assert len(ingest_calls) == 3

        print(
            "  [Integration] --add-file and --add-table operations verified successfully."
        )

    finally:
        os.environ.pop("ORACLE_EXPLICIT_COLLECTION", None)
        # Restore original ingest function and rag_context_root
        rag_manager.ingest = orig_ingest
        if orig_rag_root is not None:
            oracle_agent.rag_context_root = orig_rag_root

        # Clean up files and directories created during the test
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir)
        if os.path.exists(external_file):
            os.remove(external_file)
        if os.path.exists(external_dir):
            shutil.rmtree(external_dir)


if __name__ == "__main__":
    test_maintenance_flags_parsing()
    test_add_flags_parsing()
    test_lancedb_operations()
    test_add_operations()
    print("\n🎉 All LanceDB Maintenance CLI Tests Passed!")
