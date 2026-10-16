# Local RAG Retrieval

Use RAG only after documents have been selected and obtained. It is a retrieval
layer over the local corpus, not a scholarly database, an autonomous literature
review, or proof that a passage answers the research question.

Create page-addressable corpus files so every hit retains a physical PDF page:

```bash
.venv/bin/python scripts/prepare_pdf_rag_corpus.py \
  --pdf '/absolute/path/to/source.pdf' \
  --output-dir rag/topic/corpus \
  --source 'Author, Title (Year)'
```

Build and query the GPTme-RAG index:

```bash
gptme-rag index rag/topic/corpus --persist-dir rag/topic/index

gptme-rag search \
  'the approved conceptual retrieval question' \
  --persist-dir rag/topic/index \
  -n 8 --show-context --raw
```

Preserve the corpus manifest, source PDF checksum, index location, exact query,
and retrieval settings. Inspect bounded surrounding context, then verify any
quotation against the source page image. Keep retrieval findings distinct from
the final interpretation and from Feynman's paid synthesis.
