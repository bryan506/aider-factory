import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../python")),
)
import validator


class TestE2EDoclingGrounding(unittest.TestCase):
    def test_deterministic_grounding_promotion_on_docling_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            source_md = tmp_path / "January-2026-FX-Report.md"
            source_md.write_text(
                "# FX Volatility Report\n\n"
                "In January 2026, the US Dollar Index (DXY) rose by 1.4% following robust labor data.\n\n"
                "The European Central Bank signaled potential rate cuts in early Q2.\n",
                encoding="utf-8",
            )

            review_md = tmp_path / "review_draft.md"
            review_md.write_text(
                "# Architectural Analysis\n\n"
                '- [evidence] "In January 2026, the US Dollar Index (DXY) rose by 1.4% following robust labor data."\n'
                '- [evidence] "The European Central Bank signaled potential rate cuts in early Q2."\n',
                encoding="utf-8",
            )

            report_md = tmp_path / "validation_report.md"

            class Args:
                file = str(review_md)
                source = str(source_md)
                report = str(report_md)
                tag = "evidence"
                autofix = True
                no_print = True
                loops = 1
                verify_all = False
                redo_oracle = False
                baseline_ledger = None
                ledger = None
                oracle_template = None

            validator._run(Args())

            validated_content = review_md.read_text(encoding="utf-8")
            self.assertIn('- [validated] "In January 2026, the US Dollar Index (DXY) rose by 1.4% following robust labor data."', validated_content)
            self.assertIn('- [validated] "The European Central Bank signaled potential rate cuts in early Q2."', validated_content)
            self.assertNotIn("[evidence]", validated_content)


if __name__ == "__main__":
    unittest.main()
