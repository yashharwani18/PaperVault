# Full installer and small updates

Khoj v0.5.0 build6 has two APKs with the same package, version and retained signing key:

- `output/Khoj-0.5.0-android.apk`: complete offline installer, including both model weights. Use for a new installation or model repair.
- `output/Khoj-0.5.0-android-update.apk`: small update for an existing installation whose private offline models are intact. It includes model metadata and license notices, but no GGUF weights.

Install either APK over the existing app. Keep Khoj installed to retain its library, index, preferences and private model files. The small update verifies the installed models against the bundled recipe before enabling semantic search. It does not download models. If models are absent or damaged, Khoj explains that the complete APK must be installed over the app. The complete installer can repair models after validating their replacements; valid cached models are reused without rewriting them.

## Build and audit

Run these sequentially from the workspace root; both variants share Gradle's intermediate output location. For any `assemble*` task the builder first rebuilds the interface (`copy-pdf-assets.mjs`, `tsc -b`, `vite build`) using Node from PATH or the bundled runtime named in `docs/HANDOFF.md`, then writes `frontend/dist/khoj-ui.json`, a receipt of the frontend source digest that is packaged into the APK:

```powershell
python scripts/build_android.py
python scripts/audit_android_apk.py --models full --apk output/Khoj-0.5.0-android.apk
python scripts/build_android.py --update
python scripts/audit_android_apk.py --models update --apk output/Khoj-0.5.0-android-update.apk
```

The default Gradle setting is `-PkhojBundleModels=ON`. Direct Gradle callers can use `-PkhojBundleModels=OFF` to omit weights. The Python builder accepts this property too; `--update` is the clearer interface. Pass Gradle task arguments after the script, for example `python scripts/build_android.py testDebugUnitTest`. An artifact copied by the builder still requires the audit.

The audit verifies the package/build, retained signing certificate, no Internet permission, release non-debuggability, notices, native batching disabled, CPU dispatch/fallback libraries, ZIP alignment and 16KiB native ELF segment alignment. It also proves the packaged interface: every file under `assets/` must be byte-identical to `frontend/dist`, and the packaged `khoj-ui.json` receipt must match a digest recomputed from the current `frontend/src`, `frontend/public` and frontend configuration. A stale or hand-built bundle fails with `rebuild with scripts/build_android.py`, so an APK can no longer ship an interface that does not match the source being audited (`interface_matches_source`, `interface_source_sha256` in the report). For the full installer it verifies the exact model manifest, sizes and SHA-256 hashes; for the small update it verifies the manifest and absence of all GGUF files. Auditing a small update never replaces the full installer or its audit report. Reports are `results/android-apk.json` and `results/android-apk-update.json`; each APK has its own `.apk.sha256` file. Reported sizes are measurements of the actual audited artifacts.

Before replacing the verified build5 full installer, the builder/auditor checks its checksum against its prior report and saves it once under `output/previous-android-v0.5-build5/`, including its audit report. An existing archive must match; it is never overwritten with different bytes. The signing keystore is retained in place.

## Focused verification

```powershell
python -m unittest tests.test_android_update_packaging
python scripts/build_android.py testDebugUnitTest
```

`ModelAssetsTest` uses tiny in-memory model assets and a temporary isolated directory. It covers full-to-small model reuse, fresh-small guidance, damaged-cache preservation and a corrupt full-installer model failing without deleting the existing file. It never clears app data or touches a real keystore.

Release integration additionally installs the full APK, waits for verified private models, records model hashes and library/reading settings, installs the small APK with `adb install -r`, and checks that those files/settings and offline search remain usable. Fresh-small recovery must use a separate emulator or isolated test installation; do not clear the user's installed Khoj data. Physical ARM/KleidiAI execution remains a separate device verification step.

WorkManager is pinned to `androidx.work:work-runtime:2.10.0`; its [official release notes](https://developer.android.com/jetpack/androidx/releases/work#2.10.0) state that it is compiled against SDK35. Khoj compiles/targets SDK35 and retains minSDK26.
