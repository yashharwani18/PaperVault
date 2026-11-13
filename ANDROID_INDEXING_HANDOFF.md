# Handoff: Android indexing takes too long

## Problem and goal

The user installed Khoj on their dad's **iQOO 9 SE**, which has approximately **800 PDFs**, and reported indexing taking **24 hours**. It is still unclear whether this is actual elapsed time or Khoj's remaining-time estimate. Total pages, typical file size, scanned-page share, completed count, and screen-on versus screen-off behavior are unknown.

Investigate and improve **actual indexing throughput** while preserving extraction completeness and search quality. The user explicitly rejected making text searchable first while semantic indexing continues as a workaround for this task. Do not substitute that approach for fixing indexing.

The reported physical-phone issue is **not yet resolved or reproduced**. Do not describe build 10 as fixing the 24-hour run.

## Workspace and constraints

- Workspace: `C:\Users\Yash\Downloads\startup idea`, PowerShell, local Android toolchain and model files already available.
- User has limited remaining usage and wants concise, focused work. They initially prohibited tests, then explicitly authorized a quick verification. Eight focused instrumentation checks have now been run; avoid broad suites and repeated builds without a concrete reason.
- Deliver **full rebuilt APKs with both models**, retaining the existing signing key. Do not deliver model-free update APKs. Install over the existing app; do not instruct the user to uninstall or clear data.
- Product scope: PDFs and text search; Android currently imports PDF/PPTX. Voice input was added in build 9 and should be preserved.
- Do not run synthetic imports against the user's real Windows library. Tests belong in isolated fixtures or the task-owned emulator and must clean up their own data.
- No usable Git checkout was available during this work. Preserve unrelated edits.

## Current delivered artifact

`output/Khoj-0.5.0-android.apk`, versionName 0.5.0, now **versionCode 12**, approximately 786.7 MiB. Full release compilation and package audit passed (the audit now reads versions from `android/app/build.gradle`, no more hardcodes). Product source changed twice since build 10: the semantic-search scan tightening (see `results/ANDROID_SEARCH_SCAN_BUILD11.md`) and the zero-setup battery-optimization ask (see `results/ANDROID_BATTERY_SETUP_BUILD12.md`). The 9 previously-run focused checks plus `SearchLatencyTest` passed on both changes on the task-owned emulator. Both bundled model hashes and the retained local development signing certificate were re-verified. Khoj has no INTERNET permission. Install over the existing app; do not uninstall or clear data.

Earlier packaging evidence for build 10 stays in `results/android-indexing-build10*.log` but is superseded: build 12 is the artifact to hand out, and the 24-hour physical-phone report remains unexplained and unresolved by any build so far.

## Relevant code and confirmed mechanisms

### Embedding and chunking

- `android/app/src/main/java/org/localknowledge/library/PageIndexer.java`: chunks are up to 900 UTF-16 characters, with 80-character overlap; passages exceeding 512 model tokens are split further. Page-local staging capacity is four. Embeddings are normalized, 768-dimensional vectors.
- `NativeBackend.java`, import consumer: the Engine's `batch` implementation loops through scalar `NativeModels.embed` calls, with checkpoints between passages. Thus the four-item staging window is not true batched inference.
- `android/app/src/main/cpp/models.cpp`: a global mutex protects the model/context. CPU inference uses at most four threads, no GPU layers, an MMAP-loaded model, and a reused embedding context. Model changes replace the single resident model.
- Native multi-sequence inference remains disabled by `KHOJ_EXPERIMENTAL_NATIVE_BATCHES=OFF` in `android/app/build.gradle`. The source records that earlier multi-sequence Q8 inference failed the vector/cache-compatibility gate. **Do not simply enable it and assume correctness.**
- Embedding model: bundled `embeddinggemma-2-q8.gguf`, approximately 310 MB. Qwen 0.6B is also bundled, but ordinary search no longer uses it to choose citations; that earlier search model-switching issue was fixed before build 10.
- ARM runtime variants and KleidiAI kernels are compiled. Actual optimized-kernel selection and sustained execution on this physical iQOO have not been verified.

### PDF extraction — changed in build 10

Previously `DocumentReader.pdf` created a PDFTextStripper for each page and called `getText(doc)` with start/end page bounds. Inspection of the installed PDFBox bytecode confirmed that each call iterates the document page tree.

Build 10 changes `DocumentReader.Stripper` to traverse the document once and stream pages to the existing OCR/indexing consumer. It keeps one page of text buffered, preserves blank-page numbering and word boxes, and retains the existing OCR decision. A `PageFailure` wrapper propagates checked callback errors; runtime exceptions, including Skip, propagate directly.

OCR still runs when explicitly forced, or when OCR is enabled and a page has XObjects with fewer than 40 extracted alphanumeric characters. Rendering is capped at six million pixels, up to 200 DPI; ML Kit recognition can wait up to 60 seconds per page. We have not established whether OCR is a significant fraction of the dad's workload.

### Tokenization — changed in build 10

Previously an uncached passage was tokenized for its length check and again during embedding. A bounded eight-entry native cache now reuses exact token IDs. It clears on model changes and explicit `NativeModels.release`. Chunk boundaries, model, normalization, and vector/cache recipe remain unchanged.

This eliminates redundant tokenizer work but does not reduce the neural inference needed for each passage.

### Screen-off processing — changed in build 10

`ImportService.java` previously had no explicit CPU wake lock. It now holds a non-reference-counted PARTIAL_WAKE_LOCK tagged `Khoj:Indexing` while runnable work exists. Each acquisition expires after ten minutes and is renewed after five minutes. It releases on pause, charging-only power waits, idle work state, Android service timeout, and service destruction. WAKE_LOCK is now explicit in the manifest.

This addresses CPU suspension; it does **not** prove survival of OEM process termination, override Android service limits/Doze restrictions, or establish physical-phone throughput.

### Queue, cancellation, and ETA

- Imports use a single-thread executor. `PhoneScan.pump` checks every second and keeps up to twelve queued/running/skipping tasks.
- Checkpoints pause for user pause, charging-only restrictions, and active searches. Skip must continue to work while paused, preserve the previously published document on replacement, and prevent publishing skipped staging data.
- Phone-scan ETA currently extrapolates average **per-file** active time after only three newly completed files. It does not normalize for page count or scanned-page workload. A misleading estimate is possible, but is not established as the explanation here.
- Build 10 did not alter this ETA or the queue publication model.

## Actual measurements — important limits

Evidence: `results/android-indexing-build10-tests.log`, `results/android-indexing-build10-measurements.json`, `results/ANDROID_INDEXING_BUILD10.md`.

Device was the task-owned Android 15 **x86_64 emulator**, two vCPUs and 3 GiB RAM, not the dad's phone.

1. **Extraction before/after:** the same generated 160-page PDF, including blank pages, was read through the legacy per-page path and new streaming path. Three alternating timed pairs gave:
   - Legacy median: **280.9028 ms**.
   - New median: **271.4572 ms**.
   - Approximately **1.035x throughput**, or **3.4% less time**. This is small and has no statistical significance established from only three pairs.
   - Extracted text, source page numbers, and word boxes matched exactly on that fixture.
   - This was an **extraction component benchmark**, not complete before/after library indexing. It does not justify a major speedup claim.
2. **Token cache:** cached-token embedding vectors matched a fresh model context within 1e-5. A tokenizer-only microbenchmark showed cheaper cache hits. Uncached inputs had a short unique suffix; those timings must not be presented as total indexing speedup.
3. **Wake lock:** Android `dumpsys power` confirmed acquisition during active work, release on pause, and release on service stop. No physical screen-off throughput test was performed.
4. **Eight instrumentation tests passed:** three `IndexingBuild10Test` checks plus five existing `IndexSkipTest` checks.

The first quick test attempt failed because the legacy comparison harness initialized PDFBox resources too late, poisoning the font class initializer and causing a subsequent Skip test to fail. The harness was corrected to initialize DocumentReader before the legacy reader, then all eight tests passed in a fresh instrumentation run. No production fix was required for that harness failure.

Historical evidence, **not a current before/after comparison**: `results/first-index-long-pdf.json` measured 16 pages and 18 passages in approximately 13.06 seconds, of which 10.51 seconds were reported as native embedding time. This points toward inference as a candidate bottleneck, but does not diagnose the physical phone. `results/first-index-performance-summary.json` explicitly states that whole-pipeline speedup was not proven.

The user was told plainly: build 10 helps a little in the extraction fixture, and does not establish a fix for the 24-hour report. Do not revert to stronger claims.

## Recommended next investigation

1. Get minimal real-device evidence: actual elapsed versus estimated time, completed files/pages, active stage, a representative file's pages/chunks, whether progress stalls with the screen off, and whether Android reports interruptions. Avoid guessing from the count of 800 files.
2. Measure end-to-end time and stage breakdown on a small representative sample from that phone: extraction, OCR, tokenization, native embedding, SQLite/cache writes, model/context reload count, and pauses. Keep sensitive content out of logs. Existing `NativeModels.performance()` exposes embedding calls, embedding microseconds, context creations, model loads, batches, and tokens; import results include embedding/database timing, but timing scopes should be inspected before interpreting them.
3. Verify the ARM backend and optimized kernel actually selected at runtime. Check sustained throughput and thermal/memory-pressure behavior before changing thread counts or model size.
4. Focus inference optimization on correctness-preserving changes. True batching needs repair and comparison against the scalar vector baseline, with cache compatibility and search-quality checks. A different quantization/model would need an explicit vector migration and quality evaluation; do not silently mix incompatible vectors.
5. Investigate repeated model eviction from memory-pressure callbacks and OCR-heavy outliers only if measurements support them. The existing `LibraryApplication.onTrimMemory` schedules `NativeModels.release` at low-memory levels; whether this happens frequently on the phone is unknown.

Do not promise a completion time, reduce indexed coverage silently, or call the issue fixed based on emulator extraction timings.

## Real-device evidence tooling (added after the failed 2026-10-26 session)

The delivered APK was not rebuilt and no product code changed in that session. Two new helpers exist for handoff item 1, not yet run against the physical phone:

- `docs/PHONE_INDEXING_EVIDENCE.md`: minimal capture plan. Three questions to ask the phone user first (estimate vs wall time, screen/charger state, progress pattern), then the in-app `Khoj-support-report.json` (its own disclosure excludes document contents, filenames, paths, searches, raw errors).
- `scripts/collect_khoj_phone_diagnostics.ps1`: bounded ADB captures only (device identity, CPU layout, power/wake-locks, battery, thermals, service/exit-info history, package version, filtered logcat tails). Validated for the no-device path, exit 1; not yet run against a real device. Output lands in `results/phone-diagnostics/<timestamp>/`.

The captured data is the decision input for handoff items 2 through 5; do not start inference/batching changes before it exists.

## Commands and test environment

Toolchain configuration: `.cache/android-tools/toolchain.json`. Python: `.venv/Scripts/python.exe`. ADB: `.cache/android-tools/sdk/platform-tools/adb.exe`.

```powershell
# Full release, retaining both models and signing key
.venv/Scripts/python.exe scripts/build_android.py
.venv/Scripts/python.exe scripts/audit_android_apk.py --models full

# Focused debug/test APK build
.venv/Scripts/python.exe scripts/build_android.py assembleDebug assembleDebugAndroidTest

# Task-owned emulator (currently stopped after verification)
.venv/Scripts/python.exe scripts/start_android_emulator.py

# After installing debug and test APKs on emulator-5580
& .cache/android-tools/sdk/platform-tools/adb.exe -s emulator-5580 shell am instrument -w -r -e class org.localknowledge.library.IndexingBuild10Test,org.localknowledge.library.IndexSkipTest org.localknowledge.library.test/androidx.test.runner.AndroidJUnitRunner
```

Android toolchain and emulator operations previously required elevated sandbox execution. Use the workspace explicitly. Tests create task-owned fixtures; the benchmark files are deleted and the wake-lock test task is removed in cleanup. The emulator was stopped with `emu kill` after collecting results.
