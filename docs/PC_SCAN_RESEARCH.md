# First-run PC scan research — October 24, 2026

User requested online inspiration before implementing a whole-PC PDF scan.

## References

- [Everything FAQ](https://www.voidtools.com/faq/): fast default indexing covers filenames/folder names, not semantic document content. Do not borrow its speed claims for OCR/embeddings.
- [Everything folder indexing](https://www.voidtools.com/support/everything/folder_indexing/): visible initial/rescan status, explicit included locations, monitoring and rescan controls, retained indexes for offline locations.
- [Windows Search indexing](https://support.microsoft.com/en-us/windows/experience/performance-optimization/search-indexing-in-windows): Classic vs Enhanced scope, editable locations, local processing, initial indexing cost and later incremental updates.
- [DocFetcher](https://docfetcher.sourceforge.io/): separates index creation from search, supports exclusions, explains expensive initial extraction vs incremental updates, warns that indiscriminate indexing can clutter results.

## Product decision

Preserve the current catalogue and provide a prominent first-run choice: Scan this computer / Choose folders instead. No scan occurs from opening the app or reading the scope preview. Show fixed local drives and exclusions before consent. Protected locations are skipped without elevation; network/removable drives are not included automatically.

Use separate discovery/indexing counts, show current scan progress, queue indexing while discovery continues, retain completed indexes across restarts, and allow pausing. Keep model downloads/cloud consent separate. Avoid fake percentages or completion-time estimates before the workload is known. Automatically skip application/system/cache locations and expose optional additional excluded folders. Originals are not moved or deleted.

Whole-drive discovery must not hold pause controls hostage or repeatedly crawl an entire drive every minute. Use a slower scheduled full reconciliation for whole-PC connections; scan-now remains available. Tests use controlled directories in place of real drives.
