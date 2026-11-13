#!/usr/bin/env python3
"""Run a budgeted OpenAI web-search scout for already-missing abstracts only."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import requests


RESPONSES_URL = "https://api.openai.com/v1/responses"
MODEL_RATES = {"gpt-6-luna": {"input": 0.10, "output": 0.50}}
WEB_SEARCH_USD = 0.01
WEB_CONTEXT_RESERVATION_TOKENS = 128_000
FRAMING_RESERVATION_TOKENS = 4_096


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["work_id", "result", "candidates", "limitations"],
    "properties": {
        "work_id": {"type": "string"},
        "result": {"type": "string", "enum": ["candidate_found", "no_abstract_expected", "not_found", "uncertain"]},
        "candidates": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["url", "source_class", "classification", "locator", "confidence", "reason"],
                "properties": {
                    "url": {"type": "string"},
                    "source_class": {"type": "string", "enum": ["publisher", "journal", "institutional_repository", "author_profile", "bibliographic_database", "other"]},
                    "classification": {"type": "string", "enum": ["abstract", "repository_description", "author_summary", "search_snippet", "book_description", "uncertain"]},
                    "locator": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind", "value"],
                        "properties": {
                            "kind": {"type": "string", "enum": ["html_meta", "json_ld", "html_heading", "api_field", "visible_section"]},
                            "value": {"type": "string"}
                        }
                    },
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "reason": {"type": "string"}
                }
            }
        },
        "limitations": {"type": "array", "items": {"type": "string"}}
    }
}


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "model": "gpt-6-luna",
        "reasoning_effort": "low",
        "max_output_tokens_per_response": 1200,
        "max_tool_calls_per_response": 3,
        "maximum_responses": 4,
        "budget_usd": 0.20,
        "store": False,
    }
    for key, expected in required.items():
        if data.get(key) != expected:
            raise ValueError(f"Manifest {key} must equal approved value {expected!r}.")
    targets = data.get("targets")
    if not isinstance(targets, list) or len(targets) != 4:
        raise ValueError("Manifest must contain exactly four approved targets.")
    ids = [target.get("openalex_id") for target in targets if isinstance(target, dict)]
    if len(ids) != 4 or len(set(ids)) != 4:
        raise ValueError("Manifest target IDs must be four unique values.")
    return data


def make_prompt(work: dict[str, Any]) -> str:
    return f"""You are a bounded scholarly-source scout.

Find a genuine, explicitly presented abstract for this exact publication only:

OpenAlex ID: {work['openalex_id']}
DOI: {work.get('doi') or '[none]'}
Title: {work['title']}
Authors: {'; '.join(work['authors'])}
Year: {work['year']}
Journal or publication: {work.get('publication') or '[unknown]'}
Publisher: {work.get('publisher') or '[unknown]'}

Search priority, in this order:
1. The journal's own website or the publisher's official publication page.
2. The exact DOI landing page.
3. An institutional repository holding the publication record.
4. An author profile on a university or research-institution website.
5. A recognized bibliographic database.

Rules:
- Search only for this exact publication; do not broaden to related literature.
- Prefer journal and publisher pages even if another source ranks higher in search results.
- Return candidate URLs and locators, but do not return, reconstruct, quote, or summarize the abstract wording.
- Judge whether the located material is an abstract, repository description, author summary, search snippet, book description, or uncertain.
- A locator must describe where the text appears on the fetched page.
- Search-result snippets are not abstracts.
- If the publication appears not to have a conventional abstract, return no_abstract_expected.
- If identity or classification is uncertain, preserve that uncertainty.
"""


def reservation_usd(prompt: str, manifest: dict[str, Any]) -> float:
    rates = MODEL_RATES[manifest["model"]]
    # UTF-8 bytes conservatively upper-bound text tokens. Reserve the documented
    # web-search context ceiling as uncached input and every allowed tool call.
    input_bound = len(prompt.encode("utf-8")) + FRAMING_RESERVATION_TOKENS + WEB_CONTEXT_RESERVATION_TOKENS
    token_cost = (input_bound * rates["input"] + manifest["max_output_tokens_per_response"] * rates["output"]) / 1_000_000
    tool_cost = manifest["max_tool_calls_per_response"] * WEB_SEARCH_USD
    return token_cost + tool_cost


def extract_output_json(response: dict[str, Any]) -> dict[str, Any]:
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                value = json.loads(content["text"])
                if isinstance(value, dict):
                    return value
    raise ValueError("Response contained no structured output text.")


def request_body(work: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": manifest["model"],
        "reasoning": {"effort": manifest["reasoning_effort"]},
        "tools": [{"type": "web_search", "external_web_access": True, "search_context_size": "low"}],
        "tool_choice": "required",
        "max_tool_calls": manifest["max_tool_calls_per_response"],
        "max_output_tokens": manifest["max_output_tokens_per_response"],
        "include": ["web_search_call.action.sources"],
        "store": False,
        "text": {"format": {"type": "json_schema", "name": "abstract_source_scout", "strict": True, "schema": SCHEMA}},
        "input": make_prompt(work),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    prompts = [make_prompt(work) for work in manifest["targets"]]
    reservations = [reservation_usd(prompt, manifest) for prompt in prompts]
    total_reservation = sum(reservations)
    if total_reservation > manifest["budget_usd"] + 1e-12:
        parser.error(f"Conservative reservation USD {total_reservation:.6f} exceeds approved ceiling.")
    if args.dry_run:
        print(json.dumps({
            "model": manifest["model"],
            "targets": [work["openalex_id"] for work in manifest["targets"]],
            "maximum_responses": len(prompts),
            "max_tool_calls_per_response": manifest["max_tool_calls_per_response"],
            "max_output_tokens_per_response": manifest["max_output_tokens_per_response"],
            "conservative_total_reservation_usd": round(total_reservation, 6),
            "budget_usd": manifest["budget_usd"],
        }, indent=2))
        return 0
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        parser.error("OPENAI_API_KEY is required for the approved Responses API call.")
    if args.run_dir.exists():
        parser.error("Run directory already exists; use a new directory so the budget ledger cannot be reset.")
    args.run_dir.mkdir(parents=True)
    (args.run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger = {
        "budget_usd": manifest["budget_usd"],
        "reserved_usd": 0.0,
        "requests": [],
        "pricing": {"model_per_million_usd": MODEL_RATES[manifest["model"]], "web_search_per_call_usd": WEB_SEARCH_USD},
    }
    ledger_path = args.run_dir / "budget.json"
    results = []
    raw_dir = args.run_dir / "responses"
    raw_dir.mkdir()
    for index, (work, prompt, reserved) in enumerate(zip(manifest["targets"], prompts, reservations), 1):
        if ledger["reserved_usd"] + reserved > ledger["budget_usd"] + 1e-12:
            raise SystemExit("Budget guard refused the next request.")
        entry = {"index": index, "openalex_id": work["openalex_id"], "reserved_usd": reserved, "timestamp_utc": datetime.now(timezone.utc).isoformat()}
        ledger["requests"].append(entry)
        ledger["reserved_usd"] += reserved
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        body = request_body(work, manifest)
        try:
            response = requests.post(
                RESPONSES_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=180,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            entry["status"] = f"request_failed:{type(exc).__name__}"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            print(f"{work['openalex_id']}: request failed", file=sys.stderr)
            continue
        except ValueError:
            entry["status"] = "invalid_json_response"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            continue
        (raw_dir / f"{index:02d}-{work['openalex_id']}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            result = extract_output_json(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            entry["status"] = f"output_invalid:{type(exc).__name__}"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            continue
        if result.get("work_id") != work["openalex_id"]:
            entry["status"] = "output_work_id_mismatch"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            continue
        entry["status"] = "completed"
        entry["response_id"] = payload.get("id")
        entry["usage"] = payload.get("usage")
        entry["web_search_calls"] = sum(item.get("type") == "web_search_call" for item in payload.get("output") or [])
        results.append({"target": work, "response_id": payload.get("id"), "scout": result})
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        print(f"{work['openalex_id']}: completed")
    (args.run_dir / "scout-results.json").write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if len(results) == len(manifest["targets"]) else 1


if __name__ == "__main__":
    sys.exit(main())
