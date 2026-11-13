# Combined Android Release Implementation Plan

> **For agentic workers:** Use focused parallel work under dispatching-parallel-agents; root integrates and verifies. Steps use checkbox tracking.

**Goal:** Deliver the seven agreed release additions together, preserving offline search and existing data.
**Architecture:** Existing native Android/React app, additive preferences in settings, WorkManager discovery, native intent capture/shortcuts, full and small same-key APK builds.
**Spec:** `docs/superpowers/specs/2026-10-25-android-release-qol-design.md`.

## Global constraints

- Same package/signing key/model recipe; versionCode6, Khoj v0.5. No Internet permission or external PDF copies from scans.
- Settings-only reading/exclusion preferences; preserve backup compatibility and source revision checks.
- No user technical knobs; controls in existing simple UI. Android-only calls do not break desktop.
- Full offline installer and model-less update each consist of one APK. Fresh small installs recover with clear full-installer instructions.

## Tasks

- [ ] Scan owner: failing focused tests, implement consent-aware automatic/scheduled discovery, canonical exclusions, ETA, notification controls; report integration hooks.
- [ ] Interface owner: favorites/recent/reader memory, scan switches/exclusions, progress/ETA, shortcut button/events; TypeScript build and focused UI proof.
- [ ] Packaging owner: full/model-less assets, clear missing-model state, same-key build6 outputs and audit/update tests; no concurrent Gradle runs.
- [ ] Root: implement/test LibraryQoL reading routes and backup mapping, native PDF shares/temporary capture/dedup, picker and pin-search routes, runtime permissions, manifest/worker integration and source exclusion guards.
- [ ] Root: integrate, run frontend/JVM/Android regressions and UI checks, fresh reviewer, repair important findings.
- [ ] Root: build/audit full and small APKs, verify installed-model reuse and data retention after small update, fresh-small recovery behavior, exact release search and final documentation/artifacts.

## Execution decisions

- User explicitly requested one-sweep completion after enumerated scope; do not introduce another permission cycle for routine implementation choices. Brainstorming questions opted out; existing platform retained.
- Workspace has no Git metadata; work in supplied directory and preserve previous verified artifacts rather than creating a repository.
- Delegate only disjoint files with explicit API contracts; all Gradle/emulator runs are coordinated by root.
