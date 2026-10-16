# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Prepare stable passage IDs and materialize model selections deterministically."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def slug_for(file):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", Path(file).stem).strip("-").upper()
    return slug or "SOURCE"


def split_long_unit(unit, max_words):
    words = unit.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


def split_block(block, max_words):
    text = normalized(block)
    if not text:
        return []
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"“(\[])', text)
    units = []
    for sentence in sentences:
        units.extend(split_long_unit(sentence, max_words))
    chunks, current = [], []
    for unit in units:
        words = unit.split()
        if current and len(current) + len(words) > max_words:
            chunks.append(" ".join(current))
            current = []
        current.extend(words)
    if current:
        chunks.append(" ".join(current))
    return chunks


def passages_from_pages(pages, min_words=8, max_words=80):
    passages = []
    seen_ids = set()
    for page in pages:
        ordinal = 0
        # Work from the normalized whole page. Layout extraction may insert blank
        # lines between visual lines, so treating blank lines as paragraph
        # boundaries creates unusably small fragments.
        for text in split_block(page["text"], max_words):
            if len(text.split()) < min_words:
                continue
            ordinal += 1
            passage_id = f"{slug_for(page['file'])}-P{page['pdf_page']:04d}-B{ordinal:02d}"
            if passage_id in seen_ids:
                raise ValueError(f"Duplicate passage ID generated: {passage_id}")
            seen_ids.add(passage_id)
            passages.append({
                "passage_id": passage_id,
                "file": page["file"],
                "source": page["source"],
                "pdf_sha256": page["pdf_sha256"],
                "pdf_page": page["pdf_page"],
                "printed_page": page.get("printed_page"),
                "text": text,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            })
    return passages


def select_passages(passages, patterns, context):
    if not patterns:
        return [{**passage, "matched_patterns": []} for passage in passages]
    compiled = []
    for pattern in patterns:
        try:
            compiled.append((pattern, re.compile(pattern, re.I)))
        except re.error as error:
            raise ValueError(f"Invalid regex pattern {pattern!r}: {error}") from error
    selected = set()
    matches = {}
    page_groups = {}
    for index, passage in enumerate(passages):
        key = (passage["file"], passage["pdf_page"])
        page_groups.setdefault(key, []).append(index)
        found = [raw for raw, regex in compiled if regex.search(passage["text"])]
        if found:
            selected.add(index)
            matches[index] = found
    for indices in page_groups.values():
        positions = {index: position for position, index in enumerate(indices)}
        matched_here = [index for index in indices if index in selected]
        for index in matched_here:
            position = positions[index]
            selected.update(indices[max(0, position - context):position + context + 1])
    return [{**passages[index], "matched_patterns": matches.get(index, [])}
            for index in range(len(passages)) if index in selected]


def prepare(pages_path, output_dir, patterns=None, context=0,
            min_words=8, max_words=80):
    if context < 0 or min_words < 1 or max_words < min_words:
        raise ValueError("Require context >= 0 and 1 <= min_words <= max_words")
    pages = json.loads(pages_path.read_text())
    all_passages = passages_from_pages(pages, min_words, max_words)
    selected = select_passages(all_passages, patterns or [], context)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "passages.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2))
    (output_dir / "passage-config.json").write_text(json.dumps({
        "pages": str(pages_path),
        "patterns": patterns or [],
        "context": context,
        "min_words": min_words,
        "max_words": max_words,
        "all_passage_count": len(all_passages),
        "selected_passage_count": len(selected),
    }, ensure_ascii=False, indent=2))
    (output_dir / "evidence.txt").write_text("\n\n".join(
        f"PASSAGE_ID: {p['passage_id']}\nSOURCE: {p['source']}\n"
        f"FILE: {p['file']}\nPDF_PAGE: {p['pdf_page']}\n"
        f"VERIFIED_PRINTED_PAGE: {p['printed_page']}\nTEXT:\n{p['text']}"
        for p in selected))
    print(f"Prepared {len(selected)} candidate passages from {len(all_passages)} total passages.")


def materialize(passages_path, selections_path, output_path):
    passages = json.loads(passages_path.read_text())
    payload = json.loads(selections_path.read_text())
    selections = payload.get("selections")
    if not isinstance(selections, list) or not selections:
        raise ValueError("Expected a non-empty selections list")
    index = {passage["passage_id"]: passage for passage in passages}
    if len(index) != len(passages):
        raise ValueError("Duplicate passage IDs in passage evidence")
    checked_files = set()
    for passage in passages:
        file = passage["file"]
        if file in checked_files:
            continue
        actual = hashlib.sha256(Path(file).read_bytes()).hexdigest()
        if any(
            (item.get("file_sha256") or item.get("pdf_sha256")) != actual
            for item in passages
            if item["file"] == file
        ):
            raise ValueError(f"Source file changed since passage preparation: {file}")
        checked_files.add(file)
    seen, results = set(), []
    for selection in selections:
        if not isinstance(selection, dict) or not isinstance(selection.get("passage_id"), str):
            raise ValueError("Every selection must contain a string passage_id")
        if "quote" in selection or "text" in selection:
            raise ValueError("Model selections must reference IDs, not supply quotation text")
        passage_id = selection["passage_id"]
        if passage_id in seen:
            raise ValueError(f"Duplicate selected passage ID: {passage_id}")
        if passage_id not in index:
            raise ValueError(f"Unknown passage ID: {passage_id}")
        seen.add(passage_id)
        passage = index[passage_id]
        result = {
            **selection,
            "file": passage["file"],
            "source": passage["source"],
            "quote": passage["text"],
            "text_sha256": passage["text_sha256"],
            "verification": "materialized_from_passage_id",
            "visual_check": "pending",
        }
        for field in (
            "file_sha256", "pdf_sha256", "pdf_page", "printed_page",
            "evidence_type", "openalex_id", "queries",
        ):
            if field in passage:
                result[field] = passage[field]
        results.append(result)
    output_path.write_text(json.dumps(
        {**payload, "selections": results}, ensure_ascii=False, indent=2))
    print(f"Materialized {len(results)} exact passages from model-selected IDs.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--pages", required=True, type=Path)
    prep.add_argument("--output-dir", required=True, type=Path)
    prep.add_argument("--pattern", action="append", default=[])
    prep.add_argument("--context", type=int, default=0)
    prep.add_argument("--min-words", type=int, default=8)
    prep.add_argument("--max-words", type=int, default=80)
    build = sub.add_parser("materialize")
    build.add_argument("--passages", required=True, type=Path)
    build.add_argument("--selections", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.pages, args.output_dir, args.pattern, args.context,
                args.min_words, args.max_words)
    else:
        materialize(args.passages, args.selections, args.output)
