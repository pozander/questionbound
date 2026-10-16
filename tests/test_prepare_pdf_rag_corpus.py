import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_pdf_rag_corpus as corpus


class PdfRagCorpusTest(unittest.TestCase):
    def test_page_files_are_stable_and_blank_pages_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "book.pdf"
            pdf.write_bytes(b"pdf identity")
            with patch.object(corpus, "pdf_page_count", return_value=3), patch.object(
                corpus, "extract_pages", return_value=["first page", " \n", "third page"]
            ):
                manifest = corpus.prepare(pdf, root / "rag/corpus", "Test Book")

            self.assertEqual(manifest["generated_pages"], 2)
            self.assertEqual(manifest["blank_pdf_pages"], [2])
            page = root / "rag/corpus/page-0001.md"
            self.assertIn("physical PDF page 1", page.read_text())
            self.assertEqual(
                manifest["pdf_sha256"], hashlib.sha256(b"pdf identity").hexdigest()
            )


if __name__ == "__main__":
    unittest.main()
