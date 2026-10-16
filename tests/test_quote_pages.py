import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quote_pages import normalized, verify


class QuoteChecks(unittest.TestCase):
    def test_only_typographic_normalization(self):
        self.assertEqual(normalized("a\n  function"), "a function")
        self.assertNotEqual(normalized("a func-\ntion"), "a function")
        self.assertNotEqual(normalized("Function"), "function")

    def test_wrong_page_paraphrase_and_changed_pdf_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"test source identity")
            pages = root / "pages.json"
            pages.write_text(json.dumps([{"file": str(pdf), "pdf_page": 17,
                "printed_page": "1", "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "text": "It treats, not things but ways of behaving."}]))
            base = {"file": str(pdf), "pdf_page": 17, "quote": "not things but ways of behaving."}
            candidates = root / "candidates.json"
            candidates.write_text(json.dumps({"quotes": [base, {**base, "pdf_page": 1},
                {**base, "quote": "not objects but ways of behaving."}]}))
            output = root / "verified.json"
            self.assertTrue(verify(pages, candidates, output))
            self.assertEqual([q["verification"] for q in json.loads(output.read_text())["quotes"]],
                             ["text_match", "FAILED", "FAILED"])
            pdf.write_bytes(b"changed source")
            with self.assertRaises(ValueError):
                verify(pages, candidates, output)


if __name__ == "__main__":
    unittest.main()
