# Phone corpus retrieval implementation plan

Goal: use the 747-document private export to reproduce retrieval defects and improve Android search without rebuilding or modifying the user's library.

Approach: execute locally in the existing checkout, as authorized by “test away and better the app.” Keep existing models and scoring. Prefer targeted fixes over changing models or tuning semantic thresholds without labeled query vectors. No Git repository is present here.

- [x] Add a repeatable, read-only benchmark which verifies export checksums and runs the actual Java invoice matcher against corpus-derived identifiers and ordinary-language negative controls.
- [x] Measure chunk crowding using exported vectors as diagnostic queries; distinguish this from human-labeled semantic relevance.
- [x] Add failing JVM tests for observed identifier and candidate selection defects, then apply minimal fixes.
- [x] Run JVM tests, relevant Python regressions and corpus benchmark. Save baseline, final results, reproduction commands and limitations.

Constraints: private pages stay local, outside Android assets and distributable fixtures. Preserve source/page identities, exact number boundaries, cancellation, model identity checks and bounded candidate storage. No phone installation or publishing. Report source validation separately from end-to-end mobile quality.

Completed: 201/201 diagnostic cases (baseline 187), 4,614/4,614 page-selector oracle matches, 55 JVM tests and 20 Python tests pass. Local update APK built/audited. Focused independent production-code review found no actionable issues. Evidence and limitations: `results/PHONE_RETRIEVAL_REPORT.md`.
