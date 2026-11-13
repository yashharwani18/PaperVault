# Khoj v0.5 for Android

Standalone artifact: `output/Khoj-0.5.0-android.apk` (approximately 805 MiB). The single APK includes the native backend, shared search-first interface, PDF/PPTX support, bundled OCR, 768-dimensional EmbeddingGemma text encoder and Qwen3 0.6B. No desktop computer, Python installation, model download or companion file is required.

Android 8.0/API 26 or newer is declared, with ARM64 and x86-64 native libraries. Budget at least 2 GB free storage for the APK and extracted models, plus space for imported documents. Physical-phone performance has not been validated. This build uses CPU inference; desktop CUDA selection does not apply to Android.

Install by opening the APK on the phone and approving installation from that file source if Android asks. The app label is Khoj, version 0.5.0 (public v0.5), versionCode 3. The existing package ID and local signing key are retained so the previous Android preview can be upgraded without uninstalling its data.

## Android behavior

- First-run Find PDFs on this phone opens Android's all-files-access settings (Android 11+) or asks for legacy read permission (Android 8–10). After consent, Khoj discovers PDFs across accessible shared storage, Downloads/Documents, messaging-media folders and available SD cards. Android/data and Android/obb remain excluded. Scanned originals are indexed in place without copying; manual PDF/PPTX imports still use the system picker and retain their own managed copy. The 500-file limit applies only to manual folder imports, not phone-wide discovery.
- Search shows original page previews with literal matched words highlighted, plus the continuous PDF reader. Technical scores remain under Search details. Preview bitmaps have bounded dimensions and are not written to disk. Native rotated pages suppress exact highlights rather than showing boxes in an unverified position.
- Custom topics, renamed topics, manual classifications, display names, bulk moves and guarded Undo persist locally. Every file has a subject or Miscellaneous. Known organization settings are remapped when restoring Android backups.
- Failed/interrupted jobs have recovery actions; startup resumes interrupted imports. Retrying a retained original reuses it rather than truncating or copying over its input.
- Settings includes Android-specific privacy/update text. Support reports use Android's save picker, include only allowlisted system information and counts, and exclude document contents, names, paths, searches and raw errors. No cloud model control is offered because this APK has no Internet permission.

## Build and verification

`scripts/build_android.py` defaults to `assembleRelease`; `scripts/audit_android_apk.py` verifies/publishes the release artifact and checksum.

- Release build: successful, R8 shrinking/obfuscation and resource shrinking enabled, non-debuggable. Native JNI entry points and JavaScript bridge annotations are retained. PDFBox's optional JPEG-2000 codec is not bundled.
- APK audit: signature verified, 16 KiB alignment passed, both bundled model hashes verified, ARM64/x86-64 libraries present, no Internet permission, no test PDFs/databases in the APK. See `results/android-apk.json`.
- Android instrumentation: **6 tests passed** on the task-owned Android 15 x86-64 emulator with 3 GiB RAM. Covers real model inference, PDF/PPTX, bundled OCR, source-grounded search, backup/encryption, organization/privacy, safe cached retries and rotated-highlight fallback. See `results/phone-scan-instrumentation.log`.
- Android interface acceptance: passed; highlighted preview, hidden scores, no horizontal overflow and continuous PDF viewer. See `results/android-ui.json` and `results/android-qa/`.
- Exact release APK installed and opened on the emulator; version 0.5.0/versionCode 3 and non-debuggable package flags verified. See `results/khoj-android-release-ui.xml` and `results/khoj-android-release-acceptance.json`.
- Desktop regression suite after shared-interface changes: **23 passed**, `results/khoj-android-desktop-regression.log`.

This is a private test distribution signed with the project's local development key, not a Google Play production release. It has not been tested on a physical ARM64 phone. R8/native compilation raises inspection effort but cannot prevent determined reverse engineering.

The Windows distribution also finished as one self-contained file: `output/Library-Installer/Khoj-Setup-0.5.0.exe`, 3,567,920,552 bytes. Matching `.bin` files are no longer required; the former split build is archived separately.

## Phone-wide scan verification

The rebuilt v0.5 APK (versionCode 3) passed six emulator instrumentation tests, including reference indexing without source copies, unchanged rescans, moved originals and edits to duplicate PDFs. The Android all-files permission screen was exercised directly, along with pause/resume and discovery of a newly created PDF in Downloads outside any selected test folder. Managed-PDF byte totals stayed unchanged. See `results/phone-scan-ui.json`, `results/phone-scan-ui/scan.png`, `results/phone-scan-android-build.log` and `results/phone-scan-desktop-regression.log` (23 desktop regression tests passed).

Discovery runs separately from bounded indexing (up to 12 pending tasks). The persistent registry skips unchanged files, retains missing-source metadata, and supports explicit rescans/retries. Interrupted discovery and indexing recover after reopening when access remains available. New files can be found with Scan again; no always-running background monitoring is claimed. Permission can be revoked in Android settings. Phone-scan originals are included in a backup only when the user explicitly requests that backup; safe archive paths are used and restored files become managed copies.

Android privacy limitation: even all-files access cannot read other apps' private storage. Official reference: https://developer.android.com/training/data-storage/manage-all-files . A Google Play release requires the relevant all-files-access review; this remains a locally signed private test build.

## Android indexing performance update (versionCode 4)

This update keeps the same bundled EmbeddingGemma model, 768-dimensional normalized vectors, passage boundaries, and cache recipe. Every searchable passage is still embedded before a document finishes indexing. Existing indexes and backups remain compatible; no database schema change was needed. Install over the existing app with the same signing key.

- ARM64 now ships runtime-selected ggml CPU variants: portable ARMv8 fallback, dot-product, FP16, I8MM and newer supported combinations. Feature scoring uses the operating system's hardware capabilities before selecting a backend. Native libraries are extracted to Android's trusted nativeLibraryDir so dispatch can discover them. Both debug and release native builds use -O3.
- Reuse one embedding context while its model is loaded; clear sequence memory between passages and free the context before switching models or releasing memory. Fresh/reused vectors and intervening-input isolation are tested; ten passages create one context.
- Automatic OCR now applies to sparse image pages rather than every page containing a logo/image. Explicit Re-read with OCR still forces OCR, including selectable-text pages; image-only OCR is covered separately. The existing tasks.ocr integer stores off/automatic/forced modes without adding a column.
- Exported diagnostics include CPU feature information and process-scoped embedding counts, elapsed inference time, context creation and model loads, without document contents or paths.

Verification: 13 JVM unit tests and all nine Android instrumentation tests passed. The full instrumentation run used clean task-owned emulator data because repeated backup tests multiply their synthetic documents. Repeated scan fixtures now have unique contents to avoid deduplicating against older fixtures. Backup/restore, semantic ranking, image-only OCR, explicit OCR, organization, privacy and in-place scanning pass. See results/indexing-clean-instrumentation.log and results/indexing-release-o3-build.log.

An isolated Android 15 x86-64 emulator measurement reduced eight readable-text pages with logos from 21,110 ms (eight unnecessary OCR passes) to 263 ms (zero OCR passes). Eight warm embeddings measured 2720 ms against 2,701 ms before: essentially unchanged on x86, so no embedding-throughput speedup is claimed from this measurement. Cold model-load comparisons are cache-sensitive and are not treated as proof. See results/indexing-speed-reader-before.json, results/indexing-speed-reader-after.json and results/indexing-speed-embedding-after.json.

Release ARM disassembly confirms zero SDOT/SMMLA instructions in the portable fallback, 989 SDOT instructions in the dot-product variant, and 260 SMMLA instructions in the I8MM variant (results/indexing-arm-kernels.json). This verifies packaging/code generation, not physical-phone throughput. Moto Edge 50 / physical ARM64 performance remains to be measured.

The release audit verifies the signature, versionCode 4, model hashes, no Internet permission, all required shared libraries/CPU variants, 16 KiB ELF segment alignment and APK alignment. See results/indexing-final-apk-audit.log and results/android-apk.json.

The exact signed non-debuggable versionCode 4 APK was installed over the emulator app, opened, and returned the expected semantic source for regular languages. See results/indexing-release-acceptance.json and results/indexing-release-search-ui.xml.

## First-index engine work (versionCode 5)

The current work adds short grouped cache/staging transactions, up to four pending passages per page, coalesced ordinary progress writes, token-limit preflight and cache-output validation. The existing final document transaction, source/version checks, schema and model/cache recipe remain. Scanned PDFs stay in place. Every passage is embedded before completion; there is no lexical-only readiness mode.

Multi-sequence native inference was tested and rejected as the release default: in the fixed emulator sample, batch4 median was1,675ms versus1,719ms scalar (about2.5% faster), while some vectors differed by up to0.0032 per element and cosine fell to0.99976, outside the design's0.0001/0.99999 gate. Release builds therefore keep independent scalar inference and checkpoint between calls; the bounded bulk JNI API conservatively executes scalar inputs. Raw native batching remains a deliberately disabled experiment, and the APK audit rejects builds reporting that experiment enabled.

Arm KleidiAI v1.31.0 is built only for ARM64, using upstream runtime CPU/tensor eligibility and the upstream pinned archive hash. X86 does not include it. Disable it reproducibly with `scripts/build_android.py -PkhojKleidiAI=OFF assembleDebug`; that fallback build passed and its ARM library contains no KleidiAI Q8 marker. Upstream feature/shape checks establish eligibility, not numerical compatibility with old vectors. Physical ARM/KleidiAI numerical correctness and throughput remain unverified, and no Moto speedup is claimed. License/copyright texts ship in assets/KLEIDIAI-LICENSES.txt.

The distinct24-PDF emulator workload measured56.14s before and58.26s after, with native embedding time46.28s versus45.97s. The search during indexing took2.53s versus5.99s, and the accumulated test library differed. These single end-to-end runs do not establish a throughput improvement; generated fixtures and model/search variation are disclosed rather than hidden. An earlier7.4s run accidentally exercised duplicate-PDF detection and is explicitly discarded. See results/first-index-unique-before.json and results/first-index-after.json.

Independent correctness tests cover scalar/bulk vector equivalence in the conservative build, input order, repetition, Unicode, invalid batches and recovery, exact passage offsets, mixed/malformed cache entries, token-limit splitting, failed-batch fallback, blank pages and interruption with no open write transaction. See results/first-index-integrated-tests.log. Final large-queue, regression and release evidence is appended after verification.

Isolated on-disk persistence benchmark:60 pages/300 chunks, three rounds, identical saved text/offsets/vector blobs. Median legacy per-row writes:4400ms; grouped writes:1698ms (2.59x faster for this database work, not overall inference). See results/database-batch-benchmark.json.

Large-queue proof:1,000 distinct short generated native PDFs (about150 body characters plus unique fixture headers each), all indexed in 452.2s on the task-owned Android15 x86-64 emulator. Completed passage count includes1,000 document vectors plus one search vector. Peak app-process PSS:799.8MiB; database growth:12.53MiB; managed-source growth:zero bytes. One semantic search during this run took4.79s. This workload is not representative of long/scanned PDFs or a measured Moto speedup. See results/first-index-thousand.json and results/first-index-thousand-test.log.

Final correctness suite:16 Android instrumentation tests passed in115.856s on clean task-owned emulator app data, alongside13 JVM tests. See results/first-index-final-regression.log. Search during an additional12-file indexing run against the accumulated1,000-plus-document library took3.30s; a16-page generated PDF indexed successfully in13.06s, including safe cache reuse for repeated passages. See results/first-index-large-library-search.json and results/first-index-long-pdf.json.

Release verification complete:versionCode5, same signing key and model hashes, non-debuggable/R8-shrunk, no Internet permission, required KleidiAI notices and ARM kernels present,16KiB native segment/APK alignment passed. The exact output/Khoj-0.5.0-android.apk installed over existing emulator app data and returned the expected semantic source. See results/first-index-release-audit.log, results/android-apk.json and results/first-index-release-acceptance.json. Additional recovery tests at interruption before persistence, after cache commit, and after partial staging all passed (results/first-index-interruption-final.log). The prior verified build4 artifact/checksum/audit is retained in output/previous-android-v0.5-build4.

This is the approved direction1 performance phase; the six convenience additions and smaller update packaging are still queued. Physical Moto/ARM execution and numerical/performance validation of KleidiAI remain unverified.
