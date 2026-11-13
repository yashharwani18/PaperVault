# Text-first document expansion

User intent: retain Khoj's PDF-centered, source-verifiable text finding and expand to documents and spreadsheet text. Images, audio and video are explicitly out of scope. User selected Windows first; Android retains its actual PDF/PPTX capabilities. Proceed within this scope without another design checkpoint.

## Approach

Use native text extraction, not conversion to invented PDF pages. This preserves section/sheet/row provenance and avoids an Office installation requirement. Keep PDF and current presentation ingestion intact. Reuse staged chunking, existing embeddings, exact source hashing and committed SQLite storage; no schema migration is needed because source locators fit existing page evidence JSON.

Alternatives: converting everything to PDFs would reuse the viewer but invent misleading pagination and extra files; a native inference rewrite would expand risk and require embedding compatibility/quality evaluation. Neither is needed to deliver these formats. Quantized inference remains a separately measured migration; bounded extraction and current memory safeguards apply immediately.

## Formats and limits

DOCX, ODT, TXT, Markdown (.md/.markdown), HTML (.html/.htm), XLSX, ODS, CSV and TSV. Existing PDF/PPT/PPTX support remains. Legacy DOC/XLS, RTF, macro-enabled and encrypted containers are unsupported unless separately implemented with reliable parsing. Passive extraction never executes formulas, macros, external links or scripts. HTML never fetches assets; script/style content is excluded. Sheet formulas use cached values when present and visibly disclose missing cached values. Word tracked deletions are not indexed as current text.

Bound input to the existing 100 MiB upload limit, total expanded Office ZIP data to 128 MiB, individual XML parts to 32 MiB, extracted text to 20 million characters and source units to 10,000. Excess limits fail with a clear error and preserve the previous committed document; do not silently truncate. CSV quoting, multiline values, UTF-8/UTF-16 BOM and an explicit legacy-decoding policy require tests.

## Interfaces

New `knowledge_library/text_documents.py` owns `TEXT_EXTENSIONS`, `SPREADSHEET_EXTENSIONS`, `SUPPORTED_EXTENSIONS` (including existing PDF/PPT/PPTX), `MIME_TYPES`, `source_info(doc)`, `open_text_document(path)`. Registry extension values include leading dots. Native source wrappers implement context manager, iteration, `metadata`, `page_count`; each unit has zero-based `number` and an `extracted` dictionary matching the stage page contract.

`source_info(doc)` returns `source_kind` (pdf/presentation/text/spreadsheet), `source_format` (without dot), `preview_kind` (pdf/text), `unit_count`. Determine native types from recipe and filename; preserve existing PDF/presentation records.

Native unit `extracted` keys: page_number (positive internal ordinal), page_label, text, method (`text`/`spreadsheet`), status (`ok`/`empty`), warnings, ocr_confidence=None, evidence. Evidence uses frame `source_text`, version=1, empty geometry arrays and a `location` object. Locators include `kind`, `label`, and appropriate heading/paragraph range, line range, or sheet/row range. Integer page fields remain compatible internal source-unit ordinals, explicitly not physical pages for native formats. Public data adds `unit_number`, `location`, `location_label`, source info. Native open URIs never append #page=.

`Library.import_document` handles supported native sources plus PDF. `import_pdf` remains a strict PDF-compatible wrapper. Native originals are retained in `files/<sha>.<extension>` on upload, indexed in place for discovery. No PDF surrogate or document_sources row is needed for native formats. Native replacements must publish atomically; disable PDF's tier-one partial publication for native sources.

Public state adds `import_capabilities` with upload_extensions/folder_extensions/scan_extensions/share_extensions arrays (without dots). Desktop uploads/folders support existing plus native formats; scans support PDF and native formats (presentations only if actual dispatcher supports reference lifetime correctly). Android reports upload/folder PDF/PPTX and scan/share PDF, independently of desktop.

Document/detail and hit APIs expose source info and locations. `/documents/{id}/units/{number}` aliases text source-unit access. `/file` serves native originals as attachments with correct MIME and original extension. PDF image preview, geometry and OCR endpoints reject native formats; text viewer never invokes those endpoints. PDF reader remains unchanged.

## Lifecycle and verification

Refresh, retries, source replacement/reconnection, verify, Trash restoration, storage reporting and backup path allowlists must handle native source suffixes and locators. Source bytes, hashes, managed/reference ownership, old backups and manual organization remain protected. Generated fixtures used during verification live under .cache, skipped by whole-PC discovery; do not repopulate the user's library with tests.

End-to-end acceptance: import and search each new format with correct labels; discovery finds supported documents and ignores media; meaningful spreadsheet sheet/row references; stale source detection; unchanged refresh reuses embeddings; failed replacement preserves old version; native text viewer/download, Trash/restore and backup round trips; PDF/PPTX regressions; frontend production build; desktop bundled-runtime smoke; actual-model mixed-format search on isolated fixtures; no user documents rewritten or re-embedded for deployment.

## Per-file indexing Skip

Queued jobs skip without running; active jobs stop at the next checkpoint, including while paused. Originals and prior committed indexes remain intact. Desktop jobs disable partial publication so Skip cannot leave a partial PDF behind. The final commit cannot be skipped. Skipped scan signatures do not requeue until the source changes or a user retries. Persisted skip requests stay skipped across restart.
