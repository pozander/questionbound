#!/usr/bin/env python3
"""Deduplicate OpenAlex packs and apply a literal first/second-order abstract gate."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from typing import Any


def normalize(value: Any) -> str:
    text = re.sub(r"[‐‑–—-]+", " ", str(value or "").casefold())
    return re.sub(r"[^a-z0-9_&]+", " ", text).strip()


def literal_gate(abstract: Any) -> bool:
    text = normalize(abstract)
    standalone = "first order barrier" in text and "second order barrier" in text
    coordinated = bool(
        re.search(r"\bfirst(?:\s+order)?\s+(?:and|&)\s+second\s+order\s+barriers?\b", text)
    )
    return standalone or coordinated


def short_id(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def excerpt(abstract: str, radius: int = 220) -> str:
    low = abstract.casefold()
    starts = [i for i in (low.find("first-order"), low.find("first order"), low.find("first- and")) if i >= 0]
    start = min(starts) if starts else 0
    return re.sub(r"\s+", " ", abstract[max(0, start - radius): start + radius * 2]).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    args = parser.parse_args(argv)

    manifest = json.loads((args.run_dir / "query-manifest.json").read_text(encoding="utf-8"))
    decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    included = decisions.get("included") or {}
    records: dict[str, dict[str, Any]] = {}
    route_occurrences: dict[str, int] = {}
    route_gate_occurrences: dict[str, int] = {}

    for query in manifest["queries"]:
        payload = json.loads((args.run_dir / "results" / f"{query['id']}.json").read_text(encoding="utf-8"))
        route = query["route"]
        for rank, raw in enumerate(payload.get("records") or [], 1):
            route_occurrences[route] = route_occurrences.get(route, 0) + 1
            work_id = short_id(raw.get("openalex_id"))
            item = records.setdefault(work_id, {**raw, "work_id": work_id, "retrievals": []})
            item["retrievals"].append({"query_id": query["id"], "route": route, "rank": rank})
            if literal_gate(raw.get("abstract")):
                route_gate_occurrences[route] = route_gate_occurrences.get(route, 0) + 1

    rows = []
    for item in records.values():
        year = int(item.get("year") or 0)
        abstract = item.get("abstract") or ""
        passed = literal_gate(abstract)
        if not 1990 <= year <= 2026:
            status, reason = "excluded", "outside_approved_date_range"
        elif not abstract.strip():
            status, reason = "excluded", "abstract_unavailable"
        elif not passed:
            status, reason = "excluded", "literal_abstract_gate_failed"
        elif item["work_id"] in included:
            status, reason = "included", included[item["work_id"]]
        else:
            status, reason = "excluded", decisions["default_gate_pass_exclusion"]
        rows.append({
            "work_id": item["work_id"],
            "year": year,
            "title": item.get("title"),
            "authors": item.get("authors"),
            "venue": item.get("venue"),
            "doi": item.get("doi"),
            "url": item.get("url"),
            "abstract": abstract,
            "literal_gate": passed,
            "status": status,
            "decision_reason": reason,
            "routes": sorted({r["route"] for r in item["retrievals"]}),
            "retrievals": item["retrievals"],
            "match_excerpt": excerpt(abstract) if passed else "",
        })
    rows.sort(key=lambda row: (row["status"] != "included", row["year"], str(row["title"])))
    summary = {
        "retrieved_occurrences_by_route": route_occurrences,
        "literal_gate_occurrences_by_route": route_gate_occurrences,
        "unique_records": len(rows),
        "unique_literal_gate_passes": sum(row["literal_gate"] for row in rows),
        "included_noneducation_records": sum(row["status"] == "included" for row in rows),
        "excluded_gate_passes": sum(row["literal_gate"] and row["status"] == "excluded" for row in rows),
        "semantic_unique_additions_after_gate": sum(
            row["literal_gate"] and row["routes"] == ["C"] for row in rows
        ),
    }
    args.output_json.write_text(json.dumps({"summary": summary, "records": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with args.output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "work_id", "year", "title", "authors", "venue", "doi", "url", "literal_gate",
            "status", "decision_reason", "routes", "match_excerpt",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False) if isinstance(row[key], list) else row[key] for key in writer.fieldnames})
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
