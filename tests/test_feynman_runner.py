import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("runner", Path(__file__).resolve().parents[1] / "scripts/run_feynman_quotes.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class BudgetTests(unittest.TestCase):
    def test_gpt5_mini_is_guarded_with_documented_rates(self):
        self.assertEqual(runner.MODELS["gpt-5-mini"]["input"], 0.25)
        self.assertEqual(runner.MODELS["gpt-5-mini"]["output"], 2.0)

    def test_defaults_raise_and_preserve(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "budget.json"
            state = runner.prepare_budget(ledger)
            self.assertEqual(state["budget_usd"], 0.5)
            state.update(reserved_usd=0.2, requests=[{"reserved_usd": 0.2}])
            ledger.write_text(json.dumps(state))
            state = runner.prepare_budget(ledger, 2, reuse=True)
            self.assertEqual(state["budget_usd"], 2)
            self.assertEqual(state["reserved_usd"], 0.2)
            self.assertEqual(len(state["requests"]), 1)
            self.assertEqual(runner.prepare_budget(ledger, reuse=True), state)
            for value in (0.5, 0, -1, float("nan"), float("inf")):
                with self.assertRaises(SystemExit):
                    runner.prepare_budget(ledger, value, reuse=True)
            self.assertEqual(json.loads(ledger.read_text()), state)
            with self.assertRaises(SystemExit):
                runner.prepare_budget(ledger, 5)

    def test_runner_override_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "brief.txt").write_text("Return quotes.")
            (folder / "evidence.txt").write_text("Test evidence.")
            def fake_run(command, **kwargs):
                self.assertIn("openai/gpt-4.1-mini", command)
                self.assertEqual(kwargs["env"]["FEYNMAN_MAX_OUTPUT_TOKENS"], "2000")
                ledger = folder / "budget.json"
                state = json.loads(ledger.read_text())
                state["requests"].append({"reserved_usd": 0.01})
                state["reserved_usd"] = 0.01
                ledger.write_text(json.dumps(state))
                sessions = folder / "sessions"
                sessions.mkdir()
                message = {"type": "message", "message": {
                    "role": "assistant", "model": "gpt-4.1-mini",
                    "usage": {"input": 100, "cacheRead": 20, "output": 10, "totalTokens": 130},
                    "content": [{"type": "text", "text": '{"quotes": [{"quote": "Test evidence."}]}'}]}}
                (sessions / "test.jsonl").write_text(json.dumps(message) + "\n")
                return type("Result", (), {"returncode": 0})()
            with patch.object(runner.subprocess, "run", side_effect=fake_run):
                runner.run(folder, "feynman", budget_usd=2, model="openai/gpt-4.1-mini", max_output_tokens=2000)
            usage = json.loads((folder / "usage.json").read_text())
            self.assertAlmostEqual(usage["estimated_cost_usd"], 0.000058)
            self.assertEqual(json.loads((folder / "run-config.json").read_text())["budget_usd"], 2)

    def test_reject_unsupported_before_launch(self):
        with patch.object(runner.subprocess, "run") as launch:
            for model, cap in (("google/gemini", 5000), ("gpt-4.1", 0), ("gpt-4.1", 40000)):
                with self.assertRaises(SystemExit):
                    runner.run(Path("absent"), "feynman", model=model, max_output_tokens=cap)
            launch.assert_not_called()

    def test_runner_accepts_passage_id_selections(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "brief.txt").write_text("Select passage IDs.")
            (folder / "evidence.txt").write_text("PASSAGE_ID: SOURCE-P0001-B01")
            def fake_run(command, **kwargs):
                ledger = folder / "budget.json"
                state = json.loads(ledger.read_text())
                state["requests"].append({"reserved_usd": 0.01})
                state["reserved_usd"] = 0.01
                ledger.write_text(json.dumps(state))
                sessions = folder / "sessions"
                sessions.mkdir()
                response = {"answer": "A mapping.", "selections": [{
                    "passage_id": "SOURCE-P0001-B01", "claim": "definition"}]}
                message = {"type": "message", "message": {
                    "role": "assistant", "model": "gpt-4.1",
                    "usage": {"input": 20, "cacheRead": 0, "output": 10,
                              "totalTokens": 30},
                    "content": [{"type": "text", "text": json.dumps(response)}]}}
                (sessions / "test.jsonl").write_text(json.dumps(message) + "\n")
                return type("Result", (), {"returncode": 0})()
            with patch.object(runner.subprocess, "run", side_effect=fake_run):
                runner.run(folder, "feynman")
            self.assertEqual(json.loads((folder / "run-config.json").read_text())["output_mode"],
                             "passage_ids")
