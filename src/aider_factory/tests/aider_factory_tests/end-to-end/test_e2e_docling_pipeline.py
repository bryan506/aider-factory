import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../python")),
)
import lancedb
import rag_manager


class TestE2EDoclingPipeline(unittest.TestCase):
    def test_live_docling_pdf_ingestion_and_lancedb_population(self):
        """Zero-mock physical test: converts real PDF to markdown via Docling and indexes into LanceDB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            source_pdf = os.path.join(script_dir, "January-2026-FX-Report.pdf")

            if not os.path.exists(source_pdf):
                self.skipTest(f"Source PDF not found at {source_pdf}")

            collection_name = "e2e_docling_test"
            job_dir = tmp_path / collection_name
            job_dir.mkdir(parents=True, exist_ok=True)
            dest_pdf = job_dir / "January-2026-FX-Report.pdf"
            shutil.copy2(source_pdf, dest_pdf)

            embed_api_base = os.environ.get("EMBED_API_BASE", "http://192.168.100.1:8080/v1")
            embed_model = os.environ.get(
                "EMBED_MODEL",
                "qwen3-embedding-8b-8k-gpu:LATEST" if "192.168.100.1" in embed_api_base else "qwen3-embedding-8b-8k:LATEST"
            )
            ocr_api_base = os.environ.get("OCR_API_BASE", "http://192.168.100.2:8081/v1")
            success = rag_manager.ingest(
                context_root=str(tmp_path),
                collection_name=collection_name,
                embed_model=embed_model,
                embed_backend="openai",
                embed_api_base=embed_api_base,
                ocr_agent="glm-ocr-f16:LATEST",
                ocr_api_base=ocr_api_base,
                batch=True,
                overwrite=True,
                use_docling=True,
                docling_do_ocr=False,
            )

            self.assertTrue(success, "Live Docling ingestion failed.")

            md_path = job_dir / "January-2026-FX-Report.md"
            self.assertTrue(md_path.exists(), "Markdown file was not created on disk.")
            content = md_path.read_text(encoding="utf-8")
            self.assertTrue(len(content) > 100, "Markdown content abnormally short.")
            self.assertIn("Federal Finances", content)

            db = lancedb.connect(str(job_dir / "lancedb"))
            tables = (
                db.list_tables()
                if hasattr(db, "list_tables")
                else db.table_names()
            )
            table_list = list(getattr(tables, "tables", tables))
            self.assertTrue(len(table_list) > 0, "No LanceDB tables created.")
            tbl = db.open_table(table_list[0])
            self.assertTrue(tbl.count_rows() > 0, "LanceDB table has 0 row entries.")

    def test_live_docling_fast_path_extraction(self):
        """Zero-mock physical test: validates digital fast-path extraction without OCR."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            source_pdf = os.path.join(script_dir, "January-2026-FX-Report.pdf")

            if not os.path.exists(source_pdf):
                self.skipTest(f"Source PDF not found at {source_pdf}")

            collection_name = "e2e_docling_fast"
            job_dir = tmp_path / collection_name
            job_dir.mkdir(parents=True, exist_ok=True)
            dest_pdf = job_dir / "January-2026-FX-Report.pdf"
            shutil.copy2(source_pdf, dest_pdf)

            embed_api_base = os.environ.get("EMBED_API_BASE", "http://192.168.100.1:8080/v1")
            embed_model = os.environ.get(
                "EMBED_MODEL",
                "qwen3-embedding-8b-8k-gpu:LATEST" if "192.168.100.1" in embed_api_base else "qwen3-embedding-8b-8k:LATEST"
            )
            ocr_api_base = os.environ.get("OCR_API_BASE", "http://192.168.100.2:8081/v1")
            success = rag_manager.ingest(
                context_root=str(tmp_path),
                collection_name=collection_name,
                embed_model=embed_model,
                embed_backend="openai",
                embed_api_base=embed_api_base,
                ocr_agent="glm-ocr-f16:LATEST",
                ocr_api_base=ocr_api_base,
                batch=True,
                overwrite=True,
                use_docling=True,
                docling_do_ocr=False,
            )

            self.assertTrue(success)
            md_path = job_dir / "January-2026-FX-Report.md"
            self.assertTrue(md_path.exists())
            content = md_path.read_text(encoding="utf-8")
            self.assertIn("Treasury", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
