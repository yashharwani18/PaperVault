# Extensive phone-corpus multilingual verification

User authorized extensive testing and improvement after the first English-heavy pass. Work executes locally in the existing directory; no Git checkout exists.

- [x] Freeze explicit identifier/amount labels, language paraphrases and source-level development/holdout split before changing parsers.
- [x] Run production Java matching over every exported page, diagnose actual failures, add failing regressions, fix shared language patterns and source-row association.
- [x] Load temporary remapped index records into an emulator folder; run complete NativeBackend.search with folder scope, citations, real models and exact amount settings; remove the temporary database folder in finally.
- [x] Measure actual Android LiteRT original-query embeddings for 24 independently written English/Hindi/Hinglish questions about eight source categories.
- [x] Compare an English-translation prompt with the real Qwen/LiteRT models. Reject it if it degrades retrieval. Translation degraded and was rejected; no prompt/model/ranker change shipped.
- [x] Independent code review; replace a report-only device test outcome with an assertion for structured acceptance. Semantic cases remain explicitly diagnostic.
- [x] Verify the adjacent dated-topic filter fix, rebuild/audit update APK and save final measurements and limitations.

Privacy: only local emulator copies; no physical phone changes or external upload. Private export text/vectors stay out of APK assets. Distinguish generated structured checks, actual full-path cases and semantic diagnostics. Do not describe them as a single overall accuracy percentage.
