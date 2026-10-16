# Deprecated Google Scholar BibTeX Framework

This framework has been superseded by:

```text
literature-search-dictionary/openalex-framework.md
```

Google Scholar blocked direct HTTP testing with an unusual-traffic/captcha page, so the active path is now OpenAlex.

## Goal

Given one database search query, fetch the top 20 Google Scholar hits and save their BibTeX records.

## Important Constraint

Google Scholar does not offer an official public API. Direct HTTP requests may be blocked by captcha, consent, or unusual-traffic pages. This framework uses cautious HTTP requests and clear failure messages, but it may still require a browser cookie or a later switch to a paid search API such as SerpAPI.

## Script

```text
scripts/google_scholar_bibtex.py
```

## Usage With A Query File

```bash
python3 scripts/google_scholar_bibtex.py \
  --query-file literature-search-dictionary/queries/01-broad-marxist-leninist-ai-thinking.md \
  --max-results 20 \
  --output results/01-broad-marxist-leninist-ai-thinking.bib
```

## Dry Run

Use this before making live requests:

```bash
python3 scripts/google_scholar_bibtex.py \
  --query-file literature-search-dictionary/queries/01-broad-marxist-leninist-ai-thinking.md \
  --max-results 20 \
  --output results/01-broad-marxist-leninist-ai-thinking.bib \
  --dry-run
```

## Usage With A Raw Query

```bash
python3 scripts/google_scholar_bibtex.py \
  --query '("artificial intelligence" OR "machine intelligence") AND ("dialectical materialism" OR Marxist)' \
  --max-results 20 \
  --output results/manual-query.bib
```

## Optional Cookie

If Google Scholar returns an interstitial, set a browser-derived cookie string:

```bash
export GOOGLE_SCHOLAR_COOKIE='...'
```

Then rerun the same command.

## Output

The script writes one `.bib` file containing up to 20 BibTeX records.

## Notes For Next Step

For the first research query, use:

```text
literature-search-dictionary/queries/01-broad-marxist-leninist-ai-thinking.md
```

Suggested output:

```text
results/01-broad-marxist-leninist-ai-thinking.bib
```
