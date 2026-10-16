# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Offline first-pass judgements; never a discovery or model call."""
import csv
import json
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / 'runs/hei-closest-books-revision2-2026-10-14'
records = json.loads((RUN / 'deduplicated.json').read_text())
# Explicit analyst decisions against the saved, stable record order.
retain = {
6: 'HE action research; indexed contents emphasise teaching and learning. Methodological neighbour.',
12: 'AR professional learning in HE and communities, including African cases and university-community partnerships.',
13: 'Direct combination of system dynamics, participatory AR and HE quality management; publication provenance needs checking.',
15: 'HE teaching/learning research guide; overlaps novice-researcher readership but narrower intervention domain.',
17: 'Practical pedagogical AR guide; strong reader overlap, narrower teaching/learning remit.',
21: 'Action inquiry guide to HE reform and community partnerships; explicit practitioner and postgraduate audience.',
30: 'PALAR, action leadership and academic development; conceptual and practical neighbour.',
41: 'AR-based university-stakeholder cooperation and social mission; direct organisational and societal overlap.',
49: 'AR-based organisational transformation of universities and democratic societal functions; strongest abstract-supported direct comparator.',
248: 'Indexed contents cover technology, institutional models and virtual universities across regions; historical ICT/HE comparator.',
249: 'Explicit digital transformation of HE organisations; retain provisionally, editorial framing is broad and requires contents verification.',
256: 'IS organisational problem-solving and change; cross-sector methodological neighbour, not an HE-specific competitor.',
263: 'Empirical sociotechnical organisational change including HE; useful empirical neighbour, not established as an intervention guide.',
280: 'Indexed contents connect university societal roles, institutional change and technology; broader conceptual neighbour.'
}
special = {
1: 'High-priority title match: critical participatory AR in HE. No abstract; verify description and contents.',
2: 'Likely duplicate of record 1; abstract only says formats available. Keep pending bibliographic reconciliation.',
5: 'Likely same work as record 49, whose abstract is informative; do not count as another book.',
16: 'Strong title match; sparse Polish project note insufficient for comparison; possible relation to record 41 needs checking.',
32: 'Likely duplicate of record 12; verify edition before counting separately.',
51: 'Likely later platform/edition record of record 49, not independent comparator.',
55: 'Likely duplicate of record 30 with expanded subtitle.',
223: 'Activity-theory intervention framework; defer to approved later theoretical-neighbour stage.',
227: 'Activity-theory framework; defer to later theoretical-neighbour stage.',
247: 'High-priority ICT/HE organisational-change title; abstract is placeholder, not usable evidence. Verify contents before substantive comparison.'
}
exclude = {
36: 'Abstract explicitly identifies final project report; excluded from books-only comparison, though substantively relevant.',
60: 'Title identifies interim report, outside books-only comparison.',
69: 'Title identifies report, outside books-only comparison.',
71: 'Title identifies project deliverable/report.',
150: 'Title identifies project evaluation rather than comparative book.',
177: 'Title identifies executive summary.',
236: 'Title identifies oral-history interview.',
307: 'Title identifies briefing paper.',
8: 'Title identifies conference proceedings; not retained as authored/edited comparative book without further verification.',
61: 'Conference proceedings; outside present comparator shortlist.',
218: 'Conference proceedings in urbanism, outside HE organisational transformation scope.',
305: 'Conference proceedings; outside present comparator shortlist.',
306: 'Conference proceedings; outside present comparator shortlist.',
308: 'Conference proceedings; outside present comparator shortlist.'
}
off_topic = [4,7,10,14,47,62,70,74,75,84,85,93,94,95,100,101,103,113,116,118,119,120,121,127,131,134,135,138,139,140,141,143,145,146,147,153,154,156,157,158,159,164,165,166,169,170,171,175,176,180,181,183,186,188,191,192,195,199,205,207,209,211,213,215,216,217,219,220,221,228,229,232,233,234,235,239,240,245,258,260,261,262,267,275,276,277,278,279,285,287,291,292,293,299,301,303,304,310,311,313,315,319,321,322]
for i in off_topic:
    exclude[i] = 'Title-stage exclusion from closest practical books: principal subject is outside HE-sector organisational transformation/intervention guidance. Not a judgement of scholarly quality.'
fields = ['record_index','openalex_id','title','authors','year','doi','url','screening_status','screening_basis','reason','query_ranks']
counts = {}
with (RUN/'inventory-screened-first-pass.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for i,r in enumerate(records):
        status, basis, reason = 'uncertain', 'title only', 'Not shortlisted at title stage; abstract/contents assessment remains open. No automatic exclusion for absent abstract.'
        if i in retain:
            status,basis,reason = 'retain','abstract or indexed contents',retain[i]
        elif i in special:
            basis,reason = 'metadata/selected abstract',special[i]
        elif i in exclude:
            status,basis,reason = 'exclude','abstract' if i == 36 else 'title only',exclude[i]
        row = {k:r.get(k) for k in ['openalex_id','title','year','doi','url']}
        row.update(record_index=i,authors='; '.join(r['authors']),screening_status=status,screening_basis=basis,reason=reason,query_ranks=json.dumps(r['query_ranks']))
        writer.writerow(row)
        counts[status] = counts.get(status,0)+1
print(json.dumps(counts))
