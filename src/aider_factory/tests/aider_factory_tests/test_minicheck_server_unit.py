import concurrent.futures
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure python directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../python")))

# Prevent weight download during unit test module import if MiniCheck is uninstantiated
try:
    import minicheck
except ImportError:
    mock_minicheck = MagicMock()
    sys.modules["minicheck"] = mock_minicheck
    sys.modules["minicheck.minicheck"] = mock_minicheck

try:
    import fastapi
    from fastapi.testclient import TestClient
except ImportError:
    mock_fastapi = MagicMock()
    sys.modules["fastapi"] = mock_fastapi
    sys.modules["fastapi.testclient"] = mock_fastapi
    TestClient = None

try:
    import nltk
except ImportError:
    nltk = None

import minicheck_server as ms
from validator import _ENTAIL_PROMPT, _parse_entail


class TestMiniCheckServerUnit(unittest.TestCase):
    @unittest.skipIf(nltk is None, "nltk is not installed in the test runner environment")
    def test_nltk_tables_installed_and_functional(self):
        text = "Empirical spread observations. Liquidity dynamics stabilize."
        sents = nltk.sent_tokenize(text)
        self.assertEqual(len(sents), 2)
        self.assertEqual(sents[0], "Empirical spread observations.")
        self.assertEqual(sents[1], "Liquidity dynamics stabilize.")

    def test_sentence_splitting_financial_and_numerical_tokens(self):
        claim = "Market makers widen quoted spreads by 2.4x baseline. Reversion edge is 18.5 bps."
        sents = ms._sentences(claim)
        self.assertEqual(len(sents), 2)
        self.assertIn("Market makers widen quoted spreads by 2.4x baseline.", sents)
        self.assertIn("Reversion edge is 18.5 bps.", sents)

    def test_sentence_filter_drops_fragments_below_min_len(self):
        claim = "Market makers widen spreads. No. Ok. Short."
        sents = ms._sentences(claim)
        self.assertIn("Market makers widen spreads.", sents)
        self.assertNotIn("No.", sents)
        self.assertNotIn("Ok.", sents)

    def test_empty_or_whitespace_claim_handling(self):
        self.assertEqual(ms._sentences(""), [""])
        self.assertEqual(ms._sentences("   "), [""])

    def test_parse_prompt_handles_crlf_windows_newlines(self):
        raw = "DOCUMENT:\r\nSource content.\r\n\r\nCLAIM:\r\nClaim content.\r\n\r\nIs the CLAIM fully supported"
        doc, claim = ms._parse(raw)
        self.assertEqual(doc, "Source content.")
        self.assertEqual(claim, "Claim content.")

    def test_parse_prompt_multi_paragraph_document(self):
        prompt = _ENTAIL_PROMPT.format(
            document="Paragraph 1.\n\nParagraph 2.\n\nParagraph 3.",
            claim="Asserted claim text."
        )
        doc, claim = ms._parse(prompt)
        self.assertEqual(doc, "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3.")
        self.assertEqual(claim, "Asserted claim text.")

    def test_parse_prompt_with_nested_keywords_in_body(self):
        raw = "DOCUMENT:\nSource says: 'CLAIM: 100% true'.\n\nCLAIM:\nQuoting DOCUMENT: is safe.\n\nIs the CLAIM fully supported"
        doc, claim = ms._parse(raw)
        self.assertEqual(doc, "Source says: 'CLAIM: 100% true'.")
        self.assertEqual(claim, "Quoting DOCUMENT: is safe.")

    def test_parse_xml_tagged_prompt(self):
        xml_prompt = "<evidence_passages>Passage A</evidence_passages>\n<claim_to_verify>Claim B</claim_to_verify>"
        doc, claim = ms._parse(xml_prompt)
        self.assertEqual(doc, "Passage A")
        self.assertEqual(claim, "Claim B")

    def test_parse_fallback_on_unanchored_claim(self):
        raw = "DOCUMENT: Some document\n\nCLAIM: Some claim without trailer"
        doc, claim = ms._parse(raw)
        self.assertEqual(doc, "Some document")
        self.assertEqual(claim, "Some claim without trailer")

    @unittest.skipIf(TestClient is None, "fastapi.testclient is not installed in the test runner environment")
    def test_chat_completions_schema_and_status_codes(self):
        client = TestClient(ms.app)
        with patch.object(ms, "_scorer") as mock_scorer:
            mock_scorer.score.return_value = ([1], [0.9421])
            payload = {
                "model": "minicheck-flan-t5-large",
                "messages": [{"role": "user", "content": "DOCUMENT:\nDoc.\n\nCLAIM:\nClaim.\n\nIs the CLAIM fully supported"}]
            }
            res = client.post("/v1/chat/completions", json=payload)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["choices"][0]["message"]["content"], "0.9421")
            self.assertEqual(data["choices"][0]["finish_reason"], "stop")

    @unittest.skipIf(TestClient is None, "fastapi.testclient is not installed in the test runner environment")
    def test_scorer_exception_returns_safe_zero_score(self):
        client = TestClient(ms.app)
        with patch.object(ms, "_scorer") as mock_scorer:
            mock_scorer.score.side_effect = RuntimeError("GPU out of memory")
            payload = {
                "model": "minicheck-flan-t5-large",
                "messages": [{"role": "user", "content": "DOCUMENT:\nDoc.\n\nCLAIM:\nClaim.\n\nIs the CLAIM fully supported"}]
            }
            res = client.post("/v1/chat/completions", json=payload)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["choices"][0]["message"]["content"], "0.0000")

    @unittest.skipIf(TestClient is None, "fastapi.testclient is not installed in the test runner environment")
    def test_concurrent_chat_requests(self):
        client = TestClient(ms.app)
        with patch.object(ms, "_scorer") as mock_scorer:
            mock_scorer.score.return_value = ([1], [0.8800])
            payload = {
                "model": "minicheck-flan-t5-large",
                "messages": [{"role": "user", "content": "DOCUMENT:\nDoc.\n\nCLAIM:\nClaim.\n\nIs the CLAIM fully supported"}]
            }
            def _req():
                return client.post("/v1/chat/completions", json=payload).status_code

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(_req) for _ in range(4)]
                results = [f.result() for f in futures]
            self.assertEqual(results, [200] * 4)

    def test_validator_parse_entail_probabilities(self):
        self.assertAlmostEqual(_parse_entail("0.9805"), 0.9805)
        self.assertAlmostEqual(_parse_entail("0.0000"), 0.0)
        self.assertAlmostEqual(_parse_entail("1.0"), 1.0)
        self.assertAlmostEqual(_parse_entail("0.50"), 0.50)

    def test_validator_parse_entail_text_labels(self):
        self.assertEqual(_parse_entail("SUPPORTED"), 1.0)
        self.assertEqual(_parse_entail("YES"), 1.0)
        self.assertEqual(_parse_entail("UNSUPPORTED"), 0.0)
        self.assertEqual(_parse_entail("NO"), 0.0)
        self.assertEqual(_parse_entail("CONTRADICT"), 0.0)

    def test_validator_parse_entail_unparseable_fallback(self):
        self.assertIsNone(_parse_entail(""))
        self.assertIsNone(_parse_entail("   "))
        self.assertIsNone(_parse_entail("error: connection timed out"))


if __name__ == "__main__":
    unittest.main()
