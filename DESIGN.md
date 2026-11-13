---
name: PaperVault
description: An always-dark reading-room catalogue with purple gradient actions.
colors:
  background: "#1b181d"
  surface: "#252128"
  raised: "#2f2a33"
  border: "#413a46"
  muted: "#b0a6b6"
  accent: "#c9b2d9"
  ink: "#ebe7ee"
  action-start: "#b294ec"
  action-end: "#d0b5f6"
  action-ink: "#261735"
typography:
  display:
    fontFamily: "Lora, serif"
    fontSize: "clamp(34px,3.4vw,49px)"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  section:
    fontFamily: "Inter, sans-serif"
    fontSize: "18px"
    fontWeight: 500
    letterSpacing: "-0.025em"
  folder:
    fontFamily: "Lora, serif"
    fontSize: "23px"
    fontWeight: 400
    lineHeight: 1.3
  control:
    fontFamily: "Inter, sans-serif"
    fontSize: "12px"
    fontWeight: 500
rounded:
  control: "6px"
  search: "10px"
  panel: "12px"
  dialog: "16px"
spacing:
  tight: "8px"
  control: "12px"
  group: "24px"
  section: "40px"
  desktop-gutter: "48px"
  phone-gutter: "20px"
components:
  button-primary:
    textColor: "{colors.action-ink}"
    rounded: "{rounded.control}"
    padding: "10px 15px"
    height: "42px"
  search:
    rounded: "{rounded.search}"
    height: "64px"
  result:
    rounded: "{rounded.panel}"
    padding: "24px"
---

# Design System: Local Knowledge Library

## Overview

**Creative North Star: "Reading-room catalogue"**

A restrained catalogue for personal documents, lecture decks, and invoices. Lora gives titles a readable editorial voice; Inter keeps controls and dense source data direct. Graphite-violet surfaces keep the interface permanently dark. Purple gradients mark actions and selected destinations, following the user's explicit palette change.

**Key Characteristics:**

- Flat, rule-separated directories.
- Editorial titles with practical operational controls.
- Lavender text and purple gradient actions on dark violet neutrals.
- Responsive navigation that preserves every destination.

The visual source of truth is `frontend/src/catalogue.css`, imported after `style.css`. The older stylesheet retains functional layout rules; its original purple dashboard styling is not a second visual authority. All display and UI fonts are self-hosted. No raster artwork ships in this redesign.

## Colors

Background, surface, raised, border, muted, accent, and ink correspond to the CSS custom properties in the frontmatter. Primary buttons and the search action use a 115-degree gradient from action-start to action-end; their text uses action-ink. Active navigation uses a darker purple gradient from `#433052` to `#34263f`.

**The Permanent Dark Rule.** Keep the application shell dark at all times. Original source documents retain their own page colors so invoices and slides remain verifiable.

Warnings and errors retain amber and red semantics. User-chosen folder colors are stored document organization metadata and may vary independently of the chrome.

## Typography

Lora 400 is reserved for major page titles, folder names, dialog titles, and tool-section headings. Inter 400, 500, and 600 carries body content and controls. The root is 15px; search text is 15px on desktop and 14px on phones. Body explanations are generally 13–16px. Dense metadata is 10–12px and must remain secondary. Numeric amounts use tabular figures where supported.

At 800px and below, page titles become 38px; folder names are 23px on the stacked phone directory. Wrap long folder names. Truncate long document titles in rows and expose the source through the open-document control.

## Layout

The desktop rail is 254px, reducing to 218px at 1200px. Main content has a 1430px maximum width with 48px gutters, reducing to 30px and then 20–22px on phones. Related controls group tightly; sections separate by approximately 40px.

At 800px and below, replace the rail with four bottom destinations: Library, Documents, Bills, and More. More opens the full navigation drawer with focus containment, Escape dismissal, scroll locking, and focus restoration. At 500px and below, the two-column folder directory becomes one column. The search field remains sticky while the catalogue scrolls. Full-page screenshots may show fixed navigation at the original viewport boundary.

## Elevation & Depth

**The Flat Directory Rule.** Organize folders and document rows with rules and spacing instead of raised card shells.

Search uses a restrained offset soft shadow; dialogs and menus use stronger offset soft shadows to express temporary layers. Result panels use a single border. No decorative glass or glowing background is part of the system.

## Shapes

Folder entries and document rows have square rule-separated edges. Controls use 6px radii, search 10px, result panels 12px, and dialogs 16px. Small status chips use 4px radii. The logo is a simple outlined book mark from the existing Lucide icon system.

## Components

Primary buttons use the purple gradient, dark text, and a 42px minimum height. Secondary actions use transparent backgrounds and a fine border. Hover brightens primary gradients; keyboard focus uses a 2px accent outline with a 4px offset. Disabled controls lose opacity and do not accept input.

Search has a large input, a distinct submit control, and a keyboard shortcut on desktop. Phone search retains the input and action while hiding the shortcut. Amount matching options remain in a disclosure below the field.

Folder entries use a Lora title, an unobtrusive user-colored icon, document count, update date, and onward arrow. Hover or focus changes the reading surface; hover moves the onward arrow 3px diagonally. Navigation transitions use 180ms ease-out. Reduced-motion removes transitions.

Results show an answer tied to cited sources, actual invoice amounts, and source passages. They use lavender text on dark panels, never styling similarity as certainty. The original source viewer preserves white PDF pages and yellow evidence highlights. Uploads, backup tools, and invoice forms share the same field and button grammar.

## Do's and Don'ts

- **Do** preserve the user's always-dark commitment and purple gradient actions.
- **Do** use live library data and retain source-document fidelity.
- **Do** use Lora for editorial titles and Inter for working controls.
- **Do** retain visible keyboard focus and reduced-motion support.
- **Don't** restore green-tinted chrome or a light application shell.
- **Don't** turn the folder directory into nested generic cards.
- **Don't** replace actual source values with a user's approximate search amount.

Some source-viewer labels still inherit legacy eyebrow styling; this is not a reusable heading pattern. The detector's Inter overuse advisories are retained as a deliberate control-legibility tradeoff, paired with the distinctive Lora display face.

## Simplified library surface
Preserve the reading-room palette and fonts. Keep three primary navigation choices and one collapsed Settings disclosure. Use compact folder rows and topic links instead of large cards on home; show source scan status in a single neutral row. Setup and secondary scan controls use native details/summary disclosures. Search remains the largest interactive control; Add documents is the sole primary header action. Remove redundant workspace identity, privacy blocks, footers and search examples.

## Organization controls

Recovery controls use the same dialog and button styles as organization. Show the source problem, expected location and next action in plain language. Keep source paths wrapping on narrow screens. Separate extraction repair from source reconnection; keep technical errors in disclosures. Indexing activity shows actionable recovery below the affected filename. Never label a failed queue as all caught up.

Use row checkboxes and a compact contextual action row for bulk moves and topic edits. Keep selection counts explicit. Document menus expose Move to folder, Edit topics and Rename display name; result cards expose Organize. The move form includes destination-folder creation and offers undo after completion. The topic editor uses searchable labelled checkboxes with selected-topic chips, custom topic creation and explicit restoration of automatic suggestions. Saved display names remain separate from original filenames. Keep the primary save action sticky within the scrolling organization form on narrow screens. Preserve the existing reading-room palette and fonts.

## Continuous PDF reader

Search results show full-width source pages, capped at 1000 CSS pixels, with translucent yellow passage highlights. Keep page number and highlight status above each preview. Extracted text is collapsed under Matched text. Preserve file metadata, selection and Open at page actions. Show explicit loading, retry and unavailable-source states; previews have no nested scrolling region.
Use the bundled Mozilla PDF.js PDFViewer in vertical scroll mode. Source pages keep their original white background; the reader chrome retains the dark violet palette. Keep one scrolling document region, a fixed page/zoom toolbar, and the existing document-context pane. Fit width responds to window resizing. The current physical page follows scroll position.

## Khoj v0.5 simplification

Keep the reading-room palette and typography. Use the same purple book mark for native icon and SVG brand/favicon, with Khoj v0.5 identity. Search is the first interaction, with a text-labelled Search button. Show highlighted original pages before optional explanations. Group secondary result controls under More options; hide scores under Search details. Settings uses plain-language links and closed disclosures for privacy, updates, support reports and Advanced settings. Hardware and file metadata stay collapsed. On narrow screens the recently-added heading has a full row and filters wrap below it.
