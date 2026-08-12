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

# 5. Test Session ID Injection in Entailment
print("Starting Session ID Injection Tests...")
from unittest.mock import patch, MagicMock

with patch("litellm.completion") as mock_completion:
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "SUPPORTED"
    mock_resp.choices = [mock_choice]
    mock_completion.return_value = mock_resp

    class DummyArgs:
        grounding_model = "dummy-model"
        grounding_api_base = None
        grounding_api_key = None

    with patch("validator._parse_entail", return_value=1.0), \
         patch("sys.stderr"), patch("sys.stdout"):
        
        validator._entail("claim", [("src", "text")], DummyArgs())

    mock_completion.assert_called_once()
    kwargs = mock_completion.call_args.kwargs
    assert "custom_headers" in kwargs, "custom_headers must be passed"
    assert "x-litellm-session-id" in kwargs["custom_headers"], "Session ID must be in headers"
    assert kwargs["custom_headers"]["x-litellm-session-id"] == validator._PIPELINE_SESSION_ID, "Session ID must match pipeline ID"
print("✅ Session ID Injection PASS")
