# Cybernetics and function

Research goal: find definitions of cybernetics and of function within cybernetics,
especially concepts that work across machines, thought, and nervous systems.

Exact user-supplied terms, submitted as one search:

```text
"function" "cybernetics" "thought" "machine" "nervous system"
```

Run date: 2026-09-26. Inclusive publication-year filters: 1950-1980.
Maximum results: 50, sorted by OpenAlex relevance. No synonym expansion.
Search uses the existing deterministic PyAlex script, with no LLM retrieval.
Results can change as the upstream index changes. The date filters apply to
OpenAlex metadata, which needs verification for historic texts and reprints.

Command from the project root, with OPENALEX_API_KEY set:

```bash
.venv/bin/python scripts/openalex_bibtex.py \
  --query-file literature-search-dictionary/queries/cybernetics-function-1950-1980.md \
  --from-year 1950 --to-year 1980 --max-results 50 \
  --format markdown \
  --output results/cybernetics-function-1950-1980-exact.md
```

Earlier foundational texts can be considered during citation follow-up;
the initial retrieval window has not been expanded.
