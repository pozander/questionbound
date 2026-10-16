# Bounded Feynman Synthesis

Use Feynman after discovery, screening, full-text retrieval, and local passage
selection. Read the project's `FEYNMAN_README.md` before preparing a run. Use
the passage-ID workflow; the legacy model-generated quotation workflow is for
reproducing old runs only.

## Evidence Preparation

1. Put the verbatim research question and approved clarification in `brief.txt`.
2. Define exact PDFs and physical PDF pages in `sources.json`.
3. Extract the pages deterministically:

```bash
.venv/bin/python scripts/quote_pages.py prepare \
  --config runs/topic/sources.json --output-dir runs/topic
```

4. Prepare stable passages, with any patterns and context treated as research
   inputs rather than hidden implementation details:

```bash
.venv/bin/python scripts/passage_evidence.py prepare \
  --pages runs/topic/pages.json --output-dir runs/topic \
  --pattern 'definition|defined|means' --context 1
```

Before the paid call, show every selected file and page, selection rationale,
omitted-source limitations, regex patterns, context setting, exact model,
maximum output tokens, tool boundary, and total USD ceiling. Wait for explicit
approval of this fixed manifest. Approval to prepare it is not approval to run
the model.

## Bounded Run

```bash
.venv/bin/python scripts/run_feynman_quotes.py \
  --run-dir runs/topic \
  --model gpt-4.1 \
  --budget-usd 0.50 \
  --max-output-tokens 5000
```

Defaults are GPT-4.1 and a USD 0.50 total ceiling, but always state them rather
than relying on defaults. The ceiling is finite and cumulative for its ledger.
Use a new run directory for each attempt. Do not delete a ledger to resume or
bypass a ceiling. Never escalate model or budget automatically.

Feynman must return claims linked to `passage_id` values, with no `quote` or
`text` fields. Its model tools are disabled in this workflow, so state plainly
that it cannot inspect omitted pages or search elsewhere.

## Deterministic Quotation Materialization

```bash
.venv/bin/python scripts/passage_evidence.py materialize \
  --passages runs/topic/passages.json \
  --selections runs/topic/candidates.json \
  --output runs/topic/checked-evidence.json
```

Materialization verifies IDs and PDF checksums, then copies the stored exact
text and page metadata. It proves provenance from prepared evidence, not OCR
quality, relevance, or interpretation. Inspect decisive page images and reject
conceptual category errors. Report actual model tokens and estimated cost
separately from conservative budget reservations.
