#!/usr/bin/env python3
# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Run an approved OpenAlex query manifest with bounded process concurrency."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable
import re


FORMATS = {"bibtex": "bib", "json": "json", "markdown": "md", "csv": "csv"}
MODES = {"lexical", "semantic"}
HARD_STOP_PATTERN = re.compile(
    r"(?:HTTP\s+|status(?:\s+code)?\s*[:=]?\s*|\b)(401|402|403|429)\b",
    flags=re.IGNORECASE,
)


def safe_process_text(value: str | None) -> str:
    """Keep diagnostics while redacting an API key if a client echoed its URL."""
    return re.sub(r"([?&]api_key=)[^&\s]+", r"\1[REDACTED]", value or "").strip()


def load_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("queries"), list):
        raise ValueError("Manifest must be an object containing a queries list.")
    date_range = payload.get("date_range")
    if date_range is not None and (
        not isinstance(date_range, list)
        or len(date_range) != 2
        or not all(isinstance(year, int) for year in date_range)
        or date_range[0] > date_range[1]
    ):
        raise ValueError("date_range must be [from_year, to_year].")

    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(payload["queries"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"Query {index} must be an object.")
        query_id = item.get("id")
        query = item.get("query")
        mode = item.get("mode", "lexical")
        maximum = item.get("max_results", 20)
        if not isinstance(query_id, str) or not query_id.strip():
            raise ValueError(f"Query {index} requires a non-empty id.")
        if query_id in seen:
            raise ValueError(f"Duplicate query id: {query_id}")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"Query {query_id} requires non-empty query text.")
        if mode not in MODES:
            raise ValueError(f"Query {query_id} has unsupported mode: {mode}")
        if not isinstance(maximum, int) or maximum < 1:
            raise ValueError(f"Query {query_id} requires positive max_results.")
        if mode == "semantic" and maximum > 50:
            raise ValueError(f"Query {query_id}: semantic max_results cannot exceed 50.")
        seen.add(query_id)
        queries.append({**item, "id": query_id, "query": query, "mode": mode,
                        "max_results": maximum, "manifest_index": index})
    if not queries:
        raise ValueError("Manifest contains no queries.")
    return payload, queries


def command_for(
    item: dict[str, Any], manifest: dict[str, Any], output: Path,
    output_format: str, python: str, dry_run: bool,
) -> list[str]:
    command = [python, str(Path(__file__).with_name("openalex_bibtex.py")),
               "--query", item["query"], "--search-mode", item["mode"],
               "--max-results", str(item["max_results"]),
               "--format", output_format, "--output", str(output)]
    date_range = manifest.get("date_range")
    if date_range:
        command.extend(["--from-year", str(date_range[0]),
                        "--to-year", str(date_range[1])])
    if item.get("journal_scope"):
        command.extend(["--journal-scope", str(item["journal_scope"])])
    if dry_run:
        command.append("--dry-run")
    return command


def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def run_one(
    item: dict[str, Any], command: list[str], runner: Callable[[list[str]], Any]
) -> dict[str, Any]:
    started = time.monotonic()
    process = runner(command)
    stderr = safe_process_text(process.stderr)
    stdout = safe_process_text(process.stdout)
    return {
        "id": item["id"],
        "route": item.get("route", ""),
        "mode": item["mode"],
        "manifest_index": item["manifest_index"],
        "status": "completed" if process.returncode == 0 else "failed",
        "returncode": process.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout": stdout,
        "stderr": stderr,
        "stop_admission": process.returncode != 0 and bool(HARD_STOP_PATTERN.search(stderr)),
    }


def run_batch(
    manifest: dict[str, Any], queries: list[dict[str, Any]], output_dir: Path,
    output_format: str, workers: int, semantic_workers: int, python: str,
    dry_run: bool, runner: Callable[[list[str]], Any] = execute,
) -> list[dict[str, Any]]:
    extension = FORMATS[output_format]
    pending = list(queries)
    running: dict[Future[dict[str, Any]], dict[str, Any]] = {}
    results: dict[str, dict[str, Any]] = {}
    stop_admission = False

    def semantic_running() -> int:
        return sum(item["mode"] == "semantic" for item in running.values())

    def admit(pool: ThreadPoolExecutor) -> None:
        nonlocal pending
        while pending and len(running) < workers and not stop_admission:
            # Start the slower semantic lane as early as possible, while its
            # separate cap prevents concurrent semantic calls from provoking
            # OpenAlex's tighter endpoint rate limit.
            semantic_slot = next(
                (index for index, item in enumerate(pending)
                 if item["mode"] == "semantic"), None
            ) if semantic_running() < semantic_workers else None
            lexical_slot = next(
                (index for index, item in enumerate(pending)
                 if item["mode"] != "semantic"), None
            )
            slot = semantic_slot if semantic_slot is not None else lexical_slot
            if slot is None:
                return
            item = pending.pop(slot)
            output = output_dir / f"{item['id']}.{extension}"
            command = command_for(item, manifest, output, output_format, python, dry_run)
            future = pool.submit(run_one, item, command, runner)
            running[future] = item

    with ThreadPoolExecutor(max_workers=workers) as pool:
        admit(pool)
        while running:
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                item = running.pop(future)
                result = future.result()
                result["output"] = str((output_dir / f"{item['id']}.{extension}").resolve())
                results[item["id"]] = result
                stop_admission |= result["stop_admission"]
            admit(pool)

    reason = "Stopped after authentication, quota, or rate-limit response."
    for item in pending:
        results[item["id"]] = {
            "id": item["id"], "route": item.get("route", ""),
            "mode": item["mode"], "manifest_index": item["manifest_index"],
            "status": "not_attempted", "returncode": "", "elapsed_seconds": 0,
            "stdout": "", "stderr": reason, "stop_admission": False,
            "output": str((output_dir / f"{item['id']}.{extension}").resolve()),
        }
    return sorted(results.values(), key=lambda result: result["manifest_index"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--format", choices=tuple(FORMATS), default="json")
    parser.add_argument("--workers", type=int, default=3,
                        help="Maximum simultaneous query processes (default: 3).")
    parser.add_argument("--semantic-workers", type=int, default=1,
                        help="Maximum simultaneous semantic queries (default: 1).")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.workers < 1 or args.semantic_workers < 1:
        parser.error("--workers and --semantic-workers must be positive.")
    if args.semantic_workers > args.workers:
        parser.error("--semantic-workers cannot exceed --workers.")
    try:
        manifest, queries = load_manifest(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    audit_path = args.output_dir / "openalex-batch-audit.json"
    outputs = [args.output_dir / f"{item['id']}.{FORMATS[args.format]}" for item in queries]
    conflicts = [path for path in [audit_path, *outputs] if path.exists()]
    if conflicts:
        parser.error("Refusing to overwrite existing artifact(s): " +
                     ", ".join(str(path) for path in conflicts[:5]))
    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    results = run_batch(manifest, queries, args.output_dir, args.format, args.workers,
                        args.semantic_workers, args.python, args.dry_run)
    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(args.manifest.resolve()),
        "settings": {"workers": args.workers, "semantic_workers": args.semantic_workers,
                     "format": args.format, "dry_run": args.dry_run},
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "queries": results,
    }
    if args.dry_run:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    else:
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        print(f"Audit log: {audit_path}")
    completed = sum(result["status"] == "completed" for result in results)
    print(f"Completed {completed}/{len(results)} queries with up to {args.workers} workers.")
    return 0 if completed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
