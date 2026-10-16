# Books-only pearl-string / citation-chain search

`scripts/openalex_pearl_search.py` performs one generation of citation chaining:

- backward: books cited by the seed (`cited_by` filter);
- forward: books citing the seed (`cites` filter).

Multiple `--seed` IDs are combined with OR, allowing known editions/platform records
to contribute links. Results are deduplicated by OpenAlex ID, not by title or edition.
Seed records themselves are excluded from the exported candidate inventory.
No keywords, semantic ranking, author expansion, LLM calls or downloads are used.

## Preview without network or writes

```sh
.venv/bin/python scripts/openalex_pearl_search.py \
  --seed W4396546505 --seed W4306983291 \
  --direction both --max-results 500 --max-requests 30 --dry-run
```

These two IDs are previously identified records of the Levin–Greenwood book;
include other verified records explicitly if the approved brief requires them.

After approval of the exact seed list, directions and caps, run the same command
without `--dry-run`, adding `--brief PATH_TO_APPROVED_BRIEF` and
`--output-dir runs/NEW_RUN_NAME`. Credentials are read only from `OPENALEX_API_KEY`.
Enclosing quote characters around the key are tolerated. The output directory must
not exist. Providing a brief is not itself proof of user approval: follow AGENTS.md.

## Bounds and reproducibility

The result cap applies separately to each direction across all seeds, before
excluding seeds. The request ceiling includes seed metadata requests. Requests are
sequential, timeout after 45 seconds, and are not retried automatically. Results
use publication-date ascending order; equal-date ordering is provider-controlled.
Cursor pagination and the exact raw responses/parameters are saved. This is a
fixed procedure, not a promise of identical future results from a live catalogue.

The script saves `manifest.json`, the approved brief, hashed raw responses,
`summary.json`, `books.json`, `books.bib`, `inventory.csv`, and `citation-edges.csv`.
Each edge identifies seed, direction and retrieved work. Where query results and
reference metadata disagree, the seed is left blank and evidence marked
`query_match_only_seed_unresolved`; no relationship is invented.

Caps and request failures are reported; successfully retrieved partial data is
exported even after a request failure. Check `summary.json`'s `complete`, not just
the process exit code. Reaching a record cap is a successful but incomplete run.
Bibliographic records retain provider metadata and require verification: OpenAlex
book classifications and citation coverage are imperfect, and editions may remain
separate. Missing links do not establish the absence of relevant books.

API semantics: https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/filter-works.md

Offline tests:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_openalex_pearl_search.py'
```
