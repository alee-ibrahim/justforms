# Phase 3 screens

Additions to [PHASE-2-SCREENS.md](PHASE-2-SCREENS.md) §5 (submissions) for the Phase 3 build:
files and signatures in the detail view, the integrity badge and signed PDF, checking a PDF,
the activity log and comments, filters, the column picker, bulk actions and the Excel export.
Tokens, type and motion come from [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with
[REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md). Conventions are the same as in PHASE-2-SCREENS:
**[add]** marks a shadcn component to add with the CLI, copy in "quotes" ships as written,
studio copy is English only, and form content (labels, answers) takes `lang`/`dir` from the
submission's form language.

Nothing new needs adding from shadcn: `calendar`, `checkbox`, `dialog`, `dropdown-menu`,
`hover-card`, `popover`, `progress`, `radio-group` and `alert-dialog` are already installed.

## 1. Detail view additions

```
┌──────────────────────── Sheet (end edge) ────────────────────────────────┐
│ #0047   ◐ In review                         [‹ Prev] [Next ›]  [✕]        │
│ Submitted 23 Oct 2026 09:03, version 4, Dhivehi                          │
│ [✓ Integrity verified]  [Download PDF]                                   │
│ [Status: In review ▾]                                                    │
│──────────────────────────────────────────────────────────────────────────│
│ [Answers] [Activity 3]                                                   │
│  Copy of ID card    ┌────────────────────────────────────┐               │
│                     │ [thumb] id-front.jpg  1.2 MB   [⤓] │  Item, outline│
│                     └────────────────────────────────────┘               │
│  Signature          ┌────────────────────────────────────┐               │
│                     │        ~~~ signature image ~~~     │  Card, sheet  │
│                     │ ────────────────────────────────── │  baseline     │
│                     └────────────────────────────────────┘               │
│                     I confirm the information is true.     statement     │
│                     Signed      23 Oct 2026 09:02:51                     │
│                     Received    23 Oct 2026 09:03:02                     │
│                     IP address  203.0.113.7                              │
│                     Device      Mozilla/5.0 (iPhone …)   (truncated, Tooltip full)
│                     Strokes     sha256 3f9a…c21e         mono            │
└──────────────────────────────────────────────────────────────────────────┘
```

- **Files**: `Item variant="outline" size="sm"` rows: 32px thumbnail (`ItemMedia
  variant="image"`, `?preview=1`) for PNG/JPEG/GIF/WebP, otherwise a PDF or file icon; name
  in `<bdi dir="auto">`; size; icon-only download `Button` with `Tooltip` "Download".
- **Signature**: the server-rendered PNG on a `Card` (Sheet background, never inverted in
  dark mode: the card stays white so the ink reads as ink; the baseline hairline at 70%).
  Under it a definition list (`<dl>` grid, muted labels): "Signed", "Received", "IP address",
  "Device", "Strokes". Times in the studio's local time with seconds, `tabular-nums`. The
  statement (attestation) is form content: `lang`/`dir` of the form. "Strokes" shows the
  first 4 and last 4 hex digits of the SHA-256 in mono with a `Tooltip` holding the full hash.
- **Integrity badge** (`Badge variant="outline"`, left of the PDF button):
  - verified: check icon + "Integrity verified"; `HoverCard` text: "The answers, files and
    signatures match the fingerprint taken when this was submitted, and the activity log is
    unbroken."
  - failed: `Badge variant="destructive"` with x icon + "Integrity check failed"; HoverCard:
    "Something changed this submission outside JustForms after it was submitted. Download the
    PDF and contact your administrator." Failed also shows above the tabs as
    `Alert variant="destructive"`.
  - checking: no badge until the check returns (it is fast; no skeleton).
- **PDF button** (`Button variant="outline" size="sm"`, file icon):
  - ready: "Download PDF" (link to the PDF endpoint, `download`).
  - pending: disabled, `Spinner` + "Preparing PDF"; the sheet polls every 2 s.
  - none (no signature on the form): "Create PDF" starts generation, then behaves as pending.
  - failed: "Create PDF again" + muted text "Couldn't create the PDF."
  - Toast when a PDF the user asked for becomes ready: "PDF ready" with action "Download".

## 2. Activity and comments

```
 [Answers] [Activity 4]
 ┌──────────────────────────────────────────────────────────┐
 │ 💬 Aminath Ali commented                  Today 10:14    │
 │    Called the applicant, documents are fine.             │
 │ ⇄ Aminath Ali changed status to Approved   Today 10:15   │
 │ 📄 Signed PDF created                      Today 09:03   │
 │ ✚ Submitted                                Today 09:03   │
 └──────────────────────────────────────────────────────────┘
 Add a comment
 [__________________________________________] [Comment]
```

- `ItemGroup` of `Item size="sm"` rows, newest first: icon (`ItemMedia variant="icon"`),
  `ItemTitle` "{actor} commented" / "{actor} changed status to {status}" / "Submitted" /
  "Signed PDF created" / "Exported to Excel by {actor}" / "{actor} viewed a sensitive answer",
  `ItemDescription` the comment text (`whitespace-pre-wrap`) or the reason for a rejection,
  time at the end (`tabular-nums`, muted).
- Comment composer below the tabs, always visible on the Activity tab: `Field` with
  `FieldLabel` "Add a comment", `Textarea` (rows 2, max 4000), primary `Button size="sm"`
  "Comment" (disabled while empty or sending). Ctrl/⌘+Enter sends. Toast "Comment added".
  Viewers can comment (DESIGN 7).
- Comments are plain text, never Markdown or HTML.
- Empty: "No activity yet." (cannot normally happen: "Submitted" is always there).

## 3. Check a PDF

Entry: `Button variant="outline"` "Check a PDF" in the submissions page header, next to
Export. Opens a `Dialog`:

```
┌ Check a signed PDF ─────────────────────────────────────┐
│ Find out whether a PDF from JustForms is genuine and       │
│ unchanged, and whether it still matches the submission.  │
│ ┌ - - - - - - - - - - - - - - - - - - - - - - - - - ┐    │
│ ┆  Drop a PDF here or [Choose PDF]                    ┆    │
│ └ - - - - - - - - - - - - - - - - - - - - - - - - - ┘    │
│ ┌ ✓ Genuine and unchanged ─────────────────────────┐    │
│ │ Submission #0047, Youth programme application      │    │
│ │ Signed 23 Oct 2026 09:03 by this JustForms install   │    │
│ │ Matches the submission as it is stored now.        │    │
│ │ Key fingerprint 7C:1E:…:A0          (mono)         │    │
│ └────────────────────────────────────────────────────┘    │
│                                        [Check another]   │
└──────────────────────────────────────────────────────────┘
```

- Drop area is `Empty` (dashed) + `Button` that opens a hidden `accept="application/pdf"`
  input, as in the public file upload. Checking shows `Spinner` + "Checking".
- Results (`Alert`, with icon, title and a short `<dl>`):
  - "Genuine and unchanged" (default variant, check icon).
  - "Changed after signing" (destructive): "The PDF's signature does not cover its current
    contents. Someone edited the file."
  - "Not signed by this JustForms" (destructive): "The PDF is signed, but not with this
    install's key." / "This PDF has no digital signature."
  - "Doesn't match the stored submission" (destructive): "The PDF is genuine, but the
    submission's data has changed since it was signed."
  - "Submission not found" (destructive): "The PDF is genuine, but its submission was deleted
    or you don't have access to it."
- The same check runs on the command line: `justforms verify-pdf file.pdf`.

## 4. Filters

```
 [🔍 Search answers   /] [+ Filter] [Submitted: Any time ▾] [Version: All ▾] [Columns ▾]
 [Age at least 18 ✕] [Track is Technology ✕] [Clear filters]
```

- "Filter" `Popover` with a three-step row: question `Select` (questions of the latest
  version, top level, in form order; labels in `<bdi dir="auto">` with the form's `lang`) →
  operator `Select` that depends on the type → value control → [Add filter]:
  - text, email, phone: "contains" + `Input`;
  - number, rating: "is", "at least", "at most" + `Input type=number`;
  - date: "on or after", "on or before" + `Input type=date`;
  - single choice: "is" / "is not" + option `Select`; multi choice: "includes" + option
    `Select`;
  - yes/no: "is" + `Select` Yes / No;
  - file, signature: "has an answer" / "has no answer" (no value).
- Active filters show as `Badge variant="outline"` chips that read as a sentence, each with
  an icon `Button` (aria-label "Remove filter: {sentence}"). "Clear filters" is a link
  `Button` after the chips.
- "Submitted" `Popover` with presets ("Any time", "Today", "Last 7 days", "Last 30 days")
  as a `RadioGroup`, and a `Calendar mode="range"` for a custom range.
- "Version" `Select`: "All versions", "Version 3", …
- Filters, status tab and search live in the URL search params so a filtered view can be
  shared and Back works.
- Phones: the filter row collapses to [Filter (2)] which opens the same controls in a
  `Drawer`.

## 5. Columns

- `DropdownMenu` "Columns" with a `DropdownMenuCheckboxItem` per top-level question
  (label in the form's language), then a separator and "Reset columns".
- Default: the first three questions that are not long text, files or signatures.
- Persisted per user per form in `localStorage` (`justforms:columns:{userId}:{formId}`).
- Sensitive columns stay masked in the table whatever the picker says.

## 6. Selection and bulk actions

- A `Checkbox` column at the start of the table; the header checkbox selects the loaded
  rows (indeterminate when some are). Phones: no bulk actions.
- With rows selected, a bar replaces the filter row:

```
 │ 3 selected   [Change status ▾] [Export selected] [Delete]          [Clear selection] │
```

- "Change status" `DropdownMenu` (New, In review, Approved, Rejected). Rejected opens a
  `Dialog` "Reject 3 submissions" with a required `Textarea` "Reason (added to each activity
  log)" and [Reject 3] (destructive). Others apply at once. Toast "Changed 3 submissions to
  Approved".
- "Delete" (owners only) opens `AlertDialog` "Delete 3 submissions?" / "They are removed
  from lists and exports now and erased for good after 30 days." [Delete 3] (destructive).
  Toast "Deleted 3 submissions".
- Viewers see neither the checkbox column nor the bar.

## 7. Export to Excel

Entry: `DropdownMenu` "Export" in the page header: "Export all matching (48)" and, with a
selection, "Export selected (3)". Both open the same `Dialog`:

```
┌ Export to Excel ────────────────────────────────────────┐
│ 48 submissions, with every question from all versions.   │
│ Repeaters go to their own sheets.                        │
│ ⚠ Includes sensitive answers: National ID number.        │  Alert, only if any
│   Store the file somewhere safe.                         │
│                                                          │
│ ████████████░░░░░░  Preparing export                     │  after Export
│                                     [Cancel] [Export]    │
└──────────────────────────────────────────────────────────┘
```

- Headers use the form's own language (forms have one language; the per-export language
  choice in PHASE-2-SCREENS 5.2 is dropped).
- After "Export": `Progress` (indeterminate until the worker reports a row count, then rows
  done / total) and "Preparing export". When done: "Your export is ready" with a primary
  [Download] button; closing the dialog early leaves the job running and shows a toast
  "Export ready" with "Download" when it finishes.
- Failed: `Alert variant="destructive"` "Couldn't create the export. Try again." + [Try again].
- The download is an `.xlsx` that expires after 24 hours ("Available for 24 hours").

## 8. Forms list

- Replace the "Version" column with "Submissions": the number of new submissions as a
  `Badge` (default variant, dot) when > 0, then the total in muted text, e.g.
  `[● 3 new] 48`. Unpublished forms show "-" with no badge. (Fixes P3-9 of the Phase 2
  review.)

## 9. Builder: signature question

- "Signature" is enabled in the palette (group Other). Inspector adds "Statement above the
  pad" (form-language `Textarea`), description "For example: I confirm the information in
  this form is true. It is printed with the signature in the signed PDF."
- A form with a signature creates a signed PDF for every submission (shown in the detail
  view as above).

## 10. People with access (per-form roles)

A card on the Share page, after "Versions", visible whether or not the form is published:

```
┌ People with access ──────────────────────────────────────────┐
│ Who can open this form in JustForms. Organisation admins can     │
│ always open every form.                                        │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ (AA) Aminath Ali  aminath@example.org     Owner (admin)  │   │  Item, not editable
│ │ (IN) Ibrahim N.   ibrahim@example.org     [Editor ▾] [✕] │   │  Select + icon Button
│ │ (MH) mariyam@example.org      [Submissions viewer ▾] [✕] │   │
│ └──────────────────────────────────────────────────────────┘   │
│ [ name@example.org ] [Submissions viewer ▾] [Add]              │  InputGroup-free row
│ A submissions viewer can view and export submissions, but      │
│ can't edit the form. Editors also edit the form and change     │
│ status.                                                        │
│ Owners also manage access and delete.                          │
└───────────────────────────────────────────────────────────────┘
```

- `Card` like the other Share cards; people as `Item size="sm"` rows with `Avatar`
  initials, `ItemTitle` name (or email), `ItemDescription` email, and at the end either a
  role `Select` (Owner, Editor, Submissions viewer; API value `viewer`) plus an icon `Button` "Remove {name}" with
  `Tooltip`, or a muted "Owner (organisation admin)" for admins.
- Add row: `Input type="email"` with label "Add someone by email" (visually hidden label
  only if the placeholder repeats it; keep a visible `FieldLabel`), role `Select` defaulting
  to Submissions viewer, `Button` "Add". Only people who already belong to the organisation can be
  added; otherwise `FieldError`: "No one with that email is in your organisation. Ask an
  admin to add them first."
- Every change saves at once; toast "Access updated". Removing yourself as an owner asks
  first (`AlertDialog` "Remove your own access?").
- Editors and viewers see the list read-only (no selects, no add row) with the note "Only
  owners can change who has access."
- The form must keep at least one owner: the last owner's select and remove button are
  disabled with tooltip "A form needs at least one owner".

## 11. Self-critique

First ideas and what changed:

| First idea | Problem | Now |
|---|---|---|
| A full-width green "Verified ✓" banner on every submission | Second saturated colour; shouts about the normal case | Quiet outline badge; only failure gets the stamp colour and an Alert |
| Show the signature image inverted in dark mode | Ink would turn light; looks like a different signature | The signature card stays paper-white in both modes |
| Raw event types in the activity list (`status_changed`) | System vocabulary | Sentences with the actor: "Aminath Ali changed status to Approved" |
| A separate "Verify" page | One more place to find | A dialog on the submissions page, plus the CLI |
| Export language radio (from PHASE-2-SCREENS 5.2) | Forms have one language now | Dropped |
| Filter builder with nested AND/OR groups | Staff triage needs "narrow down", not logic | Flat list of chips, all must match |
