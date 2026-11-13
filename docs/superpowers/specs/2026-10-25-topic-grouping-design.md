# Khoj: form coherent topics before naming them

Status: implemented and applied to the local desktop library on 2026-10-25, following the user's grouping-first choice and removal of the blocking design checkpoint. Validation and rollback paths are recorded in `results/topic-grouping-live-update.json`.

## Intent

Suggested folders should describe a shared subject in their documents. A document without convincing peers stays searchable in Miscellaneous instead of being forced into an unrelated topic. This is a focused backend change, using existing embeddings and the installed local naming model.

## Approaches and decision

- Naming only: improve representative titles and excerpts while keeping fixed-count K-means. Less code, but the measured misplaced documents remain.
- Grouping first, selected by the user: form similarity-based groups, permit abstention, then name representative members. More groups and some ungrouped documents are expected.
- Replace the embedding or language model: requires a separate evaluation and possibly re-indexing; current evidence does not justify it. The installed naming model already names clean commodity and Smith chart groups sensibly.

## Proposed behavior

1. Keep existing normalized document means as inputs. Validate dimensions, finite values and nonzero norms; invalid vectors receive the fallback rather than contaminating a rebuild. Count identical file contents once when fitting groups, then restore all corresponding memberships.
2. Subtract a fitted library mean and normalize for topic organization only. Use complete-linkage cosine clustering with a distance cutoff, initially 0.55, rather than a fixed number of groups. Complete linkage bounds the worst pairwise distance inside each group: the broader review found that average linkage still merged a predictive-maintenance pitch into lunar-imaging material. A named group needs at least two distinct source hashes. The tradeoff is narrower groups: the RFC filename family splits into 13 groups in this library. The cutoff is an engineering starting point, not a calibrated confidence percentage. Review resulting names and memberships before deployment; a family splitting into several specific topics is not automatically an error.
3. Initially assign only the coherent primary group. Remove automatic extra memberships based solely on proximity to several centroids. Explicit user-selected multiple topics remain supported.
4. Select naming examples by proximity to the group center, in deterministic order, rather than import recency. Use the installed local model; include bounded source evidence when readable titles are insufficient. If naming fails, use shared supported terms or Miscellaneous, never a title from one arbitrary outlier. Record whether naming used the model or fallback.
5. Persist the centering transform, schema version, centroids and member-distance acceptance bounds together. Incremental assignment applies the same transform and abstains outside a group's accepted region. Old or malformed saved state must not be interpreted using the new geometry.
6. Preserve manually corrected memberships, user-created topics and renamed topics across rebuilds even when an automatic group disappears. Keep retired user-referenced topics available rather than dropping a correction. Publish a rebuild atomically; failure leaves the old organization available.

## Boundaries

No original files move or change, no re-embedding, no automatic test-path exclusions, no new model, and no changes to search ranking. Standalone experiments used a path-filtered subset only for diagnosis. The actual change must also work with the complete library. Avoid silently truncating groups at the current 64-row output slice. Pairwise clustering has quadratic costs; measure rebuild time and memory on this library and define a bounded failure path before applying it to larger libraries.

## Acceptance evidence

- Regressions cover coherent groups, unrelated outliers, duplicate contents, invalid vectors, deterministic ordering, old state and incremental abstention.
- Organization tests cover manual corrections and renamed automatic topics whose original group disappears, plus rollback on rebuild failure.
- Read-only evaluation on the current library keeps the commodity pair and Smith chart family together while separating the Olympiad flyer, tourism and cancel-culture examples.
- Include the newly discovered predictive-maintenance versus lunar-imaging case. Review full lecture documents versus slide fragments and resulting RFC subgroups explicitly; do not claim success solely from the first eight probes.
- Report group counts, singletons, largest groups, time and memory, with representative content review beyond the eight diagnostic pairs. Preserve the distinction between diagnostic success and general quality.
- Run the existing workspace and organization regression suites. Apply a rebuild to the user's library only after the implementation passes on a separate copy.

## Current evidence

Implementation evidence: `results/topic-grouping-tests.xml` and `results/topic-grouping-api-tests.xml`; copy validation in `results/topic-grouping-implementation-validation.json`; live verification in `results/topic-grouping-live-verification.json`. All nine diagnostic cases pass on the live library, all 962 documents have memberships, and manual organization settings match the pre-update backup. Original document and chunk rows were fingerprinted unchanged during the rebuild.

Implementation decisions: tiny libraries use stricter uncentered grouping; fitting is bounded at 4096 distinct documents and retains current topics above that limit. Persisted float32 member geometry enforces the fitted pairwise bound for incremental acceptance. Duplicate copies cannot influence naming support or examples. Separate components retain distinct visible folders even when generated names coincide. Readable titles take priority in the small naming model; content supplies shared-domain support and unreadable-title evidence.

`results/topic-quality-diagnostic.json`: 279 path-filtered documents; K-means passed 4/8 diagnostic pair checks, centered average-linkage at 0.55 passed 8/8 (48 groups, 43 singletons).

`results/topic-quality-full-library.json`: 910 embedded documents without path exclusions; the same centered method formed 32 multi-document groups and 17 singletons, retaining the commodity pair, separating the Olympiad flyer and keeping the Smith chart family together. Large fixture groups remain, as expected when their files remain included.

`results/topic-naming-diagnostic.json`: live local model calls returned “Gold And Copper Commodities” and “Smith Chart” for clean groups. Two naming examples and eight hand-selected pair checks are not a complete quality benchmark.

`results/topic-quality-broader-review.json`: average linkage is invariant under one fixed input permutation. Clustering plus distance construction took about 0.04 seconds for 910 vectors; the diagnostic process peaked at about 268 MiB including Python, imported libraries, SQLite and chunk-vector loading. These timings exclude LLM naming. Content review found the predictive-maintenance/lunar-imaging merge and fragmentation of some lecture families.

`results/topic-quality-linkage-comparison.json`: complete linkage at 0.55 passed the expanded 9/9 pair probes, forming 60 multi-document groups and 15 singletons on all 910 embedded documents. It splits RFCs and some lecture families more finely than average linkage. This is why the proposed grouping rule was revised after broader review. Raising its cutoff to 0.65 reintroduced a failed pair probe.
