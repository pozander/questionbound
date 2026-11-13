import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import materialize_agentic_abstracts as materializer


def record(work_id="W1", doi="10.1/example"):
    return {
        "openalex_id": f"https://openalex.org/{work_id}",
        "title": "A Study of Meaningful Technology Use",
        "authors": ["Ada Lovelace"],
        "year": 2020,
        "doi": doi,
        "abstract": None,
    }


def scouts(work_id="W1"):
    return {
        work_id: {
            "target": {"openalex_id": work_id},
            "scout": {
                "work_id": work_id,
                "candidates": [{
                    "url": "https://publisher.test/article",
                    "classification": "abstract",
                    "confidence": "high",
                    "source_class": "publisher",
                }],
            },
        }
    }


class Fetcher:
    def fetch(self, url):
        return {
            "url": url,
            "document_title": "A Study of Meaningful Technology Use",
            "document_text": "A Study of Meaningful Technology Use Ada Lovelace 2020 10.1/example",
            "abstract": "A publisher supplied abstract about meaningful technology use. " * 3,
            "method": "html_meta:citation_abstract",
        }


class MaterializeAgenticAbstractTests(unittest.TestCase):
    def test_scout_url_materializes_with_provenance(self):
        pack = {"records": [record()]}
        with tempfile.TemporaryDirectory() as directory:
            output, audit = materializer.materialize(pack, scouts(), Path(directory), 5, fetcher=Fetcher())
        self.assertEqual(audit["remaining_missing"], 0)
        self.assertEqual(audit["abstracts_added"], 1)
        self.assertIn("publisher supplied", output["records"][0]["abstract"])
        self.assertIn("bounded OpenAI", output["records"][0]["abstract_provenance"]["provider"])

    def test_exact_doi_openaire_is_identity_checked(self):
        response = unittest.mock.Mock()
        response.url = "https://api.openaire.eu/search/publications?doi=10.1%2Fexample&format=json"
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "response": {"results": {"result": [{"metadata": {"oaf:entity": {"oaf:result": {
                "pid": {"@classid": "doi", "$": "10.1/example"},
                "title": {"$": "A Study of Meaningful Technology Use"},
                "creator": {"$": "Ada Lovelace"},
                "description": {"$": "Abstract A database supplied abstract about meaningful technology use. " * 3},
            }}}}]}}
        }
        with patch.object(materializer.requests, "get", return_value=response):
            found = materializer.fetch_openaire_abstract(record(), 5)
        self.assertIn("database supplied", found["abstract"])
        self.assertEqual(found["method"], "openaire_api:oaf:result.description")

    def test_wrong_doi_is_rejected(self):
        response = unittest.mock.Mock()
        response.url = "https://api.openaire.eu/search/publications"
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "response": {"results": {"result": [{"metadata": {"oaf:entity": {"oaf:result": {
                "pid": {"@classid": "doi", "$": "10.1/wrong"},
                "title": {"$": "A Study of Meaningful Technology Use"},
                "creator": {"$": "Ada Lovelace"},
                "description": {"$": "A long but incorrect abstract. " * 5},
            }}}}]}}
        }
        with patch.object(materializer.requests, "get", return_value=response):
            found = materializer.fetch_openaire_abstract(record(), 5)
        self.assertNotIn("abstract", found)

    def test_scout_ceiling_is_enforced(self):
        payload = {"results": [
            {"target": {"openalex_id": f"W{i}"}, "scout": {"candidates": []}}
            for i in range(5)
        ]}
        with self.assertRaises(ValueError):
            materializer.scout_map(payload)

    def test_dry_run_makes_no_network_request_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "pack.json"
            scout = root / "scout.json"
            pack.write_text(json.dumps({"records": [record()]}))
            scout.write_text(json.dumps({"results": list(scouts().values())}))
            with patch.object(materializer.requests, "get", side_effect=AssertionError("network")):
                code = materializer.main([
                    "--input", str(pack), "--scout-results", str(scout),
                    "--pdf-dir", str(root / "pdfs"), "--output", str(root / "out.json"),
                    "--audit-output", str(root / "audit.json"), "--dry-run",
                ])
            self.assertEqual(code, 0)
            self.assertFalse((root / "out.json").exists())


if __name__ == "__main__":
    unittest.main()
