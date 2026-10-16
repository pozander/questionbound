"""Execute four user-approved book-only OpenAlex combinations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from pyalex import config
from openalex_bibtex import works_query, plain_record_for_work, bibtex_for_work

root=Path(__file__).resolve().parents[1]
out=root/'runs/hei-closest-books-2026-10-14'
out.mkdir(exist_ok=False)
config.api_key=os.environ['OPENALEX_API_KEY'].strip().strip("'\"")
if os.environ.get('OPENALEX_MAILTO'): config.email=os.environ['OPENALEX_MAILTO']
h='("higher education" OR university OR universities OR "tertiary education")'
t='(ICT OR "information technology" OR "information systems" OR "educational technology" OR "digital transformation" OR digitalisation)'
o='("organizational change" OR "organisational change" OR "organizational transformation" OR "organisational transformation" OR "institutional change" OR "institutional development")'
rs=[
 '("action research" OR "participatory action research" OR "action inquiry")',
 '("action research" OR "action design research" OR "design science research")',
 '("action research" OR "design-based research" OR "educational design research" OR "research through design")',
 '("action research" OR "participatory design" OR "developmental work research" OR "formative intervention")'
]
queries=[' AND '.join([h,t,o,r]) for r in rs]
manifest={'research_question':'So now run an openAlex search for the "closest attempts" of the book.', 'clarification':'First practical-neighbour strand: books on ICT-mediated organisational transformation in higher education through action research or related intervention traditions; empirical domain and readership proximity, not generic change management.', 'approval_reply':'Let us try. Run.', 'queries':queries,'filters':{'type':'book'},'date_language_journal_oa_filters':None,'max_results_per_query':20,'sort':'relevance_score:desc','exclusions':'Non-books, generic change-management works without the approved concept intersections. No theoretical-neighbour expansion in this pass.','execution':'Four OpenAlex searches only; no Feynman, downloads, or manuscript edits. Existing PyAlex query builder and export functions reused with type=book filter.','required_result':'Deduplicated candidates, preserved raw responses, preliminary relevance/readership assessment and explicit gaps.', 'unresolved_issues':[], 'timestamp_utc':datetime.now(timezone.utc).isoformat()}
(out/'search-brief.json').write_text(json.dumps(manifest,indent=2))
def fetch(pair):
    i,q=pair
    try:
        works,meta=works_query(q,None,None,[]).filter(type='book').get(per_page=20,return_meta=True)
        assert all(w.get('type')=='book' for w in works)
        result={'query_id':i,'query':q,'filter':{'type':'book'},'timestamp_utc':datetime.now(timezone.utc).isoformat(),'meta':meta,'results':list(works)}
        (out/f'q{i}-raw.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
        print(json.dumps({'query':i,'total_matches':meta.get('count'),'returned':len(works)}),flush=True)
        return result
    except Exception as e:
        # Do not serialize exception URLs: these can contain API credentials.
        result={'query_id':i,'query':q,'error_type':type(e).__name__}
        (out/f'q{i}-error.json').write_text(json.dumps(result,indent=2))
        print(json.dumps({'query':i,'error_type':type(e).__name__}),flush=True)
        return result
with ThreadPoolExecutor(max_workers=4) as pool:
    batches=list(pool.map(fetch,enumerate(queries,1)))
unique={}
for batch in batches:
    for w in batch.get('results',[]):
        item=unique.setdefault(w['id'],{'work':w,'query_ids':[]})
        item['query_ids'].append(batch['query_id'])
records=[dict(plain_record_for_work(x['work']),query_ids=x['query_ids']) for x in unique.values()]
(out/'deduplicated.json').write_text(json.dumps(records,indent=2,ensure_ascii=False))
(out/'books.bib').write_text('\n\n'.join(bibtex_for_work(x['work'],i) for i,x in enumerate(unique.values(),1)))
print('UNIQUE',len(records))
for r in records: print(json.dumps(r,ensure_ascii=False))
