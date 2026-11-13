# Library parity progress and evidence

This document records incremental work against the full mission, not production acceptance.

## Implemented so far

- The shared interface no longer receives the document catalog from `/state`. It requests `include_documents=false` and reads library views from `/api/library-page`; `/state` still accepts `include_documents=true` for the few screens that need a full list.
- Desktop `/api/library-page` supports name A–Z/Z–A (natural numeric ordering with Unicode normalization), date added, size, date modified, document type and recently opened, plus folder, type, status, added/modified dates, size, favorites, recent, topic, name and search-scope filters. Every page response also carries alphabet offsets and the type list.
- Android `/api/library-page` supports added-date, size and natural name sorts, the same page metadata, and every filter except modified date. Modified sorts/filters and recently-opened ordering fall back to an explicitly fetched catalog on Android.
- Name and modified-date search scoping now resolves through the same backend filter path on desktop; the shared UI sends `library_filters` instead of thousands of document IDs. Android supports the name filter but not the modified-date filter.
- The interface uses server alphabet offsets for jumping, keeps selection metadata for rows from earlier pages, and opens search results and filename matches by document id when the item is not on the current page.
- Bills and Library tools fetch the full catalog only when those screens are opened. Filename suggestions use a bounded candidate endpoint on desktop and the lazy catalog on Android.
- Both platforms still have model-free exact filename matching, duplicate-safe selection and filename-first direct `/api/search` results. Content-only requests preserve the existing retrieval path. Unified calibrated ranking remains unfinished.
- Android manual text-only imports include PDF, PPTX, DOCX, XLSX, TXT, MD, CSV and TSV. Automatic phone scan is PDF-only.
- New imports can retain supplied modification time tied to source hash; older imports and unavailable metadata remain unknown. Scanner timestamps are used only for corresponding referenced sources.
- Reader return-position handling and superseded-search cancellation are implemented. Android can cancel queued work and checks interruption during retrieval; native inference already running may finish, and Windows workers may continue after a client disconnect.
- Additive database indexes and backward-compatible backup schema handling exist. The desktop old-backup restore/query-plan test passed. Android schema unit checks and instrumentation compilation passed; no device restore/query-plan test has run.

## Evidence

- Desktop focused tests: the database-page test now covers natural name paging, alphabet offsets, expanded types, the name filter, filename candidates and `include_documents=false`; the incremental-catalog and library-filter tests still pass (3 passed in the latest run).
- `scripts/validate_library_ui.py` runs a mock-data browser interaction using 2,002 synthetic records without a catalog in `/state`: bounded rows, server page requests at offsets 0 and 100, natural name paging, alphabet jump from server offsets, name-filter scoping, duplicate filename choice, unique direct open without content search, shrinking-library clamp, bulk removal/undo and a narrow viewport check. The mocked API is not a backend or Android test.
- TypeScript (`tsc -b`) and the production Vite build pass.
- Android `compileDebugJavaWithJavac` passes. The release APK was rebuilt after the UI/backend changes and package-audited; SHA-256 `ac0d65c981cc3f986be212d6459ebe9d2e46e556d5493febb1f81dcb63ee12ca`. The audit verifies packaging and signature, not runtime correctness.
- Prior checks: 41 desktop search/document tests, 37 desktop library/upgrade/organization tests, 15 frontend tests. `results/filename-api-microbenchmark.json` and `results/library-browse-microbenchmark.json` remain synthetic metadata/JS microbenchmarks only.

## Critical remaining work

- Desktop name/type/modified ordering scans filtered metadata and sorts it before slicing; the default added/size pages use indexed SQL. This needs a measured 1,000–10,000-document benchmark and, if necessary, persisted sort keys or indexes.
- `/state?include_documents=true` still builds and transfers the full catalog for Bills, Library tools, Android modified/recent ordering and Android filename suggestions. Those legacy screens are intentionally lazy but not database-backed.
- Android still lacks server-side modified-date filtering/sorting and recently-opened paging, so those selections load the catalog.
- Approximate filename scoring and calibrated unified ranking, large-result grouping and exact-source validation still need work.
- Android Office/plain-text import, search, source navigation, metadata and backup integration require execution on a device; multilingual quality parity, Qwen/embedding comparisons and source-highlighting parity are unverified. The release lint still reports Kotlin 2.4 versus 2.1 metadata diagnostics while Gradle succeeds.
- No light theme, complete mobile reader polish, virtual-collection parity, scalable bulk-operation measurements, or real 1,000–10,000-document/device latency, memory, battery and thermal results exist yet.
