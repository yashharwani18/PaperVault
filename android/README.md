# Standalone offline Android preview

Built locally on 22 October 2026. The APK contains the UI, native processing libraries, bundled Latin-script OCR, Qwen3 0.6B Q4_K_M and the EmbeddingGemma 2 Q8_0 text encoder. It does not connect to the PC backend or download models at runtime. The merged application manifest removes INTERNET permission.

The installable development APK is copied to `output/Local-Library-offline.apk`. It is a private testing build, signed with the project’s local development key in `android/signing/`, which must be retained for compatible updates. The key and build/model caches are ignored by version control.

## Phone support and behavior

- Android 8.0/API 26 or newer, ARM64. The universal development build also includes an AVX2 x86-64 library for the test emulator. A current Android System WebView is needed for the shared UI/PDF viewer.
- The user’s 8 GB RAM phone is the intended hardware target. Functional tests run in an Android 15 x86-64 emulator; this is not a physical-phone performance or battery qualification.
- Models total about 794 MB. They are copied and checksum-verified in app-private storage on first launch. Allow at least about 3 GB of free space for the APK, installed assets and working copies; documents need additional space.
- One native model is resident at a time. Inference uses CPU, up to four available threads, bounded contexts and execution deadlines. Imports can be paused or restricted to charging. Foreground import work has an Android notification; interrupted tasks remain retryable.
- PDF and PPTX files are selected through Android’s system picker, including recursively selected folders. No broad storage permission is used. Imports accept up to 500 files, 100 MB each, with page/archive/work limits.
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

## Validation artifacts

- 13 JVM parsing/layout tests passed; 3 Android integration tests passed, including real bundled models, OCR, search and authenticated backup rejection. Native PDF rendering and system file-picker import also passed. The home screen was visually checked at Android font scale 1.3.
- JVM parsing/layout tests: `android/app/build/test-results/testDebugUnitTest/`.
- Emulator integration tests: `android/app/src/androidTest/`, `results/android-instrumentation.log`.
- Emulator screenshots and UI checks: `results/android-qa/`.
- Build log: `results/android-build.log`.

All test invoices and the test presentation are synthetic. The user’s deleted Pawan Bills folder is not used or packaged.
