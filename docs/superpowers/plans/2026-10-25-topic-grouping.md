# Coherent Topic Grouping Implementation Plan

> Execute inline with superpowers:executing-plans; verify each task before proceeding.

**Goal:** Group documents by supported similarity before generating folder names, with uncertain files in Miscellaneous.

**Architecture:** A pure topic-grouping module fits versioned, centered complete-linkage groups. Workspace integration names representative members and atomically publishes memberships with the fitted transform. Organization retains definitions referenced by user corrections.

**Tech stack:** Existing Python, NumPy, scikit-learn, SQLite and optional local Qwen.

**Spec:** ../specs/2026-10-25-topic-grouping-design.md

## Constraints and decisions

No original-file changes, re-embedding, new model or search-ranking changes. No path-based exclusions. Use cutoff 0.55 after centering; for libraries with fewer than eight distinct documents, use uncentered vectors with the stricter distance cutoff 0.15, since subtracting the mean of two documents makes even close neighbors point in opposite directions. Cap pairwise fitting at 4096 distinct documents; exceedance retains current topics and returns an actionable explanation, without marking an unsuccessful rebuild current. Do not truncate output groups.

## Review focus

Malformed/mixed vectors; tiny or identical libraries; incremental assignments using old geometry; corrections referring to retired automatic groups; interrupted publication. Each is covered by regression tests below.

## Tasks

- [x] Write failing tests in `tests/test_topic_grouping.py`: coherent groups and outliers; duplicates do not establish a topic; deterministic representative order; invalid vectors; capacity bound; versioned incremental rejection; transaction rollback; preservation of retired user-owned topics.
- [x] Add `knowledge_library/topic_grouping.py`: `fit_topics(documents, vectors)` returns versioned state and ordered member IDs; `match_topic(state, vector, source_hash=None)` returns one supported name or None. Validate saved state, reuse its transform, accept original hashes directly, and require both a member-derived centroid threshold and an unambiguous best candidate for new content.
- [x] Update `workspace_features.py`: stream and validate vector means, replace K-means/overlap logic, select representative evidence, record naming provenance, publish all state atomically, clear stale centroids on an empty library, and retain source-based fallback for mocked/nonvector libraries.
- [x] Update `organization.py`: remember automatic definitions selected/renamed by the user, capture legacy references before rebuilding, and allow reapplication inside the caller's transaction.
- [x] Run focused workspace/organization/API regressions. Add regressions for any review findings before fixes.
- [x] Run an actual-model naming/rebuild evaluation on a SQLite backup under `results/`, verify the expanded nine pairs, and inspect all generated names plus representative group content. Confirm source library was not changed by evaluation.
- [x] Have a fresh reviewer inspect the implementation; resolve substantive findings, run relevant proof, and report the result and remaining limitations. Deployment to the desktop payload and rebuilding saved live topics require successful copy validation first.

## Execution ledger

- Planning: the user's grouping-first choice and removal of the blocking approval requirement are treated as instruction to proceed. No further design checkpoint.
- Workspace: existing non-Git project directory; no branch/worktree operations are available or required.
- Ruling: do not fit on a filtered library. Development fixtures stay included; similarity groups can accommodate them without consuming a fixed cluster count.

- Verification: 38 focused regressions, 10 actual-model API regressions, 14 focused topic tests independently repeated by the reviewer, and all 9 expanded diagnostic pairs on both the library copy and the updated live library. Live source document/chunk fingerprints and manual settings are unchanged.
- Review: incremental pairwise acceptance, duplicate fallback/example support, and same-name component merging were reproduced with failing tests and fixed. Final reviewer reported no blockers.
- Environment ruling: sandboxed API tests hung before test execution in Windows asyncio socketpair setup. A diagnostic stack identified the cause; the targeted runs were stopped and rerun successfully with loopback access. No product changes were made for this environment issue.
- Deployment: three backend files copied and SHA-256 verified in the existing desktop payload. The bundled runtime imports schema 1 / topics-coherent-v6. The live library was rebuilt after a consistent SQLite backup. See results/topic-grouping-live-update.json and results/topic-grouping-desktop-update.json.
