# Khoj Android: faster first indexing with the existing engine

Status: approved by the user, 2026-10-25.

## Intent and agreed direction

The user selected direction 1: improve the current llama.cpp embedding pipeline, investigate Arm KleidiAI, and group SQLite writes. The triggering workload is 824 PDFs on a Moto Edge 50: mostly short documents with some image-only pages. Discovery is already fast; generating the first complete semantic index is the concern.

Keep Khoj offline, simple to use, and useful with full embeddings. Every searchable passage must have its embedding before a document finishes indexing. Scanned originals remain in place. An update must retain existing indexed work and compatible backups.

The six previously approved convenience additions and smaller update APKs remain queued. This design covers the performance work first, rather than silently including that separate feature batch. It does not implement a new runtime, PC-assisted indexing, cloud inference, or text-only readiness.

## Current implementation and evidence

- `NativeBackend.importTask` processes a document on a single indexing executor. PDF extraction invokes a page consumer; that consumer splits passages, embeds each uncached passage synchronously, and writes staging/cache/progress rows separately.
- Chunk boundaries are 900 UTF-16 characters with 80-character overlap, including the existing surrogate-boundary behavior and token-limit splitting. The native limit is 512 tokens per passage.
- Embedding input includes the filename-derived title. The cache key contains the model SHA and `embeddinggemma2-q8-mean512-v1` input recipe.
- `models.cpp` uses mean pooling, normalizes 768 output floats, reuses one embedding context, and clears its memory before each passage. Native inference is serialized by a mutex, including Qwen generation.
- The APK already includes runtime-selected ARM CPU variants and a portable fallback. `GGML_CPU_KLEIDIAI` is currently off. The pinned llama.cpp b11714 includes KleidiAI Q8 support and pins KleidiAI v1.31.0.
- Documents are assembled in a temporary staging database, then published in a main-database transaction. Source hash/version checks protect existing entries. Pause, charging-only operation, and search priority are checked between work units.
- Previous emulator evidence: eight warm embeddings took approximately 2.70 seconds both before and after context reuse. The earlier OCR fix reduced an eight-page text-and-logo extraction fixture from 21.1 seconds to 0.263 seconds. Neither is physical Moto performance evidence.

## Approaches considered

1. **Optimize the existing engine (selected).** Bounded embedding batches, KleidiAI investigation, and grouped database writes. Preserves the current model and avoids an index migration, provided vector compatibility passes.
2. **Replace inference with LiteRT-LM.** A mobile-oriented runtime with accelerator options, but requires model-format/runtime integration and renewed embedding compatibility validation. Not selected for this release.
3. **Let a PC prepare a compatible phone index.** Potentially useful optional acceleration, but requires a new authenticated/local transfer design and exact model/recipe matching. Not selected for this release.

The user chose option 1 because it directly addresses the current bottleneck with less product change.

## Required behavior

- Preserve the model bytes, task/title formatting, tokenization, pooling, normalization, chunk order/offsets, highlighted-page evidence, and the existing cache namespace unless compatibility fails.
- Never concatenate independent passages into one embedding. Batched inputs use independent sequence IDs and return one vector per input in the same order.
- Preserve partial/final status handling, OCR behavior, duplicate handling, reference-source validation, backup schema, retry behavior, and managed-import behavior.
- Search and pause can preempt indexing between bounded batches. Do not run many concurrent model instances or load all documents into memory.
- Existing valid cache hits require no inference. New vectors are published only after complete validation of that inference result.

## Proposed implementation

### 1. Bounded native embedding batches

Add a native batch API alongside the scalar API. It accepts up to four passage strings, each at most 512 tokens, and returns one 768-dimensional normalized vector per passage. The scalar entry point stays available for queries, compatibility, baseline tests, and controlled fallback.

Benchmark capacities 1, 2, and 4; the production capacity is a builder-selected measured value, not an assumed speedup. Configure sequence count, per-sequence context, logical batch, and physical microbatch consistently with the pinned llama.cpp API. A maximum-four batch contains at most 2,048 tokens. Each sequence starts at position zero and is isolated from the others. Clear sequence memory before every invocation. Reuse the selected context where practical; do not accumulate scalar and batch contexts unnecessarily.

Retain the existing per-passage token-limit splitting before batching, including the current resulting offsets and overlap. Reject invalid output cardinality, dimensions, non-finite values, or zero norms. Return no partial batch as a successful result. For supported allocation/inference failures, clear the failed context and retry affected inputs through the proven scalar path; unrecoverable native/process failures use the existing interrupted-job recovery. The scalar path must be independently callable and not recursively call the failed batch route.

Initially collect uncached passages within a page, flush at capacity and at page end, and map results back to the existing staged chunk order. This bounds text/evidence retention and permits frequent checkpoints. Cross-document batching and concurrent OCR/extraction are deferred: they complicate recovery and CPU contention and require separate evidence.

### 2. Arm KleidiAI

Build KleidiAI only for ARM64; keep it off for x86-64. Use the dependency version already pinned by the current llama.cpp tree, verify/cache its source archive, and make subsequent builds reuse that verified dependency. Do not replace the pinned llama.cpp revision merely to obtain unrelated changes.

Keep the existing runtime CPU dispatch and portable fallback. Let upstream tensor/shape/CPU eligibility determine when KleidiAI applies. Verify packaged dependencies, CPU-feature detection, 16 KiB ELF alignment, and the absence of a new Internet permission. No GPU requirement or model download is introduced.

Maintain a reproducible KleidiAI-off build configuration for comparison/rollback. Packaging and static inspection alone do not prove ARM correctness or speed. An APK may be produced using upstream runtime eligibility after the applicable build/audit tests pass, but physical ARM correctness/performance remains explicitly unverified unless actually executed. Do not claim a Moto speedup from x86 emulator results. If available device evidence shows a correctness or performance regression, retain KleidiAI-off as the default.

### 3. Group database writes without weakening recovery

Collect a small result set outside write transactions. Insert page/chunk staging rows in short explicit transactions rather than one commit per row. Group newly computed cache entries in short main-database transactions. Batch writes must not hold a main-database write transaction while OCR, inference, pause waits, or charging waits execute.

Coalesce repetitive progress updates on a short bounded interval, retaining immediate task start, stage transitions, pause/wait state reporting where applicable, and final completed/failed status. Checkpoint checks still occur before inference batches even when no progress row is written.

Keep the final document-publish transaction and original hash/version checks. Preserve the current SQLite synchronization/durability settings. Do not introduce a database schema migration or relax synchronization for a speed claim. Cache entries committed before interruption can be reused on retry; an incomplete staging database never replaces the old document index.

### 4. Measurement and diagnostics

Extend allowlisted counters to distinguish completed passages, inference batches, token count, embedding time, and context/model loads. Report aggregate timing for extraction/OCR, embedding, and database work in generated test results; avoid document contents, filenames, paths, or search text in exported diagnostics. Retain existing diagnostic field meanings or add explicit versioned fields.

## Verification and acceptance

1. Establish reproducible scalar/current-write baselines before implementation. Separate cold model preparation from warm throughput. Do not compile concurrently with timing runs. Use repeated runs and report dispersion, input sizes, CPU backend, and device/emulator identity.
2. Batch equivalence: compare each batched vector to its scalar equivalent, including mixed lengths, shuffled order, repeated inputs, non-ASCII text, maximum-length inputs, and different preceding batches. Require finite 768-dimensional unit vectors, cosine similarity at least 0.99999, and maximum absolute element error at most 0.0001. A failing comparison blocks cache-compatible deployment; do not silently change the recipe/model to pass.
3. Functional retrieval: preserve existing topic ordering, exact/semantic search behavior, source highlights, amount grounding, and representative retrieval ranking with cached old vectors mixed with newly computed vectors. Treat near-ties separately from meaningful relevance regressions.
4. Recovery: interrupt before/during staging and publication; test explicit pause/resume, search during indexing, source changes, failed batch fallback, repeated scans, missing references, and retry without duplicate PDF copies or lost old indexes.
5. Database proof: compare staged page/chunk contents and vectors to the scalar path; verify cache-hit behavior, atomic replacement, unchanged schema, and backup/restore compatibility.
6. Throughput: time both batch-only embeddings and complete indexing of generated short native PDFs, mixed native/OCR documents, and a long document. Add a large-library/queued-job run while searching. Record passages/sec, end-to-end elapsed time, search latency, process memory, database/storage growth, and batch size. Account for WebView/system memory exclusions.
7. Select a batch setting only if repeated warm measurements show a meaningful improvement (proposed target: at least 10% median throughput improvement outside observed run variation) without degrading correctness or search responsiveness. A RAM increase above 128 MiB relative to the same-device scalar baseline is grounds to lower the capacity or retain scalar mode. These thresholds are builder proposals, not prior user requirements. If none qualifies, report that result and retain scalar defaults; still evaluate the database optimization independently.
8. Run existing JVM/instrumentation regressions, release shrinking, signing/model-hash/native-library/16 KiB/no-test-data audits, and installation plus semantic search on the exact release APK. Physical Moto throughput is reported only if measured on that phone.

## Release and rollback

Retain Khoj v0.5 branding, package name, signing key, and bundled model hashes. Increment Android versionCode from 4 for a distributed update. Preserve the currently verified APK and checksum as a rollback reference; ordinary Android version downgrades are not presented as a guaranteed in-place recovery method. Keep the scalar/native build switch so a subsequent higher-version update can restore the old engine behavior without deleting user data.

The user-facing result is faster first indexing where measured, with the same search-first interface and full semantic index. Release notes distinguish measured improvements from unverified ARM expectations. The previous 30–90-minute estimate is not an acceptance threshold or a benchmark claim.

## Decisions left to the builder

Choose the smallest helper/API boundaries, bounded progress interval (initial proposal: at most one ordinary write per second), context capacity selected by the benchmarks, generated fixture mix, and exact instrumentation layout. Resolve pinned llama.cpp parameter details through its local headers/examples and tests. Do not expand into the separate feature backlog, a new model/prefix, or a new runtime without returning to the user.

## Resources checked

- llama.cpp batched embedding example: https://github.com/ggml-org/llama.cpp/blob/master/examples/embedding/embedding.cpp
- Arm KleidiAI integration: https://learn.arm.com/learning-paths/mobile-graphics-and-gaming/performance_llama_cpp_sme2/kleidiai_integration/
- Android SQLite transaction batching: https://developer.android.com/topic/performance/sqlite-performance-best-practices#batch-multiple-insertions-in-a-single-transaction
- Google LiteRT-LM embedding alternative: https://developers.google.com/edge/litert-lm/embedding_models

This workspace currently has no local `.git` entry, so the design is saved as a file rather than committed. Do not initialize a repository or alter unrelated repository state to satisfy documentation bookkeeping.
