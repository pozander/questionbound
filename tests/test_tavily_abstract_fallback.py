import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tavily_abstract_fallback as fallback


def record(number, *, abstract=None, doi=None, cited=0):
    return {
        "openalex_id": f"https://openalex.org/W{number}",
        "title": f"Systems Action Research Study {number}",
        "authors": ["Robert L. Flood"],
        "year": 2010,
        "doi": doi,
        "cited_by_count": cited,
        "abstract": abstract,
    }


class TavilyAbstractFallbackTests(unittest.TestCase):
    def test_loads_local_key_and_environment_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tavily.env"
            path.write_text("# local secret\nTAVILY_API_KEY='FILE-KEY'\n")
            with patch.dict(fallback.os.environ, {}, clear=True):
                self.assertEqual(fallback.load_api_key(path), "FILE-KEY")
            with patch.dict(
                fallback.os.environ, {"TAVILY_API_KEY": "ENV-KEY"}, clear=True
            ):
                self.assertEqual(fallback.load_api_key(path), "ENV-KEY")

    def test_query_uses_doi_when_present_and_title_without_it(self):
        self.assertEqual(
            fallback.build_query(record(1, doi="https://doi.org/10.1/XYZ")),
            '"10.1/xyz" "Flood" abstract',
        )
        query = fallback.build_query(record(2))
        self.assertIn('"Systems Action Research Study 2"', query)
        self.assertIn('"Flood" 2010 abstract', query)

    def test_deduplicates_and_uses_reciprocal_rank(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one.json"
            second = root / "two.json"
            first.write_text(json.dumps({"query": "one", "records": [record(1), record(2)]}))
            second.write_text(json.dumps({"query": "two", "records": [record(2), record(3)]}))
            records, queries = fallback.load_and_rank_packs([first, second])
        self.assertEqual(queries, ["one", "two"])
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["openalex_id"], "https://openalex.org/W2")
        self.assertEqual(len(records[0]["source_queries"]), 2)

    def test_reconciles_duplicate_manifestations_and_propagates_abstract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            without = record(1, doi="10.1/version-a")
            with_abstract = record(2, doi="10.1/version-b", abstract="Existing abstract")
            with_abstract["title"] = without["title"]
            (root / "one.json").write_text(json.dumps({"query": "one", "records": [without]}))
            (root / "two.json").write_text(json.dumps({"query": "two", "records": [with_abstract]}))
            records, _ = fallback.load_and_rank_packs([root / "one.json", root / "two.json"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["abstract"], "Existing abstract")
        self.assertEqual(len(records[0]["openalex_ids"]), 2)
        self.assertEqual(len(records[0]["doi_aliases"]), 2)

    def test_reconciles_numbered_and_unnumbered_chapter_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = record(1)
            plain["title"] = "Systems Thinking and Practice for Action Research"
            numbered = record(2, abstract="Existing chapter abstract")
            numbered["title"] = "9 Systems Thinking and Practice for Action Research"
            (root / "one.json").write_text(json.dumps({"query": "one", "records": [plain, numbered]}))
            records, _ = fallback.load_and_rank_packs([root / "one.json"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["abstract"], "Existing chapter abstract")

    def test_identity_and_explicit_abstract_extraction(self):
        expected = record(1, doi="10.1007/s11213-010-9169-1")
        result = {
            "title": "Action research and systems thinking | SpringerLink",
            "url": "https://doi.org/10.1007/s11213-010-9169-1",
            "content": "Publication page",
            "raw_content": "# Article\n\n## Abstract\n\nThis is a sufficiently long abstract about action research and systems thinking that is suitable for testing.\n\n## Keywords\n\nAction research",
        }
        accepted, score, reasons = fallback.identity_match(expected, result)
        self.assertTrue(accepted)
        self.assertEqual(score, 1.0)
        self.assertEqual(reasons, ["doi"])
        abstract = fallback.extract_abstract(result["raw_content"])
        self.assertTrue(abstract.startswith("This is a sufficiently long abstract"))
        self.assertNotIn("Keywords", abstract)

    def test_flattened_abstract_and_html_metadata(self):
        flooded = "AbstractThis article investigates systems thinking and action research in a sufficiently detailed sentence for reliable extraction. Keywords systems"
        self.assertTrue(fallback.extract_abstract(flooded).startswith("This article"))
        document = '<meta name="citation_abstract" content="' + ("A publisher supplied abstract sentence. " * 4) + '">'
        abstract, method = fallback.extract_html_abstract(document)
        self.assertIn("publisher supplied", abstract)
        self.assertEqual(method, "html_meta:citation_abstract")
        generic = '<meta name="description" content="' + ("Generic handbook description. " * 5) + '">'
        self.assertEqual(fallback.extract_html_abstract(generic), (None, None))

    def test_source_hierarchy(self):
        urls = [
            "https://www.researchgate.net/publication/1",
            "https://research.monash.edu/item/1",
            "https://link.springer.com/article/1",
        ]
        ordered = sorted(urls, key=lambda url: fallback.source_class(url)[1])
        self.assertIn("springer", ordered[0])
        self.assertIn("monash", ordered[1])

    def test_bare_search_snippet_is_not_promoted(self):
        text = "A long search snippet about a paper without an explicit abstract heading. " * 4
        self.assertIsNone(fallback.extract_abstract(text))

    def test_enrichment_is_capped_at_five_and_records_provenance(self):
        records = []
        for number in range(1, 7):
            item = record(number, doi=f"10.1/test{number}")
            item["aggregate_rank"] = number
            records.append(item)

        class Client:
            def __init__(self):
                self.calls = []

            def search(self, query, max_results):
                self.calls.append((query, max_results))
                doi = query.split('"')[1]
                return {
                    "request_id": f"request-{len(self.calls)}",
                    "usage": {"credits": 1},
                    "results": [
                        {
                            "title": "Publication page",
                            "url": f"https://doi.org/{doi}",
                            "score": 0.9,
                            "content": "Relevant result",
                        }
                    ],
                }

        class Fetcher:
            def fetch(self, url):
                number = url.rsplit("test", 1)[-1]
                return {
                    "url": url,
                    "content_type": "text/html",
                    "bytes": 1000,
                    "document_title": f"Systems Action Research Study {number}",
                    "document_text": "Systems Action Research Study by Robert Flood 2010 10.1/test",
                    "abstract": "A verified abstract sentence. " * 5,
                    "method": "html_meta:citation_abstract",
                }

        client = Client()
        enriched, attempts = fallback.enrich_records(records, client, 5, 3, fetcher=Fetcher())
        self.assertEqual(len(client.calls), 5)
        self.assertEqual(len(attempts), 5)
        self.assertTrue(all(item["status"] == "abstract_added" for item in attempts))
        self.assertIsNotNone(enriched[4]["abstract"])
        self.assertIsNone(enriched[5]["abstract"])
        self.assertEqual(enriched[0]["abstract_provenance"]["provider"], "deterministic extraction after Tavily discovery")

    def test_dry_run_needs_no_key_and_makes_no_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "pack.json"
            pack.write_text(json.dumps({"query": "test", "records": [record(1)]}))
            with patch.object(fallback.requests, "post", side_effect=AssertionError("network")):
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    code = fallback.main(
                        [
                            "--input", str(pack),
                            "--output", str(root / "output.json"),
                            "--audit-output", str(root / "audit.json"),
                            "--dry-run",
                        ]
                    )
            self.assertEqual(code, 0)
            self.assertIn("Maximum search credits for this run: 1", stdout.getvalue())
            self.assertFalse((root / "output.json").exists())

    def test_existing_output_stops_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "pack.json"
            output = root / "output.json"
            audit = root / "audit.json"
            pack.write_text(json.dumps({"query": "test", "records": [record(1)]}))
            output.write_text("keep me")
            with patch.dict(fallback.os.environ, {"TAVILY_API_KEY": "SECRET"}), patch.object(
                fallback.requests, "post", side_effect=AssertionError("network")
            ):
                code = fallback.main(
                    [
                        "--input", str(pack),
                        "--output", str(output),
                        "--audit-output", str(audit),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(output.read_text(), "keep me")

    def test_cli_loads_key_from_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "pack.json"
            key_file = root / "tavily.env"
            pack.write_text(json.dumps({"query": "test", "records": [record(1)]}))
            key_file.write_text("TAVILY_API_KEY=FILE-SECRET\n")

            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"request_id": "request-1", "usage": {"credits": 1}, "results": []}

            with patch.dict(fallback.os.environ, {}, clear=True), patch.object(
                fallback.requests, "post", return_value=Response()
            ) as post:
                code = fallback.main(
                    [
                        "--input", str(pack),
                        "--output", str(root / "output.json"),
                        "--audit-output", str(root / "audit.json"),
                        "--api-key-file", str(key_file),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer FILE-SECRET")


if __name__ == "__main__":
    unittest.main()
