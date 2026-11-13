#!/usr/bin/env python3
"""Offline reconciliation and transparent triage for the approved ICT-access run."""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path


def compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def match(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def assess(record: dict) -> tuple[int, list[str], list[str]]:
    title = compact(record.get("title"))
    abstract = compact(record.get("abstract"))
    text = f"{title}. {abstract}"
    score = 0
    categories: list[str] = []
    signals: list[str] = []

    rules = [
        (r"first[- ]order barrier|second[- ]order barrier", 18, "educational-barriers"),
        (r"third[- ]order barrier", 12, "educational-barriers"),
        (r"barrier.{0,80}(technology integration|ICT integration)|(?:technology|ICT).{0,80}barrier", 7, "educational-barriers"),
        (r"first[- ]level digital divide", 15, "divide-levels"),
        (r"second[- ]level digital divide", 18, "divide-levels"),
        (r"third[- ]level digital divide|third digital divide", 18, "divide-levels"),
        (r"digital inequal", 10, "digital-inequality"),
        (r"digital divide", 6, "digital-divide"),
        (r"meaningful use|effective use", 8, "meaningful-use"),
        (r"internet skills|digital skills|ICT skills|e-literacy|digital literacy", 6, "skills"),
        (r"tangible outcomes|benefit(?:ing|s)?.{0,40}(internet|digital)|internet.{0,40}outcomes|digital outcomes", 8, "outcomes"),
        (r"material access|physical access|unequal access|internet access", 5, "access"),
        (r"capabilit|self-efficacy|confidence", 4, "capabilities-confidence"),
        (r"organi[sz]ational|institutional|workplace|implementation", 3, "organizational-institutional"),
    ]
    for pattern, weight, category in rules:
        if match(text, pattern):
            score += weight
            categories.append(category)
            signals.append(category)

    if match(text, r"access") and match(text, r"skills?|uses?|usage|outcomes?|benefits?|capabilit"):
        score += 8
        signals.append("access-plus-post-access")
    if match(text, r"skills?") and match(text, r"uses?|usage") and match(text, r"outcomes?|benefits?"):
        score += 8
        signals.append("skills-use-outcomes-chain")
    if match(text, r"systematic review|literature review|review and future|research agenda|achievements and shortcomings"):
        score += 6
        signals.append("review-or-agenda")
    if match(title, r"origins?|definition|conceptuali[sz]|theory|evolution|from .+ to |rethinking|beyond"):
        score += 4
        signals.append("conceptual-or-developmental")

    route_count = len(record.get("routes", []))
    score += min(route_count, 5) * 2
    cited = int(record.get("cited_by_count") or 0)
    score += min(8, int(math.log10(cited + 1) * 3))

    if not abstract:
        signals.append("missing-abstract")
    if record.get("type") in {"book-review", "paratext", "software", "study-registration", "conference-abstract"}:
        score -= 10
        signals.append("low-priority-type")
    if match(text, r"internet of things|voice assistant") and not match(text, r"digital inequal|digital divide"):
        score -= 5
        signals.append("adjacent-device-adoption")

    return score, sorted(set(categories)), signals


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: screen_ict_access_stage1.py RESULTS_DIR OUTPUT_DIR")
    results_dir, output_dir = map(Path, sys.argv[1:])
    output_dir.mkdir(parents=True, exist_ok=True)
    works: dict[str, dict] = {}
    routes: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(results_dir.rglob("*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        for rank, raw in enumerate(pack["records"], 1):
            oid = compact(raw.get("openalex_id"))
            if not oid:
                continue
            works.setdefault(oid, raw.copy())
            routes[oid].append({
                "file": path.name,
                "mode": pack.get("search_mode"),
                "query": pack.get("query"),
                "rank": rank,
            })

    rows = []
    for oid, work in works.items():
        work["routes"] = routes[oid]
        year = work.get("year")
        in_range = isinstance(year, int) and 1980 <= year <= 2026
        score, categories, signals = assess(work)
        work.update(triage_score=score, categories=categories, signals=signals, in_approved_year_range=in_range)
        rows.append(work)
    rows.sort(key=lambda r: (not r["in_approved_year_range"], -r["triage_score"], -int(r.get("cited_by_count") or 0), compact(r.get("title")).casefold()))

    (output_dir / "union.json").write_text(json.dumps({
        "method": "Deduplicate by OpenAlex work ID; retain all retrieval routes and ranks; offline transparent triage only.",
        "retrieved_occurrences": sum(len(v) for v in routes.values()),
        "unique_records": len(rows),
        "records": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    fields = ["openalex_id", "title", "year", "type", "authors", "venue", "doi", "cited_by_count", "is_open_access", "in_approved_year_range", "triage_score", "categories", "signals", "route_count", "best_rank", "abstract"]
    with (output_dir / "triage.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **{key: row.get(key) for key in fields},
                "authors": "; ".join(row.get("authors") or []),
                "categories": "; ".join(row["categories"]),
                "signals": "; ".join(row["signals"]),
                "route_count": len(row["routes"]),
                "best_rank": min(r["rank"] for r in row["routes"]),
                "abstract": compact(row.get("abstract")),
            })

    candidates = [r for r in rows if r["in_approved_year_range"]][:180]
    lines = [
        "# Offline triage candidate pack",
        "",
        "The score is a transparent inspection aid, not a relevance verdict. Final decisions require title/abstract review.",
        "",
    ]
    for index, row in enumerate(candidates, 1):
        lines.extend([
            f"## {index}. {compact(row.get('title')) or '[untitled]'}",
            "",
            f"- ID: {row['openalex_id']}",
            f"- Year/type: {row.get('year')} / {row.get('type')}",
            f"- Authors: {'; '.join(row.get('authors') or [])}",
            f"- Citations reported by OpenAlex: {row.get('cited_by_count')}",
            f"- Triage score/categories: {row['triage_score']} / {', '.join(row['categories']) or 'none'}",
            f"- Retrieval: " + "; ".join(f"{r['mode']}:{r['file']}@{r['rank']}" for r in row["routes"]),
            "",
            compact(row.get("abstract")) or "[No abstract in OpenAlex]",
            "",
        ])
    (output_dir / "candidate-pack.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"retrieved_occurrences": sum(len(v) for v in routes.values()), "unique_records": len(rows), "candidate_pack": len(candidates)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
