import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../python")),
)
import lancedb
import rag_manager


class TestE2EDoclingPipeline(unittest.TestCase):
    @patch("rag_manager.embed_texts")
    def test_live_docling_pdf_ingestion_and_lancedb_population(self, mock_embed):
        def fake_embed(texts, backend, model, api_base, batch_size=8):
            return [[0.05] * 384 for _ in texts]

        mock_embed.side_effect = fake_embed
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

            success = rag_manager.ingest(
                context_root=str(tmp_path),
                collection_name=collection_name,
                embed_model="BAAI/bge-m3",
                embed_backend="sentence-transformers",
                batch=True,
                overwrite=True,
            )

            self.assertTrue(success, "Ingestion failed to complete.")

            md_path = job_dir / "January-2026-FX-Report.md"
            self.assertTrue(md_path.exists(), "Markdown file was not created.")
            content = md_path.read_text(encoding="utf-8")
            self.assertTrue(
                len(content) > 200, "Markdown content abnormally short."
            )
            self.assertIn("Treasury", content)
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
            self.assertTrue(
                tbl.count_rows() > 0, "LanceDB table has 0 row entries."
            )

    @patch("rag_manager.embed_texts")
    def test_live_docling_with_do_ocr_disabled(self, mock_embed):
        def fake_embed(texts, backend, model, api_base, batch_size=8):
            return [[0.05] * 384 for _ in texts]

        mock_embed.side_effect = fake_embed
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            source_pdf = os.path.join(script_dir, "January-2026-FX-Report.pdf")

            if not os.path.exists(source_pdf):
                self.skipTest(f"Source PDF not found at {source_pdf}")

            collection_name = "e2e_docling_no_ocr"
            job_dir = tmp_path / collection_name
            job_dir.mkdir(parents=True, exist_ok=True)
            dest_pdf = job_dir / "January-2026-FX-Report.pdf"
            shutil.copy2(source_pdf, dest_pdf)

            success = rag_manager.ingest(
                context_root=str(tmp_path),
                collection_name=collection_name,
                embed_model="BAAI/bge-m3",
                embed_backend="sentence-transformers",
                batch=True,
                overwrite=True,
                use_docling=True,
                docling_do_ocr=False,
            )

            self.assertTrue(success)
            md_path = job_dir / "January-2026-FX-Report.md"
            self.assertTrue(md_path.exists())
            content = md_path.read_text(encoding="utf-8")
            self.assertIn("Federal Finances", content)

    @patch("rag_manager._ocr_image", return_value="# Fallback Markdown\nExtracted via OCR.")
    @patch("rag_manager._rasterize")
    @patch("rag_manager.embed_texts")
    def test_live_docling_disabled_fallback_to_rasterize(self, mock_embed, mock_rasterize, mock_ocr):
        def fake_embed(texts, backend, model, api_base, batch_size=8):
            return [[0.05] * 384 for _ in texts]

        mock_embed.side_effect = fake_embed
        mock_rasterize.return_value = [("dummy_page1.png", "")]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            source_pdf = os.path.join(script_dir, "January-2026-FX-Report.pdf")

            if not os.path.exists(source_pdf):
                self.skipTest(f"Source PDF not found at {source_pdf}")

            collection_name = "e2e_docling_disabled"
            job_dir = tmp_path / collection_name
            job_dir.mkdir(parents=True, exist_ok=True)
            dest_pdf = job_dir / "January-2026-FX-Report.pdf"
            shutil.copy2(source_pdf, dest_pdf)

            rag_manager.ingest(
                context_root=str(tmp_path),
                collection_name=collection_name,
                embed_model="BAAI/bge-m3",
                embed_backend="sentence-transformers",
                ocr_agent="dummy-ocr",
                ocr_api_base="http://localhost:8080/v1",
                batch=True,
                overwrite=True,
                use_docling=False,
            )

            mock_rasterize.assert_called_once()


if __name__ == "__main__":
    unittest.main()
