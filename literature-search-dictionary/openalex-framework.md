# OpenAlex BibTeX Framework

## Goal

Given one database search query, fetch the top 20 OpenAlex work results and save generated BibTeX records.

## Why OpenAlex

OpenAlex is designed for programmatic access to scholarly metadata. It is a better fit than Google Scholar for repeatable literature-search workflows.

## Script

```text
scripts/openalex_bibtex.py
```

## Usage With A Query File

```bash
python3 scripts/openalex_bibtex.py \
  --query-file literature-search-dictionary/queries/01-broad-marxist-leninist-ai-thinking.md \
  --max-results 20 \
  --output results/01-broad-marxist-leninist-ai-thinking.bib
```

## Dry Run

Use this before making live requests:

```bash
python3 scripts/openalex_bibtex.py \
  --query-file literature-search-dictionary/queries/01-broad-marxist-leninist-ai-thinking.md \
  --max-results 20 \
  --output results/01-broad-marxist-leninist-ai-thinking.bib \
  --dry-run
```

## Usage With A Raw Query

```bash
python3 scripts/openalex_bibtex.py \
  --query 'Pär-ola zander' \
  --max-results 20 \
  --output results/foo-par-ola-zander-openalex.bib
```

## Polite Pool

OpenAlex recommends identifying automated requests with an email address. You can pass one directly:

```bash
python3 scripts/openalex_bibtex.py \
  --query 'Pär-ola zander' \
  --mailto you@example.org \
  --output results/foo-par-ola-zander-openalex.bib
```

Or set:

```bash
export OPENALEX_MAILTO='you@example.org'
```

## Output

The script writes one `.bib` file containing up to 20 generated BibTeX records from OpenAlex metadata.

## Notes

OpenAlex search is not identical to a library database Boolean search. The script preserves the full query text, but if a query returns weak results, create an OpenAlex-specific simplified query variant.
