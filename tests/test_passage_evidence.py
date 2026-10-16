import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from passage_evidence import materialize, passages_from_pages, prepare


class PassageEvidenceTests(unittest.TestCase):
    def page(self, pdf, text, page=16):
        return {"file": str(pdf), "source": "Glushkov 1966",
                "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "pdf_page": page, "printed_page": "2", "text": text}

    def test_stable_page_bound_ids_and_filter_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "W1503984168.pdf"
            pdf.write_bytes(b"stable source")
            pages = root / "pages.json"
            pages.write_text(json.dumps([self.page(pdf,
                "Header words that should form the first passage.\n\n"
                "A function is a single-valued mapping from inputs to outputs.\n\n"
                "Following context explains the formal restriction clearly.")]))
            prepare(pages, root, [r"single-valued"], 1, 5, 10)
            passages = json.loads((root / "passages.json").read_text())
            self.assertEqual([p["passage_id"] for p in passages], [
                "W1503984168-P0016-B01", "W1503984168-P0016-B02",
                "W1503984168-P0016-B03"])
            self.assertEqual(passages[1]["matched_patterns"], ["single-valued"])
            self.assertIn("PASSAGE_ID: W1503984168-P0016-B02",
                          (root / "evidence.txt").read_text())

    def test_materialize_uses_source_text_and_rejects_model_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"source identity")
            page = self.page(pdf, "A function maps an admissible input to one output.")
            passages = passages_from_pages([page], min_words=3, max_words=20)
            passages_path = root / "passages.json"
            passages_path.write_text(json.dumps(passages))
            selection = {"answer": "Mapping.", "selections": [{
                "passage_id": passages[0]["passage_id"],
                "claim": "Explicit mapping definition", "status": "explicit"}]}
            selections_path = root / "selections.json"
            selections_path.write_text(json.dumps(selection))
            output = root / "checked.json"
            materialize(passages_path, selections_path, output)
            checked = json.loads(output.read_text())["selections"][0]
            self.assertEqual(checked["quote"], passages[0]["text"])
            self.assertEqual(checked["verification"], "materialized_from_passage_id")
            selection["selections"][0]["quote"] = "model wording"
            selections_path.write_text(json.dumps(selection))
            with self.assertRaisesRegex(ValueError, "reference IDs"):
                materialize(passages_path, selections_path, output)

    def test_unknown_duplicate_and_changed_pdf_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"source identity")
            passages = passages_from_pages([
                self.page(pdf, "A sufficiently long passage for deterministic selection.")], 3, 20)
            passages_path = root / "passages.json"
            passages_path.write_text(json.dumps(passages))
            selections = root / "selections.json"
            output = root / "output.json"
            selections.write_text(json.dumps({"selections": [{"passage_id": "UNKNOWN"}]}))
            with self.assertRaisesRegex(ValueError, "Unknown"):
                materialize(passages_path, selections, output)
            passage_id = passages[0]["passage_id"]
            selections.write_text(json.dumps({"selections": [
                {"passage_id": passage_id}, {"passage_id": passage_id}]}))
            with self.assertRaisesRegex(ValueError, "Duplicate selected"):
                materialize(passages_path, selections, output)
            selections.write_text(json.dumps({"selections": [{"passage_id": passage_id}]}))
            pdf.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Source file changed"):
                materialize(passages_path, selections, output)


if __name__ == "__main__":
    unittest.main()
