# Offline retrieval upgrade implementation plan

Spec: `docs/superpowers/specs/2026-10-28-offline-retrieval-upgrade.md`.

- [x] Prepare hash-checked public source pages and frozen multilingual queries as test-only assets.
- [x] Run actual Android chunking, LiteRT document/query embeddings and the current Qwen rewrite recipe; export a reusable private benchmark snapshot.
- [x] Test a page-deduplicated BM25/RRF evaluator and save development selection before scoring test rankings.
- [x] Promote only a candidate that passes the predeclared quality and phone-latency gates; preserve build 21 if no candidate passes.
- [x] For a promoted candidate, implement the smallest production change with regression tests, verify bills/export/UI and build/audit the APK. Otherwise document results and the next justified experiment.

Outcome: no promotion. Development-selected hybrid failed test relevance gates. Build 21 runtime ranking and distributed APKs remain unchanged. See `results/retrieval-upgrade/README.md`. Production implementation and phone-latency checks were unnecessary after the quality failure.

No original PDFs or personal library data are modified. Benchmark source assets never belong in the release APK. Use existing cached weights first. Do not claim a neural reranker, broader real-bill validation or physical-phone testing was performed unless it actually was.
