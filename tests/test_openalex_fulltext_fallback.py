import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import openalex_fulltext_fallback as fallback


PDF = b"%PDF-1.4\n" + b" " * 1100 + b"\n%%EOF\n"


class Response:
    def __init__(self, status=200, data=None, body=b"", url="https://example.org/final", encoding="utf-8"):
        self.status_code = status
        self.data = data
        self.content = body
        self.body = body
        self.url = url
        self.encoding = encoding

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def json(self):
        return self.data

    def iter_content(self, chunk_size):
        yield self.body


class FulltextFallbackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = {
            "id": "https://openalex.org/W123",
            "display_name": "Exact Study Title",
            "publication_year": 2020,
            "doi": "https://doi.org/10.1234/example",
            "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
            "best_oa_location": {
                "pdf_url": "https://repo.example/paper.pdf",
                "landing_page_url": "https://repo.example/item",
                "is_oa": True,
                "license": "cc-by",
                "version": "acceptedVersion",
                "source": {"display_name": "Repository"},
            },
            "primary_location": None,
            "locations": [],
        }
        self.row = {"openalex_id": "W123", "title": "Exact Study Title", "status": "unavailable"}

    def test_read_only_latest_unavailable(self):
        path = self.root / "downloads.jsonl"
        rows = [
            {"openalex_id": "W123", "status": "downloaded", "title": "old"},
            {"openalex_id": "W123", "status": "unavailable", "title": "new"},
            {"openalex_id": "W456", "status": "downloaded", "title": "done"},
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        self.assertEqual(fallback.read_unavailable(path), [rows[1]])

    def test_location_candidates_prioritize_pdf_and_add_doi(self):
        candidates = fallback.location_candidates(self.work)
        self.assertEqual(candidates[0]["kind"], "pdf")
        self.assertEqual(candidates[0]["origin"], "best_oa_location")
        self.assertEqual(candidates[-1]["origin"], "doi")

    def test_landing_identity_and_relative_pdf(self):
        html = b'''<html><head>
        <meta name="citation_doi" content="10.1234/example">
        <meta name="citation_title" content="Exact Study Title">
        <meta name="citation_pdf_url" content="/download.pdf">
        </head></html>'''
        parser = fallback.LandingParser("https://publisher.example/article")
        parser.feed(html.decode())
        self.assertEqual(parser.pdf_urls, ["https://publisher.example/download.pdf"])
        self.assertEqual(fallback.landing_identity(self.work, parser), (True, "exact_doi"))

    @patch.object(fallback, "validate_pdf_identity", return_value=(True, "test_identity"))
    @patch.object(fallback.requests, "get")
    def test_external_location_download(self, get, identity):
        get.side_effect = [Response(data=self.work), Response(body=PDF, url="https://repo.example/paper.pdf")]
        result = fallback.recover_one(self.row, self.root, "secret", 10, 2000, 20, 10)
        self.assertEqual(result["status"], "external_oa_downloaded")
        self.assertTrue((self.root / "W123.pdf").exists())
        self.assertNotIn("secret", json.dumps(result))

    @patch.object(fallback, "validate_pdf_identity", return_value=(True, "test_identity"))
    @patch.object(fallback.requests, "get")
    def test_doi_landing_discovers_pdf(self, get, identity):
        work = {**self.work, "best_oa_location": None}
        html = b'''<meta name="citation_doi" content="10.1234/example">
                   <meta name="citation_pdf_url" content="https://publisher.example/full.pdf">'''
        get.side_effect = [
            Response(data=work),
            Response(body=html, url="https://publisher.example/article"),
            Response(body=PDF, url="https://publisher.example/full.pdf"),
        ]
        result = fallback.recover_one(self.row, self.root, "secret", 10, 2000, 20, 10)
        self.assertEqual(result["status"], "publisher_pdf_downloaded")

    @patch.object(fallback, "validate_pdf_identity", return_value=(False, "wrong_pdf"))
    @patch.object(fallback.requests, "get")
    def test_pdf_identity_failure_is_not_published(self, get, identity):
        get.side_effect = [
            Response(data=self.work),
            Response(body=PDF, url="https://repo.example/paper.pdf"),
            Response(status=404),
            Response(status=404),
        ]
        result = fallback.recover_one(self.row, self.root, "secret", 10, 2000, 20, 10)
        self.assertEqual(result["status"], "unresolved")
        self.assertFalse((self.root / "W123.pdf").exists())
        self.assertIn("pdf_identity_rejected", {a.get("status") for a in result["attempts"]})

    @patch.object(fallback.requests, "get")
    def test_wrong_landing_identity_is_rejected(self, get):
        work = {**self.work, "best_oa_location": None, "doi": None}
        work["primary_location"] = {"landing_page_url": "https://publisher.example/wrong"}
        html = b'''<meta name="citation_title" content="A Completely Different Work">
                   <meta name="citation_author" content="Someone Else">
                   <meta name="citation_pdf_url" content="https://publisher.example/wrong.pdf">'''
        get.side_effect = [Response(data=work), Response(body=html)]
        result = fallback.recover_one(self.row, self.root, "secret", 10, 2000, 20, 10)
        self.assertEqual(result["status"], "unresolved")
        self.assertFalse((self.root / "W123.pdf").exists())
        self.assertEqual(get.call_count, 2)

    @patch.object(fallback.requests, "get")
    def test_dry_run_has_no_network_or_output(self, get):
        log = self.root / "downloads.jsonl"
        log.write_text(json.dumps(self.row) + "\n", encoding="utf-8")
        output = self.root / "absent"
        self.assertEqual(fallback.main(["--download-log", str(log), "--output-dir", str(output), "--dry-run"]), 0)
        get.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
