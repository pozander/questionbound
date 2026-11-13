import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tavily_phrase_search as phrase_search


class TavilyPhraseSearchTests(unittest.TestCase):
    def manifest(self, root: Path, queries=None) -> Path:
        path = root / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "research_question": "Who wrote the remembered passage?",
                    "language_boundary": "English only",
                    "approval": "Approved by user",
                    "queries": queries or ['"enters triumphantly" "leaves diminished"'],
                }
            )
        )
        return path

    def test_manifest_normalizes_strings_and_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.manifest(
                root,
                ["  exact   phrase  ", {"id": "variant", "query": "near phrase"}],
            )
            payload = phrase_search.load_manifest(path)
        self.assertEqual(payload["queries"][0]["id"], "q01")
        self.assertEqual(payload["queries"][0]["query"], "exact phrase")
        self.assertEqual(payload["queries"][1]["id"], "variant")

    def test_manifest_enforces_query_ceiling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.manifest(root, [f"query {i}" for i in range(31)])
            with self.assertRaisesRegex(ValueError, "at most 30"):
                phrase_search.load_manifest(path)

    def test_dry_run_needs_no_key_and_makes_no_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "audit.json"
            with patch.object(
                phrase_search.requests, "post", side_effect=AssertionError("network")
            ), contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = phrase_search.main(
                    [
                        "--manifest",
                        str(self.manifest(root)),
                        "--output",
                        str(output),
                        "--dry-run",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("Maximum Tavily search credits: 1", stdout.getvalue())
            self.assertFalse(output.exists())

    def test_run_preserves_queries_results_and_usage(self):
        manifest = {
            "research_question": "test",
            "approval": "approved",
            "language_boundary": "English only",
            "queries": [{"id": "q01", "query": "phrase", "rationale": "exact"}],
        }
        response = {
            "request_id": "req-1",
            "usage": {"credits": 1},
            "results": [{"title": "Candidate", "url": "https://example.test"}],
        }
        with patch.object(phrase_search, "tavily_search", return_value=response):
            audit = phrase_search.run(manifest, "secret", 5, 30)
        self.assertEqual(audit["reported_credits"], 1)
        self.assertEqual(audit["attempts"][0]["query"], "phrase")
        self.assertEqual(audit["attempts"][0]["results"][0]["title"], "Candidate")

    def test_existing_output_stops_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "audit.json"
            output.write_text("keep")
            with patch.object(
                phrase_search.requests, "post", side_effect=AssertionError("network")
            ):
                code = phrase_search.main(
                    [
                        "--manifest",
                        str(self.manifest(root)),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(output.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
