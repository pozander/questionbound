#!/usr/bin/env python3
# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Turn OpenAlex Markdown packs into deduplicated, passage-ID evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from passage_evidence import split_block


RECORD_START = re.compile(r"(?m)^## \d+\. ")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_pack(path: Path) -> tuple[str, list[dict]]:
    text = path.read_text(encoding="utf-8")
    query_match = re.search(r"(?m)^Query: `(.+)`$", text)
    if not query_match:
        raise ValueError(f"Missing query metadata in {path}")
    query = query_match.group(1)
    starts = [match.start() for match in RECORD_START.finditer(text)]
    records = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        block = text[start:end].strip()
        title_match = re.match(r"## \d+\. (.+)", block)
        abstract_parts = block.split("\nAbstract:\n", 1)
        if not title_match or len(abstract_parts) != 2:
            raise ValueError(f"Malformed record in {path}: {block[:80]!r}")
        metadata = dict(
            re.findall(r"(?m)^- ([A-Za-z ]+): (.*)$", abstract_parts[0])
        )
        openalex_url = metadata.get("OpenAlex")
        if not openalex_url or not re.fullmatch(
            r"https://openalex\.org/W\d+", openalex_url
        ):
            raise ValueError(f"Missing OpenAlex work ID in {path}: {title_match.group(1)}")
        records.append(
            {
                "openalex_id": openalex_url.rsplit("/", 1)[-1],
                "title": title_match.group(1),
                "authors": metadata.get("Authors"),
                "year": metadata.get("Year"),
                "venue": metadata.get("Venue"),
                "abstract": abstract_parts[1].strip(),
                "query": query,
                "file": str(path.resolve()),
                "file_sha256": file_hash(path),
            }
        )
    return query, records


def prepare(inputs: list[Path], output_dir: Path, max_words: int = 100) -> dict:
    if max_words < 20:
        raise ValueError("--max-words must be at least 20")
    works: dict[str, dict] = {}
    input_manifest = []
    total_records = 0
    for path in inputs:
        query, records = parse_pack(path)
        total_records += len(records)
        input_manifest.append(
            {
                "file": str(path.resolve()),
                "sha256": file_hash(path),
                "query": query,
                "record_count": len(records),
            }
        )
        for record in records:
            existing = works.get(record["openalex_id"])
            if existing:
                existing["queries"].append(record["query"])
            else:
                works[record["openalex_id"]] = {
                    **record,
                    "queries": [record["query"]],
                }

    passages = []
    omitted = []
    for work in works.values():
        abstract = work["abstract"]
        if abstract == "_No abstract available from OpenAlex._":
            omitted.append(
                {
                    "openalex_id": work["openalex_id"],
                    "title": work["title"],
                    "reason": "No abstract available from OpenAlex",
                }
            )
            continue
        source = (
            f"{work['authors']} ({work['year']}). {work['title']}. "
            f"{work['venue']}. OpenAlex {work['openalex_id']}"
        )
        for ordinal, chunk in enumerate(split_block(abstract, max_words), start=1):
            passage_id = f"{work['openalex_id']}-A-B{ordinal:02d}"
            passages.append(
                {
                    "passage_id": passage_id,
                    "file": work["file"],
                    "file_sha256": work["file_sha256"],
                    "source": source,
                    "evidence_type": "OpenAlex abstract",
                    "openalex_id": work["openalex_id"],
                    "queries": work["queries"],
                    "text": chunk,
                    "text_sha256": hashlib.sha256(chunk.encode()).hexdigest(),
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "passages.json").write_text(
        json.dumps(passages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    evidence = []
    for passage in passages:
        evidence.append(
            f"PASSAGE_ID: {passage['passage_id']}\n"
            f"SOURCE: {passage['source']}\n"
            f"EVIDENCE_TYPE: {passage['evidence_type']}\n"
            f"FOUND_BY_QUERIES: {json.dumps(passage['queries'], ensure_ascii=False)}\n"
            f"TEXT:\n{passage['text']}"
        )
    (output_dir / "evidence.txt").write_text(
        "\n\n".join(evidence) + "\n", encoding="utf-8"
    )
    manifest = {
        "inputs": input_manifest,
        "total_query_records": total_records,
        "unique_works": len(works),
        "works_with_abstracts": len(works) - len(omitted),
        "passage_count": len(passages),
        "max_words_per_passage": max_words,
        "deduplication_key": "OpenAlex work ID",
        "selection": "All available abstracts; no topical regex filter",
        "omitted": omitted,
    }
    (output_dir / "evidence-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-words", type=int, default=100)
    args = parser.parse_args()
    manifest = prepare(args.input, args.output_dir, args.max_words)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
