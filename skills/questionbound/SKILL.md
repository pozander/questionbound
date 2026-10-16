---
name: questionbound
description: "Use for auditable literature research with QuestionBound: approve a fixed research brief, run deterministic OpenAlex discovery and PDF retrieval, use bounded Tavily gap recovery or local RAG, and perform budget-limited Feynman synthesis with verifiable quotations. Also use for questions about this pipeline and its research controls."
---

# QuestionBound Literature Research

Resolve the QuestionBound checkout before running project commands:

1. Use the current repository when it contains `AGENTS.md` and
   `scripts/openalex_bibtex.py`.
2. Otherwise use the directory named by `QUESTIONBOUND_ROOT`, if set and valid.
3. If neither identifies a checkout, ask the user to open or locate one. Do not
   guess a machine-specific path or clone a repository without being asked.

Keep executable logic in the checkout. This skill supplies routing and operating
rules; do not duplicate its Python scripts here.

## Start Every Research Run With A Contract

Read the project's `AGENTS.md` before using OpenAlex, Feynman, or the research
pipeline. Preserve the user's research question verbatim. Keep interpretations,
clarifications, exclusions, and proposed synonyms in separate fields.

Before any network search or paid model call:

1. Resolve material ambiguity with the user.
2. Display a concise research brief containing the verbatim question, agreed
   clarification, exclusions, evidence boundary, execution boundary, required
   result, and unresolved issues.
3. Assess whether discovery should be lexical, semantic, or hybrid. Show the
   recommendation, rationale, proposed queries, filters, selection method,
   model, and spending ceiling as applicable.
4. Wait for explicit approval of that displayed version.

An initial instruction to "search" or "run Feynman" does not approve details
introduced later. Renew approval when meaning, evidence, tools, model, or budget
changes materially. Maintenance, offline tests, and drafting a brief do not
trigger this gate.

## Choose The Smallest Suitable Stage

- For scholarly discovery, metadata, abstracts, BibTeX, CSV, or deterministic
  OpenAlex PDF retrieval, read `references/openalex.md`.
- For analysis of a fixed, approved evidence subset and exact page-linked
  quotations, read `references/feynman.md`.
- For semantic retrieval within PDFs already held locally, read
  `references/rag.md`.

Do not use Feynman as the default discovery engine. Prefer OpenAlex for corpus
discovery, deterministic local tools for extraction and matching, RAG for
retrieval from a curated corpus, and Feynman only for bounded conceptual
synthesis where its token cost is justified.

## Preserve The Division Of Labor

- The researcher owns meaning, scope, approval, and final evidential standards.
- Codex proposes queries, prepares artifacts, runs deterministic tools, and
  audits relevance and provenance.
- OpenAlex discovers and retrieves structured scholarly records and available
  full text; its ranking is not a relevance verdict.
- Tavily may recover a bounded number of missing abstracts or source pages; its
  results remain separately logged and do not silently broaden the corpus.
- RAG retrieves likely passages from already indexed documents; it does not
  discover the literature or validate an interpretation.
- Feynman compares only approved passages and selects stable passage IDs; it
  must not invent or transcribe quotation wording.
- Local materialization inserts exact extracted text and page metadata; visual
  review resolves decisive OCR or layout uncertainty.

Keep each run in a new, descriptively named output directory. Retain its brief,
approval record, query or evidence manifest, settings, raw response, checked
evidence, usage record, and limitations. Report insufficient evidence rather
than shifting the question to something easier.
