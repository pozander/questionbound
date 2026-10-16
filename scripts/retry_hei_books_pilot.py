# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Retry only failed approved searches, sequentially, preserving successful results."""
import json
import os
from pathlib import Path
from datetime import datetime,timezone
import requests
from openalex_bibtex import plain_record_for_work,bibtex_for_work
out=Path(__file__).resolve().parents[1]/'runs/hei-closest-books-2026-10-14'
manifest=json.loads((out/'search-brief.json').read_text())
for i,q in enumerate(manifest['queries'],1):
    if (out/f'q{i}-raw.json').exists(): continue
    r=requests.get('https://api.openalex.org/works',params={'search':q,'filter':'type:book','per-page':20,'sort':'relevance_score:desc','api_key':os.environ['OPENALEX_API_KEY'].strip().strip("'\"")},timeout=45)
    print('Query',i,'HTTP',r.status_code,flush=True)
    if r.status_code!=200:
        print(r.text[:700],flush=True)
        break
    result=r.json()
    result.update({'query_id':i,'query':q,'filter':{'type':'book'},'timestamp_utc':datetime.now(timezone.utc).isoformat()})
    (out/f'q{i}-raw.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print('Matches',result['meta']['count'],'returned',len(result['results']),flush=True)
unique={}
for i in range(1,5):
    p=out/f'q{i}-raw.json'
    if not p.exists(): continue
    for w in json.loads(p.read_text())['results']:
        item=unique.setdefault(w['id'],{'work':w,'query_ids':[]}); item['query_ids'].append(i)
records=[dict(plain_record_for_work(x['work']),query_ids=x['query_ids']) for x in unique.values()]
(out/'deduplicated.json').write_text(json.dumps(records,indent=2,ensure_ascii=False))
(out/'books.bib').write_text('\n\n'.join(bibtex_for_work(x['work'],i) for i,x in enumerate(unique.values(),1)))
print('UNIQUE',len(records))
for r in records: print(r['openalex_id'].split('/')[-1],r['year'],r['query_ids'],r['title'])
