<!-- impeccable:product-schema 1 -->
# Product

PaperVault v0.5 is a local-first document workspace for personal PDFs, college presentations, and business invoices. It indexes source passages locally and retrieves them through English and Hindi/Hinglish queries, semantic search, and structured invoice matching. Results link back to the original page.

## Audience and tasks
An individual keeps college material and business bills together on their own computer, with Android on an 8 GB RAM phone as a future deployment target. The shipped surfaces are the standalone Windows desktop app and an offline Android preview APK. The user removed the dedicated Bills & invoices navigation tab; My library remains the default for all PDFs. Invoice documents remain part of the library. Frequent tasks are discovering PDFs automatically, opening folders, importing files or a folder, searching remembered details, and verifying a result against its source. Folder-first home, with search always within reach, was confirmed by the user.

## Product truth
Preserve physical collections, automatic linked folders, import progress, PDF/PPTX support, invoice review and matching controls, source viewer, comparison, recoverable trash, and backup tools. Use live library data; do not invent counts or claims. Preserve local security protections. The Android preview uses on-device voice recognition when available, with typed fallback. Speech accuracy and physical phone performance remain unverified. The PC web app remains typed-input only.

## Brand commitments
Always dark mode, explicitly requested by the user. The user later requested replacing the green tint and green accents with purple gradients. Replace the existing visual identity completely. The interface must remain practical on desktop and phone-sized screens. Do not remove existing functions or alter stored documents for the redesign.

## Workflow
The PC app now runs in its own Windows executable/window using WinForms and WebView2 with bundled Python, dependencies, and offline models. Preserve the existing catalogue. The native host starts and owns the local engine, uses an owned folder chooser, minimizes to tray, restores a single instance, and stops its backend when closed. First-run choices are explicit: scan fixed local drives or choose folders. No whole-PC scan runs before consent. Scope/exclusions are visible; discovery/indexing progress is separate. Folder connections reconcile every minute; whole-drive connections hourly. Automatic scans index originals in place without copying PDFs. Existing scans relink to unchanged originals; no files are deleted during migration. Indexed text remains when originals are unavailable, but opening PDF pages requires a matching original. Explicit uploads retain managed files. Topic links remain suggestions and every indexed document belongs to a subject or Miscellaneous. Local installation uses the existing data/pc-prototype library; the portable default is data/library beside the executable. The existing Android preview is unchanged. Optional local Ollama or opt-in Claude explanations operate on retrieved evidence separately from local search. Pasted API keys stay in server memory for the session.

User confirmed code-first implementation and review of the working interface. No approved image comp exists.

## Simplified navigation

Recovery is available from document menus and failed PDF viewers through Fix source or extraction. Incomplete documents expose a direct Fix action. Missing originals retain searchable indexed text; reconnecting requires matching SHA-256 contents and does not copy the PDF. Interrupted standalone imports retry on startup; connected-folder jobs retain durable scan provenance and recover through discovery. Failed retries stay visible with plain explanations and technical details under a disclosure. Retrying an incomplete extraction re-reads the pages even when the original bytes and recipe are unchanged. Repeated retry requests share active work.
The primary sidebar has My library, All documents, and Scan & folders. Models, advanced library tools, backup, indexing history and recently added live under Settings. Home prioritizes search, a compact live scan status, folder links, suggested subject topics and recent documents. Generic shared-term groups remain in Library tools. Avoid repeated privacy labels, workspace chrome, promotional connection panels and large folder tiles. Source locations show counts and pause/resume first, with setup and secondary actions disclosed on demand.

The embedded PDF reader scrolls continuously through pages using Mozilla PDF.js PDFViewer. Preserve source-page jumps and highlights, page counter, zoom, text selection and document search; page buttons are optional shortcuts. Keep rendering bounded for long documents.

Every search result shows a large original PDF page with the retrieved passage highlighted. Extracted text remains under Matched text. Previews load near the viewport after retrieval, use indexed native/OCR word coordinates, and verify the original version before rendering. Missing or changed originals show a recoverable error. Rendered pages use a bounded memory cache, with no PDF copies or disk preview cache.

Live search streams embeddings into one matrix, keeping only page identities for scoring and loading full passages for the selected results. Vector integrity checks remain enabled. A fresh SQLite read snapshot covers ranking and passage loading, so concurrent indexing cannot mix document versions. No persistent search cache or additional on-disk index is created.

## Offline release

The separate Windows release compiles proprietary backend modules with Cython into stripped native binaries. The minimal launcher remains readable; third-party dependencies retain their source and notices. This raises inspection effort without guaranteeing protection against reverse engineering. The existing development installation and library stay separate.

The per-user installer includes Python, models and an offline Microsoft WebView2 prerequisite. Installed program files live under LocalAppData/Programs/LocalKnowledgeLibrary; default library data lives separately under LocalAppData/LocalKnowledgeLibrary/library. Upgrade and uninstall preserve library data and original PDFs. Startup performs a small CUDA execution check, selects CUDA when usable and CPU otherwise, and shows hardware status in first-run setup. Scan consent remains explicit.

The private release candidate is unsigned. Public closed-source redistribution requires resolving PyMuPDF commercial licensing and a real separate clean-computer validation. Bundled-runtime CPU and CUDA acceptance are distinct from that unperformed machine test.

## User organization

Documents support single and bulk moves between library collections, with an undo action. A destination folder can be created within the move form. Moves update library metadata; original PDF paths and bytes stay in place. Queued source refreshes respect the document's current collection.

Users can create and rename topics, replace a document's automatic classifications with their own choices, and restore automatic suggestions explicitly. Corrections and topic names survive indexing, topic rebuilds, restarts, backup/restore and trash recovery. Unclassified choices fall back to Miscellaneous. Custom empty topics remain visible for later use.

Document display names can be renamed independently of filenames and embedding titles. A filename/display-name filter and bulk selection live in the document list; organization is also available from search results. Per-document organization metadata is removed when a trashed document is permanently deleted. All organization changes reuse the existing workspace settings store and require no re-embedding.

## PaperVault v0.5: simple search first

The current product name is PaperVault and the public version is v0.5 (numeric 0.5.0). Main navigation is Search, All files and Folders. Search and highlighted pages lead; avoid asking ordinary users to understand models, technical scores or internal retrieval concepts. Settings contains plain-language backups/help/privacy/update information and explicit support-report download. Models and specialist tools are behind a closed Advanced settings disclosure. Manual installer updates preserve the existing AppId and library paths. Support reports export only allowlisted aggregate/system fields, never document contents, names, paths, searches, keys or raw errors.
