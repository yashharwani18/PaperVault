# Finding bills and invoices

Launch `Start-Library.cmd` and choose **Bills & invoices**. Add your invoice PDFs and select the bill/invoice option. Enable English OCR for scanned invoices. Originals stay on this PC.

Click **Review bill** on the bill row, or use the document menu. The original PDF appears beside the fields. Focus a field to highlight literal supporting text where available; source highlighting does not validate the field's meaning. Check the party, invoice date, sale/purchase type, invoice number, amount, currency and physical source page, then mark the fields reviewed. Automatic suggestions remain unreviewed until checked. You can correct fields when a layout is not recognized.

For your example, record party `Bhagwanti Trading`, date `2026-09-25`, and type `Sale`. Search:

> What did I sell to Bhagwanti Trading on Sept 25 2026?

The app matches the party, date and transaction type together, excludes purchase records, and opens the matching original invoice page. It shows the source passage, including any extracted item details; it does not generate an answer or invent a transaction. Exact invoice-number searches also work. These field lookups require no embedding inference.

Sale-only and purchase-only queries also exclude records whose transaction type is unspecified. Find those through a general invoice query and review their type first; an unknown type is never silently treated as a sale.

Exact amount searches work in a folder or the general search: `which invoice had 13600 subtotal?`, `subtotal of 13,600.00`, or `invoice total INR 30,744.00`. Subtotal and total are separate fields. These searches match an English field label and decimal amount in the indexed source text, show the physical page and supporting passage, and require no embedding inference or re-upload. They also work when a document has no extracted bill record. No matching amount means no results; unrelated similar invoices are not substituted. Optional party/date/type filters still require matching bill metadata. Range comparisons are currently rejected; use one exact amount. Explicit currency queries require a currency beside the source amount. OCR or unusual layouts can miss a match, so check the original when necessary.

With Qwen installed, try `hello mere bhai kaisa hai, muje wo wala invoice dikha na jaha pe 13800 ka invoice ban raha tha`. The local interpreter extracts search filters; it does not read the invoices or supply facts. For `13800 ka invoice`, **total** is assumed and displayed explicitly. Write `subtotal` or `tax se pehle` when you mean the amount before tax. Interpretation is automatic. Explicit English field queries keep using the exact parser to protect numeric correctness, and Qwen participates in the response for every completed search.

The interpreter's output is validated: amount values must occur literally in the request, party names must appear there, complete dates must agree with the deterministic date parser, and sale/purchase types must have supporting words. Unsupported comparisons and multiple amounts request clarification rather than returning similar invoices. Check the displayed interpretation, since a small model can still misunderstand wording. Each completed search also shows a brief response with a source link and exact excerpt; PPT/PPTX citations identify the slide. Related semantic passages are not presented as proof of an answer. There is no enable/disable checkbox. Amounts spelled entirely in words and arbitrary Hindi date spellings are not certified. Existing party/date filters still depend on reviewed or extracted bill metadata; missing metadata cannot be guessed from an amount match.

Dates such as `September 25, 2026`, `25 Sep 2026`, `25/09/2026` and `2026-09-25` are accepted. Numeric dates use **day/month/year**. Include a four-digit year for specific dates. Calendar ranges such as `in September 2026`, `from 01/09/2026 to 30/09/2026`, `last September`, `last month`, `today` and `yesterday` work. Relative dates use this PC's local calendar. The filter panel also provides an inclusive start and end date.

While reviewing a bill, add an explicit alias such as `BT` for `Bhagwanti Trading`. It then works in queries and the party search filter. Aliases are mappings you choose; the app does not silently merge similar company names. Manage/remove aliases under **Backup & storage**.

Try `all sales to BT in September 2026` or `Which bill contained A4 paper?`. Item matching checks actual indexed descriptions across the invoice PDF, including later pages. It matches words, not a structured accounting line-item ledger. If no description matches, no item passage is invented. Search returns up to 100 matching invoices and reports truncation; use filters to narrow larger sets.

Replacing a PDF invalidates its old bill fields and review flag. Moving it preserves its bill record. Removing a document moves its metadata, pages and vectors to recoverable trash and removes it from search. Restore it from **Backup & storage**, with no re-embedding. Removing its bill classification keeps the PDF in the general library.

Current scope: one invoice per PDF, English labels and English OCR. OCR quality must be reviewed. Detected bundled invoices, credit notes and unfamiliar amount conventions are flagged for manual attention. This is a document finder, with no payment reconciliation, accounting ledger or tax calculations. Multi-invoice PDF splitting and line-item aggregation are not implemented.

The regression suite uses clearly marked synthetic invoices. The separate read-only acceptance run against the user's 13 Pawan Bills passed 20/20 exact amount searches; expected values were checked directly against SHA-verified PDFs. See `results/pawan-20-search-tests.json`. This validates those amount queries, not every invoice feature or layout.

**Start-Demo.cmd** opens the separate library on port 8766, initially seeded with 16 synthetic invoices. Documents you subsequently import remain there. **Stop-Demo.cmd** stops it. Your normal library has no invented Bhagwanti Trading sales; upload your actual bill to find your real transaction.
