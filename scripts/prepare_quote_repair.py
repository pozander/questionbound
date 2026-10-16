# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Legacy: build a repair prompt from failed model-generated quotations."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run-dir", required=True, type=Path)
args = parser.parse_args()
run = args.run_dir
checked = json.loads((run / "verified.json").read_text())
failed = [q for q in checked["quotes"] if q["verification"] == "FAILED"]
pages = json.loads((run / "pages.json").read_text())
keys = {(q["file"], q["pdf_page"]) for q in failed}
repair = run / "repair"
repair.mkdir(exist_ok=False)
brief = """Return valid JSON only: {"quotes": [{"repair_index":0,"file":"exact file","source":"author/year","pdf_page":17,"quote":"exact contiguous text","relevance":"reason","category":"definition|function|cross-disciplinary|limitation","claim_type":"explicit|interpretation"}]}.
Repair each failed quotation below. Use the same file and page. Choose a SHORTER 8-20 word contiguous passage serving its purpose. COPY the wording and punctuation character-for-character from the normalized source page below. Whitespace has already been collapsed. Do not fix OCR, remove punctuation, add ellipses, or use remembered wording. Avoid garbled passages by choosing a clean shorter fragment. Do not repeat the rejected quote. Return one quote per repair_index. No tools are available; output directly, without asking confirmation.\n"""
brief += json.dumps([{ "repair_index": i, **q} for i, q in enumerate(failed)], ensure_ascii=False)
(repair / "brief.txt").write_text(brief)
(repair / "evidence.txt").write_text("\n\n".join(
    f"FILE: {p['file']}\nPDF_PAGE: {p['pdf_page']}\nTEXT:\n{' '.join(p['text'].split())}"
    for p in pages if (p["file"], p["pdf_page"]) in keys))
print(f"Prepared {len(failed)} repairs from {len(keys)} pages.")
