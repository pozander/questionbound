#!/usr/bin/env python3
"""Extract a PDF into page-labelled Markdown files for text RAG indexing."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdf_page_count(pdf: Path) -> int:
    info = subprocess.check_output(["pdfinfo", str(pdf)], text=True)
    match = re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)
    if not match:
        raise ValueError(f"Could not read PDF page count: {pdf}")
    return int(match.group(1))


def extract_pages(pdf: Path, expected_count: int) -> list[str]:
    raw = subprocess.check_output(
        ["pdftotext", "-layout", str(pdf), "-"], text=True
    )
    pages = raw.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != expected_count:
        raise ValueError(
            f"Extracted {len(pages)} pages but PDF reports {expected_count}: {pdf}"
        )
    return pages


def prepare(pdf: Path, output_dir: Path, source: str) -> dict:
    pdf = pdf.resolve()
    count = pdf_page_count(pdf)
    pages = extract_pages(pdf, count)
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("page-*.md"):
        stale.unlink()

    generated = []
    blank_pages = []
    width = max(4, len(str(count)))
    for page_number, text in enumerate(pages, start=1):
        if not text.strip():
            blank_pages.append(page_number)
            continue
        filename = f"page-{page_number:0{width}d}.md"
        path = output_dir / filename
        content = (
            f"# {source} - physical PDF page {page_number}\n\n"
            f"Source PDF: `{pdf.name}`\n\n"
            f"Physical PDF page: `{page_number}`\n\n"
            "## Extracted page text\n\n"
            f"{text.strip()}\n"
        )
        path.write_text(content, encoding="utf-8")
        generated.append(
            {
                "file": filename,
                "physical_pdf_page": page_number,
                "sha256": sha256(path),
            }
        )

    manifest = {
        "schema_version": 1,
        "source": source,
        "pdf": str(pdf),
        "pdf_sha256": sha256(pdf),
        "pdf_pages": count,
        "extraction": "pdftotext -layout",
        "generated_pages": len(generated),
        "blank_pdf_pages": blank_pages,
        "documents": generated,
    }
    manifest_path = output_dir.parent / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    manifest = prepare(args.pdf, args.output_dir, args.source)
    print(
        f"Prepared {manifest['generated_pages']} page documents from "
        f"{manifest['pdf_pages']} physical PDF pages."
    )
    print(f"Manifest: {args.output_dir.parent / 'corpus-manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
