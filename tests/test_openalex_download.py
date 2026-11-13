import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import openalex_download as download
from openalex_bibtex import render_output


PDF = b"%PDF-1.4\n" + b" " * 1100 + b"\n%%EOF\n"


class Response:
    def __init__(self, status=200, data=None, body=PDF):
        self.status_code, self.data, self.body = status, data, body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def json(self):
        return self.data

    def iter_content(self, chunk_size):
        yield self.body


class DownloadsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = {"openalex_id": "W123", "title": "Audit label", "notes": ""}
        self.metadata = {"id": "https://openalex.org/W123", "display_name": "Actual title",
                         "publication_year": 1956, "has_content": {"pdf": True}}

    def selection(self, text):
        path = self.root / "selection.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_selection_and_duplicate_validation(self):
        path = self.selection('openalex_id,title,selected\nhttps://openalex.org/W123,"Title, with comma",true\n,Skipped,false\n')
        self.assertEqual(download.read_selection(path)[0]["openalex_id"], "W123")
        path = self.selection("openalex_id\nW123\nhttps://openalex.org/W123\n")
        with self.assertRaises(ValueError):
            download.read_selection(path)

    def test_csv_export_roundtrip(self):
        text = render_output([self.metadata], '"cybernetics"', "csv")
        self.assertEqual(download.read_selection(self.selection(text)), [])
        rows = list(csv.DictReader(io.StringIO(text)))
        rows[0]["selected"] = "true"
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        self.assertEqual(download.read_selection(self.selection(stream.getvalue()))[0]["title"], "Actual title")

    @patch.object(download.requests, "get")
    def test_download_and_repeat_without_network(self, get):
        get.side_effect = [Response(data=self.metadata), Response()]
        result, stop = download.fetch_one(self.row, self.root, "secret", 10, 2000)
        self.assertEqual(result["status"], "downloaded")
        self.assertFalse(stop)
        self.assertNotIn("secret", json.dumps(result))
        repeat, _ = download.fetch_one(self.row, self.root, "secret", 10, 2000)
        self.assertEqual(repeat["status"], "existing")
        self.assertEqual(repeat["sha256"], result["sha256"])
        self.assertEqual(get.call_count, 2)

    @patch.object(download.requests, "get")
    def test_invalid_payload_never_published(self, get):
        for body in (b"<html>Login</html>", b"%PDF-1.4" + b" " * 1100):
            get.side_effect = [Response(data=self.metadata), Response(body=body)]
            result, _ = download.fetch_one(self.row, self.root, "secret", 10, 2000)
            self.assertEqual(result["status"], "error")
            self.assertFalse((self.root / "W123.pdf").exists())
            self.assertFalse(list(self.root.glob("*.part")))

    @patch.object(download.requests, "get")
    def test_unavailable_and_wrong_id(self, get):
        get.return_value = Response(data={**self.metadata, "has_content": {"pdf": False}})
        result, _ = download.fetch_one(self.row, self.root, "secret", 10, 2000)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(get.call_count, 1)
        get.return_value = Response(data={**self.metadata, "id": "https://openalex.org/W999"})
        result, _ = download.fetch_one(self.row, self.root, "secret", 10, 2000)
        self.assertEqual(result["status"], "error")

    @patch.object(download.requests, "get")
    def test_quota_stops_remaining_and_logs(self, get):
        get.return_value = Response(status=429)
        path = self.selection("openalex_id\nW123\nW456\n")
        with patch.dict("os.environ", {"OPENALEX_API_KEY": "secret"}):
            code = download.main(["--selection", str(path), "--output-dir", str(self.root), "--workers", "1"])
        self.assertEqual(code, 1)
        self.assertEqual(get.call_count, 1)
        records = [json.loads(line) for line in (self.root / "downloads.jsonl").read_text().splitlines()]
        self.assertEqual([r["status"] for r in records], ["error", "not_attempted"])

    def test_parallel_fetch_is_bounded_and_keeps_selection_order(self):
        rows = [{"openalex_id": f"W{i}", "title": str(i), "notes": ""}
                for i in range(6)]
        lock = threading.Lock()
        active = peak = 0

        def fake_fetch(row, *args):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return {**row, "status": "downloaded"}, False

        with patch.object(download, "fetch_one", side_effect=fake_fetch):
            records = download.fetch_rows(rows, self.root, "secret", 10, 2000, 3)
        self.assertEqual(peak, 3)
        self.assertEqual([record["openalex_id"] for record in records],
                         [row["openalex_id"] for row in rows])

    def test_parallel_hard_stop_does_not_admit_more_work(self):
        rows = [{"openalex_id": f"W{i}", "title": str(i), "notes": ""}
                for i in range(5)]

        def fake_fetch(row, *args):
            return {**row, "status": "error"}, True

        with patch.object(download, "fetch_one", side_effect=fake_fetch) as fetch:
            records = download.fetch_rows(rows, self.root, "secret", 10, 2000, 2)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([record["status"] for record in records].count("not_attempted"), 3)

    @patch.object(download.requests, "get")
    def test_dry_run_has_no_side_effects(self, get):
        path = self.selection("openalex_id\nW123\n")
        output = self.root / "absent"
        self.assertEqual(download.main(["--selection", str(path), "--output-dir", str(output), "--dry-run"]), 0)
        get.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
