# Android and desktop library parity implementation plan

> **For agentic workers:** Use superpowers:executing-plans for this plan. Work in the existing checkout; preserve existing indexed data and user changes.

**Goal:** Deliver the full Android and Windows search, large-library and reliability requirements in the attached mission.

**Architecture:** Preserve the existing desktop retrieval engine and the shared React interface. Add equivalent platform-owned metadata/search capabilities without re-embedding existing documents, and validate cross-platform behavior against the same observable examples. Build deliverables only after feature and migration checks.

**Tech Stack:** React/TypeScript, Python/FastAPI/SQLite, Android Java/SQLite, local Qwen and EmbeddingGemma.

**Spec:** `C:/Users/Yash/.codex/attachments/e1efa4bc-eae5-4c02-b869-8e5b537f1944/pasted-text-1.txt`.

## Global Constraints

- Preserve indexed documents and original files, existing business search and source evidence, offline operation, and user permissions.
- Android indexes text only; no visual embeddings or new cloud inference. No model changes without baseline resource/quality benchmarks.
- Exact unique accessible filename opens on explicit submit without LLM; duplicates must be presented for selection.
- Never invent modified dates or source evidence; avoid rendering 10,000 cards and avoid LLM/embedding calls for ordinary metadata browsing.
- Final acceptance requires functional parity and measured behavior on both platforms; record missing physical-device evidence explicitly.

## Review Focus

- Duplicate filenames in separate folders and hidden, unavailable, renamed or moved source files.
- Unicode/punctuation variants and file extensions without collisions or accidental auto-open.
- Filtering and pagination under concurrent index, document move and removal.
- Existing SQLite databases, backups and interrupted indexing across upgrades.
- Long PDFs, low memory, low storage, denied permissions and model failure.

## Workstreams

- [ ] Audit desktop and Android extraction, search, storage, resource behavior and UI; maintain parity matrix and measured baselines.
- [ ] Specify and implement cross-platform exact filename matching, source availability checks, duplicate-safe direct open and regression tests.
- [ ] Build tested approximate filename/content hybrid ranking and transparent, deduplicated result reasons without degrading structured invoice search.
- [ ] Implement database-backed paging, metadata sorting/filters and preferences across both backends; preserve genuine file timestamps and local reading history.
- [ ] Implement virtualized library browsing, alphabet navigation, filters, selection, scroll restoration, and accessible responsive layouts.
- [ ] Close Android text-format, extraction, organization, indexing recovery and reader parity gaps where feasible without visual inference.
- [ ] Measure equivalent corpora, search quality, resource usage and 100–10,000 document behavior; run reliability and migration tests.
- [ ] Build and inspect Windows/Android deliverables; produce parity, UX, ranking, benchmark and installation reports, clearly identifying unverified physical-device behavior.
