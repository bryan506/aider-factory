import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../python")),
)
import rag_manager


def _get_docling_calls(mock_sub):
    return [
        c
        for c in mock_sub.call_args_list
        if c.args and isinstance(c.args[0], list) and any("docling_runner.py" in str(x) for x in c.args[0])
    ]


class TestDoclingRouting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def setup_ingest(self, filename, content=b"dummy", use_docling=True, docling_do_ocr=True):
        target = self.tmp_path / "knowledge" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        rag_manager.ingest(
            context_root=str(self.tmp_path),
            collection_name="knowledge",
            embed_model="dummy",
            embed_backend="sentence-transformers",
            ocr_only=True,
            batch=True,
            use_docling=use_docling,
            docling_do_ocr=docling_do_ocr,
        )
        return target

    @patch("fitz.open")
    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_use_docling_false_bypasses_docling(
        self, mock_subprocess, mock_rasterize, mock_fitz
    ):
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Digital text content " * 10
        mock_fitz.return_value = [mock_page]
        mock_rasterize.return_value = []

        self.setup_ingest("digital.pdf", use_docling=False)
        self.assertEqual(len(_get_docling_calls(mock_subprocess)), 0)
        mock_rasterize.assert_called_once()

    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_raw_image_bypasses_docling(self, mock_subprocess, mock_rasterize):
        mock_rasterize.return_value = []
        self.setup_ingest("image.png")
        self.assertEqual(len(_get_docling_calls(mock_subprocess)), 0)
        mock_rasterize.assert_called_once()

    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_office_document_routes_to_docling(
        self, mock_subprocess, mock_rasterize
    ):
        def side_effect(*args, **kwargs):
            if args and isinstance(args[0], list) and any("docling_runner.py" in str(x) for x in args[0]):
                md_path = args[0][8]
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write("Extracted office document text " * 10)
                res = MagicMock()
                res.returncode = 0
                return res
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            return res

        mock_subprocess.side_effect = side_effect
        self.setup_ingest("document.docx")
        self.assertEqual(len(_get_docling_calls(mock_subprocess)), 1)
        mock_rasterize.assert_not_called()

    @patch("fitz.open")
    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_digital_pdf_early_break(
        self, mock_subprocess, mock_rasterize, mock_fitz
    ):
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Digital text content " * 10
        mock_fitz.return_value = [mock_page]

        def side_effect(*args, **kwargs):
            if args and isinstance(args[0], list) and any("docling_runner.py" in str(x) for x in args[0]):
                md_path = args[0][8]
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write("Digital PDF parsed markdown " * 10)
                res = MagicMock()
                res.returncode = 0
                return res
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            return res

        mock_subprocess.side_effect = side_effect
        # When docling_do_ocr=False, fitz check runs and breaks early for digital text
        self.setup_ingest("digital.pdf", docling_do_ocr=False)
        mock_fitz.assert_called_once()
        self.assertEqual(len(_get_docling_calls(mock_subprocess)), 1)
        mock_rasterize.assert_not_called()

    @patch("fitz.open")
    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_scanned_pdf_bypasses_docling_and_rasterizes(
        self, mock_subprocess, mock_rasterize, mock_fitz
    ):
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Scan"  # < 100 characters
        mock_fitz.return_value = [mock_page]
        mock_rasterize.return_value = []

        # When docling_do_ocr=False, scanned PDFs bypass Docling via fitz check
        self.setup_ingest("scanned.pdf", docling_do_ocr=False)
        mock_fitz.assert_called_once()
        self.assertEqual(len(_get_docling_calls(mock_subprocess)), 0)
        mock_rasterize.assert_called_once()

    @patch("fitz.open")
    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_scanned_pdf_uses_docling_when_ocr_enabled(
        self, mock_subprocess, mock_rasterize, mock_fitz
    ):
        def side_effect(*args, **kwargs):
            if args and isinstance(args[0], list) and any("docling_runner.py" in str(x) for x in args[0]):
                md_path = args[0][8]
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write("Extracted text via Docling OCR " * 10)
                res = MagicMock()
                res.returncode = 0
                return res
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            return res

        mock_subprocess.side_effect = side_effect

        # When docling_do_ocr=True (default), Docling attempts to parse the scan
        self.setup_ingest("scanned_with_ocr.pdf", docling_do_ocr=True)
        mock_fitz.assert_not_called()
        self.assertEqual(len(_get_docling_calls(mock_subprocess)), 1)
        mock_rasterize.assert_not_called()

    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_docling_crash_falls_back_to_vision_ocr(
        self, mock_subprocess, mock_rasterize
    ):
        def side_effect(*args, **kwargs):
            res = MagicMock()
            if args and isinstance(args[0], list) and any("docling_runner.py" in str(x) for x in args[0]):
                res.returncode = 1
                res.stderr = "Isolated crash"
            else:
                res.returncode = 0
                res.stdout = ""
            return res

        mock_subprocess.side_effect = side_effect
        mock_rasterize.return_value = []

        self.setup_ingest("crash.pdf")
        self.assertEqual(len(_get_docling_calls(mock_subprocess)), 1)
        mock_rasterize.assert_called_once()

    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_docling_subprocess_timeout_triggers_ocr_fallback(
        self, mock_subprocess, mock_rasterize
    ):
        def side_effect(*args, **kwargs):
            if args and isinstance(args[0], list) and any("docling_runner.py" in str(x) for x in args[0]):
                import subprocess
                raise subprocess.TimeoutExpired(cmd="uv run", timeout=120)
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            return res

        mock_subprocess.side_effect = side_effect
        mock_rasterize.return_value = []

        self.setup_ingest("timeout.pdf")
        self.assertEqual(len(_get_docling_calls(mock_subprocess)), 1)
        mock_rasterize.assert_called_once()

    @patch("fitz.open")
    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_docling_do_ocr_true_passes_argument(
        self, mock_subprocess, mock_rasterize, mock_fitz
    ):
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Digital content " * 10
        mock_fitz.return_value = [mock_page]

        def side_effect(*args, **kwargs):
            if args and isinstance(args[0], list) and any("docling_runner.py" in str(x) for x in args[0]):
                md_path = args[0][8]
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write("Extracted text " * 10)
                res = MagicMock()
                res.returncode = 0
                return res
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            return res

        mock_subprocess.side_effect = side_effect
        self.setup_ingest("digital.pdf", docling_do_ocr=True)
        docling_calls = _get_docling_calls(mock_subprocess)
        self.assertEqual(len(docling_calls), 1)
        call_args = docling_calls[0].args[0]
        self.assertEqual(call_args[9], "true")

    @patch("fitz.open")
    @patch("rag_manager._rasterize")
    @patch("subprocess.run")
    def test_docling_do_ocr_false_passes_argument(
        self, mock_subprocess, mock_rasterize, mock_fitz
    ):
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Digital content " * 10
        mock_fitz.return_value = [mock_page]

        def side_effect(*args, **kwargs):
            if args and isinstance(args[0], list) and any("docling_runner.py" in str(x) for x in args[0]):
                md_path = args[0][8]
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write("Extracted text " * 10)
                res = MagicMock()
                res.returncode = 0
                return res
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            return res

        mock_subprocess.side_effect = side_effect
        self.setup_ingest("digital.pdf", docling_do_ocr=False)
        docling_calls = _get_docling_calls(mock_subprocess)
        self.assertEqual(len(docling_calls), 1)
        call_args = docling_calls[0].args[0]
        self.assertEqual(call_args[9], "false")


if __name__ == "__main__":
    unittest.main()
