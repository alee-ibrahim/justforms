# Submissions viewer

Two ways to read submissions that look like the form people filled in, instead of a list of
label/value rows:

1. **Form view**: one submission laid out as the filled form (same pages, sections,
   half-width pairs, logo, title, language and direction), read-only, on its own linkable page.
2. **Cards**: the Submissions page can show a grid of cards instead of the table; each card
   carries the answers that identify the submission.

Replaces the detail `Sheet` of [PHASE-2-SCREENS.md](PHASE-2-SCREENS.md) §5.3 and the phone item
list of §5.3; adds to [PHASE-3-SCREENS.md](PHASE-3-SCREENS.md) (files, signatures, integrity,
activity, filters and bulk actions are unchanged and reused). Tokens, type and motion come from
[DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with [REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md).
Copy in "quotes" ships as written, English only; form content (labels, answers, titles) takes
`lang`/`dir` from the submission's form version.

Nothing new from shadcn: `tabs`, `toggle-group`, `switch`, `badge`, `card`, `item`,
`dropdown-menu`, `select`, `button-group`, `kbd`, `tooltip`, `separator`, `skeleton`, `empty`
and `alert` are installed.

## 1. Form view

### 1.1 Route and flow

- Route `/forms/$formId/submissions/$ref`, where `$ref` is the reference number without the
  hash and padding (`/submissions/47` for `#0047`). A submission id (UUID) also works and is
  replaced with the reference in the address bar, so links from notification emails
  (`?open=<id>` on the list) keep working: the list forwards them here.
- The list's view state (status tab, search, filters, date range, version) travels in the
  search params of the viewer link, so Previous / Next walk the same filtered list the person
  was looking at, and "Back to submissions" returns to it with the row they opened focused.
- A full page on every screen size (no sheet): the answers need the form's width (40rem) plus
  room for the details, the page is linkable and printable, and Back works.
- Backend: `GET /forms/{id}/submissions/seq/{n}` returns the same detail as
  `GET /submissions/{id}` (viewer role or above).

### 1.2 Desktop (≥ lg, 1024px)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ Forms / Youth programme application      Edit  Preview  Share  Submissions                │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ [‹ Submissions]                                         12 of 48  [‹ Previous] [Next ›]   │
│ #0047  ◐ In review  Step 1 of 2                                                           │
│ Submitted 23 Oct 2026 09:03, by ✓ aminath@example.org, version 4                          │
│ [Status: In review ▾]   [Print]  [Download PDF]  [✓ Integrity verified]                   │
├────────────────────────────────────────────────────────────┬─────────────────────────────┤
│   ┌───────────────── sheet (form theme, 40rem) ─────────┐   │ [Details] [Activity 3]      │
│   │ [logo]                                              │   │ ┌ Approval ──────────────┐ │
│   │ Youth programme application                        │   │ │ 1. Director  Waiting…  │ │
│   │─────────────────────────────────────────────────────│   │ └────────────────────────┘ │
│   │ About you                          (page title)     │   │ Hidden values              │
│   │ Full name                │ Date of birth            │   │   campaign   spring        │
│   │ Aminath Ali              │ 3 Feb 2004               │   │ Audit details              │
│   │ ─────────────────────────┼───────────────────────── │   │   Content hash 3f9a…c21e   │
│   │ Phone                                               │   │   ...                      │
│   │ +960 777 1234                                       │   │                            │
│   │ ─────────────────────────────────────────────────── │   │                            │
│   │ Track                                               │   │                            │
│   │ [✓ Technology] [✓ Other: Marine biology]            │   │                            │
│   │ About you ▸ section (start border, indented)        │   │                            │
│   │ Dependents                                          │   │                            │
│   │  ┌ Dependent 1 ───────────────────────────────────┐ │   │                            │
│   │  │ Name  Aisha        Relationship  Child         │ │   │                            │
│   │  └────────────────────────────────────────────────┘ │   │                            │
│   │ Documents                     (page 2, stacked)     │   │                            │
│   │ Copy of ID card  [thumb id-front.jpg 1.2 MB ⤓]      │   │                            │
│   │ Signature  [signature on white] statement, audit    │   │                            │
│   └─────────────────────────────────────────────────────┘   │                            │
└────────────────────────────────────────────────────────────┴─────────────────────────────┘
```

- Two columns: the desk with the sheet (flexible), and a 22rem aside flush to the end edge
  (`border-s`, `bg-card`, no radius, scrolls with the page, sticky below the header on tall
  screens). The aside holds `Tabs` "Details" | "Activity {n}".
- **Header** (studio chrome, English, LTR):
  - Row 1: `Button variant="ghost" size="sm"` "Submissions" with a start chevron (link back to
    the list with the same search). At the end: position "12 of 48" (muted, `tabular-nums`,
    hidden when the submission is not in the current list), `ButtonGroup` with
    `Button variant="outline" size="sm"` "Previous" / "Next" (chevrons, disabled at the ends,
    `Tooltip` with the `Kbd` K / J).
  - Row 2: `h1` reference `#0047` (`text-xl`, `tabular-nums`), `SubmissionStatusBadge`, and
    "Step 1 of 2" (muted) while an approval runs.
  - Row 3: metadata as separate spans joined with commas: "Submitted {date time}", ", by
    {email}" (`BadgeCheckIcon`, tooltip "Signed in" / "Email confirmed with a code"),
    ", version {n}".
  - Row 4: actions. Status `Select` "Status: In review" (editors and owners only; disabled
    with the note "The status changes when the approval finishes." while an approval runs;
    "Rejected" opens the reason field inline, as in PHASE-2 §5.3). `Button variant="outline"
    size="sm"` "Print". `PdfButton` (Download PDF / Preparing PDF / Create PDF). Integrity
    `Badge` + `HoverCard`. Viewers see "You can view submissions. Ask an owner to change
    status." instead of the `Select`.
  - A failed integrity check also shows the destructive `Alert` under the header.
- **Sheet**: the same frame as the public page: `bg-card`, `rounded-md border`, padding 20px
  phone / 40px desktop, max width from the form theme (`--df-page-width`, default 40rem),
  inside the theme scope (`themeScope` of the form theme: colours, fonts, radius, density,
  colour scheme), with `contentProps(formLanguage(schema))` and `DirectionProvider`. Header =
  the renderer's `FormHeader` (logo at the theme's size and place, title, no description, no
  header image: it pushes the answers below the fold).
- **Pages are stacked**: every page the respondent went through, in order, separated by a
  `Separator`; its title as the public page title (`text-xl`). No progress bar, no Back/Next.
  Pages the logic skipped are left out unless they hold answers (imports).
- **Questions** keep the form's grid: `QuestionGrid` + `widthClass` from the renderer, so
  half-width questions pair on the sheet ≥ 32rem and stack on phones, exactly as filled.
  Each question is a `dt`/`dd` pair inside the page's `dl`:
  - label: `text-sm font-medium text-muted-foreground` (the printed part of the form),
  - answer: `text-base` in Ink, on a ruled answer line (`border-b` hairline, 6px under the
    text), like ink on a paper form. Help text, placeholders and requirement marks are not
    shown.
- **Sections**: the section title (`text-lg`) and the start border + indent the public form
  uses (`@min-[32rem]:border-s ps-4`). **Content blocks**: headings and paragraphs render as on
  the form (they give the answers their context); dividers as `Separator`; images are skipped.
- **Repeaters**: the repeater label, then one block per row stacked (`rounded-md border p-4`),
  titled "Dependent 2" (from the add-button text) or "Entry 2", holding the row's questions in
  the same grid. "No entries" when empty.
- **Skipped questions** (hidden by logic for this respondent) are left out, like the filled
  form. When there are any, a `Switch` "Show skipped questions ({n})" above the sheet shows
  them with the muted answer "Skipped (not shown to the respondent)".
- **Hidden values** (`hidden` questions) are not on the sheet: they are listed under
  "Hidden values" in Details (key in mono, value).

### 1.3 Answers by type

| Type | Shown as |
|---|---|
| Short text | text, `displayText` for dv, `whitespace-pre-wrap` |
| Long text | paragraphs, line breaks kept (`whitespace-pre-wrap`), max 36rem |
| Email | `mailto:` link, `<bdi dir="ltr">` |
| Phone | grouped "+960 777 1234" (`formatPhone`), `tel:` link, `<bdi dir="ltr">` |
| Number | `tabular-nums`, `<bdi dir="ltr">` |
| Date | "3 Feb 2004" (English, Western digits, date only; no time-zone shift), `<bdi dir="ltr">` |
| Time | "14:30", `<bdi dir="ltr">` |
| Single choice, dropdown | the chosen option as a chip: `Badge variant="secondary"` with `CheckIcon`; a typed "Other" answer as chip "Other: {text}" ("Other" is English, `<En>`; the text keeps the form's direction) |
| Multi choice | one chip per chosen option, in the form's option order, then the Other chip; chips wrap |
| Yes / no | chip "Yes" (`CheckIcon`) or "No" (`XIcon`), English |
| Rating | "4 out of 5" with the stars drawn (filled up to the answer), `aria-label` "4 out of 5" |
| File | one card per file, the whole card is the target (≥ 44px, keyboard reachable): images show a 64px thumbnail and "Open", which shows a larger preview in a `Dialog` with [Download]; other files (PDF, Word, …) show a type icon and "Download" and download on tap. Names wrap (`break-all`), never run off a phone screen |
| Signature | `SignatureBlock`: image on white paper, statement, audit rows |
| Sensitive (any type) | masked `••••567`, lock icon, link `Button` "Show" (editors and owners; tooltip "Viewing is recorded"); viewers see "Sensitive" |
| Empty | muted "No answer" |

### 1.3.1 Imported submissions

- The header's "Submitted" time is the submission's own `submitted_at` (for imports, the
  original Jotform time), as in the lists, cards, filters, sorting and exports. The import time
  is a secondary detail: ", imported {date time}" at the end of the metadata line, and the
  activity's first entry reads "Imported from Jotform" (not "Submitted").
- Copies of imported files and signatures (`importedFiles`) show **with their questions** on the
  sheet, as file cards; imported signatures carry an "Imported" badge and "Image from Jotform,
  not captured by JustForms".
- Details › "Imported from Jotform": the Jotform submission id on its own line (`break-all`),
  "Imported {date time}", files of questions no longer on the form, and links not copied yet
  (wrapping).

### 1.4 Phones and tablets (< lg)

```
┌──────────────────────────────┐
│ [‹ Submissions]   [‹] [›]    │  icon-only Prev/Next with tooltips
│ #0047  ◐ In review           │
│ Submitted 23 Oct 2026 09:03, │
│ by aminath@example.org, v… │
│ [Status: In review ▾]        │
│ [Print] [Download PDF] [✓…]  │
│ [Answers][Details][Activity 3]│ Tabs, full width
│┌────────────────────────────┐│
││ [logo]                      ││ sheet full-bleed (no desk edge
││ Youth programme application ││ under 640px), the form's grid
││ Full name                   ││ stacks
││ Aminath Ali                 ││
││ ─────────────────────────── ││
│└────────────────────────────┘│
└──────────────────────────────┘
```

- The aside's two tabs join the sheet as a third: "Answers" | "Details" | "Activity {n}".
- The sheet is full-bleed under 640px (no border, no radius), as on the public form.
- All controls 44px tall on touch screens (existing `pointer-coarse` rules).

### 1.5 RTL (dv form)

Only the sheet mirrors: labels and answers start at the right, the section border is on the
right, repeater blocks and chips flow right to left, Thaana at the dv scale. Emails, phone
numbers, dates, numbers and the masked value are `<bdi dir="ltr">`; "Yes", "No", "Other",
"No answer", "out of" are English `<En>` runs. The header, actions and aside stay English LTR.

### 1.6 Details and Activity

- **Details**: the "Imported from Jotform" note, the approval block (`ApprovalBlock`, with
  "Send the email again" and "Stop approval" for editors), "Hidden values", and the existing
  `AuditDetails` (hashes, chain, PDF hash) at the end.
- **Activity**: the comment box (`CommentBox`: "Add a comment", Ctrl/⌘+Enter) above the
  activity list (`ActivityList`), unchanged. Viewers can comment.
- A header `Button variant="outline" size="sm"` "Comment" switches to Activity and focuses the
  comment field.

### 1.7 Print

"Print" calls `window.print()`. The print stylesheet prints only the viewer's print root: the
reference, status, submitted line and respondent, then the sheet with every page. Studio
header, form bar, actions, tabs, aside and the skipped-questions switch are not printed. The
sheet prints without border or desk, in the light scheme, at full paper width; repeater blocks,
signatures and file rows avoid page breaks inside (`break-inside: avoid`). Sensitive answers
print masked unless revealed.

### 1.8 Navigation and keyboard

| Key | Action |
|---|---|
| J | Next (older) submission in the current list |
| K | Previous (newer) submission |
| Esc | Back to submissions (not while typing or with a menu open) |

- Keys are ignored while typing in an input, textarea or contenteditable.
- At the end of the loaded list, Next loads the next page of the list and moves on.
- After moving, focus goes to the `h1` (reference), and a polite live region says "#0046".
- "Back to submissions" focuses the row (or card) of the submission last viewed.

### 1.9 States

| State | Treatment |
|---|---|
| Loading | header `Skeleton`s and a sheet with 6 `Skeleton` blocks after 300ms |
| Not found / no access | `Empty` "Submission not found" / "It was deleted, or you don't have access to it." [Back to submissions] |
| Error | `Alert variant="destructive"` "Couldn't load this submission. Check your connection." [Try again] |
| Integrity failed | destructive `Alert` under the header (PHASE-3 §1) |

## 2. Cards

### 2.1 Toggle

```
[🔍 Search answers  /] [+ Filter] [Submitted ▾] [Version ▾]      [Card fields ▾] [▦ Table|▤ Cards]
```

- `ToggleGroup type="single" variant="outline" size="sm"` with "Table" (`TableIcon`) and
  "Cards" (`LayoutGridIcon`), visible ≥ md, at the end of the filter row. "Columns" shows in
  Table view, "Card fields" in Cards view.
- The choice is remembered per user per form in `localStorage`
  (`justforms:submissions-view:{userId}:{formId}`). Default Table.
- Phones (< md) always show cards (one column); the toggle and the pickers are not shown.
- Filters, search, status tabs, date range, version, "Load older", selection and bulk actions
  are shared by both views (same query, same selection).

### 2.2 Card

```
┌──────────────────────────────────────────┐
│ ☐ #0047                      ◐ In review │
│ 23 Oct 2026 09:03, step 1 of 2           │
│                                          │
│ Full name        Aminath Ali             │
│ Email            aminath@example.org     │
│ Phone            +960 777 1234           │
│ Track            Technology              │
│                                          │
│ 📎 2 files   ✍ Signed   aminath@ex…      │
└──────────────────────────────────────────┘
```

- `Card` (`gap-3 py-4`, hairline border, no shadow) on the desk. The reference is a link to
  the form view whose hit area covers the whole card (`after:absolute after:inset-0`); the
  selection `Checkbox` (editors, ≥ md) sits above it (`relative z-10`) with the label
  "Select #0047". Keyboard: Tab reaches the checkbox and the link; focus ring on the card
  (`has-[a:focus-visible]:ring-3`).
- Top row: checkbox, reference (`font-semibold tabular-nums`), status badge at the end.
- Second row (muted, `tabular-nums`): submitted time, ", step 1 of 2" while an approval runs.
- Answers: a `dl` grid `grid-cols-[minmax(0,8rem)_minmax(0,1fr)]`, label muted `text-sm`,
  value `text-sm` truncated to one line (long text: two lines), `lang`/`dir="auto"` per value;
  sensitive values masked with the lock icon. Empty answers show "-".
- Footer (only when there is something): `PaperclipIcon` "{n} files", `SignatureIcon`
  "Signed", the respondent email (`bdi dir="ltr"`, truncated) when the form confirms addresses.
- The card of the submission last viewed has the marker wash (as the open row had).
- Grid: 1 column < md, 2 columns ≥ md, 3 columns ≥ xl (`grid gap-3`).

### 2.3 Which answers a card shows

- **Automatic** (no choice saved): up to four top-level questions in form order: the first
  short text (preferring one whose label or key says "name"), the first email, the first
  phone, and the first single choice, dropdown or yes/no. If fewer than four are found, the
  next short questions fill the rest. Never long text, files, signatures or hidden values.
- **Chosen**: editors and owners pick in a `DropdownMenu` "Card fields": label "Show on cards",
  one `DropdownMenuCheckboxItem` per top-level question (form language, `bdi`), up to six
  (others disabled with "Up to 6 on a card"), separator, "Use automatic choice". The choice is
  saved to the form (`PATCH /forms/{id}` `cardFields`, stored in the form's settings), so
  everyone sees the same cards. Toast on failure: "Couldn't save the card fields. Try again."
  Viewers see the cards but not the picker.
- Questions removed from the form drop out; if none remain, the automatic choice applies.

### 2.4 States

Same as the table (PHASE-2 §5.4): 6 card `Skeleton`s after 300ms; "No submissions match these
filters." [Clear filters] in place of the grid; error `Alert` above.

## 3. Table

Unchanged, except that a row opens the form view (Enter or click) instead of the sheet, and the
row of the submission last viewed is focused and washed when coming back.

## 4. Self-critique

| First idea | Problem | Changed to |
|---|---|---|
| Keep the sheet and render the form inside it | 40rem sheet in a 42rem panel leaves no room for details; not linkable; printing a sheet overlay is fragile | A page with the sheet and an aside; the same page on phones |
| Run the real renderer with disabled inputs | Disabled inputs are low-contrast and read as "you can't do this"; empty selects and radio rows waste space; screen readers announce dozens of disabled controls | Read-only `dt`/`dd` pairs on the form's own grid, answers in Ink on a ruled line |
| Labels at the public size (`text-lg` 600), answers below | The answer is what a reviewer reads; big labels drown it | Labels small and muted (the printed part), answers at body size in Ink (the written part) |
| Show every option of a choice with ticks | Long option lists bury the answer | Only chosen options, as chips with a tick |
| Show skipped questions inline as "Skipped" | Clutters the sheet with questions the respondent never saw | Hidden by default, one switch to show them |
| Card grid with identical shadowed cards | SaaS-kit tell (FORMS-LIST §6) | Hairline cards on the desk, no shadow, content-first (answers as a short `dl`), marker wash only for the last viewed |
| Card fields per person in `localStorage`, like columns | A team reviewing the same form should see the same cards | Saved on the form by editors; the view choice (table or cards) stays personal |
