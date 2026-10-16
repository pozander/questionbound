# Feynman: from selected sources to auditable quotations

## Purpose and division of work

OpenAlex retrieves candidates. The researcher screens them and selects exact
work IDs in a CSV. The deterministic downloader retrieves those PDFs. Local
scripts extract approved pages and give bounded passages stable IDs. Feynman
interprets the passages and selects IDs supporting its claims; it does not copy
quotation wording. A local script materializes exact text and page metadata from
those IDs. Human/assistant review addresses OCR and interpretation rather than
repeating the whole literature search.

Earlier runs produced plausible prose but repeatedly inserted ellipses, combined
non-contiguous text, repaired OCR, and confused printed pages with PDF pages.
A stronger model alone did not fix that. Passage IDs remove transcription from
the model's job instead of attempting to detect and repair it afterward.

## Why page-labelled extraction works

A PDF is an ordered sequence of physical pages, including its cover, blank
pages, and contents. Page 1 here means the first page shown in a PDF viewer.
It does not necessarily contain the printed number 1.

`scripts/quote_pages.py prepare` runs Poppler's `pdftotext -layout` on each
selected PDF. Poppler separates physical pages using form-feed characters.
The script splits at those boundaries, keeps empty interior pages, removes
only the terminal empty segment, and checks the count against `pdfinfo`.
A mismatch stops processing. Text is not reflowed into arbitrary page-sized
chunks, and the LLM does not generate page numbers.

Each record in `pages.json` contains:

- `file`: the exact local PDF path.
- `source`: author/title/year label.
- `pdf_sha256`: the hash of the PDF that was extracted.
- `pdf_page`: the one-based physical page index.
- `printed_page`: a separately verified label, or null.
- `text`: that physical page's extracted text.

Example: in our copy of Ashby's Introduction, printed page 1 is PDF page 17.
Using an assumed offset for every book would be wrong. Labels may also be Roman
numerals, absent, repeated, or discontinuous. We enter verified labels for
individual pages; unknown values remain null. A bibliographic inference is
not silently treated as a visually verified printed label.

The source configuration selects exact physical pages. These are chosen as
likely conceptual passages using the preceding search and text inspection. This
is a bounded analysis, not an exhaustive reading of the works. The full PDFs
remain available for later, separately approved passes.

`scripts/passage_evidence.py prepare` divides each approved page into bounded
passages. IDs are derived from the file stem, physical page, and passage ordinal,
for example `W1503984168-P0016-B02`. IDs are assigned before optional filtering,
so changing search patterns does not renumber the surviving passages. The script
can include neighboring passages as context and records the exact patterns and
settings in `passage-config.json`.

## Running the passage-ID workflow

Run from the project root. Requirements: the project Python environment,
Poppler (`pdfinfo`, `pdftotext`), Node, an installed/authenticated Feynman, and
access to GPT-4.1 through its OpenAI provider.

```bash
.venv/bin/python scripts/quote_pages.py prepare \
  --config runs/my-new-extraction/sources.json \
  --output-dir runs/my-new-extraction

.venv/bin/python scripts/passage_evidence.py prepare \
  --pages runs/my-new-extraction/pages.json \
  --output-dir runs/my-new-extraction \
  --pattern 'function|mapping|correspondence' \
  --pattern 'dependence|transition|input.?output' \
  --context 1

.venv/bin/python scripts/run_feynman_quotes.py \
  --run-dir runs/my-new-extraction

.venv/bin/python scripts/passage_evidence.py materialize \
  --passages runs/my-new-extraction/passages.json \
  --selections runs/my-new-extraction/candidates.json \
  --output runs/my-new-extraction/checked-evidence.json
```

The exact patterns are research inputs and must be shown with the evidence
boundary before the paid run. Omit `--pattern` to include every passage from the
approved pages. `--context 1` includes one adjacent passage on each side of a
match from the same physical page.

The Feynman brief must request IDs, not quotation strings. A minimal schema is:

```json
{
  "answer": "synthesis",
  "selections": [
    {
      "passage_id": "W1503984168-P0016-B02",
      "claim": "what this passage supports",
      "status": "explicit definition"
    }
  ],
  "limitations": ["remaining gap"]
}
```

Feynman may interpret, compare, and classify passages, but must not return a
`quote` or `text` field. Materialization rejects model-supplied wording, unknown
IDs, duplicate selections, and PDFs whose checksums have changed.

The paid runner refuses to reuse a directory with an existing `budget.json`.
For another run, create a new directory with a source configuration, brief,
and prepared evidence. Do not delete a previous budget ledger to resume it.

## Configurable runs

The defaults remain GPT-4.1, a USD 0.50 total ceiling, and 5,000 output
tokens per response. For a new directory already containing brief.txt and
evidence.txt, these can be overridden explicitly:

```bash
.venv/bin/python scripts/run_feynman_quotes.py \
  --run-dir runs/my-new-extraction \
  --budget-usd 2.00 \
  --model gpt-4.1-mini \
  --max-output-tokens 3000
```

`--budget-usd` is a total ceiling, not additional credit. With
`--budget-ledger`, omitting it preserves the existing ceiling; specifying a
higher amount raises that ceiling and records the change, retaining all
reservations and requests. Lowering an existing ceiling is rejected. New
ledgers may use any finite positive ceiling. There is no unlimited bypass.
Use a new run directory for each attempt, even when sharing a ledger.

`--model` currently accepts gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, and
gpt-5-mini, with
an optional openai/ prefix. This is deliberately not arbitrary-provider
support: other protocols, token accounting, and pricing need a tested guard.
The runner rejects unsupported models before launching Feynman. The fetch
guard rejects non-OpenAI destinations and redirects rather than leaving
alternate model endpoints unbudgeted. It is not an OS-level network sandbox.

`--max-output-tokens` is independent of model choice; valid range is 1-32768
for the configured models. Keep 5000 for extraction, or try 2000-3000 for a
short repair. Too small a cap can truncate JSON and waste a call. Smaller
models do not automatically need smaller outputs.

Prices and model output limits live in scripts/feynman_models.json, not in
the runner or guard. Each run snapshots these settings in run-config.json;
each reservation also records its model and rates. Update prices when the
provider changes them. Adding a model requires checking API compatibility
and the reservation assumptions, not just adding a name.

### Model choice

Standard text prices checked 2026-09-26, USD per million tokens:

| Model | Uncached input | Output | Guard supported |
| --- | ---: | ---: | --- |
| GPT-4.1 | 2.00 | 8.00 | Yes, default |
| GPT-4.1 mini | 0.40 | 1.60 | Yes |
| GPT-4.1 nano | 0.10 | 0.40 | Yes |
| GPT-5 mini | 0.25 | 2.00 | Yes |
| Gemini 3.1 Flash-Lite | 0.25 | 1.50 | No, comparison candidate |

Sources: [GPT-4.1](https://developers.openai.com/api/docs/models/gpt-4.1),
[mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
[nano](https://developers.openai.com/api/docs/models/gpt-4.1-nano),
[GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini),
[Google pricing](https://ai.google.dev/gemini-api/docs/pricing).

GPT-4.1 is a defensible baseline for this bounded extraction, not a proven
best-value choice. The earlier mini run used a different workflow, so its
failure is not a controlled model comparison. Before buying another
provider's credits, test mini on identical evidence with the same checker.
Compare relevant quotations recovered, interpretation quality, repair cost,
and review effort, not merely price per token. Gemini is cheaper than 4.1
on the published rates, but we have not established better quality here.
Nano is an optional low-cost experiment, not our recommendation for nuanced
conceptual synthesis. No automatic model fallback or escalation occurs.

## Bounded execution

The runner passes `brief.txt` and the labelled passage texts directly to Feynman
using the selected model (default `openai/gpt-4.1`) and `--thinking off`. The runner disables model tools
at the API boundary: no subagents, web searches, arbitrary file access, or
long tool loops. It remains a Feynman model run, but not its full autonomous
literature-review workflow. Feynman supplies relevance judgments, selects
passage IDs, and drafts an interpretation as structured JSON.

The local runner accepts either the new `selections` output or legacy `quotes`
output and records the mode in `run-config.json`. It saves the response as
`candidates.json`. The model does not need to write a file itself or ask
permission to finish.

## What deterministic materialization proves

`passage_evidence.py materialize` looks up each selected passage ID in
`passages.json`, verifies that the underlying PDF checksum has not changed, and
copies the stored passage text and page metadata into `checked-evidence.json`.
Because the model never supplies quotation text, there is no fuzzy matching or
quotation-repair pass in the default workflow.

Materialization proves provenance from a prepared passage ID. It does not prove
that OCR is correct, that the passage is relevant, or that Feynman's
interpretation is sound. Render decisive pages and inspect them visually, then
record any publication transcription separately from the raw extracted text.

## Legacy quotation workflow

Existing runs and scripts remain reproducible. When a brief asks Feynman to
return a `quotes` list, `quote_pages.py verify` performs strict contiguous text
matching, and `prepare_quote_repair.py` can prepare a bounded repair. This mode
is retained for old artifacts, not recommended for new research runs.

### What the legacy checker proves, and what it does not

The verifier checks file identity, physical page, and a contiguous quotation
match. It normalizes Unicode compatibility forms and whitespace only. It
does not ignore case, rewrite words, repair OCR, remove punctuation, join
hyphenated words, or accept approximate semantic similarity.

`text_match` means the quotation occurs in the extracted text of the claimed
page. `FAILED` means it cannot be accepted on that evidence. The verifier
returns a nonzero exit status if any candidate fails. It never silently moves
a quote to a different page or replaces the wording.

A text match does not guarantee correct OCR, faithful interpretation, or an
accurate printed page number. Render the cited PDF page, check the words and
surrounding context, then record that review separately. Do not call a quote
fully checked based only on a substring match. Printed labels are supplied
from reviewed metadata, never trusted from model output.

For failed legacy quotes, give Feynman only the failed candidates and the relevant
labelled pages in a new bounded repair pass. Do not re-run the entire corpus.
Do not expand the total spending budget without deciding that explicitly.

For a legacy run this can be done with:

```bash
.venv/bin/python scripts/prepare_quote_repair.py --run-dir runs/topic-legacy
.venv/bin/python scripts/run_feynman_quotes.py \
  --run-dir runs/topic-legacy/repair \
  --budget-ledger runs/topic-legacy/budget.json
.venv/bin/python scripts/quote_pages.py verify \
  --pages runs/topic-legacy/pages.json \
  --candidates runs/topic-legacy/repair/candidates.json \
  --output runs/topic-legacy/repair/verified.json
```

The shared ledger preserves all earlier reservations. The repair directory must
be new, and a repair must stay within the previously approved evidence boundary.

Visual review is recorded explicitly in `visual-review.json`. Keep the raw
machine-matched quote alongside `publication_quote`, which can correct OCR
only after checking the page image. For example, a verbatim OCR match may
contain `conununication`; a visually checked transcription reads
`communication`. These are different verification stages, not a reason to
weaken the matcher. Publication quotation marks can be typographically
normalized, and line-break hyphenation can be joined, with corrections noted.

`assemble_quote_report.py` combines the two verified sets and the explicit
visual annotations, preserves the raw text in `checked-quotes.json`, totals
usage, and creates a readable report. It requires recorded review but cannot
prove that a reviewer actually looked at an image; that remains a human or
assistant responsibility.

## Spending control and token accounting

`feynman_budget.cjs` is loaded only into this run through `NODE_OPTIONS`.
It intercepts OpenAI Responses requests, permits only the selected configured model without hidden
server-side conversation state, removes tools, forces the standard service
tier, and caps output at the selected limit (default 5,000 tokens). Before each request it reserves a
conservative upper cost using serialized UTF-8 input bytes plus 4,096 tokens
of framing headroom, charged at uncached input rates, plus the maximum output.
Text tokens cannot outnumber their UTF-8 bytes under the byte-level tokenizer;
serialized JSON adds further conservatism. Non-text payloads are rejected.

If the next reservation exceeds the selected ceiling (default USD 0.50), the request is rejected before
being sent. Reservations are retained on failure and for retries, so a failed
request does not free capacity for unlimited retries. This pilot runs a single
Feynman process without model tools; the simple ledger is not intended for
concurrent agents or a shared billing account. It is a local request-admission
budget based on the specified model's pricing, not an account-wide provider
billing limit. Unsupported providers require a separate tested integration.

Prices used: USD 2.00 per million uncached input tokens, USD 0.50 per million
cached input tokens, USD 8.00 per million output tokens.
[Official GPT-4.1 model documentation](https://developers.openai.com/api/docs/models/gpt-4.1).

After the run, `usage.json` sums usage from the dedicated Feynman session logs:
`input` is uncached input, `cacheRead` is cached input, `output` is generated
tokens, and `totalTokens` includes all three. Repeated context is counted
again on subsequent calls. New runs compute `estimated_cost_usd` from token
usage and the selected pricing snapshot, preserving `feynman_logged_cost_usd`
separately. Historical pilot files used Feynman's logged model cost. Neither
is a checked OpenAI invoice. Both exclude Codex setup and independent review.
`budget.json` records reservations, not actual charges.

## Run artifacts

- `sources.json`: selected files, physical pages, labels, and provenance.
- `pages.json` and `evidence.txt`: deterministic extraction.
- `brief.txt`: exact research question, scope, schema, and quotation rules.
- `passages.json` and `passage-config.json`: stable evidence units and settings.
- `candidates.json`: original model output, retained unchanged for audit.
- `checked-evidence.json`: locally materialized passage text and metadata.
- `sessions/`, `usage.json`, `budget.json`, and `console.txt`: execution records.

Keep failed drafts and corrections distinguishable from checked evidence. Use
the final materialized and visually reviewed evidence for writing, not an
unverified model summary. Run directories are intentionally ignored by Git
because they may contain copyrighted texts, local paths, session records, and
research material that requires a separate publication decision.
