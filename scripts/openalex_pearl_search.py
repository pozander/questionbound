#!/usr/bin/env python3
# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""One-generation, books-only citation chaining. No LLM calls or PDF retrieval."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from openalex_bibtex import bibtex_for_work, plain_record_for_work

API = 'https://api.openalex.org/works'


def work_id(value):
    value = re.sub(r'^https?://openalex.org/', '', value.strip(), flags=re.I).upper()
    if not re.fullmatch(r'W\d+', value):
        raise ValueError('Seeds must be OpenAlex work IDs, such as W2741809807.')
    return value


def plan(seeds, direction, limit, max_requests):
    seeds = sorted(set(map(work_id, seeds)), key=lambda x: int(x[1:]))
    if not seeds or len(seeds) > 100:
        raise ValueError('Provide between 1 and 100 distinct seeds.')
    if limit < 1 or max_requests < 1:
        raise ValueError('Limits must be positive.')
    directions = ['backward', 'forward'] if direction == 'both' else [direction]
    return dict(seeds=seeds, directions=directions, max_results_per_direction=limit,
                max_requests=max_requests, generations=1, type='book',
                sort='publication_date:asc', queries={d: {
                    'filter': f"type:book,{'cited_by' if d == 'backward' else 'cites'}:" + '|'.join(seeds),
                    'sort': 'publication_date:asc', 'per-page': min(200, limit), 'cursor': '*'
                } for d in directions})


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


class Client:
    def __init__(self, folder, key, maximum):
        self.folder, self.key, self.maximum, self.calls = folder, key, maximum, 0

    def get(self, url, params):
        if self.calls >= self.maximum:
            raise RuntimeError('Request ceiling reached; remaining retrieval is incomplete.')
        self.calls += 1
        prefix = self.folder / f'request-{self.calls:03d}'
        provenance = dict(url=url, params=params, timestamp_utc=datetime.now(timezone.utc).isoformat())
        try:
            response = requests.get(url, params={**params, 'api_key': self.key}, timeout=45)
        except requests.RequestException:
            # Never serialize exceptions: requests may include the credential-bearing URL.
            provenance['error'] = 'Network request failed; no automatic retry.'
            save(prefix.with_suffix('.json'), provenance)
            raise RuntimeError(provenance['error']) from None
        provenance['status_code'] = response.status_code
        if response.status_code != 200:
            save(prefix.with_suffix('.json'), provenance)
            raise RuntimeError(f'OpenAlex HTTP {response.status_code}; response body omitted to protect credentials.')
        raw = response.content
        # A successful response should never contain the credential; fail closed if it does.
        if self.key.encode() in raw:
            raise RuntimeError('Response unexpectedly contained credential; not saved.')
        prefix.with_suffix('.raw.json').write_bytes(raw)
        provenance['sha256'] = hashlib.sha256(raw).hexdigest()
        save(prefix.with_suffix('.json'), provenance)
        try:
            return json.loads(raw)
        except ValueError:
            raise RuntimeError('Invalid JSON response; raw response preserved.') from None


def collect(config, get, works, edges, progress):
    seeds = {}
    for seed in config['seeds']:
        seeds[seed] = get(f'{API}/{seed}', {})
    for direction in config['directions']:
        params = dict(config['queries'][direction])
        state = dict(returned=0, total_matches=None, complete=False, capped=False)
        progress[direction] = state
        seen_cursors = set()
        while True:
            cursor = params['cursor']
            if cursor in seen_cursors:
                raise RuntimeError('Repeated cursor; retrieval stopped.')
            seen_cursors.add(cursor)
            data = get(API, params)
            state['total_matches'] = data['meta']['count']
            remaining = config['max_results_per_direction'] - state['returned']
            page = data['results'][:remaining]
            for record in page:
                wid = work_id(record['id'])
                state['returned'] += 1
                if record.get('type') != 'book':
                    raise RuntimeError('API returned a non-book despite the book filter.')
                if wid in seeds:
                    continue
                works[wid] = record
                matched = []
                refs = {work_id(x) for x in record.get('referenced_works', [])}
                for sid, seed in seeds.items():
                    seed_refs = {work_id(x) for x in seed.get('referenced_works', [])}
                    if (direction == 'backward' and wid in seed_refs) or (direction == 'forward' and sid in refs):
                        matched.append(sid)
                        edges.add((sid, direction, wid, 'reference_list'))
                if not matched:
                    # Keep the retrieval while acknowledging inconsistent/missing link metadata.
                    edges.add(('', direction, wid, 'query_match_only_seed_unresolved'))
            next_cursor = data['meta'].get('next_cursor')
            state['complete'] = state['returned'] >= state['total_matches'] or not next_cursor
            state['capped'] = not state['complete'] and state['returned'] >= config['max_results_per_direction']
            if state['complete'] or state['capped']:
                break
            if not page:
                raise RuntimeError('Empty page with remaining cursor; retrieval incomplete.')
            params = {**params, 'cursor': next_cursor}


def export(folder, works, edges):
    ordered = sorted(works, key=lambda x: int(x[1:]))
    records = [plain_record_for_work(works[x]) for x in ordered]
    save(folder / 'books.json', records)
    (folder / 'books.bib').write_text('\n\n'.join(bibtex_for_work(works[x], i+1) for i,x in enumerate(ordered)), encoding='utf-8')
    with (folder / 'citation-edges.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['seed_id', 'direction', 'book_id', 'evidence'])
        writer.writerows(sorted(edges))
    with (folder / 'inventory.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['openalex_id', 'title', 'year', 'doi', 'url'])
        for r in records:
            writer.writerow([r.get(k) for k in ['openalex_id', 'title', 'year', 'doi', 'url']])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', action='append', required=True, help='Repeat for each known edition/record.')
    parser.add_argument('--direction', choices=['backward', 'forward', 'both'], default='both')
    parser.add_argument('--max-results', type=int, default=500, help='Maximum returned records per direction across all seeds.')
    parser.add_argument('--max-requests', type=int, default=30, help='Includes seed metadata calls. No retries.')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--brief', type=Path, help='Existing approved brief, copied verbatim into run folder.')
    parser.add_argument('--dry-run', action='store_true', help='Print plan without network or file writes.')
    args = parser.parse_args(argv)
    try:
        config = plan(args.seed, args.direction, args.max_results, args.max_requests)
    except ValueError as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps(config, indent=2))
        return 0
    if not args.output_dir or not args.brief:
        parser.error('Live execution requires --output-dir and --brief; obtain approval first.')
    brief = args.brief.read_bytes()
    key = os.environ.get('OPENALEX_API_KEY', '').strip().strip('\"\x27')
    if not key:
        parser.error('Set OPENALEX_API_KEY in the environment.')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'approved-brief.txt').write_bytes(brief)
    config['brief_sha256'] = hashlib.sha256(brief).hexdigest()
    config['limitations'] = 'Changing catalogue; incomplete citation coverage; provider book labels; editions not automatically merged; no semantic ranking. Equal-date ordering is provider-controlled.'
    save(args.output_dir / 'manifest.json', config)
    client = Client(args.output_dir, key, args.max_requests)
    works, edges, progress = {}, set(), {}
    error = None
    try:
        collect(config, client.get, works, edges, progress)
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        error = str(exc) if isinstance(exc, RuntimeError) else 'Unexpected response schema; inspect saved raw responses.'
    export(args.output_dir, works, edges)
    summary = dict(status='error' if error else 'finished', error=error,
                   requests=client.calls, unique_book_records=len(works), directions=progress,
                   complete=not error and all(v['complete'] for v in progress.values()))
    save(args.output_dir / 'summary.json', summary)
    print(json.dumps(summary, indent=2))
    return 1 if error else 0


if __name__ == '__main__':
    raise SystemExit(main())
