import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import openalex_batch as batch


class OpenAlexBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def manifest(self, payload):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_loads_fixed_manifest_and_rejects_duplicate_ids(self):
        path = self.manifest({"date_range": [2000, 2026], "queries": [
            {"id": "a", "query": "alpha", "mode": "lexical"},
            {"id": "b", "query": "beta", "mode": "semantic", "max_results": 50},
        ]})
        payload, queries = batch.load_manifest(path)
        self.assertEqual(payload["date_range"], [2000, 2026])
        self.assertEqual([item["manifest_index"] for item in queries], [1, 2])
        path = self.manifest({"queries": [
            {"id": "same", "query": "a"}, {"id": "same", "query": "b"}]})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            batch.load_manifest(path)

    def test_bounded_workers_and_semantic_workers(self):
        queries = [
            {"id": f"s{i}", "query": "q", "mode": "semantic", "max_results": 10,
             "manifest_index": i, "route": "C"} for i in range(1, 5)
        ] + [
            {"id": f"l{i}", "query": "q", "mode": "lexical", "max_results": 10,
             "manifest_index": i + 4, "route": "B"} for i in range(1, 4)
        ]
        lock = threading.Lock()
        active = semantic_active = peak = semantic_peak = 0

        def runner(command):
            nonlocal active, semantic_active, peak, semantic_peak
            semantic = command[command.index("--search-mode") + 1] == "semantic"
            with lock:
                active += 1
                semantic_active += semantic
                peak = max(peak, active)
                semantic_peak = max(semantic_peak, semantic_active)
            time.sleep(0.02)
            with lock:
                active -= 1
                semantic_active -= semantic
            return subprocess.CompletedProcess(command, 0, "ok", "")

        results = batch.run_batch({}, queries, self.root, "json", 3, 2,
                                  sys.executable, False, runner)
        self.assertEqual(peak, 3)
        self.assertLessEqual(semantic_peak, 2)
        self.assertTrue(all(item["status"] == "completed" for item in results))

    def test_semantic_lane_starts_even_when_manifest_lists_lexical_first(self):
        queries = [
            {"id": f"l{i}", "query": "q", "mode": "lexical", "max_results": 10,
             "manifest_index": i} for i in range(1, 5)
        ] + [{"id": "s1", "query": "q", "mode": "semantic", "max_results": 10,
              "manifest_index": 5}]
        started = []
        lock = threading.Lock()

        def runner(command):
            with lock:
                started.append(command[command.index("--search-mode") + 1])
            time.sleep(0.02)
            return subprocess.CompletedProcess(command, 0, "ok", "")

        batch.run_batch({}, queries, self.root, "json", 3, 1,
                        sys.executable, False, runner)
        self.assertIn("semantic", started[:3])

    def test_hard_stop_leaves_unadmitted_queries_unattempted(self):
        queries = [{"id": str(i), "query": "q", "mode": "lexical",
                    "max_results": 10, "manifest_index": i} for i in range(1, 6)]
        calls = 0

        def runner(command):
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(command, 2, "", "error: HTTP 429")

        results = batch.run_batch({}, queries, self.root, "json", 2, 1,
                                  sys.executable, False, runner)
        self.assertEqual(calls, 2)
        self.assertEqual([item["status"] for item in results].count("not_attempted"), 3)

    def test_dry_run_has_no_filesystem_side_effects(self):
        manifest = self.manifest({"date_range": [2000, 2026], "queries": [
            {"id": "preview", "query": "alpha", "mode": "lexical"}]})
        output = self.root / "absent"
        self.assertEqual(batch.main(["--manifest", str(manifest),
                                     "--output-dir", str(output), "--dry-run"]), 0)
        self.assertFalse(output.exists())

    def test_redacts_keys_and_recognizes_client_error_status(self):
        command = ["query"]

        def runner(_):
            return subprocess.CompletedProcess(
                command, 2, "", "429 Client Error: https://api.openalex.org/x?api_key=secret")

        item = {"id": "a", "mode": "lexical", "manifest_index": 1}
        result = batch.run_one(item, command, runner)
        self.assertTrue(result["stop_admission"])
        self.assertNotIn("secret", result["stderr"])


if __name__ == "__main__":
    unittest.main()
