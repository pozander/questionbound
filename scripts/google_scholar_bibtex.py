#!/usr/bin/env python3
# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""
Fetch BibTeX records for top Google Scholar search results.

Google Scholar does not provide an official public API and may block automated
requests. This script is deliberately conservative: it rate-limits requests,
uses browser-like headers, supports an optional cookie, and fails with a clear
message when Scholar returns a consent, captcha, or unusual page.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


SCHOLAR_BASE = "https://scholar.google.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class ScholarSearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cids: list[str] = []
        self._in_result = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "div" and "gs_r" in attr.get("class", ""):
            self._in_result = True
            cid = attr.get("data-cid")
            if cid and cid not in self.cids:
                self.cids.append(cid)
        if self._in_result and tag == "a":
            href = attr.get("href", "")
            match = re.search(r"q=info:([^:]+):scholar\.google\.com", href)
            if match:
                cid = urllib.parse.unquote(match.group(1))
                if cid not in self.cids:
                    self.cids.append(cid)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_result:
            self._in_result = False


class BibtexLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.href: str | None = None
        self._capture_text = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "a":
            href = attr.get("href", "")
            if "scholar.bib" in href:
                self.href = href
            self._capture_text = True

    def handle_data(self, data: str) -> None:
        if self._capture_text and "BibTeX" in data:
            pass

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture_text = False


def read_query(args: argparse.Namespace) -> str:
    if args.query:
        return args.query.strip()

    if not args.query_file:
        raise SystemExit("Provide --query or --query-file.")

    text = Path(args.query_file).read_text(encoding="utf-8")
    fenced = re.search(r"```(?:text)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def make_request(url: str, cookie: str | None, timeout: int) -> str:
    headers = {
        "User-Agent": os.environ.get("SCHOLAR_USER_AGENT", DEFAULT_USER_AGENT),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if cookie:
        headers["Cookie"] = cookie

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from Google Scholar.\n{body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def scholar_search_url(query: str, start: int) -> str:
    params = {
        "q": query,
        "hl": "en",
        "as_sdt": "0,5",
        "start": str(start),
    }
    return f"{SCHOLAR_BASE}/scholar?{urllib.parse.urlencode(params)}"


def citation_url(cid: str) -> str:
    params = {
        "q": f"info:{cid}:scholar.google.com/",
        "output": "cite",
        "hl": "en",
    }
    return f"{SCHOLAR_BASE}/scholar?{urllib.parse.urlencode(params)}"


def absolute_scholar_url(href: str) -> str:
    return urllib.parse.urljoin(SCHOLAR_BASE, html.unescape(href))


def detect_block(page: str) -> str | None:
    lowered = page.lower()
    if "unusual traffic" in lowered or "sorry" in lowered and "google" in lowered:
        return "Google Scholar returned an unusual-traffic or captcha page."
    if "enable javascript" in lowered and "cookies" in lowered:
        return "Google Scholar returned a cookies/javascript interstitial."
    if "our systems have detected" in lowered:
        return "Google Scholar detected automated traffic."
    return None


def collect_cids(query: str, limit: int, cookie: str | None, timeout: int, delay: float) -> list[str]:
    cids: list[str] = []
    for start in range(0, limit, 10):
        page = make_request(scholar_search_url(query, start), cookie, timeout)
        blocked = detect_block(page)
        if blocked:
            raise RuntimeError(blocked)

        parser = ScholarSearchParser()
        parser.feed(page)
        for cid in parser.cids:
            if cid not in cids:
                cids.append(cid)
            if len(cids) >= limit:
                return cids

        if not parser.cids:
            raise RuntimeError(
                "No Scholar result IDs found. The page structure may have changed, "
                "or Scholar may have returned a non-results page."
            )
        time.sleep(delay)
    return cids


def fetch_bibtex(cid: str, cookie: str | None, timeout: int, delay: float) -> str:
    cite_page = make_request(citation_url(cid), cookie, timeout)
    blocked = detect_block(cite_page)
    if blocked:
        raise RuntimeError(blocked)

    parser = BibtexLinkParser()
    parser.feed(cite_page)
    if not parser.href:
        raise RuntimeError(f"No BibTeX link found for Scholar result ID {cid}.")

    time.sleep(delay)
    bib = make_request(absolute_scholar_url(parser.href), cookie, timeout)
    if not bib.strip().startswith("@"):
        blocked = detect_block(bib)
        if blocked:
            raise RuntimeError(blocked)
        raise RuntimeError(f"BibTeX endpoint returned unexpected content for {cid}.")
    return bib.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Return BibTeX records for the top Google Scholar hits."
    )
    parser.add_argument("--query", help="Raw Google Scholar query string.")
    parser.add_argument("--query-file", help="Markdown or text file containing a query.")
    parser.add_argument("--max-results", type=int, default=20, help="Number of hits to fetch.")
    parser.add_argument("--output", default="results/google-scholar-results.bib")
    parser.add_argument("--delay", type=float, default=8.0, help="Seconds between requests.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the parsed query and first Scholar URL without requesting it.",
    )
    parser.add_argument(
        "--cookie",
        default=os.environ.get("GOOGLE_SCHOLAR_COOKIE"),
        help="Optional Google Scholar cookie string, or set GOOGLE_SCHOLAR_COOKIE.",
    )
    args = parser.parse_args()

    if args.max_results < 1:
        raise SystemExit("--max-results must be at least 1.")

    query = read_query(args)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("Parsed query:")
        print(query)
        print("\nFirst Scholar URL:")
        print(scholar_search_url(query, 0))
        print(f"\nOutput path: {output_path}")
        return 0

    try:
        cids = collect_cids(query, args.max_results, args.cookie, args.timeout, args.delay)
        bibtex_records = []
        for index, cid in enumerate(cids, start=1):
            print(f"[{index}/{len(cids)}] Fetching BibTeX for Scholar ID {cid}", file=sys.stderr)
            bibtex_records.append(fetch_bibtex(cid, args.cookie, args.timeout, args.delay))

        output_path.write_text("\n\n".join(bibtex_records) + "\n", encoding="utf-8")
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Wrote {len(bibtex_records)} BibTeX records to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
