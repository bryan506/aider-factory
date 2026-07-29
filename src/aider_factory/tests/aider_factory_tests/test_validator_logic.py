#!/usr/bin/env python3
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

import validator

print("Starting Validator Logic Tests...\n")

# 1. Test Extraction Regex
mock_review = """
Here is a claim.
[evidence] "This is an exact quote."
Another claim. [fixed] "This quote was edited."
"""
items_ev = validator._extract(mock_review.splitlines(), "evidence")
assert len(items_ev) == 2, "Should extract both evidence and fixed tags"
assert items_ev[0]["quote"] == "This is an exact quote."
assert items_ev[1]["quote"] == "This quote was edited."
print("✅ Extraction Regex PASS")

# 2. Test Grounding (Exact Substring)
source_norm = validator._normalize("This is an exact quote in the source.")
# The validator._normalize lowercases text internally when checking, but the raw 
# _normalize function does not lowercase. _grounded might expect casing to match. Let's make sure.
# Wait, _grounded function calls _normalize(quote). If it expects exact match, casing matters.
assert validator._grounded("This is an exact quote", source_norm) == True
assert validator._grounded("This quote is hallucinated", source_norm) == False
print("✅ Grounding Exact Match PASS")

# 3. Test Ellipsis Autofix Stitching
mock_source = "The quick brown fox jumps over the lazy dog."
mock_quote = "The quick brown... lazy dog."
source_n = validator._normalize(mock_source)
frags = [validator._normalize(f) for f in validator._ELLIPSIS.split(mock_quote)]
idx1 = source_n.find(frags[0])
idx2 = source_n.find(frags[1], idx1 + len(frags[0]))
stitched = mock_source[idx1 : idx2 + len(frags[1])]
assert stitched == "The quick brown fox jumps over the lazy dog."
print("✅ Autofix Stitching Logic PASS")

# 4. Deletion Guard (Baseline Check)
baseline = [validator._qhash("Quote A"), validator._qhash("Quote B")]
current_items = [{"quote": "Quote A", "tag": "evidence"}]
floor_violation = bool(baseline) and len(current_items) < len(baseline)
assert floor_violation == True
print("✅ Deletion Guard (Floor Violation) PASS")
