import os
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../python")))
import lancedb
from lancedb.pydantic import LanceModel, Vector
import rag_manager
import validator


class TestE2EOracleClaims(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        os.chdir(self.original_cwd)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_e2e_physical_claims_validation_and_report_generation(self):
        """Zero-mock physical test: validates markdown against LanceDB and verifies on-disk report."""
        coll_dir = os.path.join(self.temp_dir, ".aider_factory", "markdown", "lanceDB", "test_claims")
        db_dir = os.path.join(coll_dir, "lancedb")
        os.makedirs(db_dir, exist_ok=True)

        # Resolve correct embedder model and endpoint
        embed_api_base = os.environ.get("EMBED_API_BASE", "http://192.168.100.1:8080/v1")
        embed_model = os.environ.get(
            "EMBED_MODEL",
            "qwen3-embedding-8b-8k-gpu:LATEST" if "192.168.100.1" in embed_api_base else "qwen3-embedding-8b-8k:LATEST"
        )
        os.environ["EMBED_API_BASE"] = embed_api_base
        os.environ["EMBED_MODEL"] = embed_model
        os.environ["ORACLE_EMBED_BACKEND"] = "openai"
        os.environ["ORACLE_EMBED_API_BASE"] = embed_api_base
        os.environ["ORACLE_EMBED_MODEL"] = embed_model

        # Probe endpoint connectivity first
        try:
            import requests
            requests.get(f"{embed_api_base}/models", timeout=2).raise_for_status()
        except Exception:
            self.skipTest(f"Live embedding endpoint at {embed_api_base} is offline.")

        # 1. Create a physical LanceDB table with ground truth content and live vector embeddings
        db = lancedb.connect(db_dir)

        fact_text = "The central bank increased the key policy rate by 25 basis points in Q3."
        vec = rag_manager.embed_texts(
            [fact_text],
            backend="openai",
            model=embed_model,
            api_base=embed_api_base,
        )[0]
        dim = len(vec)

        class FactChunk(LanceModel):
            source_file: str
            text: str
            vector: Vector(dim)

        tbl = db.create_table("test_claims_table", schema=FactChunk, mode="overwrite")
        tbl.add([
            {
                "source_file": "macro_notes.md",
                "text": fact_text,
                "vector": vec,
            }
        ])

        # 2. Write a physical response markdown file to test
        response_file = os.path.join(self.temp_dir, "oracle_response.md")
        report_file = os.path.join(self.temp_dir, "oracle_claims_report.md")

        with open(response_file, "w", encoding="utf-8") as f:
            f.write(
                "# Oracle Analysis\n\n"
                "The central bank increased the key policy rate by 25 basis points in Q3.\n\n"
                "Unicorn equities grew by 900% without any economic justification.\n"
            )

        # Run physical claims validator
        validator._run_claims_only(
            SimpleNamespace(
                file=response_file,
                report=report_file,
                db=db_dir,
                collection="test_claims",
                top_k=5,
                threshold=2.0,
                region_threshold=2.0,
                entail_threshold=2.0,
                margin=2,
                region_paragraphs=0,
                para_margin=0,
                minicheck=False,
                no_print=True,
                no_rag=False,
                embed_api_base=embed_api_base,
                embed_model=embed_model,
            )
        )

        # 3. Assert report is generated on disk
        self.assertTrue(os.path.exists(report_file), "Claims validation report must exist on disk.")
        with open(report_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Claim Verification", content)
        self.assertIn("oracle_response.md", content)
        self.assertIn("Unicorn equities grew by 900%", content)
        self.assertIn("macro_notes.md", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
