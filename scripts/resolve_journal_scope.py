#!/usr/bin/env python3
"""Resolve a human-authored journal scope to auditable OpenAlex source IDs."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests


API_URL = "https://api.openalex.org/sources"


def normalized(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"^the\s+", "", value)
    return re.sub(r"[^a-z0-9]+", "", value)


def unique_journals(groups: list[dict[str, Any]]) -> dict[str, list[str]]:
    memberships: dict[str, list[str]] = {}
    for group in groups:
        group_id = group["id"]
        for journal in group["journals"]:
            memberships.setdefault(journal, []).append(group_id)
    return memberships


def resolve_one(
    session: requests.Session, title: str, api_key: str | None
) -> dict[str, Any]:
    params = {"search": title, "per-page": 5}
    if api_key:
        params["api_key"] = api_key
    for attempt in range(6):
        response = session.get(API_URL, params=params, timeout=30)
        if response.status_code != 429:
            break
        time.sleep(2 + attempt)
    response.raise_for_status()
    candidates = response.json().get("results", [])
    title_key = normalized(title)
    exact = [
        item
        for item in candidates
        if title_key in normalized(item.get("display_name", ""))
        and item.get("type") == "journal"
    ]
    if not exact:
        names = [item.get("display_name") for item in candidates]
        raise ValueError(f"Could not resolve {title!r} uniquely; candidates: {names}")
    exact.sort(key=lambda item: item.get("works_count") or 0, reverse=True)
    chosen = exact[0]
    if len(exact) > 1:
        chosen = dict(chosen)
        chosen["resolution_note"] = (
            "Multiple exact-title journal records; selected the one with the "
            "largest OpenAlex works_count. Candidates: "
            + ", ".join(item["id"].rsplit("/", 1)[-1] for item in exact)
        )
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve journal names in a scope registry to OpenAlex sources."
    )
    parser.add_argument("registry", type=Path)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Seconds between requests; increase when using the anonymous API.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Resolve every journal again instead of reusing existing records.",
    )
    args = parser.parse_args()

    payload = json.loads(args.registry.read_text(encoding="utf-8"))
    memberships = unique_journals(payload["groups"])
    lookup_overrides = payload.get("openalex_lookup_overrides", {})
    existing = {
        item["ais_name"]: item for item in payload.get("resolved_sources", [])
    }
    resolved = []
    unresolved = []
    session = requests.Session()
    api_key = os.environ.get("OPENALEX_API_KEY")

    for index, (title, groups) in enumerate(memberships.items(), start=1):
        if title in existing and not args.refresh:
            resolved.append(existing[title])
            print(f"[{index}/{len(memberships)}] cached {title}")
            continue
        try:
            item = resolve_one(session, lookup_overrides.get(title, title), api_key)
        except (requests.RequestException, ValueError) as exc:
            unresolved.append({"ais_name": title, "groups": groups, "error": str(exc)})
            print(f"[{index}/{len(memberships)}] UNRESOLVED {title}: {exc}")
            time.sleep(args.delay)
            continue
        resolved.append(
            {
                "ais_name": title,
                "openalex_id": item["id"].rsplit("/", 1)[-1],
                "openalex_name": item["display_name"],
                "issn_l": item.get("issn_l"),
                "issns": item.get("issn") or [],
                "groups": groups,
                **(
                    {"resolution_note": item["resolution_note"]}
                    if item.get("resolution_note")
                    else {}
                ),
            }
        )
        print(f"[{index}/{len(memberships)}] {title} -> {item['id']}")
        time.sleep(args.delay)

    payload["resolved_sources"] = resolved
    payload["unresolved_sources"] = unresolved
    args.registry.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Resolved {len(resolved)} unique journals; "
        f"{len(unresolved)} unresolved in {args.registry}"
    )
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
