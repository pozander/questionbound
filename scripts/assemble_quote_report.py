"""Legacy: combine checked quote candidates, repairs, and visual review."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run-dir", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
run = args.run_dir
first = json.loads((run / "verified.json").read_text())
repair = json.loads((run / "repair/verified.json").read_text())
fixes = {q["repair_index"]: q for q in repair["quotes"]}
review = {r["quote_number"]: r for r in json.loads((run / "visual-review.json").read_text())}
quotes, failed_index = [], 0
for number, original in enumerate(first["quotes"], 1):
    q = original.copy()
    if q["verification"] == "FAILED":
        q = fixes[failed_index].copy()
        if (q["file"], q["pdf_page"]) != (original["file"], original["pdf_page"]):
            raise ValueError("Repair changed source or page")
        failed_index += 1
    if q["verification"] != "text_match":
        raise ValueError("Unverified candidate cannot enter final report")
    annotation = review[number]
    q.update(quote_number=number, raw_quote=q["quote"],
             publication_quote=annotation.get("publication_quote", q["quote"]),
             printed_page=annotation["printed_page"],
             visual_check="reviewed_by_Codex", review_note=annotation["note"],
             bibliographic_page=annotation.get("bibliographic_page"))
    quotes.append(q)
usages = [json.loads(p.read_text()) for p in (run / "usage.json", run / "repair/usage.json")]
total = {k: sum(u[k] for u in usages) for k in ["calls", "input", "cacheRead", "output", "totalTokens", "estimated_cost_usd"]}
(run / "total-usage.json").write_text(json.dumps(total, indent=2))
(run / "checked-quotes.json").write_text(json.dumps(quotes, ensure_ascii=False, indent=2))
lines = ["# Cybernetics and function: checked quotations", "",
    "Two-source GPT-4.1 pilot, 2026-09-26. Twelve selected pages, not an exhaustive review.", "",
    "All 12 raw quotations now match their specified extracted pages. Each cited page was also visually reviewed by Codex. "
    "Below, publication wording incorporates explicitly recorded OCR corrections. The unmodified raw quotes and corrections "
    "remain in runs/cybernetics-quotes-gpt41/checked-quotes.json. Printed and physical PDF pages are kept separate.", "",
    "## Findings", "",
    "Ashby offers direct support for a cross-disciplinary vocabulary grounded in behaviour. "
    "Function as what a system does is a defensible interpretation of his functional approach, "
    "not an explicit universal definition of the noun. Sugita emphasizes system behaviour, "
    "parametric interaction, and disciplinary limits. Neither these excerpts nor the pilot "
    "justify collapsing mathematical mapping, behavioural description, and purpose into one definition.", "",
    "The original model synthesis overstates consensus and excludes purpose too broadly. "
    "Treat it as a draft: the checked quotations below, with their contexts and limitations, are the deliverable.", "",
    "## Evidence", ""]
for q in quotes:
    file = Path(q["file"]).resolve()
    label = q["printed_page"] or "unlabelled (bibliographic p. 45 inferred)"
    lines += [f"### {q['quote_number']}. {q['source']} — {q['category']}", "",
              f"File: [{file.name}](<{file}>) · PDF page **{q['pdf_page']}** · Printed page **{label}**", "",
              "> " + q["publication_quote"], "", q["review_note"], ""]
lines += ["## Usage", "",
          f"GPT-4.1: {total['calls']} calls; {total['input']:,} input tokens; {total['cacheRead']:,} cached input; "
          f"{total['output']:,} output; **{total['totalTokens']:,} total tokens**.", "",
          f"**Estimated API cost: USD {total['estimated_cost_usd']:.6f}**, within the USD 0.50 request-admission budget. "
          "This includes the repair pass and excludes Codex implementation and visual review. It is a logged model-cost estimate, not an invoice."]
args.output.write_text("\n".join(lines) + "\n")
print(f"Wrote {len(quotes)} checked quotations to {args.output}")
