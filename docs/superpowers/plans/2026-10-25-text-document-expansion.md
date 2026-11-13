# Text Document Expansion Implementation Plan

> Execute in this session using focused agents and integrate/review each contribution. No further approval checkpoint; Windows-first scope was explicitly selected.

**Goal:** Add native text documents and spreadsheet text to Windows imports, discovery, search and source viewing while preserving PDF behavior and accurate Android capabilities.

**Architecture:** Bounded passive extractors yield labeled source units; existing stages store their passages/vectors atomically. Additive source metadata drives text UI. Existing PDF reader and embedding profile remain unchanged.

**Spec:** ../specs/2026-10-25-text-document-expansion.md

**Tech stack:** Python standard ZIP/XML/csv/html parsing, existing SQLite/NumPy/model stack, React/TypeScript, existing Java capability emitter.

## Constraints / review focus

No images/audio/video, invented pagination, formula execution, remote fetches, global re-embedding or live test fixtures. Test malformed/oversized containers, sparse cells and quoted multiline records, interrupted replacements, source mutation, backup traversal, unsupported Android formats and accidentally invoking PDF routes for text.

## Tasks

- [x] Extractor: create `knowledge_library/text_documents.py` and `tests/test_text_documents.py`. Pin the exported registry/wrapper/metadata contracts from the spec. Observe failing tests, implement, verify focused Unicode/structure/formula/bounds cases.
- [x] Ingestion/lifecycle: update `library.py`, `maintenance.py`, `export.py`, `recovery.py` as needed. Preserve strict import_pdf, add generic import_document, share staging with native units, enrich results/documents/pages with locations, protect source identity, and round-trip storage/verify/refresh/Trash/backup. Add `tests/test_text_document_library.py` with a fake encoder and isolated fixtures.
- [x] UI: update upload/folder capability handling, result labels/previews, a text viewer and accurate shared-platform copy; leave ContinuousPdf unchanged. Add format capability arrays in Android's native state, preserve its current readers. Extend folder-inventory tests and run TypeScript/Vite build.
- [x] Integration: root updates server dispatch/validation/MIME/units/geometry guards, discovery registry and API capability state, plus `tests/test_text_document_api.py`. Verify actual imports, discover/index source ownership, source-aware errors and old PDF routes.
- [x] Review: independent focused reviews of extraction, lifecycle and UI plus whole-change review; fix substantive findings with regressions.
- [x] Acceptance/deployment: focused suites, actual-model mixed-format isolated search, PDF/PPTX regressions, browser text/PDF flows, source/runtime payload fingerprints. Update local desktop code/interface only after proof; leave the user's 365-document library and Trash unchanged except normal app operation.

## Ledger

- User selected Windows-first; Android's new-format ingestion is not part of this change, and the interface must remain truthful about it.
- New source types retain existing ordinal fields internally for compatibility but display explicit source locations everywhere.
- Quantized/native inference is optional inspiration, not a safe drop-in for the current validated profile. Do not substitute a runtime change for delivering document support.

## Per-file indexing Skip

Queued jobs skip without running; active jobs stop at the next checkpoint, including while paused. Originals and prior committed indexes remain intact. Desktop jobs disable partial publication so Skip cannot leave a partial PDF behind. The final commit cannot be skipped. Skipped scan signatures do not requeue until the source changes or a user retries. Persisted skip requests stay skipped across restart.

## Delivered verification

42 focused Python tests, 37 PDF/presentation/recovery/API regressions, 8 compact retrieval tests, 9 frontend tests, TypeScript and production build passed. Isolated Chromium verified native sheet/row viewing, original PDF canvas and queued Skip/Retry. Real CUDA model ranked the intended PDF/TXT/CSV/DOCX/XLSX source first for five paraphrased queries. Bundled runtime verified native import/search/verify/refresh and Skip API. Desktop backend and frontend payload hashes match source/build. Configured personal library retains 365 documents and 667 Trash entries. Reports: results/text-expansion/. Existing model profile retained; installer and Android APK were not rebuilt.
