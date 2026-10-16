# QuestionBound

**Auditable literature research from a fixed question to verified quotation.**

QuestionBound is a human-governed literature-research pipeline. It combines
deterministic OpenAlex discovery, a bounded Tavily fallback for missing
abstracts, explicit document selection, reproducible PDF retrieval,
page-addressable evidence, and budget-limited Feynman synthesis.

It is designed for conceptual research where preserving the meaning of the
research question matters as much as finding papers. It is lighter than a full
systematic-review platform and more inspectable than an autonomous research
agent.

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

## Division Of Labor

- **Researcher:** owns meaning, scope, approval, and evidential standards.
- **Codex:** proposes queries, runs deterministic tools, and audits provenance.
- **OpenAlex:** supplies structured scholarly discovery and available full text.
- **Tavily:** investigates a small number of declared metadata gaps.
- **Local RAG:** retrieves passages from documents already selected and indexed.
- **Feynman:** compares only approved evidence under an explicit cost ceiling.
- **Local scripts:** insert exact stored text and reject unknown passage IDs.

Read [AGENTS.md](AGENTS.md) for the research-contract rules that keep these
roles separate.

## Requirements

- Python 3.10 or newer
- An [OpenAlex API key](https://openalex.org/settings/api)
- Poppler (`pdftotext` and `pdfinfo`) for PDF evidence preparation
- Node.js and an installed Feynman CLI only for bounded Feynman runs
- GPTme-RAG only when local semantic retrieval is wanted
- A Tavily API key only for the optional abstract fallback

Install the Python dependencies in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Set credentials in the environment. Never put them in a query, result file, or
command-line argument:

```bash
export OPENALEX_API_KEY='your-openalex-api-key'
export OPENALEX_MAILTO='you@example.org'       # optional
export TAVILY_API_KEY='your-tavily-api-key'   # optional
```

For Tavily, a private `.secrets/tavily.env` file is also supported. The entire
`.secrets/` directory is ignored by Git.

## Quick Start

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

### AIS Extended Scope

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
  --output-dir downloads/topic
```

The downloader validates basic PDF integrity and records provenance plus SHA-256
values in `downloads.jsonl`. It does not search by title, choose substitute
editions, use library credentials, or access shadow libraries.

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

## Repository Layout

```text
scripts/                         deterministic pipeline commands
tests/                           offline unit tests
skills/questionbound/            installable Codex skill
journal-scopes/ais-extended.json AIS journal registry
literature-search-dictionary/    example dictionaries and query families
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
