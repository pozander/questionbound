"""Prepare page-labelled evidence and check quotations without an LLM."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unicodedata


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def prepare(config_path, output):
    config = json.loads(config_path.read_text())
    records = []
    for source in config:
        pdf = Path(source["file"])
        info = subprocess.check_output(["pdfinfo", str(pdf)], text=True)
        count = int(re.search(r"^Pages:\s+(\d+)", info, re.M).group(1))
        raw = subprocess.check_output(["pdftotext", "-layout", str(pdf), "-"], text=True)
        pages = raw.split("\f")
        if not pages[-1].strip():
            pages.pop()
        if len(pages) != count:
            raise ValueError(f"{pdf}: extracted page count differs from PDF page count")
        checksum = hashlib.sha256(pdf.read_bytes()).hexdigest()
        for page_no in source["pdf_pages"]:
            if not 1 <= page_no <= count:
                raise ValueError(f"Invalid PDF page {page_no} for {pdf}")
            records.append({"file": str(pdf), "source": source["source"],
                            "pdf_sha256": checksum, "pdf_page": page_no,
                            "printed_page": source.get("verified_printed_pages", {}).get(str(page_no)),
                            "text": pages[page_no - 1]})
    output.mkdir(parents=True, exist_ok=True)
    (output / "pages.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    (output / "evidence.txt").write_text("\n\n".join(
        f"SOURCE: {r['source']}\nFILE: {r['file']}\nPDF_PAGE: {r['pdf_page']}\n"
        f"VERIFIED_PRINTED_PAGE: {r['printed_page']}\nPAGE TEXT:\n{r['text']}" for r in records))
    print(f"Prepared {len(records)} pages, preserving physical PDF boundaries.")


def verify(pages_path, candidates_path, output):
    pages = json.loads(pages_path.read_text())
    candidates = json.loads(candidates_path.read_text())
    index = {(p["file"], p["pdf_page"]): p for p in pages}
    for file in {p["file"] for p in pages}:
        actual = hashlib.sha256(Path(file).read_bytes()).hexdigest()
        if any(p["pdf_sha256"] != actual for p in pages if p["file"] == file):
            raise ValueError(f"PDF changed since extraction: {file}")
    results = []
    for candidate in candidates["quotes"]:
        page = index.get((candidate.get("file"), candidate.get("pdf_page")))
        quote = candidate.get("quote", "")
        valid = isinstance(quote, str) and len(quote.split()) >= 3
        matched = bool(page and valid and normalized(quote) in normalized(page["text"]))
        results.append({**candidate, "printed_page": page["printed_page"] if page else None,
                        "verification": "text_match" if matched else "FAILED",
                        "pdf_sha256": page["pdf_sha256"] if page else None,
                        "visual_check": "pending"})
    output.write_text(json.dumps({**candidates, "quotes": results}, ensure_ascii=False, indent=2))
    failures = sum(r["verification"] == "FAILED" for r in results)
    print(f"{len(results)-failures}/{len(results)} quotes match the specified extracted page.")
    return bool(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--config", required=True, type=Path)
    prep.add_argument("--output-dir", required=True, type=Path)
    check = sub.add_parser("verify")
    check.add_argument("--pages", required=True, type=Path)
    check.add_argument("--candidates", required=True, type=Path)
    check.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.config, args.output_dir)
    else:
        raise SystemExit(verify(args.pages, args.candidates, args.output))
