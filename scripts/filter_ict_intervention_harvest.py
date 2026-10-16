# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Offline lexical candidate filter, not automatic relevance screening."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / 'runs/hei-closest-books-revision2-2026-10-14/deduplicated.json'
target = root / 'runs/hei-ict-intervention-filter-2026-10-15'
ict = r'\bICT\b|digital|information technolog|information systems|online|blended|mobile.learning|e.learning|computer|technolog'
intervention = r'action research|action inquiry|design.based research|design science|participatory design|intervention|co.design|developmental work research|formative experiment'
records = json.loads(source.read_text())
hits = []
for i, record in enumerate(records):
    text = record['title'] + ' ' + (record.get('abstract') or '')
    a, b = re.search(ict, text, re.I), re.search(intervention, text, re.I)
    if a and b:
        hits.append(dict(record_index=i, ict_match=a.group(), intervention_match=b.group(), **record))
target.mkdir(exist_ok=True)
(target/'lexical-candidates.json').write_text(json.dumps(hits, ensure_ascii=False, indent=2))
(target/'filter-manifest.json').write_text(json.dumps(dict(source=str(source), fields=['title','abstract'],
    ict_regex=ict, intervention_regex=intervention, operation='case-insensitive intersection',
    input_records=len(records), output_records=len(hits),
    limitations='Broad technology stem increases recall and false positives. Co-occurrence does not establish a methodological connection. Non-matches with missing abstracts remain uncertain.'), indent=2))
print(f'{len(hits)} lexical candidates from {len(records)} saved records; no network calls.')
