import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_openalex_abstract_evidence import prepare


def record(number, work_id, title, abstract):
    return f"""## {number}. {title}

- Authors: A. Author
- Year: 2020
- Venue: IS Journal
- OpenAlex: https://openalex.org/{work_id}

Abstract:

{abstract}
"""


class AbstractEvidenceTest(unittest.TestCase):
    def test_deduplicates_ids_and_omits_missing_abstracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.md"
            second = root / "second.md"
            first.write_text(
                '# OpenAlex Abstract Pack\n\nQuery: `"definition of efficiency"`\n\n'
                + record(1, "W1", "Definition", "Efficiency relates useful output to resources consumed.")
                + record(2, "W2", "Missing", "_No abstract available from OpenAlex._")
            )
            second.write_text(
                '# OpenAlex Abstract Pack\n\nQuery: `"efficiency refers to"`\n\n'
                + record(1, "W1", "Definition", "Efficiency relates useful output to resources consumed.")
            )

            manifest = prepare([first, second], root / "run", max_words=100)
            passages = json.loads((root / "run/passages.json").read_text())

            self.assertEqual(manifest["total_query_records"], 3)
            self.assertEqual(manifest["unique_works"], 2)
            self.assertEqual(manifest["works_with_abstracts"], 1)
            self.assertEqual(passages[0]["passage_id"], "W1-A-B01")
            self.assertEqual(len(passages[0]["queries"]), 2)


if __name__ == "__main__":
    unittest.main()
