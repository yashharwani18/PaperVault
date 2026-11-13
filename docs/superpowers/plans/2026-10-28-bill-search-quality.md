# Bill search quality and trust

Approved scope: the user's items 1, 2 and 4, resumed after verifying embedding export. Prioritize the Android app used in this chat and preserve the export feature.

1. Freeze a repeatable test corpus from the 13 available real source PDFs. Independently extract and hash-check invoice numbers, totals, subtotals and physical pages. Generate English, Hindi, Hinglish and absent-match queries. Keep synthetic identifier collisions, nearby values, partial indexing and malformed queries separate. Do not call 13 real bills a 50–100 bill validation.
2. Run the actual Android PDF reader and structured search against that corpus in a temporary test collection. Record every failed query before changing search code. Fix only demonstrated failures, with unit regressions; deterministic invoice/amount queries should work without model interpretation.
3. Expose explicit invoice-number evidence in search responses. Put exact/nearby amount labels, requested amounts and differences in the visible result cards. Report partial reading coverage and avoid presenting missing results as a complete-library conclusion.
4. Verify the corpus again, run Android unit regressions, test frontend evidence labels and PC export reader, inspect result screens at normal and enlarged text, then build and audit a new update APK.

Files: `scripts/prepare_bill_search_quality.py`, generated `.cache/bill-quality/assets/`, Android `BillSearchQualityTest`, `InvoiceNumbers`, `Money`, `NativeBackend`, frontend `searchEvidence.ts`, `SearchMatchEvidence.tsx`, `App.tsx`, `catalogue.css`, and a saved `results/bill-search-quality/` report.

Constraints: no changes to original PDFs or personal library databases; test fixture PDF/text assets are Android-test-only and never packaged in the release. Existing source verification and amount review rules remain intact. No new unrelated product features. Full physical-phone testing remains outside emulator evidence.

Completed: 90 frozen queries on 13 real PDFs went from 86 passing to 90 passing. Source matching now accepts spaced/wrapped INV prefixes and symmetric bare/prefixed IDs. Deterministic amount and identifier queries avoid generation. Visible evidence labels and incomplete-coverage notices are implemented.

Review found two additional bugs, reproduced before fixing: literal matches erased structured invoice evidence, and saved ID 25 could hide an amount 2500. Both have passing API regressions. Final proof: 49 Android unit tests, 11 targeted emulator tests, frontend evidence checks, PC export-reader tests and normal/200% text result checks pass. Build 21 update APK is signed and audited; generated real-PDF test assets are excluded. See `results/BILL_SEARCH_QUALITY.md` and `results/bill-search-quality-summary.json`. The 50–100-real-bill milestone remains unverified because only 13 independently source-checked real bills were available.
