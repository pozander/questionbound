import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_agentic_abstract_scout as scout


def target(number):
    return {
        "openalex_id": f"W{number}",
        "title": f"Study {number}",
        "authors": ["Ada Lovelace"],
        "year": 2000 + number,
        "doi": f"10.1/{number}",
        "publication": "Journal of Tests",
        "publisher": "Test Publisher",
    }


def manifest():
    return {
        "model": "gpt-6-luna",
        "reasoning_effort": "low",
        "max_output_tokens_per_response": 1200,
        "max_tool_calls_per_response": 3,
        "maximum_responses": 4,
        "budget_usd": 0.20,
        "store": False,
        "targets": [target(i) for i in range(1, 5)],
    }


class Response:
    status_code = 200

    def __init__(self, work_id):
        result = {
            "work_id": work_id,
            "result": "candidate_found",
            "candidates": [],
            "limitations": [],
        }
        self.payload = {
            "id": f"resp-{work_id}",
            "usage": {"input_tokens": 10, "output_tokens": 10},
            "output": [
                {"type": "web_search_call"},
                {"type": "message", "content": [{"type": "output_text", "text": json.dumps(result)}]},
            ],
        }

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class AgenticAbstractScoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest_path = self.root / "manifest.json"
        self.manifest_path.write_text(json.dumps(manifest()), encoding="utf-8")

    def test_prompt_prioritizes_journal_and_publisher(self):
        prompt = scout.make_prompt(target(1))
        self.assertLess(prompt.index("journal's own website"), prompt.index("exact DOI landing page"))
        self.assertIn("Prefer journal and publisher pages", prompt)

    def test_reservation_fits_approved_ceiling(self):
        data = manifest()
        total = sum(scout.reservation_usd(scout.make_prompt(work), data) for work in data["targets"])
        self.assertLess(total, 0.20)
        self.assertGreater(total, 0.12)

    def test_request_is_bounded_and_structured(self):
        body = scout.request_body(target(1), manifest())
        self.assertEqual(body["model"], "gpt-6-luna")
        self.assertEqual(body["max_tool_calls"], 3)
        self.assertEqual(body["tool_choice"], "required")
        self.assertTrue(body["text"]["format"]["strict"])

    def test_dry_run_has_no_key_or_side_effects(self):
        run_dir = self.root / "absent"
        with patch.object(scout.requests, "post", side_effect=AssertionError("network")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = scout.main(["--manifest", str(self.manifest_path), "--run-dir", str(run_dir), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn('"model": "gpt-6-luna"', output.getvalue())
        self.assertFalse(run_dir.exists())

    @patch.object(scout.requests, "post")
    def test_live_run_writes_budget_and_results(self, post):
        post.side_effect = [Response(f"W{i}") for i in range(1, 5)]
        run_dir = self.root / "run"
        with patch.dict(scout.os.environ, {"OPENAI_API_KEY": "secret"}):
            code = scout.main(["--manifest", str(self.manifest_path), "--run-dir", str(run_dir)])
        self.assertEqual(code, 0)
        ledger = json.loads((run_dir / "budget.json").read_text())
        self.assertEqual(len(ledger["requests"]), 4)
        self.assertLessEqual(ledger["reserved_usd"], 0.20)
        results = json.loads((run_dir / "scout-results.json").read_text())
        self.assertEqual(len(results["results"]), 4)
        for call in post.call_args_list:
            self.assertNotIn("secret", json.dumps(call.kwargs["json"]))


if __name__ == "__main__":
    unittest.main()
