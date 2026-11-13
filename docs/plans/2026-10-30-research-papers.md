# Research papers and references implementation plan

**Goal:** Evaluate real paper retrieval and automatically prepare editable references in the Windows app.

**Architecture:** Use an isolated corpus and library for a page-grounded retrieval benchmark. Detect paper metadata locally at successful PDF ingestion, retaining source provenance and manual corrections. Format CSL-JSON in the reader using a bundled CSL processor and official styles; custom independent CSL files extend the style selection offline.

**Constraints:** Preserve the existing personal library and original files. No document upload or external metadata lookup. Missing bibliographic fields remain missing and visible. Ordinary documents must not become papers because their text mentions a DOI. Treat references as drafts until checked. Keep Android preview unchanged.

## Tasks

- [x] Download primary-source papers, pin hashes and page evidence before scoring, run current ingestion and retrieval. Investigate failures before editing retrieval and retain baseline metrics.
- [x] Add paper metadata extraction, persistence and APIs with tests for detection, negatives, source replacement, manual correction, and malformed inputs.
- [x] Add a real CSL formatter with bundled styles, custom styles, BibTeX/RIS/CSL-JSON exports, and meaningful output/escaping tests.
- [x] Add automatic reference preview to the reader, style selection, copy/download and editable metadata with visible incomplete-state feedback.
- [x] Run focused regressions, production frontend build, browser interaction/visual checks and repeat the paper benchmark after any retrieval changes. Record measured results and limitations.

## Review focus

- False identification from references in ordinary documents.
- False metadata from PDF export titles, affiliation lines, email addresses and preprint sidebars.
- Silent retention of references after replacing a PDF with another source.
- Malicious CSL/metadata producing executable output or malformed exports.
- Claimed accuracy that measures document matching but ignores the supporting passage.
