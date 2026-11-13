# PaperVault for Android

The Android preview runs indexing and search on the phone. The full APK bundles the models and OCR data. Initial indexing can take a long time on a phone. [Install the Android preview](../README.md#android-preview)

The build script writes the full APK to `output/Khoj-0.5.0-android.apk`. The signing key in `android/signing/` is needed to build an update that Android will accept over an existing installation. A separately signed build needs a fresh installation.

## Phone support and behavior

- Android 8.0/API 26 or newer, ARM64. The universal development build also includes an AVX2 x86-64 library for the test emulator. A current Android System WebView is needed for the shared UI/PDF viewer.
- On first launch, PaperVault copies the models to app storage and verifies their checksums. Allow about 3 GB free for the APK, installed assets, and working copies, plus space for your documents.
- One native model is resident at a time. Inference uses CPU, up to four available threads, bounded contexts and execution deadlines. Imports can be paused or restricted to charging. Foreground import work has an Android notification; interrupted tasks remain retryable.
- Use Android’s file picker to select PDFs, PPTX files, or folders. The optional whole-phone PDF scan requests all-files access. Imports accept up to 500 files, 100 MB each.
- PPTX imports text and table text in presentation order. Its PDF preview is explicitly a text preview, not a reproduction of original slide layout. Images/charts require checking the retained original deck. Legacy `.ppt` must be exported to `.pptx` or PDF.
- Scanned PDFs use bundled ML Kit Latin-script OCR. Recognition and field association remain reviewable. The observed `lnvoice` OCR spelling is an explicit label cue, never a digit correction; original text and coordinates are retained.
- Search supports local embeddings, constrained Qwen interpretation/source navigation, exact or nearby amounts, saved bill filters, review scope and source-page citations. Quantized mobile vectors have their own model/input identity; PC vectors/calibration are not silently reused.
- On-device speech recognition is used only through Android’s on-device API when available (Android 12+). Microphone permission is requested on tap. Transcripts remain editable before searching. There is no cloud speech fallback. Spoken accuracy is not verified.
- Android ZIP/encrypted backups use a separate format from PC backups. Restore verifies checksums and the known SQL schema, and imports into new collections while retaining existing documents. Encryption uses PBKDF2-HMAC-SHA256 and AES-256-GCM. Large encrypted-backup memory use remains to be profiled on a physical phone.

## Build

1. `python scripts/setup_android.py` installs workspace-local JDK 17, Gradle 8.11.1, Android SDK 35, NDK 28.2 and CMake 3.22.1, downloads the pinned model and llama.cpp sources, and records hashes in `.cache/android-tools/toolchain.json`.
2. Build the frontend with the project’s Node runtime and `tsc -b`, then `vite build` from `frontend/`.
3. `python scripts/build_android.py` builds/signs the APK and copies it to `output/`.

The build requires public dependency downloads; app use is offline. Source code and user documents are not sent to an online build service. Model identities are also recorded in the APK’s `offline-models.json` and `NOTICE.txt`.

## Tests

Run JVM tests with `python scripts/build_android.py testDebugUnitTest`. Device and emulator tests live in [app/src/androidTest](app/src/androidTest).
