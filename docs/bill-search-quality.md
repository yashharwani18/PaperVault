# Repeatable Android bill-search checks

The available real corpus contains **13 real bills**, not 50–100. Its 90 frozen English, Hindi and Hinglish queries cover invoice numbers, exact totals, subtotals, physical source pages and absent matches. Positive values are independently checked against SHA-verified original PDFs using PyMuPDF before Android sees them. These are developer-assisted labels, not independent human annotations.

The Android test runs the real PDF reader, then exercises structured search with page-sized indexed passages. Embeddings are deliberately unnecessary for these queries. This measures extraction and structured lookup; it does not certify OCR, semantic search, other layouts, or performance on a physical phone. Synthetic tests separately cover number/amount collisions, nearby values, ambiguous multiple amounts, incomplete reading and export integrity.

## Run again

```powershell
.venv/Scripts/python.exe scripts/prepare_bill_search_quality.py
python scripts/build_android.py --update testDebugUnitTest assembleDebugAndroidTest assembleRelease
```

Install the resulting release and test APKs on a **test emulator**, then run:

```powershell
adb -s emulator-5580 shell am instrument -w -e class org.localknowledge.library.BillSearchQualityTest,org.localknowledge.library.BillQueryTest org.localknowledge.library.test/androidx.test.runner.AndroidJUnitRunner
node scripts/test_search_evidence.mjs
```

The Android report is `files/bill-search-quality.json` inside the test installation. Saved workspace reports are `results/bill-quality-red.json` and `results/bill-quality-verification.json`. Queries stay fixed between the before/after runs. Tests create their own collection and remove only their own records and copied source files afterward. The original PDFs and personal databases are read only. Generated real-document test assets live under `.cache/bill-quality/assets`, included only in the Android **test APK**.

## Result interpretation

- **Invoice number:** the identifier matched page text, or a visibly qualified saved field.
- **Exact total/subtotal:** the stated field and amount occurred in indexed source text. Review status is shown separately.
- **Nearby total/subtotal:** the actual source amount, requested value and signed difference are visible. Nearby amounts are never relabeled as exact.
- **Incomplete search coverage:** the app reports how many files have searchable text and how many need reading or review. An empty search does not establish that an unread file lacks the requested bill.

Recognized invoice-number, Hindi/Hinglish amount and explicit field requests bypass model classification. Unsupported multiple amounts request clarification instead of dropping a number. Original-page opening and field-review safeguards remain unchanged.
