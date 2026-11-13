# Offline Windows Release Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task by task.

**Goal:** Ship a Windows installer with a compiled offline backend and automatic usable-CUDA/CPU selection.

**Architecture:** Keep the WinForms/WebView2 shell, Python runtime, existing models and React UI. Compile proprietary modules with Cython; retain only a minimal launcher as readable Python. Separate installed application files from per-user library data. Build a clean release from an allowlist, never the development library.

**Tech Stack:** Cython, native C compiler, Inno Setup, existing WinForms/.NET 4.7.2, FastAPI and PyTorch.

**Spec:** User selected fully offline compiled backend, source/debug exclusions, Windows installer, CUDA when usable and CPU otherwise. Preserve existing library and product behavior. Compilation raises reverse-engineering effort; it cannot make replication impossible.

## Global Constraints

- No user PDFs, database, local path preferences, API keys or test data in release.
- Preserve original PDFs and existing development installation.
- CUDA availability must include a small execution probe; CPU is the automatic fallback.
- No silent GPU out-of-memory model retry that risks changing indexing recipes. Show actionable error if selected device later runs out of memory.
- Application and library uninstall/upgrade boundaries must preserve user data.
- Do not claim fresh-machine or signed release verification without evidence.

## Review Focus

- Missing driver or unsupported GPU must select CPU.
- Fresh runtime must import compiled FastAPI/Pydantic modules without original sources.
- Non-admin install, spaces in paths, repeated upgrade and uninstall must preserve data.
- Full release must exclude source/debug files for proprietary modules and development preferences.
- Bundled runtime/model licensing and dependency notices remain available.

### Task 1: Device selection and first-run checks

- [x] Add failing tests for CUDA success, unavailable CUDA and probe failure.
- [x] Implement reusable device selection and hardware report; desktop runtime uses it before engine startup.
- [x] Show selected device, RAM and free space in first-run scan setup, without changing consent.
- [x] Verify focused tests and frontend build.

### Task 2: Compiled release

- [x] Bootstrap pinned build tools into workspace cache; verify downloads.
- [x] Compile a small module and verify binary import before compiling the full package.
- [x] Build release with Cython semantics compatible with FastAPI, package runtime/dependencies/models via strict allowlist.
- [x] Exclude proprietary source/bytecode/generated C/debug information; smoke-test installed runtime imports and engine.

### Task 3: Installer and release proof

- [x] Build per-user installer, prerequisite checks, shortcuts, safe upgrade/uninstall and first-run data location.
- [x] Test installation to a fresh workspace directory using only bundled runtime; test CPU execution, source search, PDF preview, upgrade and uninstall data retention.
- [x] Request focused code review and fix important findings.
- [x] Deliver installer, hashes and honest test report. Physical second-machine validation and trusted publisher signing remain separate if unavailable.

## Execution record

All local implementation and proof steps completed. Physical separate-machine validation, publisher signing and commercial PDF licensing remain external release prerequisites, as recorded in results/OFFLINE_RELEASE_REPORT.md. Validation-kit testing used explicit workspace directories; no existing library was modified.
