# Work item: Document processing worker workflow

- Recorded at: 2026-07-25T13:33:31+05:00
- Status: planned

## Prompt

> Please make one technical document on how the workers will work for different kind of documents ( PDF , docx , html , .... etc ) and the documents with different kind of pages have tables , text , pictures , diagrams ,... etc . please share the complete workflow . please also share the workflow of each kind of worker in the technical document .

## Outcome

Created `Docs/worker-document-processing-workflow.docx`, defining the end-to-end ingestion workflow and the responsibilities, inputs, outputs, safety controls, and handoffs for each worker.

## Implementation intent

- Preserve the existing semantic Kafka lifecycle:
  `DocumentSubmitted` -> `DocumentFetched` -> `ContentExtracted` ->
  `ChunksCreated` -> `EmbeddingsGenerated` -> `DocumentIndexed`.
- Add a canonical normalized document model so all parsers emit the same
  document, page/section, content-unit, table, figure/diagram, and chunk
  contracts.
- Route files by detected MIME/magic bytes rather than extension alone and
  support PDF, DOCX, HTML, XLSX/CSV, PPTX, images/TIFF, email, and bounded
  archive containers.
- Process mixed page content as ordered content units. Dedicated enrichment
  paths handle OCR, reading order, tables, figures, charts, diagrams, captions,
  policy classification, and sensitive-content controls.
- Persist immutable originals and derived artifacts in tenant-prefixed MinIO
  storage. Events carry artifact references and metadata only, never document
  content.
- Maintain stage-local idempotency, PostgreSQL transactional outbox delivery,
  retry topics, DLQs, lineage, quality scores, and manual-review artifacts.
- Keep tenant isolation mandatory across events, object keys, relational state,
  embedding manifests, and Qdrant payloads/filters.

## Worker breakdown

| Worker | Primary responsibility |
| --- | --- |
| Submission/source connector | Validate the source and tenant, record lifecycle state, and write `DocumentSubmitted` to the outbox. |
| Document Fetcher | Retrieve the source bytes, fingerprint and inspect them, store the immutable original, and emit `DocumentFetched`. |
| Content Extractor | Select a parser profile, extract source structure, normalize it to the canonical model, enforce extraction-quality gates, and emit `ContentExtracted`. |
| OCR/layout/enrichment specialists | Improve scans and mixed layouts; reconstruct tables; bind captions; describe supported visuals; classify policy/PII; retain confidence and provenance. |
| Chunker | Build semantically complete, policy-aware chunks with source anchors and table/visual handling, then emit `ChunksCreated`. |
| Embedder | Generate versioned BGE-M3 representations with content/model-cache safeguards, then emit `EmbeddingsGenerated`. |
| Indexer | Upsert tenant-filtered Qdrant payloads and vectors, reconcile lifecycle state, and emit `DocumentIndexed`. |
| Outbox Publisher | Reliably publish committed PostgreSQL outbox rows to Kafka without business transformation. |

## Acceptance criteria

- Every indexed chunk has a tenant ID, document ID, immutable artifact version,
  source anchor, content checksum, policy labels, and worker/parser/model
  lineage.
- A retry or duplicate event never creates duplicate artifacts, chunks,
  embeddings, or Qdrant points.
- Every page or logical section has a terminal extraction status: succeeded,
  skipped with reason, needs review, or failed.
- Low-confidence OCR, table reconstruction, reading order, and visual
  interpretation are marked for fallback or review rather than presented as
  asserted facts.
- Originals, normalized models, enrichment artifacts, chunks, and index
  receipts remain independently reproducible without re-fetching the source.
