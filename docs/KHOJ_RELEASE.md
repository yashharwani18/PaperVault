# Khoj v0.5

Public name: **Khoj**. Public version: **v0.5**. Package version: **0.5.0**; Windows file version: **0.5.0.0**. The app, taskbar/tray, installer, Start menu shortcut, favicon and support report use this identity and the same purple book mark.

Internal executable, configuration, mutex and data-directory names retain the prior Library identifiers. The installer AppId is unchanged. This preserves existing installations and library locations during the rename; users should launch the Khoj shortcut.

## Updates

This release uses manual installer updates. Khoj does not check for, download, or install updates automatically. Back up the library, close Khoj and install the newer package from the publisher in the same location. The setup executable contains all offline components; no companion `.bin` files are required. Program files can be replaced without relocating originals or deleting the separate library data directory. Reopening retains interrupted-job recovery.

Use increasing 0.5.x versions for subsequent fixes. A future automatic updater needs a real distribution endpoint, signed packages, authenticated update metadata and a tested rollback design; none is simulated in this release. Do not downgrade an active database in place. Restore a verified backup to a separate library if an earlier version is needed.

Public distribution remains subject to the existing signing, dependency licensing and independent clean-machine validation requirements. This is an unsigned private release candidate.

## Privacy

Local PDF discovery, extraction, search and viewing run on the computer. Scans read originals in place; manual uploads may retain a managed copy. Extracted text, embeddings, file locations, organization choices and submitted feedback are stored locally. The local database is not encrypted. Password-protected backups are optional.

Cloud assistance is off by default. When a user explicitly enables Claude and requests an explanation, the question and retrieved excerpts, including their source filenames and page information, are sent to Anthropic. API keys remain in the server session. Ollama explanations use the configured local service. There is no automatic analytics or support-report upload.

## Support reports

Settings → Get a support report → Save support report downloads a JSON file. Export is an authenticated, explicit POST action and sends nothing remotely.

The report uses fixed fields: Khoj/Python versions, OS family, process architecture, memory totals/use, CPU/CUDA selection, fixed model readiness/provider states, cloud-enabled flag, database size, document/page/chunk/job counts and allowlisted error-category counts. It excludes document contents, PDF pages, names, paths, searches, feedback, tokens, API keys, source hashes, raw errors and logs. It does not read/hash original PDFs for export.

## Simple interface

Main navigation is Search, All files and Folders. Search has an explicit labelled button; original pages with yellow passage highlights lead the results. Extra result controls are grouped under More options. Scores and match diagnostics require opening Search details. Models and advanced tools require Settings → Advanced settings. Document menus keep common actions visible and place specialist actions under More options. Computer hardware details and file-viewer metadata are collapsed.

## Verification

- 28 focused release, privacy, packaging, recovery and organization tests passed: `results/khoj-tests.xml`.
- Desktop/narrow browser acceptance used real embeddings and source pages; verified hidden scores/advanced settings and a downloaded support report with no fixture contents, filenames, paths or query: `results/khoj-ui-validation.json`.
- Compiled native acceptance verified Khoj v0.5 and diagnostics exclusion: `results/compiled-khoj-validation.json`.
- Native release manifest hashes were verified; 31 compiled modules. Windows executable metadata reports Khoj, version 0.5.0.0.
- Existing desktop copy was updated/reopened; live About and diagnostics endpoints passed. User document organization was not changed by validation.
- Focused review found no important privacy, security or data-preservation issue. Upgrade compatibility was reviewed statically; no new clean-machine test is claimed.
- Installer build evidence: `results/khoj-installer-build.log`; distribution checksums: `output/Library-Installer/SHA256SUMS.txt`.
