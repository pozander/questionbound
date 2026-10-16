#!/usr/bin/env python3
"""Download explicitly selected OpenAlex PDFs; no search or title matching."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import requests


ID_PATTERN = re.compile(r"(?:https://openalex.org/)?(W[0-9]+)", re.IGNORECASE)
FIELDS = ["timestamp_utc", "openalex_id", "title", "notes", "resolved_title",
          "resolved_year", "source_url", "status", "path", "bytes", "sha256", "detail"]


class FetchError(Exception):
    def __init__(self, detail, stop=False):
        super().__init__(detail)
        self.stop = stop


def read_selection(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        allowed = {"openalex_id", "title", "selected", "notes"}
        if "openalex_id" not in headers or len(headers) != len(set(headers)):
            raise ValueError("CSV requires unique headers including openalex_id.")
        if set(headers) - allowed:
            raise ValueError("Unknown CSV columns: " + ", ".join(set(headers) - allowed))
        rows, seen = [], set()
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV row {number}: incorrect number of fields.")
            row = {key: value.strip() for key, value in row.items()}
            flag = row.get("selected", "true").lower()
            if flag not in {"true", "false", "1", "0", "yes", "no"}:
                raise ValueError(f"CSV row {number}: selected must be true or false.")
            if flag in {"false", "0", "no"}:
                continue
            match = ID_PATTERN.fullmatch(row["openalex_id"])
            if not match:
                raise ValueError(f"CSV row {number}: expected W followed by digits or an OpenAlex work URL.")
            work_id = match.group(1).upper()
            if work_id in seen:
                raise ValueError(f"CSV row {number}: duplicate selected ID {work_id}.")
            seen.add(work_id)
            rows.append({"openalex_id": work_id, "title": row.get("title", ""),
                         "notes": row.get("notes", "")})
    return rows


def pdf_info(path):
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        head = stream.read(1024)
        if not head.startswith(b"%PDF-"):
            raise ValueError("File does not start with a PDF signature.")
        digest.update(head)
        size += len(head)
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
            size += len(chunk)
        stream.seek(max(0, size - 2048))
        if size < 1024 or b"%%EOF" not in stream.read():
            raise ValueError("PDF is too small or lacks an end marker; possible truncated response.")
    return size, digest.hexdigest()


def check_response(response):
    if response.status_code != 200:
        code = response.status_code
        # Never include response URLs or exception messages containing the API key.
        raise FetchError(f"HTTP {code}", stop=code in {401, 402, 403, 429})


def fetch_one(row, output_dir, api_key, timeout, max_bytes):
    work_id = row["openalex_id"]
    target = output_dir / f"{work_id}.pdf"
    source = f"https://content.openalex.org/works/{work_id}.pdf"
    record = {**row, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "source_url": source, "path": str(target.resolve())}
    temporary = None
    stop = False
    try:
        if target.exists():
            size, checksum = pdf_info(target)
            record.update(status="existing", bytes=size, sha256=checksum,
                          detail="Preserved local PDF; remote content not rechecked.")
            return record, False

        with requests.get(f"https://api.openalex.org/works/{work_id}",
                          params={"api_key": api_key}, timeout=timeout) as response:
            check_response(response)
            work = response.json()
        if not isinstance(work, dict) or work.get("id") != f"https://openalex.org/{work_id}":
            raise ValueError("Metadata response did not match the requested work ID.")
        record.update(resolved_title=work.get("display_name", ""),
                      resolved_year=work.get("publication_year", ""))
        if (work.get("has_content") or {}).get("pdf") is not True:
            record.update(status="unavailable", detail="OpenAlex reports no cached PDF.")
            return record, False

        with requests.get(source, params={"api_key": api_key}, stream=True,
                          timeout=timeout) as response:
            check_response(response)
            with tempfile.NamedTemporaryFile(dir=output_dir, prefix=f".{work_id}-",
                                             suffix=".part", delete=False) as stream:
                temporary = Path(stream.name)
                size = 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("Download exceeds --max-mb.")
                    stream.write(chunk)
            size, checksum = pdf_info(temporary)
            # Atomic publication without replacing any file created by another run.
            os.link(temporary, target)
        record.update(status="downloaded", bytes=size, sha256=checksum, detail="")
    except FetchError as exc:
        record.update(status="error", detail=str(exc))
        stop = exc.stop
    except requests.RequestException as exc:
        record.update(status="error", detail=f"Network failure ({type(exc).__name__}); rerun to retry.")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        record.update(status="error", detail=f"Validation or local file failure ({type(exc).__name__}).")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return record, stop


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True, type=Path, help="Audited CSV with openalex_id and optional title, selected, notes.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the plan without network calls or file writes.")
    parser.add_argument("--timeout", type=float, default=60, help="Network connect/read timeout in seconds.")
    parser.add_argument("--max-mb", type=int, default=200, help="Maximum size per PDF (MiB).")
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.max_mb <= 0:
        parser.error("--timeout and --max-mb must be positive.")
    try:
        rows = read_selection(args.selection)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    if not rows:
        parser.error("No selected rows.")
    if args.dry_run:
        for row in rows:
            print(f"{row['openalex_id']} -> {args.output_dir / (row['openalex_id'] + '.pdf')} | {row['title']}")
        print(f"{len(rows)} selected works. No network calls or file writes.")
        return 0
    api_key = os.environ.get("OPENALEX_API_KEY")
    if not api_key:
        parser.error("Set OPENALEX_API_KEY before downloading.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / "downloads.jsonl"
    incomplete, stopped = False, False
    with log_path.open("a", encoding="utf-8") as log:
        for row in rows:
            if stopped:
                record = {**row, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                          "status": "not_attempted", "detail": "Stopped after authentication, quota, or rate-limit response."}
            else:
                record, stopped = fetch_one(row, args.output_dir, api_key,
                                            args.timeout, args.max_mb * 1024 * 1024)
            incomplete |= record["status"] not in {"downloaded", "existing"}
            log.write(json.dumps({field: record.get(field, "") for field in FIELDS}, ensure_ascii=False) + "\n")
            log.flush()
            print(f"{row['openalex_id']}: {record['status']} {record.get('detail', '')}")
    print(f"Audit log: {log_path}")
    return 1 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
