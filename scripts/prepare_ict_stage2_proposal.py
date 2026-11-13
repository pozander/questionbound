#!/usr/bin/env python3
"""Prepare the fixed Stage-2 proposal without making network requests."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from tavily_abstract_fallback import build_queries


PDF_DEFER = {
    "W2618164195",  # population-specific empirical evidence; older-adult study retained elsewhere
    "W2886224444",  # additional country case; five-country and developing-country studies prioritized
    "W3193973490",  # pandemic/online-teaching extension; core barrier sources prioritized
    "W4400315705",  # recent capability case; broad capability source prioritized
}


def short_id(record: dict) -> str:
    return record["openalex_id"].rstrip("/").rsplit("/", 1)[-1]


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare_ict_stage2_proposal.py SELECTED_JSON OUTPUT_DIR")
    selected_path, output_dir = Path(sys.argv[1]), Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)
    records = json.loads(selected_path.read_text(encoding="utf-8"))["records"]
    missing = [r for r in records if not r.get("abstract")][:10]
    pdf_records = [r for r in records if r.get("is_open_access") and short_id(r) not in PDF_DEFER]
    if len(pdf_records) != 40:
        raise SystemExit(f"Expected 40 proposed PDF records, got {len(pdf_records)}")

    pdf_csv = output_dir / "pdf-selection-proposed.csv"
    with pdf_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["openalex_id", "title", "selected", "notes"])
        writer.writeheader()
        for record in pdf_records:
            writer.writerow({
                "openalex_id": short_id(record),
                "title": record["title"],
                "selected": "true",
                "notes": f"Stage-2 proposal; strand={record['strand']}; {record['selection_rationale']}",
            })

    lines = [
        "# Stage 2 proposal — abstract recovery and deterministic PDF retrieval",
        "",
        "Status: proposed, not yet approved or executed.",
        "",
        "## Stage 1 accounting",
        "",
        "- Initial retrieval: 600 occurrences from 9 lexical and 3 semantic queries.",
        "- Initial unique OpenAlex IDs: 492.",
        "- Controlled expansion: 15 exact-title lookups attempted; 13 produced result files; 65 occurrences added.",
        "- Reconciled unique OpenAlex IDs after expansion: 555.",
        f"- Manually selected central/contextual sources: {len(records)}.",
        f"- Selected sources lacking OpenAlex abstracts: {len(missing)}.",
        f"- Proposed exact-ID PDF retrievals: {len(pdf_records)}.",
        "",
        "Semantic date implementation note: OpenAlex semantic search rejected date-range filters. The approved 1980–2026 inclusion boundary was therefore applied locally; no out-of-range semantic record was selected.",
        "",
        "## Tavily fallback boundary",
        "",
        "- Purpose: recover abstracts/source pages only for the 10 listed selected records; not general discovery.",
        "- Maximum 2 query forms per record, 3 search results per query, and 3 direct page fetches per record.",
        "- Maximum 19 search credits and 30 direct page fetches.",
        "- No purchase or account upgrade.",
        "",
    ]
    for i, record in enumerate(missing, 1):
        lines.extend([f"### T{i}. {record['title']}", ""])
        for query in build_queries(record)[:2]:
            lines.append(f"- `{query}`")
        lines.append("")

    lines.extend([
        "## Proposed deterministic PDF retrieval",
        "",
        "The downloader will request only the exact OpenAlex IDs below, validate PDF structure, preserve checksums and provenance, and record unavailable works. It will not search for substitute editions.",
        "",
        "| ID | Year | Strand | Source |",
        "|---|---:|---|---|",
    ])
    for record in pdf_records:
        title = record["title"].replace("|", "\\|")
        lines.append(f"| {short_id(record)} | {record['year']} | {record['strand']} | {title} |")

    lines.extend([
        "",
        "## Full 65-source selected corpus",
        "",
        "| ID | Year | Strand | Abstract | OA flag | Source |",
        "|---|---:|---|:---:|:---:|---|",
    ])
    for record in records:
        title = record["title"].replace("|", "\\|")
        lines.append(f"| {short_id(record)} | {record['year']} | {record['strand']} | {'yes' if record.get('abstract') else 'no'} | {'yes' if record.get('is_open_access') else 'no'} | {title} |")

    lines.extend([
        "",
        "## Execution and spending boundary",
        "",
        "- Authorized if approved: the fixed Tavily fallback above and exact-ID OpenAlex retrieval of the 40 proposed PDFs.",
        "- Not authorized by Stage-2 approval: Feynman or any other paid model call.",
        "- Tavily: at most 19 existing search credits; no purchase.",
        "- OpenAlex retrieval: no paid model call.",
        "- After retrieval, local text inspection may identify exact pages and passages. A later fixed manifest and explicit approval are required before Feynman.",
        "",
        "## Known limitations and gaps",
        "",
        "- OpenAlex is a changing catalogue and has incomplete abstracts, references, and full-text coverage.",
        "- Several foundational sources are not marked open access, including the canonical 1999 Ertmer paper and major books; they remain in the bibliographic corpus but may lack page-addressable evidence.",
        "- The English-only boundary limits global representation.",
        "- Educational-technology terminology is much more standardized than terminology in organizational and community settings, so the latter remains more heterogeneous.",
        "- Citation counts are descriptive metadata, not quality judgments.",
    ])
    (output_dir / "stage2-proposal.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"selected_corpus": len(records), "tavily_targets": len(missing), "pdf_targets": len(pdf_records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
