# A seven-day local usage pilot

The app now has a local feedback form beneath every search, including empty results. It records only submissions you choose to save. No query history is automatically collected or transmitted. Export the feedback from **Backup & storage**.

Use the separate synthetic demo first (`Start-Demo.cmd`). Every invoice is fictional. Try a party/date query, an alias, a date range, and `Which invoice contained thermal label rolls?` to inspect a match on a later page. Review a native invoice beside its highlighted PDF, then compare a scanned invoice. Do not use demo amounts as financial records.

| Day | Exercise | Record in feedback |
|---|---|---|
| 1 | Import and check ten invoices or documents | Missing/incorrect fields and indexing failures |
| 2 | Find documents using five phrases you would naturally use | Expected source and wrong/missing matches |
| 3 | Search customers by alias, date range and invoice number | Any unexpected inclusions or omissions |
| 4 | Find item descriptions, including a later invoice page | Whether the displayed passage contains the item |
| 5 | Correct bill fields and inspect scans | Fields corrected, elapsed correction time, unnecessary clicks |
| 6 | Download a backup, delete/restore a document, restore the backup separately | Whether recovery was understandable and preserved sources |
| 7 | Turn off Wi-Fi/unplug Ethernet, run Test-Offline.cmd and open a matching PDF | Restart/search/page-access outcome |

Choose useful result, wrong match, missing result, extraction error or too many steps. In the note, record the expected source, correction time and clicks if relevant. These are observations to collect through actual use, not metrics already measured by automated tests.

Review at the end of the week: successful-search proportion, wrong/missing-result count, bill corrections per document, typical correction time, repeated friction and any indexing/recovery failures. Fix recurring errors before expanding scope. A week of real use and independent human relevance judgments cannot be simulated by software test fixtures.
