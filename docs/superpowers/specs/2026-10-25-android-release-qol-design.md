# Khoj v0.5 combined Android release

User authorization: "make all of that then in one sweep" (2026-10-25), covering the previously enumerated six convenience additions and small update APK. Proceed with reasonable implementation choices, without another scope/approval cycle.

Keep the current Java/C++ offline Android backend and React interface. Preserve the models, index, signing key, package, topics and backups. Native multi-sequence batching stays off; physical Moto/KleidiAI execution remains unverified.

## Decisions

1. Automatic discovery: after prior whole-phone consent, optionally check for changed/new PDFs on app opening (throttled) and optionally every12hours through Android WorkManager. Background scans respect permission, pause, charging settings and Android restrictions; no promise of exact schedule/always-running monitoring. UI offers simple switches. Worker discovers/persists work without illegally starting foreground services from a background launch; resume indexing in an allowed execution context or on reopening. No new scan before consent.
2. Exclusions: canonical file/folder rules, persisted in existing settings. Skip traversal/enqueue, hide excluded scanned references from library/search, prevent a running ignored source from publishing. Originals untouched. Removing a rule permits a new scan. Explicit managed imports remain independent. Existing cached data is retained until Remove from Khoj; do not describe Ignore as secure erasure.
3. Sharing: ACTION_SEND/SEND_MULTIPLE/VIEW for PDF content URIs only. Capture temporary grants promptly into one retained managed copy, enqueue background indexing, and deduplicate repeated shares. Support opening an already-running app. External URL navigation remains blocked. Never accept arbitrary remote URLs, HTML, or ungranted file:// paths.
4. Favorites/reading: store favorite flag, page, last-opened and source revision in existing settings. Favorite/recent filters and simple star controls; opening a document resumes its remembered page, explicit search-result page always wins. Debounce page saves and flush on close. Clamp/reset stale pages on revised files. Remap settings on backup restoration; no new schema.
5. Progress: found/ready/remaining counts, elapsed/estimated remaining time after enough representative completions, descriptive stage and waiting/paused state. Notification has progress plus pause/resume action. ETA is approximate, withheld while discovering/too few samples and frozen/excludes paused time as practical. Request Android13+ notification permission in context; denial leaves in-app controls usable.
6. Shortcut: user-controlled request to pin a Search Khoj shortcut, with launcher confirmation/fallback text. Static long-press search shortcut. Launch/focus the existing search screen, no automatic forced home-screen placement.
7. Updates: one complete offline APK for new installs and one small update APK for existing installations, same package/versionCode/signing key. Small APK excludes GGUF assets and reuses checksum-verified private model files; preserves index/preferences. A fresh or damaged-model small install explains that the complete APK is required, with no network download or silent deletion. Model metadata/notices remain bundled. Archive verified previous release. Test full->small update and small fresh-install recovery separately.

## Integration interfaces

- Reading GET `/reading-state`: `{documents:{[id]:{favorite:boolean,page:number,last_opened:string,sha256:string}},recent_ids:string[]}`. POST `/documents/:id/reading-state`: any of `{favorite,page,opened:true}`; validates active document and page range. Root implements in `LibraryQoL.java`.
- Scan GET/PATCH `/phone-scan/options`: `{auto_scan_on_open:boolean,scheduled_scan:boolean,exclusions:[{path:string,kind:'file'|'folder'}]}`. POST/DELETE `/phone-scan/exclusions` accepts `{path,kind}`. POST `/phone-scan/exclude-document` accepts `{document_id}`. `PhoneScan.route(route,method,body)` returns result or null; `isExcluded(File)` and `visibleDocuments(JSONArray)` used centrally by root. `onAppOpen()` handles consent/throttle. `status()` adds `remaining`, `eta_s` nullable, `stage`, `active_elapsed_s`.
- Native POST `/native/pick-exclusion` `{kind:'file'|'folder'}` uses system picker, resolves safely to an eligible shared-storage path or explains unsupported provider. Native POST `/native/pin-search` and `/native/notifications` return support/permission outcomes. Root owns these routes.
- MainActivity dispatches browser event `android-focus-search` for shortcut intents; frontend navigates home and focuses search. Shared files emit `android-library-changed` after capture/enqueue; frontend reloads state and shows plain confirmation.
- Notification service accepts private service intents for pause/resume. Android runtime/manifest/Activity integration belongs to root; scan owner adds worker and requests root integration points. Packaging owner adds WorkManager dependency (`androidx.work:work-runtime:2.10.0`, verify available minSDK/SDK compatibility), versionCode6, model-bundle Gradle property and audits.

## Ownership

- Scan domain: PhoneScan.java, ImportService.java, new discovery Worker/tests; no edits to Manifest, MainActivity, NativeBackend, Gradle or frontend.
- Interface domain: frontend files, including reading UI/PhoneScan controls; no Java edits. Preserve desktop behavior by Android-only API calls/controls.
- Packaging domain: build.gradle, ModelAssets.java, build/audit scripts and update packaging tests/docs; no NativeBackend/MainActivity/frontend edits. No Gradle/emulator builds until root schedules integration.
- Root: LibraryQoL.java, MainActivity/native sharing/shortcut/picker, Manifest/resources, NativeBackend filtering/recovery hooks and backup reading-setting remap, integration tests/build/review.

## Acceptance

Focused tests for scan consent/throttling/exclusion boundary, revision-aware reading state, share grants/dedup/multiple and existing Activity, notification actions/permission denial, shortcut focus, full/small assets and cached model reuse. Build shared frontend and relevant desktop regressions. All existing Android correctness/privacy/recovery tests continue passing. UI verify favorites, recent/resume, exclusion controls, ETA/paused copy and responsive layout. Exact signed release audit/install/search, then same-key small update preserving model hashes/documents/favorites. Explain untested physical ARM execution without claiming it is final device certification.
