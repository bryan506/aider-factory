import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../python")),
)
from rag_manager import _chunk


class TestDoclingChunkerHandoff(unittest.TestCase):
    def test_headers_retained_in_chunks(self):
        docling_md = """# Macroeconomic Overview

Global inflation trended downward throughout Q4.

## Monetary Policy Decisions

Central banks maintained target policy rates.

### FX Market Volatility

Currency pairs showed mixed momentum."""
        chunks = _chunk(docling_md, chunk_size_chars=400, chunk_overlap_chars=50)
        self.assertTrue(len(chunks) >= 2)
        joined = "\n\n".join(chunks)
        self.assertIn("Macroeconomic Overview", joined)
        self.assertIn("Monetary Policy Decisions", joined)
        self.assertIn("FX Market Volatility", joined)

    def test_tables_preserved_across_chunks(self):
        docling_md = """# Financial Summary

| Indicator | Q3 2025 | Q4 2025 | YoY Change |
| :--- | :--- | :--- | :--- |
| EUR/USD | 1.0850 | 1.0450 | -3.68% |
| USD/JPY | 148.20 | 155.80 | +5.12% |
| GBP/USD | 1.3020 | 1.2540 | -3.68% |
"""
        chunks = _chunk(docling_md, chunk_size_chars=500, chunk_overlap_chars=50)
        self.assertTrue(len(chunks) > 0)
        joined = "".join(chunks)
        self.assertIn("| Indicator |", joined)
        self.assertIn("| EUR/USD | 1.0850 |", joined)

    def test_metadata_header_chunk_retention(self):
        docling_md = """# Document Metadata

- **Title**: Macroeconomic Outlook
- **Author(s)**: Research Division
- **Date**: January 2026

---

# Overview

Global inflation trended downward."""
        chunks = _chunk(docling_md, chunk_size_chars=400, chunk_overlap_chars=50)
        self.assertTrue(len(chunks) > 0)
        self.assertIn("Document Metadata", chunks[0])
        self.assertIn("Research Division", chunks[0])

    def test_atomic_code_fences(self):
        docling_md = """# Automated Hedging Strategy

Here is the implementation of the delta-neutral rebalancing script:

```python
def rebalance_portfolio(spot_fx, forward_rates, hedge_ratio=0.85):
    target_notional = spot_fx * hedge_ratio
    adjustment = target_notional - current_position
    if abs(adjustment) > tolerance:
        execute_forward_hedge(adjustment)
```

Additional explanatory text follows here."""
        chunks = _chunk(docling_md, chunk_size_chars=600, chunk_overlap_chars=50)
        joined = "".join(chunks)
        self.assertIn("```python", joined)
        self.assertIn("def rebalance_portfolio(", joined)
        self.assertIn("execute_forward_hedge(adjustment)", joined)


if __name__ == "__main__":
    unittest.main()
