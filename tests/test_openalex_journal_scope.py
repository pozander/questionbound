import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import openalex_bibtex as search


class JournalScopeTest(unittest.TestCase):
    def test_ais_extended_registry_is_complete_and_batches_at_api_limit(self):
        scope = search.load_journal_scope("ais-extended")
        grouped_names = {
            name for group in scope["groups"] for name in group["journals"]
        }
        resolved_names = {
            source["ais_name"] for source in scope["resolved_sources"]
        }

        self.assertEqual(grouped_names, resolved_names)
        self.assertEqual(len(scope["_source_ids"]), 104)
        self.assertEqual(
            [len(batch) for batch in search.source_id_batches(scope["_source_ids"])],
            [100, 4],
        )

    def test_preview_applies_source_and_year_filters_to_every_batch(self):
        ids = [f"S{number}" for number in range(1, 102)]
        urls = search.preview_urls("efficiency", 20, 2000, 2020, ids)

        self.assertEqual(len(urls), 2)
        for url in urls:
            self.assertIn("primary_location.source.id", url)
            self.assertIn("from_publication_date:2000-01-01", url)
            self.assertIn("to_publication_date:2020-12-31", url)

    def test_semantic_preview_preserves_scope_and_uses_vector_parameter(self):
        urls = search.preview_urls(
            "scholarly metadata infrastructure",
            50,
            source_ids=["S1", "S2"],
            search_mode="semantic",
        )

        self.assertEqual(len(urls), 1)
        self.assertIn("search.semantic=scholarly+metadata+infrastructure", urls[0])
        self.assertIn("primary_location.source.id:S1%7CS2", urls[0])
        self.assertNotIn("sort=relevance_score", urls[0])

    def test_semantic_request_limits_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "at most 50"):
            search.validate_search_request("semantic", "metadata", 51)
        with self.assertRaisesRegex(ValueError, "2000 characters"):
            search.validate_search_request("semantic", "x" * 2001, 50)

    def test_semantic_results_use_single_page_instead_of_cursor(self):
        class FakeQuery:
            def __init__(self):
                self.get_calls = []

            def get(self, **kwargs):
                self.get_calls.append(kwargs)
                return [{"id": "W1"}]

            def paginate(self, **kwargs):
                raise AssertionError("semantic search must not use cursor pagination")

        query = FakeQuery()
        pages = search.query_result_pages(query, "semantic", 50, 50)

        self.assertEqual(pages, [[{"id": "W1"}]])
        self.assertEqual(query.get_calls, [{"per_page": 50}])

    def test_scope_loader_rejects_unresolved_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scope.json"
            path.write_text(
                json.dumps(
                    {
                        "scope_id": "incomplete",
                        "resolved_sources": [{"openalex_id": "S1"}],
                        "unresolved_sources": [{"ais_name": "Missing"}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unresolved"):
                search.load_journal_scope(str(path))


if __name__ == "__main__":
    unittest.main()
