# Handoff: Khoj Android and Windows library parity

Updated: 2026-10-27. The user wants the work implemented, not just planned. They asked to reduce automated testing and token use; keep updates brief and run focused checks. Do not claim device validation without a connected device.

## Objective and workspace

- Workspace: `C:\Users\Yash\Downloads\startup idea`.
- Full mission: `C:\Users\Yash\.codex\attachments\e1efa4bc-eae5-4c02-b869-8e5b537f1944\pasted-text-1.txt`. Read it before continuing. It requires Windows/Android search, library scalability, text-only Android indexing, reader and UX parity, builds, and honest verification. The persistent goal is still active and incomplete.
- Do not delete or overwrite user documents or indexed libraries. Synthetic fixtures only. No cloud inference. Preserve Qwen and the existing desktop retrieval stack.
- The directory currently has no visible `.git` entry. Attempts to run Git status failed with `fatal: cannot change to 'C:/Users/Yash'`; do not assume a clean Git checkout or revert user changes.

## Catalog decoupling (verified 2026-10-27)

The shared UI no longer consumes a catalog from `/state`; it requests `include_documents=false` and drives All files, Favorites, Recently opened and home from `/api/library-page`. Desktop supports every library sort/filter server-side, including natural name ordering, modified dates, type and recent, and every response carries alphabet offsets and types. Alphabet jumps use server offsets. Search scopes travel as `library_filters` (including name/modified on desktop) instead of thousands of IDs. Search results and filename matches open by document id when the item is not on the current page. Bills and Library tools lazily fetch the catalog only when opened; Android filename suggestions do the same.

Android supports added/size/name sorts, alphabet metadata and all filters except modified date; modified and recent selections intentionally fall back to the lazy catalog. `/state` still defaults to returning documents for compatibility.

Checks: TypeScript, Vite build, three focused desktop tests (page/name/letters/candidates/`include_documents=false`, incremental catalog, library-filter scoping), the 2,002-record mock-browser check without a `/state` catalog, Android `compileDebugJavaWithJavac`, and a rebuilt/audited release APK. None of this is Android device or real-corpus validation.

Remaining risks: desktop name/type/modified ordering scans filtered metadata rather than using an index; Android modified/recent pages are not server-side; the lazy catalog still builds the full list when those legacy screens open. Do not claim complete database-backed paging across every scope or platform.

## Current implementation and evidence

- Both platforms have model-free exact filename matching, duplicate-safe selection, and direct `/api/search` filename-first results. Content-only requests preserve existing retrieval. UI offers approximate filename suggestions after content results, but unified calibrated ranking is unfinished.
- Android and desktop retain local AI/content, invoice and amount paths. The original `inv25` scenario has matching logic and focused regression work; Android device behavior is unverified. Invoice-number results prefer actual labelled source text where available.
- The shared interface pages the library through `/api/library-page`, uses server alphabet offsets, keeps selection metadata across pages, and includes favorites/recent, local search history, bulk reindex/removal and undo. Desktop pages every sort/filter; Android pages added/size/name and falls back to a lazy catalog for modified/recent. `/state` returns documents only when explicitly requested.
- Backend `/api/library-page` supports added-date, size and natural name sorts on both platforms (desktop also modified/type/recent), folder/type/status/date/size/favorite/recent/topic/name filters (desktop also modified date), alphabet offsets and type lists. Desktop search scoping accepts name and modified filters; Android accepts name. Android modified/recent paging remains unimplemented.
- Android manual text-only imports include PDF, PPTX, DOCX, XLSX, TXT, MD, CSV and TSV. Automatic phone scan is PDF-only. Office/plain-text parser JVM tests passed and instrumentation code compiled; no actual Android device execution was available.
- New imports can retain supplied modification time tied to source hash; older imports and unavailable metadata remain unknown. Scanner timestamps are used only for corresponding referenced sources. Android metadata work is compiled but not phone-tested.
- Reader return-position handling and superseded-search cancellation were added to shared UI. Android can cancel queued work and checks interruption during retrieval; native AI inference already running may finish, and Windows workers may continue after client disconnect. These behaviors are not device-verified.
- Additive database indexes and backward-compatible backup schema handling were added. A focused desktop old-backup restore/query-plan test passed. Android schema unit check and instrumentation compilation passed, but not device restore/query-plan tests.
- Prior focused checks: 41 desktop search/document tests, 37 desktop library/upgrade/organization tests, 15 frontend tests; a mocked browser check used 2,002 synthetic records. Focused later checks covered folder scope, filename API, source page, modification timestamp and server-side search filters. These are not proof of full release readiness.
- `results/filename-api-microbenchmark.json` and `results/library-browse-microbenchmark.json` are synthetic metadata/JS microbenchmarks only. Real corpus recall, device latency, memory, battery, thermal, and full 1,000–10,000-file tests remain unmeasured.

## Artifacts

- Last built and audited Android test APK: `C:\Users\Yash\Downloads\startup idea\output\Khoj-0.5.0-android.apk`, SHA-256 `ac0d65c981cc3f986be212d6459ebe9d2e46e556d5493febb1f81dcb63ee12ca`. It includes the catalog-decoupled UI and Android page metadata/name sort. It uses the local development signing key. Package audit is not phone testing; release lint still emits Kotlin metadata diagnostics.
- Desktop test bundle: `output/Local-Library-Desktop`; its `frontend/dist` contains the catalog-decoupled UI build and its `knowledge_library` copy includes the new page/state endpoints. It is not a newly built installer.
- APK release build reports success but emits Kotlin metadata 2.4 versus 2.1 compatibility diagnostics during lint. Investigate before public release; no on-device runtime proof exists.
- `docs/desktop-android-parity.md`, `docs/library-parity-progress.md` and `docs/superpowers/plans/2026-10-27-library-parity.md` record prior audit, progress and full workstreams. Treat them as potentially stale and verify source.

## Remaining substantial work

1. Finish the remaining paging gaps: Android modified/recent sorts and modified filters, lazy-catalog screens (Bills, Library tools, suggestions), and measured 1,000–10,000-document performance. Desktop name/type/modified ordering currently scans filtered metadata; add persisted sort keys or indexes if measurement shows it matters. Verify migrations and data preservation.
2. Implement an accessible light theme in addition to dark, and finish responsive Android/desktop reader and navigation details.
3. Develop and validate calibrated filename/content ranking and establish meaningful desktop/Android multilingual and financial retrieval parity without weakening existing desktop features.
4. Improve indexing/recovery, lifecycle, bulk-operation scalability, source metadata and missing-source handling. Never fabricate dates or source evidence.
5. Resolve Android Kotlin/lint diagnostics and build deliverables after the feature work. Obtain real Android hardware/emulator validation when available. The user plans broader functional testing; report missing evidence honestly.
6. Complete the requested parity/UX/ranking reports and real benchmarks where possible. Do not mark the persistent goal complete until all user requirements and evidence are met.

## Useful commands

PowerShell, from workspace. Node is bundled at `C:/Users/Yash/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe`.

- TypeScript: `& '<node path>' node_modules/typescript/bin/tsc -b` from `frontend`.
- Frontend build: `& '<node path>' node_modules/vite/bin/vite.js build` from `frontend`.
- Focused desktop tests: `.venv/Scripts/python.exe -m pytest <test> -q --basetemp .cache/<unique-name>`; local server/temp access previously required escalation.
- Android build: `python scripts/build_android.py assembleRelease --offline` (local Gradle daemon requires escalation). Then `python scripts/audit_android_apk.py --models full --apk output/Khoj-0.5.0-android.apk`.
- Android debug compile: `python scripts/build_android.py --update compileDebugJavaWithJavac --offline` (escalation).
- Keep the full mission and goal active; no subagents unless explicitly requested by the user or applicable instructions.
