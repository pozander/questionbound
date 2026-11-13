#!/usr/bin/env python3
"""Recover lawful full text for exact OpenAlex IDs after cache misses.

The primary downloader intentionally uses only OpenAlex's own PDF cache.  This
fallback consumes its ``downloads.jsonl`` audit, selects only ``unavailable``
records, and tries two bounded, identity-controlled routes:

1. PDF and landing-page URLs in the exact OpenAlex work's locations.
2. The exact DOI landing page and publisher metadata such as
   ``citation_pdf_url``.

It is not a literature search, does not substitute titles or editions, and
does not use Scholar, general web search, or an LLM.
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
from difflib import SequenceMatcher
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests


OPENALEX_ID = re.compile(r"W[0-9]+", re.I)
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
PDF_META_NAMES = {
    "citation_pdf_url",
    "eprints.document_url",
    "wkhealth_pdf_url",
}
DOI_META_NAMES = {
    "citation_doi",
    "dc.identifier",
    "dc.identifier.doi",
    "prism.doi",
}
TITLE_META_NAMES = {"citation_title", "dc.title", "dcterms.title", "og:title"}
AUTHOR_META_NAMES = {"citation_author", "dc.creator", "dcterms.creator"}
SENSITIVE_QUERY_NAMES = {"api_key", "apikey", "key", "token", "signature", "sig", "auth"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "QuestionBound/1.0"
)


def compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_title(value: Any) -> str:
    return re.sub(r"[^\w]+", " ", compact(value).casefold()).strip()


def normalize_doi(value: Any) -> str:
    text = compact(value).casefold()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    text = text.removeprefix("doi:").strip()
    match = DOI_PATTERN.search(text)
    return match.group(0).rstrip(".,;)]") if match else ""


def safe_url(value: Any) -> str | None:
    text = compact(value)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.casefold()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return None
    try:
        if ipaddress.ip_address(host).is_private:
            return None
    except ValueError:
        pass
    return text


def redact_url(value: str) -> str:
    parsed = urlparse(value)
    query = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        query.append((key, "REDACTED" if key.casefold() in SENSITIVE_QUERY_NAMES else item))
    return urlunparse(parsed._replace(query=urlencode(query)))


def pdf_info(path: Path) -> tuple[int, str]:
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
            raise ValueError("PDF is too small or lacks an end marker.")
    return size, digest.hexdigest()


def read_unavailable(path: Path) -> list[dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            work_id = compact(record.get("openalex_id")).upper()
            if not OPENALEX_ID.fullmatch(work_id):
                raise ValueError(f"Line {number}: invalid OpenAlex ID.")
            latest[work_id] = record
    return [latest[key] for key in sorted(latest) if latest[key].get("status") == "unavailable"]


def location_candidates(work: dict[str, Any]) -> list[dict[str, Any]]:
    ordered: list[tuple[str, Any]] = [
        ("best_oa_location", work.get("best_oa_location")),
        ("primary_location", work.get("primary_location")),
    ]
    ordered.extend((f"locations[{index}]", value) for index, value in enumerate(work.get("locations") or []))
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for origin, location in ordered:
        if not isinstance(location, dict):
            continue
        common = {
            "origin": origin,
            "is_oa": location.get("is_oa"),
            "license": location.get("license"),
            "version": location.get("version"),
            "source": compact((location.get("source") or {}).get("display_name")) if isinstance(location.get("source"), dict) else "",
        }
        for kind, field in (("pdf", "pdf_url"), ("landing", "landing_page_url")):
            url = safe_url(location.get(field))
            if url and url not in seen:
                seen.add(url)
                candidates.append({**common, "kind": kind, "url": url})
    doi = normalize_doi(work.get("doi"))
    if doi:
        url = f"https://doi.org/{doi}"
        if url not in seen:
            candidates.append({"kind": "landing", "url": url, "origin": "doi", "is_oa": None, "license": None, "version": None, "source": "DOI resolver"})
    return candidates


class LandingParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.metadata: dict[str, list[str]] = {}
        self.pdf_urls: list[str] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self._jsonld = False
        self._jsonld_text: list[str] = []

    def add_meta(self, name: str, content: str) -> None:
        name, content = name.casefold().strip(), compact(content)
        if name and content:
            self.metadata.setdefault(name, []).append(content)

    def add_pdf(self, href: str) -> None:
        url = safe_url(urljoin(self.base_url, href))
        if url and url not in self.pdf_urls:
            self.pdf_urls.append(url)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.casefold(): value or "" for key, value in attrs}
        if tag == "meta":
            name = attr.get("name") or attr.get("property")
            content = attr.get("content")
            if name and content:
                self.add_meta(name, content)
                if name.casefold() in PDF_META_NAMES:
                    self.add_pdf(content)
        elif tag == "link":
            rel = attr.get("rel", "").casefold()
            media_type = attr.get("type", "").casefold()
            if "alternate" in rel and media_type == "application/pdf":
                self.add_pdf(attr.get("href", ""))
        elif tag == "a":
            self._anchor_href = attr.get("href")
            self._anchor_text = []
        elif tag == "script" and attr.get("type", "").casefold() == "application/ld+json":
            self._jsonld = True
            self._jsonld_text = []

    def handle_data(self, data: str) -> None:
        if self._anchor_href is not None:
            self._anchor_text.append(data)
        if self._jsonld:
            self._jsonld_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor_href is not None:
            href = self._anchor_href
            label = compact("".join(self._anchor_text)).casefold()
            path = urlparse(urljoin(self.base_url, href)).path.casefold()
            if path.endswith(".pdf") or label in {"pdf", "download pdf", "full text pdf", "view pdf"}:
                self.add_pdf(href)
            self._anchor_href = None
            self._anchor_text = []
        elif tag == "script" and self._jsonld:
            self._consume_jsonld("".join(self._jsonld_text))
            self._jsonld = False
            self._jsonld_text = []

    def _consume_jsonld(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, list):
                stack.extend(value)
                continue
            if not isinstance(value, dict):
                continue
            graph = value.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            title = value.get("headline") or value.get("name")
            if isinstance(title, str):
                self.add_meta("citation_title", title)
            identifier = value.get("doi") or value.get("identifier")
            identifiers = identifier if isinstance(identifier, list) else [identifier]
            for item in identifiers:
                if isinstance(item, str):
                    self.add_meta("citation_doi", item)
                elif isinstance(item, dict) and isinstance(item.get("value"), str):
                    self.add_meta("citation_doi", item["value"])
            authors = value.get("author")
            authors = authors if isinstance(authors, list) else [authors]
            for author in authors:
                if isinstance(author, str):
                    self.add_meta("citation_author", author)
                elif isinstance(author, dict) and isinstance(author.get("name"), str):
                    self.add_meta("citation_author", author["name"])
            for key in ("contentUrl", "encodingUrl"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    self.add_pdf(candidate)


def landing_identity(expected: dict[str, Any], parser: LandingParser) -> tuple[bool, str]:
    expected_doi = normalize_doi(expected.get("doi"))
    observed_dois: set[str] = set()
    for name in DOI_META_NAMES:
        for value in parser.metadata.get(name, []):
            doi = normalize_doi(value)
            if doi:
                observed_dois.add(doi)
    if expected_doi and expected_doi in observed_dois:
        return True, "exact_doi"

    expected_title = normalize_title(expected.get("title"))
    titles = [normalize_title(value) for name in TITLE_META_NAMES for value in parser.metadata.get(name, [])]
    similarity = max((SequenceMatcher(None, expected_title, title).ratio() for title in titles if title), default=0.0)
    expected_authors = [compact(a.get("author", {}).get("display_name")) for a in expected.get("authorships") or [] if isinstance(a, dict)]
    expected_surname = normalize_title(expected_authors[0]).split()[-1] if expected_authors and normalize_title(expected_authors[0]) else ""
    observed_authors = " ".join(value for name in AUTHOR_META_NAMES for value in parser.metadata.get(name, [])).casefold()
    if similarity >= 0.90 and expected_surname and expected_surname in normalize_title(observed_authors).split():
        return True, f"title_author:{similarity:.3f}"
    if similarity >= 0.97:
        return True, f"title:{similarity:.3f}"
    return False, f"identity_insufficient:title_similarity={similarity:.3f}"


def fetch_openalex(work_id: str, api_key: str, timeout: float, client: Any = requests) -> dict[str, Any]:
    response = client.get(
        f"https://api.openalex.org/works/{work_id}",
        params={"api_key": api_key}, timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenAlex metadata HTTP {response.status_code}")
    work = response.json()
    if not isinstance(work, dict) or work.get("id") != f"https://openalex.org/{work_id}":
        raise RuntimeError("OpenAlex metadata identity mismatch")
    return work


def fetch_landing(candidate: dict[str, Any], expected: dict[str, Any], timeout: float, max_bytes: int, client: Any = requests) -> tuple[list[str], dict[str, Any]]:
    audit = {"route": candidate["origin"], "kind": "landing", "url": redact_url(candidate["url"])}
    try:
        response = client.get(candidate["url"], timeout=timeout, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/pdf"})
        audit["http_status"] = response.status_code
        audit["final_url"] = redact_url(getattr(response, "url", candidate["url"]))
        if response.status_code != 200:
            audit["status"] = "http_error"
            return [], audit
        content = response.content
        if len(content) > max_bytes:
            audit["status"] = "page_too_large"
            return [], audit
        if content.startswith(b"%PDF-"):
            audit["status"] = "direct_pdf_response"
            return [getattr(response, "url", candidate["url"])], audit
        parser = LandingParser(getattr(response, "url", candidate["url"]))
        parser.feed(content.decode(response.encoding or "utf-8", errors="replace"))
        ok, reason = landing_identity(expected, parser)
        audit["identity"] = reason
        audit["status"] = "accepted" if ok else "identity_rejected"
        audit["pdf_candidates"] = [redact_url(url) for url in parser.pdf_urls]
        return (parser.pdf_urls if ok else []), audit
    except requests.RequestException as exc:
        audit.update(status="network_error", error=type(exc).__name__)
        return [], audit


def validate_pdf_identity(path: Path, expected: dict[str, Any]) -> tuple[bool, str]:
    try:
        process = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "3", str(path), "-"],
            check=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False, "pdf_text_extraction_failed"
    text = process.stdout.decode("utf-8", errors="replace")
    normalized_text = normalize_title(text)
    expected_doi = normalize_doi(expected.get("doi"))
    if expected_doi and expected_doi in compact(text).casefold().replace("https://doi.org/", ""):
        return True, "pdf_exact_doi"
    title_tokens = [token for token in normalize_title(expected.get("title")).split() if len(token) >= 3]
    text_tokens = set(normalized_text.split())
    coverage = sum(token in text_tokens for token in title_tokens) / len(title_tokens) if title_tokens else 0.0
    authors = [compact(a.get("author", {}).get("display_name")) for a in expected.get("authorships") or [] if isinstance(a, dict)]
    surname = normalize_title(authors[0]).split()[-1] if authors and normalize_title(authors[0]) else ""
    author_present = bool(surname and surname in text_tokens)
    if coverage >= 0.78 and author_present:
        return True, f"pdf_title_author:coverage={coverage:.3f}"
    if coverage >= 0.92:
        return True, f"pdf_title:coverage={coverage:.3f}"
    return False, f"pdf_identity_insufficient:title_coverage={coverage:.3f};author={author_present}"


def download_pdf(url: str, target: Path, expected: dict[str, Any], timeout: float, max_bytes: int, referer: str | None = None, client: Any = requests) -> tuple[dict[str, Any], bool]:
    audit = {"kind": "pdf", "url": redact_url(url)}
    temporary: Path | None = None
    try:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.5"}
        if referer:
            headers["Referer"] = referer
        with client.get(url, stream=True, timeout=timeout, headers=headers) as response:
            audit["http_status"] = response.status_code
            audit["final_url"] = redact_url(getattr(response, "url", url))
            if response.status_code != 200:
                audit["status"] = "http_error"
                return audit, False
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.stem}-", suffix=".part", delete=False) as stream:
                temporary = Path(stream.name)
                size = 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("Download exceeds size ceiling.")
                    stream.write(chunk)
        size, checksum = pdf_info(temporary)
        identity_ok, identity = validate_pdf_identity(temporary, expected)
        audit["identity"] = identity
        if not identity_ok:
            audit.update(status="pdf_identity_rejected", bytes=size, sha256=checksum)
            return audit, False
        os.link(temporary, target)
        audit.update(status="downloaded", bytes=size, sha256=checksum)
        return audit, True
    except FileExistsError:
        size, checksum = pdf_info(target)
        audit.update(status="existing", bytes=size, sha256=checksum)
        return audit, True
    except requests.RequestException as exc:
        audit.update(status="network_error", error=type(exc).__name__)
        return audit, False
    except (OSError, ValueError) as exc:
        audit.update(status="invalid_or_local_error", error=type(exc).__name__)
        return audit, False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def recover_one(row: dict[str, str], output_dir: Path, api_key: str, timeout: float, max_bytes: int, max_candidates: int, max_pages: int, client: Any = requests) -> dict[str, Any]:
    work_id = row["openalex_id"].upper()
    target = output_dir / f"{work_id}.pdf"
    result: dict[str, Any] = {"openalex_id": work_id, "title": row.get("title", ""), "status": "unresolved", "path": str(target.resolve()), "attempts": []}
    try:
        work = fetch_openalex(work_id, api_key, timeout, client)
    except RuntimeError as exc:
        result.update(status="metadata_error", detail=str(exc))
        return result
    expected = {
        "title": work.get("display_name") or row.get("title"),
        "doi": work.get("doi"),
        "authorships": work.get("authorships") or [],
    }
    result.update(resolved_title=expected["title"], doi=normalize_doi(expected["doi"]))
    if target.exists():
        size, checksum = pdf_info(target)
        ok, identity = validate_pdf_identity(target, expected)
        if ok:
            result.update(status="existing", bytes=size, sha256=checksum, identity=identity)
        else:
            result.update(status="existing_identity_mismatch", bytes=size, sha256=checksum, identity=identity)
        return result
    candidates = location_candidates(work)
    result["candidate_count"] = len(candidates)

    pdf_queue: list[tuple[str, str]] = []
    landing_queue: list[dict[str, Any]] = []
    seen_pdf: set[str] = set()
    for candidate in candidates[:max_candidates]:
        if candidate["kind"] == "pdf":
            if candidate["url"] not in seen_pdf:
                pdf_queue.append((candidate["url"], candidate["origin"]))
                seen_pdf.add(candidate["url"])
        else:
            landing_queue.append(candidate)

    for url, origin in pdf_queue:
        audit, success = download_pdf(url, target, expected, timeout, max_bytes, client=client)
        audit["route"] = origin
        result["attempts"].append(audit)
        if success:
            result.update(status="external_oa_downloaded", chosen_route=origin, chosen_url=audit.get("final_url") or audit["url"], bytes=audit["bytes"], sha256=audit["sha256"])
            return result

    for candidate in landing_queue[:max_pages]:
        urls, landing_audit = fetch_landing(candidate, expected, timeout, min(max_bytes, 8 * 1024 * 1024), client)
        result["attempts"].append(landing_audit)
        for url in urls:
            if url in seen_pdf:
                continue
            seen_pdf.add(url)
            audit, success = download_pdf(url, target, expected, timeout, max_bytes, referer=candidate["url"], client=client)
            audit["route"] = f"{candidate['origin']}:publisher_metadata"
            result["attempts"].append(audit)
            if success:
                result.update(status="publisher_pdf_downloaded", chosen_route=audit["route"], chosen_url=audit.get("final_url") or audit["url"], bytes=audit["bytes"], sha256=audit["sha256"])
                return result

    statuses = {attempt.get("status") for attempt in result["attempts"]}
    if "identity_rejected" in statuses:
        result["detail"] = "Candidate landing pages failed deterministic identity checks or yielded no valid PDF."
    else:
        result["detail"] = "No external OpenAlex location or accepted publisher page yielded a valid PDF."
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-log", required=True, type=Path, help="Primary downloader downloads.jsonl.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-records", type=int, default=50)
    parser.add_argument("--max-candidates-per-record", type=int, default=20)
    parser.add_argument("--max-pages-per-record", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--max-mb", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if min(args.max_records, args.max_candidates_per_record, args.max_pages_per_record, args.max_mb) < 1 or args.timeout <= 0:
        parser.error("All ceilings and timeout must be positive.")
    try:
        rows = read_unavailable(args.download_log)[:args.max_records]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if not rows:
        parser.error("No unavailable records in the supplied audit log.")
    if args.dry_run:
        for row in rows:
            print(f"{row['openalex_id']} | {row.get('title', '')}")
        print(f"{len(rows)} exact OpenAlex cache misses selected; no network calls or file writes.")
        return 0
    api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not api_key:
        parser.error("Set OPENALEX_API_KEY before running the fallback.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / "recovery.jsonl"
    resolved = 0
    with log_path.open("a", encoding="utf-8") as log:
        for row in rows:
            with requests.Session() as client:
                result = recover_one(row, args.output_dir, api_key, args.timeout, args.max_mb * 1024 * 1024, args.max_candidates_per_record, args.max_pages_per_record, client)
            resolved += result["status"] in {"external_oa_downloaded", "publisher_pdf_downloaded", "existing"}
            log.write(json.dumps(result, ensure_ascii=False) + "\n")
            log.flush()
            print(f"{row['openalex_id']}: {result['status']}")
    print(f"Recovered {resolved} of {len(rows)} cache misses. Audit log: {log_path}")
    return 0 if resolved == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
