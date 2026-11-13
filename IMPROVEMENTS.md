# Requested improvements - 18 October 2026

Scope: implement items 1-10, revised 12, 13-14 and 16-19 from the discussion. Item 11 (study mode) is excluded. Item 20 (permanent quality benchmark) is deferred at the user's request; focused implementation checks still apply.

Item 12 means automatically generated linked folders based on relationships in imported documents. Membership must not copy files or move originals. A document may belong to multiple generated folders. Weak relationships must remain ungrouped, and folder explanations must expose their basis.

Item 15 decision: use Android's on-device speech recognizer where available and supported, with editable transcript and typed fallback. No bundled speech model or cloud fallback is authorized. The current repository contains the PC app, not an Android runtime; no microphone behavior will be falsely presented as implemented Android support.

| Item | Work |
|---|---|
| 1 | Clarify total versus subtotal when source evidence supports both interpretations |
| 2 | User-selectable exact/automatic/absolute/percentage amount matching |
| 3 | Explicit match reasons and missing/unreviewed field information |
| 4 | Highlight the matching source text on the original page |
| 5 | Preserve remembered amount, party and date constraints together |
| 6 | Diagnose empty, unreadable, indexing and filtered scopes |
| 7 | Source-side bill correction with version-aware undo history |
| 8 | Non-destructive invoice arithmetic checks |
| 9 | Duplicate and possible-revision discovery |
| 10 | OCR for embedded images on otherwise text-rich slides |
| 12 | Automatically generated linked folders and relationship explanations |
| 13 | Source-backed document comparison |
| 14 | Inspect and search table rows with page provenance |
| 15 | Android on-device recognition decision/specification; native implementation requires Android app |
| 16 | Import duplicate/failure summaries and completion state |
| 17 | Incremental folder refresh through explicitly reselected browser folders |
| 18 | Pause/resume processing, search priority and model/storage visibility on PC; no claim of Android battery controls |
| 19 | Existing hash-verified backup/restore extended to new metadata, plus explicit verification |

## Implemented PC behavior and limits

- Items 1-6: total/subtotal clarification when interpretations identify different bills; exact/automatic/absolute/percentage amount controls; source match reasons and OCR/unreviewed warnings; literal highlights with page-region jumps; validated party/date/direction constraints plus `29k`/`1.2 lakh` expansion; scoped extraction diagnostics. Approximate results preserve actual source values. Multiple amounts and unsupported comparisons remain rejected rather than guessed.
- Items 7-9: transactional, source-hash-bound correction undo; conservative subtotal + labelled tax arithmetic checks; exact content duplicates, possible filename revisions and repeated invoice-number review. Discounts, ambiguous arithmetic and missing fields remain unchecked/unknown. No automatic correction, merge or deletion.
- Item 10: partial image OCR on otherwise readable pages; explicit **Re-read with OCR** for existing documents. English OCR is available; diagrams and image-only table structure are not fully understood.
- Revised 12: automatic overlapping linked folders after imports, also populated for the existing library on upgrade. Topics use bounded text samples and shared terms; bills use recorded customer relationships so seller addresses/bank identifiers do not become topic names. At most 1,000 documents, 3 pages/12k characters and 256 terms per document are sampled; identical copies alone do not create topic relationships. Original collections and source files are preserved. This is not exhaustive semantic clustering.
- Item 13: compare two to five documents, showing saved fields, indexed source totals/subtotals and optional literal topic passages with original page access. It does not generate unsupported cross-document conclusions.
- Item 14: original-page table inspection/filtering and header-linked table rows in the new indexing recipe. Existing indexes need explicit refresh; no mass reindex was performed.
- Item 15: the user selected Android on-device recognition where supported, typed fallback otherwise. Native implementation awaits the Android application; no PC microphone, bundled speech download or cloud fallback was introduced.
- Item 16: upload/indexing/duplicate/attention counts, per-file retry and Done are available. Current-page progress is separate from completed-page progress at processing boundaries.
- Item 17: explicit folder reselection with opt-in refresh of unique existing filenames in the destination collection; unchanged content/recipe reuse and changed-version updates are tested. This is not background watching. Same-name collisions across browser subfolders must be refreshed individually; different filesystem roots with the same filename cannot be distinguished by browser permission alone.
- Item 18: separate indexing and interactive workers, serialized embedding inference, cooperative pause/resume and search priority at page/batch boundaries; model-file and PC process memory visibility. Active conversion/OCR/inference calls are not forcibly interrupted. Added a persisted charging-only policy on PCs that expose battery status, with controlled unplugged/plugged-state tests. Unknown power status cannot enable the option; a restored enabled policy waits safely and can be disabled. Native Android power scheduling, process survival and actual phone resource use remain device work.
- Item 19: hash-verified backup/restore now includes linked folders and correction history, including history in recoverable trash. Added stored-source/vector verification before backup. Restore accepts the known older schema lacking these new metadata tables, while rejecting unknown/modified schemas. Optional password-protected `.llbackup` exports use streaming AES-256-GCM with a random salt/nonce, scrypt-derived key and authenticated header. Restore authenticates before parsing the ZIP. Plain ZIP export remains available. Passwords are not saved; local working files/database remain unencrypted. Temporary authenticated restore ZIPs are removed on completion/failure; a process crash may require local staging cleanup.

Study mode (11) was not added. The permanent benchmark (20) remains deferred. Focused checks exercise only the implemented changes and existing affected behavior. The 8 GB phone target is not a measured application memory allowance.

Validation files: `results/workspace-improvements-tests.xml`, `results/workspace-feature-tests.xml`, `results/workspace-desktop-regression.xml`, `results/workspace-index-regression.xml`, and `results/workspace-frontend-build.log`, `results/workspace-encryption-tests.xml`, and `results/workspace-backup-api-tests.xml`. Test counts and final live/browser checks are summarized in `results/WORKSPACE_IMPROVEMENTS_REPORT.md`.
