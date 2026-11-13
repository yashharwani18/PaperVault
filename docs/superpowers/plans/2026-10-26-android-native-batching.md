# Android chunk correctness and native batching

Scope: repair page chunk coverage, activate bounded cross-page batches, preserve scalar vector compatibility, and deliver a full signed APK. No Vulkan or automatic library reindexing.

1. Reproduce current chunk/test failures and scalar batch execution. Evidence: `results/batch-current-red-tests.log`.
2. Replace capped-character segmentation and swallowed tokenizer errors with token-measured page/paragraph boundaries, bounded overlap, UTF-16-safe source offsets, and guaranteed new coverage. Native token counting must accept large pages without allocating oversized inference inputs.
3. Buffer at most four passages across pages. Persist page rows in staging, flush the remaining passages before publication, and preserve Skip and transaction checks.
4. Diagnose scalar/batch numerical differences using the pinned native backend and real model. Verify mixed lengths, permutations, repeats, norms, cache compatibility, and ranking. Keep incompatible groups on scalar inference rather than weakening the compatibility threshold.
5. Enable the native call in Java and release configuration only after parity checks. Protect untested ARM kernels with per-model runtime qualification and scalar fallback.
6. Run focused indexing, batching, and Skip checks; record component and end-to-end timing separately. Build and audit the full release with the retained key and both models. Do not claim physical-phone speedup from emulator results.
