# Android First Index Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Improve full offline Android indexing throughput while retaining compatible vectors and safe recovery.

**Architecture:** Add bounded independent-sequence inference alongside the scalar JNI API, then batch page/cache writes outside inference. Compare Arm KleidiAI builds independently and choose conservative defaults from measurements. Keep the existing staged-document publication path.

**Tech Stack:** Java 17, Android SQLite/PDFBox/MLKit, C++17 JNI, pinned llama.cpp b11714 and KleidiAI v1.31.0, Gradle/NDK28.

**Spec:** `docs/superpowers/specs/2026-10-25-android-first-index-performance-design.md` (user approved).

## Global Constraints

- Same bundled model bytes, prefixes, 900-character/80-overlap passage recipe, 512 tokens per passage, mean pooling, normalized 768 dimensions.
- At most four inputs and 2,048 aggregate tokens per inference batch; no cross-document batching.
- Preserve cache namespace only when scalar/batch equivalence passes (cosine >=0.99999, max absolute error <=0.0001).
- Never hold main-database transactions across OCR, inference or pause/power/search waits.
- Retain schema, old document index on failure, source hashes, no external PDF copies, offline/no INTERNET permission.
- Record physical ARM validation as unverified unless actually run; no extrapolated Moto timing claim.
- Existing workspace has no local Git metadata; preserve files/artifacts instead of initializing a repository or claiming commits.

## Review Focus

- Mixed cache hits, repeated text and long non-ASCII passages must preserve chunk order/offsets (Task 2).
- Different sequence lengths or order must never mix information between vectors (Task 1).
- Search/pause between batches must not leave a write transaction open (Task 2).
- Oversized input and failed batch allocation/inference must leave scalar inference usable (Task 1).
- Runtime feature fallback and new APK must retain compatible old indexes/backups (Tasks 3 and 4).

### Task 1: Independent native batch inference and measurement

**Files:** `android/app/src/main/cpp/models.cpp`, `android/app/src/main/java/org/localknowledge/library/NativeModels.java`, new `android/app/src/androidTest/java/org/localknowledge/library/EmbeddingBatchTest.java`.

**Interfaces:** Produce `NativeModels.embedBatch(String modelPath,String[] inputs): float[][]`, `tokenCount(String modelPath,String input): int`, and append batch/token counters to `performance(): long[]` without changing existing first-four fields. Preserve scalar `embed`.

- [x] Add reflection-based failing instrumentation coverage for missing batch API, preserving a scalar baseline report first. Compare mixed inputs/repeats/shuffling, empty/oversized batch, >512-token input and subsequent scalar recovery. Assert 768 finite unit floats and spec equivalence thresholds.
- [x] Run red tests on the current debug app: expected missing-method failure after scalar baseline report.
- [x] Implement a shared native embedding helper with validated independent sequence IDs, positions starting at zero, bounded reusable context capacity, checked output shapes and safe cleanup. Scalar path remains independent of batch API.
- [x] Run green tests and uncontended repeated scalar/batch capacities 1/2/4 measurements; record timings, tokens, CPU features and memory. Retain scalar production default if no batch clears the >=10% median target within memory/search constraints.

### Task 2: Page batching, short database transactions and progress

**Files:** new `android/app/src/main/java/org/localknowledge/library/PageIndexer.java`, modify `NativeBackend.java`, `KhojFeatures.java`, new `android/app/src/androidTest/java/org/localknowledge/library/PageIndexerTest.java`.

**Interfaces:** `PageIndexer` owns within-page chunk preparation, embedding/cache lookup and result mapping; accepts scalar/native batch adapter and checkpoint callback for tests. Keep `NativeBackend` responsible for document source checks and atomic final publication. Include generated-test aggregate extraction/embedding/database timings and existing diagnostic counters plus appended batches/tokens.

- [x] Write failing tests for exact legacy splitting/offsets, mixed cache hits, duplicate inputs, token-limit splitting, scalar fallback and throwing checkpoints with no active main/staging transaction.
- [x] Implement bounded work units, page-end flushes, short staging/cache transactions after inference and coalesced progress (ordinary same-stage writes at most once/second; forced transitions/completion). Preserve per-batch checkpointing.
- [x] Compare persisted chunks/pages/vectors against legacy scalar fixtures, cache-hit no-inference behavior and failures preserving old documents. Test pause/search/retry and large queue without external copies.
- [x] Benchmark full indexing (native short PDFs, OCR mix, long PDF), process PSS/database growth and searches during indexing. Retain measured defaults and record any unmet large-library/physical-device evidence explicitly.

### Task 3: Arm KleidiAI build and rollback configuration

**Files:** `android/app/src/main/cpp/CMakeLists.txt`, `android/app/build.gradle`, `scripts/build_android.py` as needed, `docs/KHOJ_ANDROID.md`.

**Interfaces:** Reproducible Gradle property `khojKleidiAI` enables ARM-only dependency, x86 remains off. Existing CPU dispatch/baseline fallback remains; pinned archive cached and verified. Keep KleidiAI-off configuration available.

- [x] Verify baseline build flag is off, then add ARM-only configurable integration to the pinned upstream dependency.
- [x] Build on/off configurations and inspect ARM instruction/backend/dependency packaging and 16KiB ELF alignment. Verify baseline feature detection stays portable and no model/schema/network changes.
- [x] Execute applicable regressions; document ARM-only correctness/throughput limitations rather than claiming an x86 comparison validates KleidiAI.

### Task 4: Review, release and proof

**Files:** Android versionCode, APK audit script, generated results, design/plan/ledger and Android documentation.

- [x] Run focused red/green proofs and full 13 JVM + existing Android regressions plus new batch/page-index tests on task-owned emulator fixtures.
- [x] Request fresh read-only whole-change review under requesting-code-review skill, address important findings and rerun affected checks.
- [x] Retain verified versionCode4 APK/checksum before publishing versionCode5 with same signing key/model hashes.
- [x] Build release, audit signature/model SHA/native variants/ELF16KiB/no-INTERNET/no-test-data, install over task emulator app, exercise exact release semantic search.
- [x] Save before/after evidence and limitations, then hand over one updated APK with install-over instructions. No false physical ARM performance claims.

## Execution ledger

- 2026-10-25: Design approved; executing natively within user's explicit implementation/benchmark authorization. Plan self-reviewed against spec. No further scope approval needed for routine implementation choices.
- Ruling: Existing project lacks local Git metadata; work in supplied workspace, no worktree/commit operations. Fresh review uses explicit changed files.
- Ruling: Page helper extraction is limited to chunk/embed/write responsibilities so native/document recovery stays in its current layer.

- Ruling: Multi-sequence native batches failed cosine/max-error compatibility and improved median emulator throughput only ~3%. Release default remains scalar; the bulk JNI API conservatively evaluates independent scalar sequences. Raw batching remains an explicit experimental CMake switch, off in release. Database write groups still contain up to four passages and checkpoint between scalar calls.
- Ruling: The first end-to-end fixture accidentally generated identical PDF bytes and exercised duplicate detection, not 24 independent documents. Discard that timing. Add unique visible fixture IDs; run the new test APK against the still-installed pre-integration debug app for a valid baseline, then install the integrated app.

- Evidence: `results/batch-compatibility.json` shows multi-sequence drift (up to ~0.0032 absolute element error). Conservative release API passes the strict scalar comparison; raw mode is not shipped.
- Evidence: valid 24-distinct-PDF baseline:56.14s total /46.28s native embeddings, after:58.26s total /45.97s native embeddings. Search during indexing differed2.53s vs5.99s and library size differed, so these single runs do not prove an end-to-end speedup. Added an isolated disk-write benchmark rather than attributing search/model-load variation to SQLite changes.
- Evidence: reviewed by fresh agent first_index_release_review; no important introduced production-path defect found. ARM feature eligibility is not proof of vector equivalence; physical KAI correctness and speed remain unverified.
- Evidence: `-PkhojKleidiAI=OFF assembleDebug` succeeds and its ARM library contains no KAI Q8 kernel marker; default-on debug build succeeds, ARM marker present, x86 marker absent.

- Evidence:1,000 distinct short native PDFs indexed in452.25s, peak app-process PSS799.8MiB,~12.5MiB database growth,zero source copying. Large-library search while another12PDFs indexed passed (3.30s search). A16-page PDF indexed in13.06s, using valid cache reuse for repeated passages. All16 Android regression tests passed in115.856s, plus13 JVM tests.

- Complete: signed build5 audit passed, required KAI notices included, raw native batching OFF, models unchanged, no Internet permission, all native ELF segments16KiB aligned. Exact release installed over existing emulator data and semantic search returned the expected source. Verified build4 APK/checksum retained under output/previous-android-v0.5-build4. See results/first-index-release-acceptance.json. Additional interruption coverage after cache commit and partial staging passed (3tests).
