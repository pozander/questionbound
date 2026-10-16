#!/usr/bin/env python3
# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Fetch OpenAlex search results using PyAlex.

The default output remains BibTeX for compatibility with the existing workflow.
Use ``--format markdown`` or ``--format json`` to create abstract packs for
cheap first-pass literature triage before fetching full papers.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

try:
    from pyalex import Works, config, invert_abstract
    from requests import RequestException
except ImportError as exc:  # pragma: no cover - exercised by users without deps.
    raise SystemExit(
        "Missing dependency: pyalex. Install it with "
        "`python3 -m pip install -r requirements.txt`."
    ) from exc


DEFAULT_EMAIL = os.environ.get("OPENALEX_MAILTO")
DEFAULT_API_KEY = os.environ.get("OPENALEX_API_KEY")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
JOURNAL_SCOPES_DIR = PROJECT_ROOT / "journal-scopes"
OPENALEX_OR_LIMIT = 100
SEMANTIC_MAX_QUERY_CHARS = 2000
SEMANTIC_MAX_RESULTS = 50


ENTRY_TYPE_BY_OPENALEX_TYPE = {
    "article": "article",
    "book": "book",
    "book-chapter": "incollection",
    "book-section": "incollection",
    "dataset": "misc",
    "dissertation": "phdthesis",
    "editorial": "article",
    "erratum": "article",
    "letter": "article",
    "paratext": "misc",
    "peer-review": "misc",
    "preprint": "misc",
    "reference-entry": "inreference",
    "report": "techreport",
    "review": "article",
    "standard": "misc",
}


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


def compact_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def load_journal_scope(value: str) -> dict[str, Any]:
    candidate = Path(value)
    path = candidate if candidate.exists() else JOURNAL_SCOPES_DIR / f"{value}.json"
    if not path.is_file():
        raise ValueError(f"Journal scope not found: {value}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("scope_id"):
        raise ValueError(f"Invalid journal scope metadata in {path}")
    unresolved = payload.get("unresolved_sources", [])
    if unresolved:
        raise ValueError(f"Journal scope has unresolved sources: {path}")
    sources = payload.get("resolved_sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"Journal scope has no resolved sources: {path}")

    source_ids = []
    for source in sources:
        source_id = source.get("openalex_id") if isinstance(source, dict) else None
        if not isinstance(source_id, str) or not re.fullmatch(r"S\d+", source_id):
            raise ValueError(f"Invalid OpenAlex source ID in {path}: {source_id!r}")
        source_ids.append(source_id)
    if len(source_ids) != len(set(source_ids)):
        raise ValueError(f"Duplicate OpenAlex source IDs in {path}")

    payload["_path"] = str(path)
    payload["_source_ids"] = source_ids
    return payload


def source_id_batches(source_ids: list[str]) -> list[list[str]]:
    if not source_ids:
        return [[]]
    return [
        source_ids[index : index + OPENALEX_OR_LIMIT]
        for index in range(0, len(source_ids), OPENALEX_OR_LIMIT)
    ]


def works_query(
    query: str,
    from_year: int | None,
    to_year: int | None,
    source_ids: list[str],
    search_mode: str = "lexical",
):
    compacted = compact_query(query)
    if search_mode == "semantic":
        query_obj = Works(params={"search.semantic": compacted})
    elif search_mode == "lexical":
        query_obj = Works().search(compacted)
    else:
        raise ValueError(f"Unsupported search mode: {search_mode}")
    if source_ids:
        query_obj = query_obj.filter(
            primary_location={"source": {"id": "|".join(source_ids)}}
        )
    if from_year:
        query_obj = query_obj.filter(from_publication_date=f"{from_year}-01-01")
    if to_year:
        query_obj = query_obj.filter(to_publication_date=f"{to_year}-12-31")
    if search_mode == "lexical":
        query_obj = query_obj.sort(relevance_score="desc")
    return query_obj


def validate_search_request(search_mode: str, query: str, max_results: int) -> None:
    if max_results < 1:
        raise ValueError("--max-results must be at least 1.")
    if search_mode == "semantic":
        if len(compact_query(query)) > SEMANTIC_MAX_QUERY_CHARS:
            raise ValueError(
                f"Semantic queries must not exceed {SEMANTIC_MAX_QUERY_CHARS} characters."
            )
        if max_results > SEMANTIC_MAX_RESULTS:
            raise ValueError(
                f"Semantic searches support at most {SEMANTIC_MAX_RESULTS} results."
            )


def query_result_pages(
    query_obj: Any,
    search_mode: str,
    per_page: int,
    max_results: int,
):
    if search_mode == "semantic":
        return [query_obj.get(per_page=per_page)]
    return query_obj.paginate(per_page=per_page, n_max=max_results)


def fetch_works(
    query: str,
    max_results: int,
    mailto: str | None,
    api_key: str | None,
    from_year: int | None = None,
    to_year: int | None = None,
    source_ids: list[str] | None = None,
    search_mode: str = "lexical",
) -> list[dict[str, Any]]:
    if mailto:
        config.email = mailto
    if api_key:
        config.api_key = api_key

    works_by_id: dict[str, dict[str, Any]] = {}
    per_page = min(200, max_results)

    try:
        for batch in source_id_batches(source_ids or []):
            query_obj = works_query(
                query, from_year, to_year, batch, search_mode=search_mode
            )
            batch_count = 0
            for page in query_result_pages(
                query_obj, search_mode, per_page, max_results
            ):
                if not page:
                    break
                for work in page:
                    work_id = work.get("id")
                    if isinstance(work_id, str):
                        works_by_id.setdefault(work_id, work)
                    batch_count += 1
                if batch_count >= max_results:
                    break
    except RequestException as exc:
        raise RuntimeError(f"OpenAlex/PyAlex request failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"OpenAlex/PyAlex failed: {exc}") from exc

    works = list(works_by_id.values())
    works.sort(key=lambda work: work.get("relevance_score") or 0, reverse=True)
    return works[:max_results]


def preview_urls(
    query: str,
    max_results: int,
    from_year: int | None = None,
    to_year: int | None = None,
    source_ids: list[str] | None = None,
    search_mode: str = "lexical",
) -> list[str]:
    per_page = min(200, max_results)
    return [
        works_query(query, from_year, to_year, batch, search_mode=search_mode)
        .paginate(per_page=per_page, n_max=max_results)
        .endpoint_class.url
        for batch in source_id_batches(source_ids or [])
    ]


def abstract_for_work(work: dict[str, Any]) -> str | None:
    abstract = work.get("abstract")
    if isinstance(abstract, str) and abstract.strip():
        return abstract.strip()

    inverted = work.get("abstract_inverted_index")
    if isinstance(inverted, dict):
        try:
            text = invert_abstract(inverted)
        except Exception:
            return None
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def concepts_for_work(work: dict[str, Any], limit: int = 8) -> list[str]:
    concepts = work.get("concepts")
    if not isinstance(concepts, list):
        return []

    names: list[str] = []
    for concept in concepts[:limit]:
        if not isinstance(concept, dict):
            continue
        name = concept.get("display_name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def authors_list_for_work(work: dict[str, Any]) -> list[str]:
    authors = authors_for_work(work)
    if not authors:
        return []
    return [name.strip() for name in authors.split(" and ") if name.strip()]


def plain_record_for_work(work: dict[str, Any]) -> dict[str, Any]:
    source = source_for_work(work)
    doi = doi_for_work(work)
    openalex_id = work.get("id")

    return {
        "openalex_id": openalex_id if isinstance(openalex_id, str) else None,
        "title": work.get("display_name"),
        "authors": authors_list_for_work(work),
        "year": work.get("publication_year"),
        "type": work.get("type"),
        "venue": source.get("display_name"),
        "doi": doi,
        "url": url_for_work(work),
        "cited_by_count": work.get("cited_by_count"),
        "is_open_access": (
            work.get("open_access", {}).get("is_oa")
            if isinstance(work.get("open_access"), dict)
            else None
        ),
        "concepts": concepts_for_work(work),
        "abstract": abstract_for_work(work),
    }


def scope_summary(journal_scope: dict[str, Any] | None) -> dict[str, Any] | None:
    if not journal_scope:
        return None
    return {
        "scope_id": journal_scope["scope_id"],
        "display_name": journal_scope.get("display_name"),
        "registry": journal_scope["_path"],
        "source_count": len(journal_scope["_source_ids"]),
    }


def json_for_works(
    works: list[dict[str, Any]],
    query: str,
    journal_scope: dict[str, Any] | None = None,
    search_mode: str = "lexical",
) -> str:
    payload = {
        "query": compact_query(query),
        "search_mode": search_mode,
        "journal_scope": scope_summary(journal_scope),
        "count": len(works),
        "records": [plain_record_for_work(work) for work in works],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def markdown_for_works(
    works: list[dict[str, Any]],
    query: str,
    journal_scope: dict[str, Any] | None = None,
    search_mode: str = "lexical",
) -> str:
    lines = [
        "# OpenAlex Abstract Pack",
        "",
        f"Query: `{compact_query(query)}`",
        "",
        f"Search mode: `{search_mode}`",
        "",
        *(
            [
                f"Journal scope: `{journal_scope['scope_id']}` "
                f"({len(journal_scope['_source_ids'])} OpenAlex sources)",
                "",
            ]
            if journal_scope
            else []
        ),
        f"Records: {len(works)}",
        "",
    ]

    for index, work in enumerate(works, start=1):
        record = plain_record_for_work(work)
        title = record["title"] or "Untitled"
        authors = ", ".join(record["authors"]) or "Unknown authors"
        year = record["year"] or "n.d."
        venue = record["venue"] or "Unknown venue"
        cited_by = record["cited_by_count"]
        concepts = ", ".join(record["concepts"]) or "None listed"

        lines.extend(
            [
                f"## {index}. {title}",
                "",
                f"- Authors: {authors}",
                f"- Year: {year}",
                f"- Venue: {venue}",
                f"- Type: {record['type'] or 'unknown'}",
                f"- Cited by: {cited_by if cited_by is not None else 'unknown'}",
                f"- Open access: {record['is_open_access']}",
                f"- DOI: {record['doi'] or 'none'}",
                f"- URL: {record['url'] or 'none'}",
                f"- OpenAlex: {record['openalex_id'] or 'none'}",
                f"- Concepts: {concepts}",
                "",
                "Abstract:",
                "",
                record["abstract"] or "_No abstract available from OpenAlex._",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def render_output(
    works: list[dict[str, Any]],
    query: str,
    output_format: str,
    journal_scope: dict[str, Any] | None = None,
    search_mode: str = "lexical",
) -> str:
    if output_format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=["openalex_id", "title", "selected", "notes"])
        writer.writeheader()
        for work in works:
            writer.writerow({"openalex_id": work.get("id"),
                             "title": work.get("display_name"), "selected": "false",
                             "notes": f"Query: {compact_query(query)}; search mode: {search_mode}; journal scope: {(journal_scope or {}).get('scope_id', 'none')}; year: {work.get('publication_year', '')}"})
        return stream.getvalue()
    if output_format == "bibtex":
        records = [
            bibtex_for_work(work, index) for index, work in enumerate(works, start=1)
        ]
        return "\n\n".join(records) + "\n"
    if output_format == "json":
        return json_for_works(works, query, journal_scope, search_mode) + "\n"
    if output_format == "markdown":
        return markdown_for_works(works, query, journal_scope, search_mode)
    raise ValueError(f"Unsupported output format: {output_format}")


def latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def bibtex_person_name(author: dict[str, Any]) -> str | None:
    display_name = author.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        return display_name.strip()
    return None


def authors_for_work(work: dict[str, Any]) -> str | None:
    authorships = work.get("authorships", [])
    if not isinstance(authorships, list):
        return None

    names: list[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author", {})
        if isinstance(author, dict):
            name = bibtex_person_name(author)
            if name:
                names.append(name)

    return " and ".join(names) if names else None


def source_for_work(work: dict[str, Any]) -> dict[str, Any]:
    primary_location = work.get("primary_location")
    if isinstance(primary_location, dict):
        source = primary_location.get("source")
        if isinstance(source, dict):
            return source
    return {}


def pages_for_work(work: dict[str, Any]) -> str | None:
    biblio = work.get("biblio")
    if not isinstance(biblio, dict):
        return None

    first_page = biblio.get("first_page")
    last_page = biblio.get("last_page")
    if first_page and last_page:
        return f"{first_page}--{last_page}"
    if first_page:
        return str(first_page)
    return None


def doi_for_work(work: dict[str, Any]) -> str | None:
    doi = work.get("doi")
    if not isinstance(doi, str) or not doi.strip():
        return None
    return doi.removeprefix("https://doi.org/").strip()


def url_for_work(work: dict[str, Any]) -> str | None:
    doi = doi_for_work(work)
    if doi:
        return f"https://doi.org/{doi}"

    primary_location = work.get("primary_location")
    if isinstance(primary_location, dict):
        landing_page_url = primary_location.get("landing_page_url")
        if isinstance(landing_page_url, str) and landing_page_url.strip():
            return landing_page_url.strip()

    openalex_id = work.get("id")
    if isinstance(openalex_id, str) and openalex_id.strip():
        return openalex_id.strip()
    return None


def entry_type_for_work(work: dict[str, Any]) -> str:
    work_type = work.get("type")
    if isinstance(work_type, str):
        return ENTRY_TYPE_BY_OPENALEX_TYPE.get(work_type, "misc")
    return "misc"


def citation_key(work: dict[str, Any], index: int) -> str:
    year = str(work.get("publication_year") or "nd")
    authorships = work.get("authorships", [])
    first_author = "openalex"
    if isinstance(authorships, list) and authorships:
        first = authorships[0]
        if isinstance(first, dict):
            author = first.get("author", {})
            if isinstance(author, dict):
                display_name = author.get("display_name")
                if isinstance(display_name, str) and display_name.strip():
                    first_author = display_name.strip().split()[-1]

    normalized = unicodedata.normalize("NFKD", first_author)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "", ascii_name).lower() or "openalex"
    return f"{slug}{year}_{index:02d}"


def add_field(fields: list[tuple[str, str]], key: str, value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text:
        fields.append((key, text))


def bibtex_for_work(work: dict[str, Any], index: int) -> str:
    entry_type = entry_type_for_work(work)
    biblio = work.get("biblio") if isinstance(work.get("biblio"), dict) else {}
    source = source_for_work(work)
    title = work.get("display_name")
    venue = source.get("display_name")

    fields: list[tuple[str, str]] = []
    add_field(fields, "title", title)
    add_field(fields, "author", authors_for_work(work))
    add_field(fields, "year", work.get("publication_year"))

    if entry_type == "article":
        add_field(fields, "journal", venue)
    elif entry_type in {"incollection", "inreference"}:
        add_field(fields, "booktitle", venue)
    else:
        add_field(fields, "howpublished", venue)

    if isinstance(biblio, dict):
        add_field(fields, "volume", biblio.get("volume"))
        add_field(fields, "number", biblio.get("issue"))
    add_field(fields, "pages", pages_for_work(work))
    add_field(fields, "doi", doi_for_work(work))
    add_field(fields, "url", url_for_work(work))
    add_field(fields, "note", f"OpenAlex: {work.get('id')}")

    body = ",\n".join(
        f"  {key} = {{{latex_escape(value)}}}" for key, value in fields
    )
    return f"@{entry_type}{{{citation_key(work, index)},\n{body}\n}}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Return OpenAlex search hits as BibTeX, JSON, or Markdown."
    )
    parser.add_argument("--query", help="Raw OpenAlex search string.")
    parser.add_argument("--query-file", help="Markdown or text file containing a query.")
    parser.add_argument(
        "--search-mode",
        choices=("lexical", "semantic"),
        default="lexical",
        help="Use regular OpenAlex text search or embedding-based semantic search.",
    )
    parser.add_argument("--max-results", type=int, default=20, help="Number of works to fetch.")
    parser.add_argument(
        "--from-year",
        type=int,
        help="Only return works published from this year onward.",
    )
    parser.add_argument(
        "--to-year",
        type=int,
        help="Only return works published up to and including this year.",
    )
    parser.add_argument(
        "--journal-scope",
        help=(
            "Named registry from journal-scopes/ (for example ais-extended) "
            "or a path to a journal-scope JSON file."
        ),
    )
    parser.add_argument("--output", default="results/openalex-results.bib")
    parser.add_argument(
        "--format",
        choices=("bibtex", "json", "markdown", "csv"),
        default="bibtex",
        help="Use markdown/json for abstract triage; csv for a download selection sheet.",
    )
    parser.add_argument(
        "--mailto",
        default=DEFAULT_EMAIL,
        help="Contact email for OpenAlex polite pool, or set OPENALEX_MAILTO.",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help=(
            "OpenAlex API key. Prefer setting OPENALEX_API_KEY so the key "
            "does not land in shell history."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the parsed query and first OpenAlex URL without requesting it.",
    )
    args = parser.parse_args()

    if args.from_year and args.to_year and args.from_year > args.to_year:
        raise SystemExit("--from-year cannot be later than --to-year.")

    query = read_query(args)
    try:
        validate_search_request(args.search_mode, query, args.max_results)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        journal_scope = (
            load_journal_scope(args.journal_scope) if args.journal_scope else None
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid --journal-scope: {exc}") from exc
    source_ids = journal_scope["_source_ids"] if journal_scope else []
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("Parsed query:")
        print(compact_query(query))
        print(f"\nSearch mode: {args.search_mode}")
        if journal_scope:
            print(
                f"\nJournal scope: {journal_scope['scope_id']} "
                f"({len(source_ids)} sources)"
            )
        print("\nOpenAlex URL(s):")
        for url in preview_urls(
            query,
            args.max_results,
            args.from_year,
            args.to_year,
            source_ids,
            search_mode=args.search_mode,
        ):
            print(url)
        print(f"\nOutput path: {output_path}")
        print(f"Output format: {args.format}")
        return 0

    try:
        works = fetch_works(
            query,
            args.max_results,
            args.mailto,
            args.api_key,
            args.from_year,
            args.to_year,
            source_ids,
            args.search_mode,
        )
        if not works:
            print("No OpenAlex works found for this query.", file=sys.stderr)
            return 1

        rendered = render_output(
            works, query, args.format, journal_scope, args.search_mode
        )
        output_path.write_text(rendered, encoding="utf-8")
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Wrote {len(works)} OpenAlex {args.format} records to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
