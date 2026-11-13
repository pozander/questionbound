#!/usr/bin/env python3
"""Materialize missing abstracts from approved scout URLs and exact-work sources."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import quote

import requests

from tavily_abstract_fallback import (
    WebFetcher,
    compact_space,
    extract_abstract,
    identity_match,
    normalized_doi,
    source_class,
    tidy_abstract,
)


OPENAIRE_URL = "https://api.openaire.eu/search/publications"
MAX_SCOUT_TARGETS = 4
MAX_CANDIDATES_PER_TARGET = 5


def short_openalex_id(value: Any) -> str:
    text = compact_space(value).rstrip("/")
    return text.rsplit("/", 1)[-1]


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def scout_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = payload.get("results")
    if not isinstance(values, list) or len(values) > MAX_SCOUT_TARGETS:
        raise ValueError(f"Scout results must contain at most {MAX_SCOUT_TARGETS} targets")
    mapped: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("scout"), dict):
            raise ValueError("Malformed scout result")
        target = item.get("target") or {}
        work_id = short_openalex_id(target.get("openalex_id") or item["scout"].get("work_id"))
        if not work_id or work_id in mapped:
            raise ValueError("Scout target IDs must be present and unique")
        candidates = item["scout"].get("candidates") or []
        if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES_PER_TARGET:
            raise ValueError(f"Each scout target may contain at most {MAX_CANDIDATES_PER_TARGET} candidates")
        mapped[work_id] = item
    return mapped


def pdf_abstract(path: Path, timeout: float) -> dict[str, Any]:
    try:
        process = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "3", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.SubprocessError as exc:
        return {"source": str(path), "error": compact_space(exc)}
    if process.returncode:
        return {"source": str(path), "error": compact_space(process.stderr) or "pdftotext failed"}
    return {
        "source": str(path.resolve()),
        "document_text": process.stdout,
        "abstract": extract_abstract(process.stdout),
        "method": "local_pdf:pdftotext:first_3_pages",
    }


def _field_text(value: Any) -> str:
    if isinstance(value, dict):
        return compact_space(value.get("$"))
    return compact_space(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def fetch_openaire_abstract(record: dict[str, Any], timeout: float) -> dict[str, Any]:
    doi = normalized_doi(record.get("doi"))
    if not doi:
        return {"error": "record has no DOI"}
    try:
        response = requests.get(
            OPENAIRE_URL,
            params={"doi": doi, "format": "json"},
            headers={"User-Agent": "QuestionBound/1.0 (exact DOI abstract verification)"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"url": f"{OPENAIRE_URL}?doi={quote(doi)}&format=json", "error": compact_space(exc)}
    try:
        results = payload["response"]["results"]["result"]
    except (KeyError, TypeError):
        return {"url": response.url, "error": "OpenAIRE response contained no results"}
    for result in _as_list(results):
        try:
            work = result["metadata"]["oaf:entity"]["oaf:result"]
        except (KeyError, TypeError):
            continue
        pids = [
            _field_text(value)
            for value in _as_list(work.get("pid"))
            if isinstance(value, dict) and compact_space(value.get("@classid")).casefold() == "doi"
        ]
        titles = [_field_text(value) for value in _as_list(work.get("title"))]
        creators = [_field_text(value) for value in _as_list(work.get("creator"))]
        description = _field_text(work.get("description"))
        probe = {
            "url": response.url,
            "title": titles[0] if titles else "",
            "content": " ".join(pids + titles + creators),
            "document_text": " ".join(pids + titles + creators),
        }
        accepted, score, reasons = identity_match(record, probe)
        if not accepted or doi not in {normalized_doi(value) for value in pids}:
            continue
        abstract = tidy_abstract(re.sub(r"(?i)^abstract\s*[:.\-—]?\s*", "", description))
        if len(abstract) < 80:
            continue
        return {
            "url": response.url,
            "abstract": abstract[:5000],
            "method": "openaire_api:oaf:result.description",
            "identity_score": score,
            "identity_reasons": reasons,
            "source_class": "bibliographic_database",
        }
    return {"url": response.url, "error": "No identity-verified OpenAIRE abstract"}


def provenance(provider: str, source: str, method: str, source_kind: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "source_url": source,
        "source_class": source_kind,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "verification": "exact_work_identity_and_explicit_abstract_field_or_label",
    }


def materialize(
    pack: dict[str, Any],
    scouts: dict[str, dict[str, Any]],
    pdf_dir: Path,
    timeout: float,
    fetcher: WebFetcher | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = deepcopy(pack)
    records = output.get("records")
    if not isinstance(records, list):
        raise ValueError("Input pack must contain a records list")
    fetcher = fetcher or WebFetcher(timeout=timeout)
    attempts: list[dict[str, Any]] = []
    for record in records:
        if compact_space(record.get("abstract")):
            continue
        work_id = short_openalex_id(record.get("openalex_id") or record.get("openalex"))
        attempt: dict[str, Any] = {"openalex_id": work_id, "title": record.get("title"), "routes": [], "status": "unresolved"}

        local_pdf = pdf_dir / f"{work_id}.pdf"
        if local_pdf.is_file():
            found = pdf_abstract(local_pdf, timeout)
            probe = {"title": "", "url": str(local_pdf), "document_text": found.get("document_text", "")}
            accepted, score, reasons = identity_match(record, probe)
            attempt["routes"].append({
                "route": "validated_local_pdf",
                "source": str(local_pdf.resolve()),
                "method": found.get("method"),
                "identity_match": accepted,
                "identity_score": score,
                "identity_reasons": reasons,
                "abstract_found": bool(found.get("abstract")),
                "error": found.get("error"),
            })
            if accepted and found.get("abstract"):
                record["abstract"] = found["abstract"]
                record["abstract_provenance"] = provenance(
                    "deterministic extraction from validated OpenAlex PDF",
                    str(local_pdf.resolve()),
                    found["method"],
                    "validated_local_pdf",
                )
                attempt["status"] = "abstract_added"
                attempt["source"] = str(local_pdf.resolve())

        scout = scouts.get(work_id)
        if attempt["status"] != "abstract_added" and scout:
            for candidate in scout["scout"].get("candidates") or []:
                classification = compact_space(candidate.get("classification"))
                if classification not in {"abstract", "uncertain"}:
                    attempt["routes"].append({"route": "scout_url", "url": candidate.get("url"), "status": f"skipped_classification:{classification}"})
                    continue
                fetched = fetcher.fetch(candidate.get("url"))
                probe = {
                    "title": fetched.get("document_title"),
                    "url": fetched.get("url"),
                    "document_text": fetched.get("document_text"),
                }
                accepted, score, reasons = identity_match(record, probe)
                attempt["routes"].append({
                    "route": "scout_url",
                    "url": candidate.get("url"),
                    "final_url": fetched.get("url"),
                    "scout_classification": classification,
                    "scout_confidence": candidate.get("confidence"),
                    "method": fetched.get("method"),
                    "identity_match": accepted,
                    "identity_score": score,
                    "identity_reasons": reasons,
                    "abstract_found": bool(fetched.get("abstract")),
                    "error": fetched.get("error"),
                })
                if accepted and fetched.get("abstract"):
                    record["abstract"] = fetched["abstract"]
                    record["abstract_provenance"] = provenance(
                        "deterministic extraction after bounded OpenAI source scouting",
                        fetched.get("url") or candidate["url"],
                        fetched["method"],
                        candidate.get("source_class") or source_class(candidate["url"])[0],
                    )
                    attempt["status"] = "abstract_added"
                    attempt["source"] = fetched.get("url") or candidate["url"]
                    break

        if attempt["status"] != "abstract_added" and normalized_doi(record.get("doi")):
            found = fetch_openaire_abstract(record, timeout)
            attempt["routes"].append({
                "route": "exact_doi_openaire",
                "url": found.get("url"),
                "method": found.get("method"),
                "identity_score": found.get("identity_score"),
                "identity_reasons": found.get("identity_reasons"),
                "abstract_found": bool(found.get("abstract")),
                "error": found.get("error"),
            })
            if found.get("abstract"):
                record["abstract"] = found["abstract"]
                record["abstract_provenance"] = provenance(
                    "deterministic exact-DOI extraction from OpenAIRE",
                    found["url"],
                    found["method"],
                    found["source_class"],
                )
                attempt["status"] = "abstract_added"
                attempt["source"] = found["url"]
        attempts.append(attempt)

    remaining = sum(not compact_space(record.get("abstract")) for record in records)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_missing": len(attempts),
        "abstracts_added": sum(item["status"] == "abstract_added" for item in attempts),
        "remaining_missing": remaining,
        "scout_target_limit": MAX_SCOUT_TARGETS,
        "candidate_limit_per_target": MAX_CANDIDATES_PER_TARGET,
    }
    output["abstract_materialization"] = summary
    return output, {**summary, "attempts": attempts}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--scout-results", required=True, type=Path)
    parser.add_argument("--pdf-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit-output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.output.exists() or args.audit_output.exists():
        parser.error("Output paths must be new; existing artifacts are never overwritten")
    try:
        pack = load_json(args.input)
        scouts = scout_map(load_json(args.scout_results))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    missing = [short_openalex_id(record.get("openalex_id")) for record in pack.get("records", []) if not compact_space(record.get("abstract"))]
    if args.dry_run:
        print(json.dumps({
            "missing_records": missing,
            "scout_targets": sorted(scouts),
            "local_pdf_candidates": [work_id for work_id in missing if (args.pdf_dir / f"{work_id}.pdf").is_file()],
            "network_routes": ["approved scout candidate URLs", "exact DOI OpenAIRE fallback"],
            "paid_calls": 0,
        }, indent=2))
        return 0
    try:
        enriched, audit = materialize(pack, scouts, args.pdf_dir, args.timeout)
        write_json(args.output, enriched)
        write_json(args.audit_output, audit)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Missing abstracts attempted: {audit['input_missing']}")
    print(f"Abstracts added: {audit['abstracts_added']}")
    print(f"Remaining missing: {audit['remaining_missing']}")
    print(f"Enriched pack: {args.output}")
    print(f"Audit: {args.audit_output}")
    return 0 if audit["remaining_missing"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
