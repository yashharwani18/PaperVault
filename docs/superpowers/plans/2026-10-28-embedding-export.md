# Android embedding export

User choice: export for PC analysis/testing, not PC app import. The earlier bill-quality work remains queued after this feature.

Implementation: add Settings > Export embeddings, using Android's save picker. Produce an unencrypted ZIP of document metadata, indexed pages/chunks, raw little-endian float32 vectors, model identity and checksums. Include committed, non-trashed data only; no originals, model weights, credentials or device paths. Require indexing to be idle, as existing backup does. Stream rows and vectors instead of loading the library into memory. Provide a standard-library Python reader for PC analysis.

- [x] Add a failing Android integration test for ZIP contents, vector round-trip, source mapping, exclusions and incomplete chunks.
- [x] Implement streamed export and save-picker action; stage the archive before writing to the chosen destination.
- [x] Add a clear Settings action, busy/cancel/error/success states and content disclosure.
- [x] Verify on the emulator, run Android unit tests, exercise the PC reader, build and audit the update APK.

Verification (26 October 2026 evening build, update variant):
- `EmbeddingExportTest` red first, then green (`results/android-export-red.log`, `results/android-export-test.log`).
- `tests/test_embedding_export_reader.py` passes (2 tests).
- The first update APK at 19:05 still carried the pre-change frontend bundle; rebuilt after the frontend build so the packaged `assets/index-BC81QmsL.js` contains the Settings action.
- `python scripts/audit_android_apk.py --models update --apk output/Khoj-0.5.0-android-update.apk` passes; report in `results/android-apk-update.json`.
- Emulator run: Settings > Export embeddings > save picker default `Khoj-embeddings-2026-10-28.zip` > success message in the app. The pulled ZIP verified with `python scripts/read_embedding_export.py`: 34 documents, 44 pages, 44 chunks, 44 vectors at 768 dimensions in one model group, zero chunks without vectors. Screenshots in `results/export-verify/`.

Constraints: preserve existing data and prior fixes. An exported embedding is useful only with its recorded model/recipe; this format is not a PC restore archive. Real user files remain untouched by tests.
