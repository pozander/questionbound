# OpenAlex Discovery And Retrieval

Run commands from the resolved QuestionBound project root. Use its
`.venv/bin/python` and
never place API keys in commands, prompts, result files, or source code. OpenAlex
credentials come from `OPENALEX_API_KEY`; `OPENALEX_MAILTO` is optional.

## Discovery

Prepare query families manually with the researcher. The script does not expand
synonyms automatically. Before a live request, show the exact queries, inclusive
year filters, result limits, output formats, and any journal scope. A dry run
parses the query and displays generated URLs without network access:

### Choose a retrieval strategy

Recommend one of these modes in the research brief and explain the choice:

- **Lexical:** prefer for definitions, quotations, named theories, established
  terminology, reproducible Boolean strategies, journal-bounded searches, and
  questions where exact word use is evidence. Use focused synonym blocks rather
  than indiscriminate lists. For Information Systems, `--journal-scope
  ais-extended` applies the maintained AIS source registry.
- **Semantic:** prefer for exploratory discovery, unfamiliar terminology,
  interdisciplinary translation, or a rich natural-language description whose
  relevant literature may use different words. Treat it as ranked discovery,
  not an exhaustive search.
- **Hybrid:** normally prefer for conceptual or interdisciplinary research.
  Run a high-precision lexical core and one or more semantic descriptions as
  separate searches, label each record with its retrieval route, union by
  OpenAlex work ID, inspect overlap, and screen the combined set.

Do not weaken the lexical query merely because semantic retrieval is available.
The lexical route protects exact concepts and auditability; the semantic route
tests for vocabulary the dictionary missed. Citation chasing from strong seed
works can then supply a third, structurally different discovery route.

The `openalex_bibtex.py` CLI supports regular `search=` and vector-based
`search.semantic=` through `--search-mode lexical` and `--search-mode semantic`.
Lexical remains the default. It does not implement OpenAlex reranking. Always
record the selected mode and do not imply that a lexical invocation performed
vector search.

Treat the journal boundary and retrieval mode as separate methodological choices.
The current lexical implementation enforces the AIS boundary using exact stored
OpenAlex source IDs. A future semantic route may be called AIS-scoped only if it
applies the same source-ID registry; otherwise label it as an unrestricted
supplement and screen its venue separately.

OpenAlex semantic search embeds work titles and abstracts, accepts up to 2,000
query characters, returns at most 50 results per query, and cannot be combined
with regular search in the same request. Preserve semantic input text verbatim
and keep its output separate until deterministic ID-level union and screening.

```bash
.venv/bin/python scripts/openalex_bibtex.py \
  --query-file runs/topic/semantic-query.txt \
  --search-mode semantic \
  --journal-scope ais-extended \
  --max-results 50 --format json \
  --output runs/topic/semantic-results.json
```

```bash
.venv/bin/python scripts/openalex_bibtex.py \
  --query '"concept one" AND "concept two"' \
  --from-year 2021 --max-results 30 --dry-run
```

Run an approved query and preserve abstracts plus metadata:

```bash
.venv/bin/python scripts/openalex_bibtex.py \
  --query '"concept one" AND "concept two"' \
  --from-year 2021 --max-results 30 \
  --format markdown --output results/topic-abstract-pack.md
```

The supported output formats are `markdown`, `json`, `bibtex`, and `csv`.
Prefer Markdown or JSON for screening, BibTeX for citation management, and CSV
to create a human-auditable retrieval selection. A query file may replace
`--query` via `--query-file PATH`.

For Information Systems searches bounded to the project registry, add:

```text
--journal-scope ais-extended
```

The scope is broad and journal membership does not establish topical relevance.
Do not refresh the registry during an ordinary search.

OpenAlex is a changing catalogue. Preserve the query, timestamp, filters, IDs,
and returned records; do not promise that a later run will rank identically.

For multiple approved queries, prefer `openalex_batch.py` with the fixed query
manifest rather than an ad hoc shell loop. Its default boundary is three query
processes and at most two simultaneous semantic queries. It preserves a separate
result per query and writes `openalex-batch-audit.json`. It makes no automatic
retries and stops admitting new work after authentication, quota, or rate-limit
responses; already-running calls may finish. Use `--dry-run` before the live
batch. Process isolation is intentional because PyAlex configuration is global.
OpenAlex does not accept date filters with semantic search, so the script applies
the approved date range locally to the bounded semantic result set; lexical date
filters remain server-side.

## Bounded Tavily Gap Recovery

Use `tavily_abstract_fallback.py` only after an approved OpenAlex result set has
missing abstracts or unresolved source pages. Show the selected records, exact
query ladder, and request ceilings before execution. Preview with `--dry-run`.
Keep its audit output beside the enriched pack and label Tavily-derived evidence
separately from OpenAlex metadata. Never promote an ambiguous search snippet to
an abstract or use the fallback to silently expand the research question.

When an approved bounded source-scout run has produced fixed candidate URLs,
`materialize_agentic_abstracts.py` can insert exact abstract text locally. It
tries validated exact-ID PDFs, the recorded URLs, and an exact-DOI OpenAIRE
record in that order. The last route is metadata retrieval for the same work,
not discovery. Preview with `--dry-run`; keep the materialization audit beside
the enriched pack. Do not accept a search snippet or a page lacking both
identity evidence and an explicit abstract field or label.

## Deterministic PDF Retrieval

Export or prepare a UTF-8 CSV with required `openalex_id` and optional `title`,
`selected`, and `notes`. Titles aid inspection but never determine retrieval.
The exact OpenAlex work ID is authoritative.

Preview first:

```bash
.venv/bin/python scripts/openalex_download.py \
  --selection selections/topic.csv \
  --output-dir downloads/topic --workers 3 --dry-run
```

After the selection and execution boundary are approved, remove `--dry-run`.
The downloader uses OpenAlex only, validates basic PDF integrity, preserves
existing valid files, and appends provenance and SHA-256 values to
`downloads.jsonl`. It does not search for substitute editions or use shadow
libraries. Review unavailable works explicitly rather than silently replacing
them. The default three-worker pool fetches distinct work IDs concurrently and
writes audit records in selection order. A hard authentication, quota, or
rate-limit response stops admission of new work; in-flight fetches finish and
the remainder are recorded as `not_attempted`. Set `--workers 1` for sequential
retrieval.

An unavailable OpenAlex-cached PDF is not proof that lawful full text is absent.
If exact failed IDs and the external-location boundary are separately approved,
preview the bounded fallback:

```bash
.venv/bin/python scripts/openalex_fulltext_fallback.py \
  --download-log downloads/topic/downloads.jsonl \
  --output-dir downloads/topic-fallback --dry-run
```

The fallback examines only external locations on the exact OpenAlex work and its
exact DOI/publisher page. It does not search by title, use Scholar, or substitute
editions. It validates landing-page identity and then independently requires DOI
or strong title/author evidence inside the downloaded PDF. Preserve
`recovery.jsonl`, including rejected candidates and checksums, beside the primary
download audit.
