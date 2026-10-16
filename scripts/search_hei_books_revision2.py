"""Fixed, approved title/abstract searches; no query expansion or model ranking."""
import csv
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime,timezone
import requests
from openalex_bibtex import plain_record_for_work,bibtex_for_work

root=Path(__file__).resolve().parents[1]
out=root/'runs/hei-closest-books-revision2-2026-10-14'
out.mkdir(exist_ok=False)
h='("higher education" OR university OR universities OR "tertiary education")'
t='(ICT OR "information technology" OR "information systems" OR "educational technology" OR "learning technology" OR digitalisation OR digitalization OR "digital transformation")'
groups=[
 '("action research" OR "participatory action research" OR "action inquiry")',
 '("action design research" OR "design science research")',
 '("design-based research" OR "educational design research" OR "research through design")',
 '("participatory design" OR "developmental work research" OR "formative intervention")',
 '("organizational change" OR "organisational change" OR "institutional change")',
 '("organizational transformation" OR "organisational transformation" OR "institutional transformation")',
 '("organizational development" OR "organisational development" OR "institutional development")',
 '("change management" OR "strategic change" OR "educational change")'
]
queries=[' AND '.join([h]+([t] if i>=4 else [])+[g]) for i,g in enumerate(groups)]
manifest={'original_question':'So now run an openAlex search for the "closest attempts" of the book.','revision_request':'ok, make a new revision. I would expect hundreds of hits, but that is not problematic at the first go.','approval_reply':'approve, assuming that this is deterministic','clarification':'Practical neighbours for theoretical positioning and eventual publisher/readership comparison. Route A: HE intervention research, no ICT requirement. Route B: HE ICT-mediated organisational transformation, no action-research requirement. Books only, known classification errors checked during screening.','queries':queries,'query_fields':'title and abstract only','filter':'type:book','sort':'relevance_score:desc','result_cap_per_query':200,'other_filters':None,'known_candidates':['Higher Education for Good','The Facilitating University'],'known_candidate_check':'Publisher descriptions and contents; if unavailable, report the gap.','excluded_work':'No separate theoretical-neighbour search, downloads, Feynman calls, manuscript changes or sales inference.','determinism':'Fixed lexical query procedure, no semantic reranking or query expansion. Live catalogue can change. Raw responses retained and locally deduplicated by OpenAlex ID in query/rank order. Subsequent relevance assessments are judgement, not deterministic screening.','timestamp_utc':datetime.now(timezone.utc).isoformat()}
(out/'search-brief.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False))
key=os.environ['OPENALEX_API_KEY'].strip().strip("'\"")
unique={}; summary=[]
for i,q in enumerate(queries,1):
    public={'filter':'type:book,title_and_abstract.search:'+q,'per-page':200,'sort':'relevance_score:desc'}
    try:
        response=requests.get('https://api.openalex.org/works',params=dict(public,api_key=key),timeout=60)
        if response.status_code!=200:
            error={'query_id':i,'status':response.status_code,'message':response.text.replace(key,'[REDACTED]')[:2000]}
            (out/f'q{i}-error.json').write_text(json.dumps(error,indent=2))
            print(json.dumps(error),flush=True)
            break
        raw=response.content
        (out/f'q{i}-raw.json').write_bytes(raw)
        result=response.json()
        assert all(w.get('type')=='book' for w in result['results'])
        meta={'query_id':i,'route':'A' if i<=4 else 'B','params':public,'timestamp_utc':datetime.now(timezone.utc).isoformat(),'total_matches':result['meta']['count'],'returned':len(result['results']),'capped':result['meta']['count']>200,'response_sha256':hashlib.sha256(raw).hexdigest()}
        (out/f'q{i}-provenance.json').write_text(json.dumps(meta,indent=2))
        summary.append(meta)
        print(json.dumps({k:meta[k] for k in ['query_id','route','total_matches','returned','capped']}),flush=True)
        for rank,w in enumerate(result['results'],1):
            item=unique.setdefault(w['id'],{'work':w,'query_ranks':[]}); item['query_ranks'].append({'query':i,'rank':rank})
    except requests.RequestException as e:
        (out/f'q{i}-error.json').write_text(json.dumps({'query_id':i,'error_type':type(e).__name__},indent=2))
        print('NETWORK ERROR query',i,type(e).__name__,flush=True)
        break
records=[dict(plain_record_for_work(x['work']),query_ranks=x['query_ranks']) for x in unique.values()]
(out/'deduplicated.json').write_text(json.dumps(records,indent=2,ensure_ascii=False))
(out/'books-unscreened.bib').write_text('\n\n'.join(bibtex_for_work(x['work'],i) for i,x in enumerate(unique.values(),1)))
with (out/'inventory.csv').open('w',newline='') as f:
    fields=['openalex_id','title','year','authors','doi','query_ranks','abstract','screening_status','screening_reason']
    writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
    for r in records:
        row={k:r.get(k) for k in fields}; row.update(authors='; '.join(r['authors']),query_ranks=json.dumps(r['query_ranks']),screening_status='pending',screening_reason='Not yet assessed'); writer.writerow(row)
(out/'retrieval-summary.json').write_text(json.dumps({'queries_completed':len(summary),'queries':summary,'records_before_deduplication':sum(x['returned'] for x in summary),'unique_records':len(records),'without_abstract':sum(not r['abstract'] for r in records)},indent=2))
print('TOTAL UNIQUE',len(records),'WITHOUT ABSTRACT',sum(not r['abstract'] for r in records),flush=True)
