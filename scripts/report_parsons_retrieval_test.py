# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Assemble the experiment output and separate reviewer assessment."""
import json
from pathlib import Path

run = Path(__file__).resolve().parents[1] / 'runs/parsons-question-retrieval-2026-10-14'
result = json.loads((run/'candidates.json').read_text())
usage = json.loads((run/'usage.json').read_text())
manifest = json.loads((run/'retrieval-manifest.json').read_text())
review = '''## Codex review (separate from Feynman's answer)

Verdict: useful first-pass synthesis, but not safe for direct insertion into the book. The central contrast—outcomes of activities versus system-referenced functional requirements—was recovered without hand-selected pages. It also recognised that analytical categories do not map one-to-one onto institutions.

Important weaknesses:

- Attribution: physical page 407 (printed 393) belongs to Neil J. Smelser's epilogue. Feynman repeatedly says Parsons explicitly states propositions on that page, without distinguishing Smelser's account of their jointly developed framework. The page itself contains clues: it refers to Parsons and Platt in the third person and cites Parsons and Smelser. Corpus-level authorship metadata alone is insufficient.
- Analytical levels: Feynman describes cultural, social, personality and behavioural subsystems as segments of society. Physical page 29 identifies these as subsystems of the general action system, not four subsystems of society. This is a substantive conceptual error.
- Overstatement: the answer leans heavily on survival, stability and social order, and makes speculative claims about Parsons inferring functions from necessity. The selected evidence does not establish all these contrasts. The retrieval missed the previously identified primary passages on progressive turbulence (physical 402), repression of desirable change (264), and the fuller AGIL exposition (24–28). These were not supplied after the fact.
- It describes the evidence as eight passages. The actual input contained seven full pages divided into 46 passages. Five selected passage IDs were mechanically materialized successfully.
- Its criticism that the author's definition does not explain institutional persistence may be a useful further question, but a stipulated orienting definition is not intended to supply a complete causal explanation.

What the verification establishes: the five selected IDs exist and exact extracted wording and PDF provenance were materialized. This does not validate each associated claim. No new visual/OCR verification was performed for this test; do not treat the materialized text as publication-ready quotations.

Experiment limits: the retrieval rules were fixed before viewing their results; the corpus/book itself was already known to be relevant. This is a within-book retrieval test, not independent literature discovery. The Codex reviewer knows the earlier findings, but these were not included in the Feynman prompt. The prior Parsons comparison and footnote were removed from the supplied author draft; the user's source file was not edited.

Cost interpretation: the API amount below excludes Codex setup, review, and earlier corpus preparation. There is no reliable conversion of these totals into the task's Codex allowance percentage, and this is not a measured end-to-end cost comparison. Local lexical retrieval itself made no model/API calls.
'''
out = '# Parsons: question-to-retrieval experiment\n\n'
out += 'Question: I started to look at Parsons precisely because his fame for functionalism. Now look for "hot functional takes". How do my text differ from his functionalism?\n\n'
out += 'Evidence: local BM25 over the entire existing book corpus; query terms function/functions/functional/functionalism; k1=1.5, b=0.75, ties resolved by ascending physical page. Top eight candidates, stopping before 20,000 characters of full-page content. No human substitution.\n\n'
out += 'Selected physical pages in rank order: ' + ', '.join(str(x['physical_page']) for x in manifest['selection']) + '. Seven pages fit the cap.\n\n'
out += f"One GPT-4.1 call; {usage['input']:,} input tokens, {usage['output']:,} output tokens; {usage['totalTokens']:,} total. Estimated API cost: ${usage['estimated_cost_usd']:.5f}. Approved ceiling: $0.20.\n\n"
out += review + '\n## Feynman answer — unedited, including errors noted above\n\n' + result['answer'] + '\n\n## Feynman limitations — unedited\n\n'
out += '\n'.join('- '+x for x in result['limitations']) + '\n'
(run/'report.md').write_text(out)
print(run/'report.md')
