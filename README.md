# QuestionBound

**Auditable literature research from a fixed question to verified quotation.**

Created by Pär-Ola Zander, Södertörn University.

QuestionBound is a human-governed literature-research pipeline.

It is for academic literature search and synthesis that is more thorough
than just asking an LLM on the topic, and less heavy-weight than a systematic
literature review (such as https://github.com/sadeghanisi/SLR). It is much more
transparent than agentic search or tools like Scite or Elicit, and customizable.
Since a lot of work is carried out deterministically, and extensive results are saved
locally, it is very token-economic and also enables local LLMs, as opposed to
e.g. chatGPT or Elicit.


It combines
deterministic OpenAlex discovery, a bounded Tavily fallback for missing
abstracts, explicit document selection, reproducible PDF retrieval,
page-addressable evidence, and budget-limited Feynman synthesis.

It has been run via Codex, but is possible to use on Claude, Goose Desktop
with minimal modification of the skill.

## What you need
- OpenAlex API key

- Python 3.10 or newer
- Poppler (`pdftotext` and `pdfinfo`) for PDF evidence preparation
- Highly recommended: The skill.
- Recommended: Tavily API key (for fallback complimentary searches)
- Recommended: GPTme-RAG (or similar) for making RAGs. (https://github.com/gptme/gptme-rag)
- Optional: Feynman for agentic analysis of output
  (and Feynman needs an LLM provider, e.g. OpenAI, as well as node.js)

Other recommended installations

## What Makes It Different

1. The researcher's verbatim question remains the controlling specification.
2. Interpretations, exclusions, synonyms, queries, and filters remain visible.
3. OpenAlex discovery is deterministic and saved before LLM interpretation.
4. Lexical and semantic search are separate, auditable retrieval routes.
5. Searches can be restricted to the included AIS Extended journal registry.
6. Tavily is a bounded, logged fallback for gaps, not a silent second corpus.
7. PDFs are retrieved from explicit OpenAlex work IDs selected in a CSV.
8. Feynman receives an approved corpus, model, output cap, and USD ceiling.
9. Models select stable passage IDs; local code materializes exact quotations.
10. Discovery, relevance judgment, synthesis, and verification remain distinct.

The result is not automatically a systematic literature review. QuestionBound
provides a reproducible research trail and evidence controls without requiring
PRISMA-scale procedure for every exploratory or conceptual question.

Read [AGENTS.md](AGENTS.md) for the research-contract rules that keep functions
separate.

## Requirements


Install the Python dependencies in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Set credentials in the environment:

```bash
export OPENALEX_API_KEY='your-openalex-api-key'
export OPENALEX_MAILTO='you@example.org'       # optional
export TAVILY_API_KEY='your-tavily-api-key'   # optional
```

For Tavily, a private `.secrets/tavily.env` file is also supported. The entire
`.secrets/` directory is ignored by Git.

## Quick Start
(Install what you need)

1. Make a research question in your favourite local-access LLM (Claude Desktop, CLI LLM, etc)
2. Approve the suggestions from the LLM, or revise:
3.  which will then call the scripts (see below)
4. The subsequent steps depends on the situation; download the most interesting
PDFs and RAG them, let Feynman take over, refine the search, etc.

## Codex Skill

The repository includes an installable Codex skill at
`skills/questionbound/`. Install it locally:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/questionbound "${CODEX_HOME:-$HOME/.codex}/skills/questionbound"
```

Open the repository as the current Codex project, then invoke it explicitly:

```text
Use $questionbound to investigate how efficiency is defined in Information
Systems. Prepare the research brief and proposed searches, but do not execute
until I approve them.
```

The skill can also be selected automatically for requests involving this
pipeline. It supplies operating instructions, while the tested executable logic
stays in the repository.

## Script Calls Overview
Preview an OpenAlex query without making a request:

```bash
.venv/bin/python scripts/openalex_bibtex.py \
  --query '"end-user development" AND "natural language interface"' \
  --from-year 2021 \
  --max-results 30 \
  --dry-run
```

Run the approved query and save metadata plus abstracts:

```bash
.venv/bin/python scripts/openalex_bibtex.py \
  --query '"end-user development" AND "natural language interface"' \
  --from-year 2021 \
  --max-results 30 \
  --format json \
  --output results/eud-search.json
```

Supported formats are `json`, `markdown`, `csv`, and `bibtex`. Existing output
files are protected from accidental replacement.

### Lexical, Semantic, And Hybrid Search

Lexical search is the default. Prefer it for definitions, named theories,
Boolean strategies, exact terminology, and bounded journal sets:

```bash
.venv/bin/python scripts/openalex_bibtex.py \
  --query 'efficiency AND (definition OR defined)' \
  --search-mode lexical \
  --journal-scope ais-extended \
  --max-results 30 \
  --format json \
  --output results/efficiency-lexical.json
```

Use semantic search for exploratory discovery when relevant literature may use
different vocabulary:

```bash
.venv/bin/python scripts/openalex_bibtex.py \
  --query 'How do scholars define efficiency in organizational information systems?' \
  --search-mode semantic \
  --max-results 50 \
  --format json \
  --output results/topic-semantic.json
```

For hybrid discovery, run lexical and semantic queries separately, preserve
their route labels, then deduplicate by OpenAlex work ID. OpenAlex is a changing
catalogue, so a repeatable procedure does not imply permanently identical
rankings.

For a larger approved search, put all routes in one fixed JSON manifest and run
them with bounded process concurrency:

```json
{
  "date_range": [2000, 2026],
  "queries": [
    {
      "id": "lexical-01",
      "route": "A",
      "mode": "lexical",
      "journal_scope": "ais-extended",
      "max_results": 30,
      "query": "\"first-order barriers\" AND \"second-order barriers\""
    },
    {
      "id": "semantic-01",
      "route": "C",
      "mode": "semantic",
      "max_results": 50,
      "query": "Research explicitly distinguishing first- and second-order barriers."
    }
  ]
}
```

```bash
.venv/bin/python scripts/openalex_batch.py \
  --manifest runs/topic/query-manifest.json \
  --output-dir runs/topic/results \
  --format json \
  --workers 3 \
  --semantic-workers 1 \
  --dry-run
```

Remove `--dry-run` after checking the plan. Each query still produces its own
artifact, and `openalex-batch-audit.json` records route, mode, output, status,
diagnostics, and elapsed time. Separate child processes isolate PyAlex's global
configuration. The scheduler defaults to three simultaneous queries and no more
than one semantic query. The slower semantic lane starts alongside the lexical
lane instead of waiting for every lexical query to finish. It makes no automatic
retries and stops admitting new
queries after an authentication, quota, or rate-limit response. Other queries
already in flight are allowed to finish and the remainder are marked
`not_attempted`. Lower `--workers` if OpenAlex asks clients to reduce request
frequency. Because OpenAlex rejects date filters combined with semantic search,
the semantic route fetches its bounded ranked set and applies the manifest's date
range locally; lexical routes keep server-side date filters.

### AIS Extended Scope
(applies only for Information Systems, my own research field. But the idea can easily
be re-scripted for any special journal area).
`journal-scopes/ais-extended.json` contains the AIS Senior Scholars premier
journals and SIG-recommended journals captured from the AIS Extended list. The
scope is enforced with stored OpenAlex source IDs, not a text search for
"information systems." Journal membership defines a disciplinary boundary; it
does not establish topical relevance.

The registry is data, not a live lookup. Refresh it deliberately with
`scripts/resolve_journal_scope.py`, inspect the resulting changes, and commit
them separately from an ordinary literature search.

### Tavily Abstract Fallback

If selected OpenAlex records lack abstracts, preview the bounded fallback:

```bash
.venv/bin/python scripts/tavily_abstract_fallback.py \
  --input results/query-1.json \
  --input results/query-2.json \
  --output results/enriched.json \
  --audit-output results/tavily-audit.json \
  --dry-run
```

Remove `--dry-run` after inspecting the selected records and exact queries.
Defaults allow five works, two query forms per work, three search results, and
three direct fetches. Hard ceilings prevent the fallback from becoming an
unbounded web-research agent. Every query, URL, extraction decision, failure,
and reported credit use is written to the audit artifact.

If a separately approved bounded source scout has located abstract pages that
the Tavily pass missed, materialize them without asking the model to transcribe
the abstract:

```bash
.venv/bin/python scripts/materialize_agentic_abstracts.py \
  --input results/enriched.json \
  --scout-results results/agentic-scout/scout-results.json \
  --pdf-dir downloads/topic \
  --output results/abstracts-complete.json \
  --audit-output results/abstract-materialization-audit.json \
  --dry-run
```

After inspection, remove `--dry-run`. The materializer first checks an already
validated exact-ID PDF, then the scout's fixed candidate URLs, and finally an
exact-DOI OpenAIRE record when a publisher blocks direct fetching. It performs
no title search and no paid model call. It requires explicit abstract metadata
or a visible abstract label, rechecks work identity, records every rejected
route, and refuses to overwrite existing artifacts.

### Tavily Passage-Attribution Search

For a bounded non-OpenAlex search whose target is a remembered phrase or
passage, prepare an approved JSON manifest:

```json
{
  "research_question": "Who wrote the remembered passage?",
  "approval": "Approved by the researcher on YYYY-MM-DD",
  "language_boundary": "English only",
  "queries": [
    {
      "id": "exact-01",
      "query": "\"enters triumphantly\" \"leaves diminished\"",
      "rationale": "Exact remembered wording"
    }
  ]
}
```

Preview the request without using a search credit:

```bash
.venv/bin/python scripts/tavily_phrase_search.py \
  --manifest selections/passage-search.json \
  --output results/passage-search-audit.json \
  --dry-run
```

Remove `--dry-run` only after checking the manifest against the approved
research brief. The script has a hard ceiling of 30 queries, makes no automatic
retries, refuses to overwrite an audit, and preserves each query, result,
request ID, failure, and provider-reported credit count. Search results remain
discovery leads; verify decisive wording against a primary text.

### Deterministic PDF Retrieval

Prepare a UTF-8 CSV with required `openalex_id` and optional `title`, `selected`,
and `notes` columns. The work ID is authoritative; the title is for inspection.

```csv
openalex_id,title,selected,notes
W1234567890,Example title,yes,Selected after abstract screening
```

Preview, then download the explicitly selected works:

```bash
.venv/bin/python scripts/openalex_download.py \
  --selection selections/topic.csv \
  --output-dir downloads/topic \
  --dry-run

.venv/bin/python scripts/openalex_download.py \
  --selection selections/topic.csv \
  --output-dir downloads/topic \
  --workers 3
```

The downloader validates basic PDF integrity and records provenance plus SHA-256
values in `downloads.jsonl`. It does not search by title, choose substitute
editions, use library credentials, or access shadow libraries. Independent work
IDs are fetched concurrently (three at a time by default), while audit entries
remain in selection-file order. After an authentication, quota, or rate-limit
response, already-running fetches finish but no additional rows are admitted;
the remainder are logged as `not_attempted`. Use `--workers 1` for sequential
retrieval or a smaller server load.

An OpenAlex cache miss does not establish that no lawful full text exists. After
approval of the exact failed IDs, the bounded fallback can inspect external
locations attached to those exact OpenAlex records and then their DOI/publisher
pages:

```bash
.venv/bin/python scripts/openalex_fulltext_fallback.py \
  --download-log downloads/topic/downloads.jsonl \
  --output-dir downloads/topic-fallback \
  --dry-run

.venv/bin/python scripts/openalex_fulltext_fallback.py \
  --download-log downloads/topic/downloads.jsonl \
  --output-dir downloads/topic-fallback
```

The fallback never searches by title or substitutes a work. It accepts a landing
page only after DOI or title/author identity checks, and it checks the downloaded
PDF itself for DOI or strong title/author evidence before publication. Candidate
URLs, rejections, hashes, and final statuses are retained in `recovery.jsonl`.
Scholar, general web search, library credentials, and shadow libraries are outside
this fallback.

## Evidence And Quotations

QuestionBound's preferred Feynman workflow prevents the model from transcribing
quotations. It extracts approved physical PDF pages, assigns stable passage IDs,
asks Feynman to select IDs, and materializes exact text locally.

```bash
.venv/bin/python scripts/quote_pages.py prepare \
  --config runs/topic/sources.json \
  --output-dir runs/topic

.venv/bin/python scripts/passage_evidence.py prepare \
  --pages runs/topic/pages.json \
  --output-dir runs/topic \
  --pattern 'definition|defined|means' \
  --context 1

.venv/bin/python scripts/run_feynman_quotes.py \
  --run-dir runs/topic \
  --model gpt-4.1 \
  --budget-usd 0.50 \
  --max-output-tokens 5000

.venv/bin/python scripts/passage_evidence.py materialize \
  --passages runs/topic/passages.json \
  --selections runs/topic/candidates.json \
  --output runs/topic/checked-evidence.json
```

The model's tools are disabled in this bounded mode. It cannot inspect omitted
pages or search outside the supplied evidence. Passage materialization proves
provenance from prepared evidence, not OCR quality, relevance, or correctness of
interpretation. Decisive pages still require visual review.

See [FEYNMAN_README.md](FEYNMAN_README.md) for the full procedure and spending
controls. See [PEARL_SEARCH_README.md](PEARL_SEARCH_README.md) for deterministic
book-only citation chaining.



## Repository Layout

```text
scripts/                         deterministic pipeline commands
tests/                           offline unit tests
skills/questionbound/            installable Codex skill
journal-scopes/ais-extended.json AIS journal registry
literature-search-dictionary/    example dictionaries and query families
CITATION.cff                     citation metadata
AGENTS.md                        research-contract working agreement
FEYNMAN_README.md                bounded synthesis and quotation procedure
PEARL_SEARCH_README.md           citation-chain procedure
```

Research runs, PDFs, RAG indexes, result packs, credentials, and virtual
environments are intentionally ignored. Each researcher retains those artifacts
locally and decides separately what evidence can be redistributed.

## Tests

The tests exercise scripts offline and do not run literature searches:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_feynman_budget.cjs
```

## Status

QuestionBound is research software extracted from a working personal pipeline.
Its controls are intentionally conservative, but OpenAlex metadata, publisher
availability, OCR, relevance judgments, and model interpretations can all be
incomplete. Inspect the saved artifacts and report insufficient evidence rather
than weakening the research question.

## License

MIT. See [LICENSE](LICENSE).

Citation metadata is provided in [CITATION.cff](CITATION.cff).
