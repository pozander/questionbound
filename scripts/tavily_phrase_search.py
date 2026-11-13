#!/usr/bin/env python3
# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Run a bounded, auditable Tavily search for passage attribution."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_KEY_FILE = PROJECT_ROOT / ".secrets" / "tavily.env"
MAX_QUERIES_CEILING = 30
MAX_RESULTS_CEILING = 10


def load_api_key(path: Path) -> str:
    key = os.environ.get("TAVILY_API_KEY", "").strip().strip("'\"")
    if key:
        return key
    try:
        lines = path.expanduser().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ""
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith("TAVILY_API_KEY="):
            value = value.split("=", 1)[1].strip()
        return value.strip("'\"")
    return ""


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")
    queries = payload.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("manifest must contain a non-empty queries list")
    if len(queries) > MAX_QUERIES_CEILING:
        raise ValueError(f"at most {MAX_QUERIES_CEILING} queries are permitted")
    normalized = []
    for index, item in enumerate(queries, 1):
        if isinstance(item, str):
            item = {"id": f"q{index:02d}", "query": item}
        if not isinstance(item, dict) or not str(item.get("query") or "").strip():
            raise ValueError(f"query {index} must be a string or an object with query")
        normalized.append(
            {
                "id": str(item.get("id") or f"q{index:02d}"),
                "query": " ".join(str(item["query"]).split()),
                "rationale": str(item.get("rationale") or "").strip(),
            }
        )
    if len({item["id"] for item in normalized}) != len(normalized):
        raise ValueError("query IDs must be unique")
    payload["queries"] = normalized
    return payload


def tavily_search(api_key: str, query: str, max_results: int, timeout: float) -> dict[str, Any]:
    response = requests.post(
        TAVILY_SEARCH_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "topic": "general",
            "include_answer": False,
            "include_raw_content": False,
            "include_usage": True,
            "auto_parameters": False,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RuntimeError("Tavily returned an unexpected response shape")
    return payload


def run(
    manifest: dict[str, Any], api_key: str, max_results: int, timeout: float
) -> dict[str, Any]:
    attempts = []
    for item in manifest["queries"]:
        attempt = {**item, "status": "request_failed", "results": []}
        try:
            response = tavily_search(api_key, item["query"], max_results, timeout)
            attempt.update(
                status="ok",
                request_id=response.get("request_id"),
                usage=response.get("usage"),
                results=response["results"],
            )
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            attempt["error"] = str(exc).replace(api_key, "[REDACTED]")
        attempts.append(attempt)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "Tavily Search",
        "endpoint": TAVILY_SEARCH_URL,
        "research_question": manifest.get("research_question"),
        "approval": manifest.get("approval"),
        "language_boundary": manifest.get("language_boundary"),
        "configuration": {
            "query_count": len(manifest["queries"]),
            "max_results_per_query": max_results,
            "automatic_retries": 0,
        },
        "reported_credits": sum(
            int((attempt.get("usage") or {}).get("credits") or 0)
            for attempt in attempts
        ),
        "attempts": attempts,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded Tavily search for exact and variant passage attribution"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--api-key-file", type=Path, default=DEFAULT_API_KEY_FILE)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not 1 <= args.max_results <= MAX_RESULTS_CEILING:
        print(
            f"error: --max-results must be between 1 and {MAX_RESULTS_CEILING}",
            file=sys.stderr,
        )
        return 2
    if args.output.exists():
        print(f"error: output already exists: {args.output}", file=sys.stderr)
        return 2
    print(f"Queries: {len(manifest['queries'])} (ceiling {MAX_QUERIES_CEILING})")
    print(f"Maximum results per query: {args.max_results}")
    print(f"Maximum Tavily search credits: {len(manifest['queries'])}")
    for item in manifest["queries"]:
        print(f"{item['id']}: {item['query']}")
    if args.dry_run:
        return 0
    api_key = load_api_key(args.api_key_file)
    if not api_key:
        print("error: Tavily API key not found", file=sys.stderr)
        return 2
    audit = run(manifest, api_key, args.max_results, args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Reported credits: {audit['reported_credits']}")
    print(f"Audit: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
