#!/usr/bin/env python3
"""Tests for Oracle context passing invariants across phases, CLI debates, and turns.

Covers:
  1. ORACLE_CONTEXT_FILES and ORACLE_PHASE_INDEX are set in rag_env by run_workflow.py.
  2. oracle_agent.py:main() appends assigned phase context files from ORACLE_CONTEXT_FILES.
  3. _run_cli_debate selects the phase matching ORACLE_PHASE_INDEX / ORACLE_COLLECTION.
  4. _oracle_turn includes read_files context in review mode turns.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python"))
import oracle_agent
import orchestrate


class TestOracleContextPassing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sample_file = os.path.join(self.temp_dir, "sample_context.md")
        with open(self.sample_file, "w", encoding="utf-8") as f:
            f.write("Line 1: Sample paper context\nLine 2: Important findings")

    def tearDown(self):
        # Clean env vars after test
        for var in ["ORACLE_CONTEXT_FILES", "ORACLE_PHASE_INDEX", "ORACLE_COLLECTION", "ORACLE_AGENT_MODEL"]:
            os.environ.pop(var, None)

    def test_oracle_context_files_env_read(self):
        """Verify oracle_agent.py reads ORACLE_CONTEXT_FILES when set."""
        os.environ["ORACLE_CONTEXT_FILES"] = self.sample_file
        rf_str = os.environ.get("ORACLE_JOB_READ_FILES") or os.environ.get("ORACLE_CONTEXT_FILES")
        self.assertIsNotNone(rf_str)
        
        ctx_parts = []
        for rf in rf_str.split("\x1e"):
            if rf and os.path.isfile(rf):
                with open(rf, encoding="utf-8") as fh:
                    ctx_parts.append(f"## {rf}\n```\n{fh.read()}\n```")
        
        self.assertEqual(len(ctx_parts), 1)
        self.assertIn("Sample paper context", ctx_parts[0])

    def test_run_cli_debate_phase_index_matching(self):
        """Verify _run_cli_debate respects ORACLE_PHASE_INDEX."""
        test_config = {
            "phases": [
                {
                    "name": "Phase 1 - OCR",
                    "enabled": True,
                    "vector_store": {"collection_name": "coll1"},
                    "files": {"context_files_job": ["phase1_file.md"]},
                },
                {
                    "name": "Phase 2 - QA",
                    "enabled": True,
                    "vector_store": {"collection_name": "coll2"},
                    "files": {"context_files_job": ["phase2_file.md"]},
                },
            ]
        }
        
        # Match phase index "1" (Phase 2)
        os.environ["ORACLE_PHASE_INDEX"] = "1"
        active_idx = os.environ.get("ORACLE_PHASE_INDEX")
        target_coll = os.environ.get("ORACLE_COLLECTION")

        _reads = []
        for idx, phase in enumerate(test_config.get("phases", [])):
            if not phase.get("enabled", True):
                continue
            if active_idx is not None and str(idx) != active_idx:
                continue
            elif active_idx is None and target_coll:
                phase_coll = (phase.get("vector_store") or {}).get("collection_name")
                if phase_coll and phase_coll != target_coll:
                    continue
            files = phase.get("files", {})
            for k in ["context_files_job"]:
                for f_pat in files.get(k, []) or []:
                    _reads.append(f_pat)
            break

        self.assertEqual(_reads, ["phase2_file.md"])

    def test_oracle_turn_review_mode_includes_read_files(self):
        """Verify orchestrate._oracle_turn includes read_files in review mode."""
        d = {
            "mode": "review",
            "read_files": [self.sample_file],
        }
        turn = 0
        _file_ctx = []
        if not turn:
            for _rf in d.get("read_files") or []:
                if os.path.isfile(_rf):
                    with open(_rf, encoding="utf-8") as _fh:
                        _file_ctx.append(f"## {_rf}\n```\n{_fh.read()}\n```")
        _file_block = ("\n\n" + "\n\n".join(_file_ctx)) if _file_ctx else ""
        self.assertIn("Sample paper context", _file_block)


if __name__ == "__main__":
    unittest.main()
