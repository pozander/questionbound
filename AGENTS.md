# QuestionBound Working Agreements

## Purpose and Responsibility

The user owns the research question, intended meaning, and acceptable scope.
Codex proposes interpretations, search strategies, source selections, and
execution settings. Feynman analyses evidence within the approved boundaries.
Do not silently substitute a nearby, easier, or more readily answerable question.

These instructions apply to research through this project's OpenAlex and
Feynman pipeline, including invocations from another working directory.
They are behavioural safeguards, not an independent technical approval gate.

## Clarify, Propose, Approve, Execute

1. Preserve the user's research question verbatim. Keep clarifications separate
   from that wording. A loose request starts brief preparation, not execution.
2. Present the proposed interpretation and ask targeted questions about material
   ambiguity. Mark unresolved meaning or scope explicitly; do not guess merely
   to complete a form. The user may confirm an interpretation with a short reply.
3. Display a concise research brief containing the fields below. Clarification
   and the proposed brief may share a message, but user confirmation cannot be
   skipped. Make additional objectives and exclusions visible as proposals.
4. Wait for an explicit user approval message after the brief has been displayed.
   The initial request to search or run Feynman does not approve details that
   Codex introduces later. If approval is absent or ambiguous, stop and ask.
5. Execute only the approved scope. Approval may cover a clearly described
   multi-step search strategy; it need not require approval for every API call.
   Obtain renewed approval for substantive changes to meaning, exclusions,
   source boundaries, tools, model, or spending ceiling.

## Required Brief

- Research question: the user's verbatim wording.
- Agreed clarification: the intended sense and objective, confirmed by the user.
  If no clarification is needed, explicitly record that the wording is accepted
  as sufficient; do not fabricate an expanded interpretation.
- Exclusions: nearby questions that are not the target; disclose proposed ones.
- Evidence boundary: databases, queries or query-expansion rules, date range,
  selection criteria, and result limits for discovery; exact files and pages
  for a fixed-evidence analysis. State who selects the evidence and why.
- Execution boundary: tools permitted, whether external search or additional
  file access is allowed, model, and spending ceiling. Identify non-LLM steps.
- Required result: what would answer the question, required provenance, and
  how insufficient evidence must be reported.
- Unresolved issues: list them explicitly. Material unresolved issues block a run.

For OpenAlex, show the proposed queries, filters, and selection method before
running the search. Do not imply that a repeatable procedure guarantees identical
results from a changing catalogue.

For Feynman restricted to excerpts, show the exact evidence manifest and selection
rationale before execution. Explicitly state that it cannot examine omitted pages
or search beyond the supplied evidence when tools are disabled. Approval to prepare
an evidence selection is not approval to run the model on that selection.

For new bounded Feynman runs, use the passage-ID workflow documented in
`FEYNMAN_README.md`. Prepare stable IDs with `passage_evidence.py`, show any
regex filters and context setting as part of the evidence boundary, instruct
Feynman to return `selections` containing IDs rather than quotation wording,
and materialize exact extracted text locally. The legacy model-generated
`quotes` workflow is for reproducing old runs only unless the user explicitly
approves it. Never add a quotation-repair model call merely because the prompt
used the obsolete schema.

## Approval and Provenance

Keep the approved brief, evidence manifest, exact execution prompt, and settings
with the run artifacts. Record the user's actual approval and which version it
covered. Never fabricate approval, infer it from the initial request, or set an
approval field merely to satisfy validation. A file fingerprint can detect changes
but does not establish that a user approved its contents.

Do not bypass these requirements by invoking Feynman directly, changing scripts,
using another provider, or performing the same unapproved research manually.
If a run cannot proceed under the agreed conditions, explain the obstacle and ask.
Unattended work must stop on unresolved research meaning or missing approval.

Mechanical retries and quotation repairs within approved boundaries do not need
renewed approval. Retain prior spending reservations and source boundaries. Repairs
must not silently change the research question or substitute different evidence.

## Evaluate the Answer, Not Just the Quotes

Begin the final research report with the approved question, clarification, and
evidence boundary. Distinguish direct definitions, exact quotations, paraphrases,
and interpretations. State what remains unanswered.

Check relevance separately from quotation accuracy: does the result address the
approved meaning, or only related concepts? Correct wording and page references
do not make an irrelevant passage an answer. A passage about what a system does,
for example, does not automatically define function as a relationship within a
system model. This is an example of ambiguity, not a default interpretation for
future questions.

Allow and clearly report insufficient evidence. Do not redefine the question to
make a run appear successful. Propose any broader search for user approval.

## Maintenance Is Not a Research Run

The approval procedure does not prohibit reading existing logs, answering workflow
questions, drafting a brief, or performing requested code/documentation maintenance
and offline tests. Those activities must not trigger new research API calls or
silently expand the investigation. Reading candidate sources to prepare an evidence
selection is permitted when that preparation is requested or approved; show the
selection before running the bounded analysis.
