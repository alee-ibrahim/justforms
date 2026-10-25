# Import from Jotform

Teams leaving Jotform bring their forms and their submission history with them (DESIGN §13).
Two flows, both studio-only (nothing changes in the public bundle):

1. **Import a form**: paste a public link, paste or upload the HTML source, or use an API key.
   The studio shows the converted form and an import report, then creates an ordinary draft.
2. **Import responses**: on a published form, upload Jotform's Excel or CSV export, check how
   each column maps onto a question, preview, then import.

Tokens, type and motion come from [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); copy follows the
glossary in [PHASE-2-SCREENS.md](PHASE-2-SCREENS.md) §7 ("question", "page", "submission").
Review with [REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md). Copy in "quotes" ships as written,
English only. Form content inside previews follows the imported form's language
(`contentProps`). Nothing new from shadcn: `tabs`, `textarea`, `input`, `field`, `radio-group`,
`select`, `native-select`, `table`, `badge`, `alert`, `accordion`, `card`, `empty`, `item`,
`scroll-area`, `toggle-group`, `skeleton`, `spinner` and `separator` are installed.

## 1. Entry points

- **Forms list** header: an outline button "Import from Jotform" (`FileInputIcon`) before
  "New form". On phones the header wraps; both buttons stay 44px tall.
- **Forms list empty state**: under "Create your first form", a second line
  "Moving from Jotform? Import a form." with a link-style `Button` to the import page.
- **New form dialog**: no change in this round (keeps the dialog short).
- **Submissions** header (owners of a published form): outline button "Import responses"
  (`UploadIcon`) next to "Check a PDF". In the "No submissions yet" empty state of a published
  form, the same action as a secondary button. Editors and viewers don't see it.

## 2. Import a form (`/forms/import/jotform`)

A studio page in the normal shell (`PageContainer`), not a dialog: the preview needs width.

### 2.1 Step 1: choose the source

```
 ← Forms
 Import from Jotform
 Bring a Jotform form into JustForms as an unpublished draft. Nothing is created until you
 check the result.

 ┌ Card ───────────────────────────────────────────────────────────────┐
 │ [ Link ] [ Source code ] [ File ] [ API key ]          (Tabs)       │
 │                                                                     │
 │ Form link                                                           │
 │ [ https://form.jotform.com/…                              ]         │
 │ The public link of the form, or just its number.                    │
 │                                                                     │
 │                                              [ Read form ]          │
 └─────────────────────────────────────────────────────────────────────┘
```

- `Tabs` (`TabsList` scrolls sideways on phones, 44px triggers):
  - **Link**: `Input type="url"` (`dir="ltr"`, `autoCapitalize="none"`, `spellCheck=false`),
    description "The public link of the form, or just its number. Only links on jotform.com
    work."
  - **Source code**: `Textarea` (mono, `rows=10`, `dir="ltr"`, `spellCheck=false`), description
    "In Jotform open Publish, then Platforms, then Source code, and copy everything. Saving the
    form's page from the browser works too."
  - **File**: a file `Input` (`accept=".html,.htm,.txt"`), description "An .html file of the
    form, up to 5 MB." The file is read in the browser and sent as text.
  - **API key**: `Input type="password"` "API key" + `NativeSelect` "Data region" (United
    States / Europe / HIPAA), then "List forms". The account's forms appear as a
    `RadioGroup` of `Item`s (title, "N submissions", status) in a `ScrollArea` capped at 20rem;
    choose one and "Read form". Description: "Find it in Jotform under Settings, API. JustForms
    uses it for this import only and never stores it."
- The primary button ("Read form") shows a `Spinner` while working; the tab content stays in
  place.
- Errors (`Alert variant="destructive"` above the button):
  - not a Jotform: "We couldn't find any Jotform questions in this. Paste the form's full
    source code, or its public link."
  - embed code with a link: "This is the embed code, not the form itself." with a link-style
    button "Read {url} instead" that switches to the Link tab and reads it.
  - fetch failed / not found / too large / timeout: "Jotform didn't send the form. Check that
    the link is public, or paste the source code instead."
  - not a jotform.com link: "Only links on jotform.com can be read. Paste the source code
    instead."
  - API key: "Jotform didn't accept this API key." / "Jotform is limiting requests. Wait a
    minute and try again."

### 2.2 Step 2: check the result

Desktop (≥ lg): two columns, report on the start side (24rem), the form preview on the end
side. Phones and tablets: `Tabs` "Report" | "Preview" above one column.

```
 Import from Jotform
 ┌ Card: Create the draft ─────────────────┐  ┌ Preview ──── [Phone|Desktop] ┐
 │ Title  [ Registration form          ]  │  │                               │
 │ Form language  ◉ English  ○ Dhivehi    │  │   (FormRenderer, preview)     │
 │ Detected from the text: English.        │  │                               │
 │ Collapsible sections become    [●━]     │  │                               │
 │ steps (pages)                            │  │                               │
 │ Each of the 5 sections is a step…       │  │                               │
 │ [ Create draft ]  [ Start over ]        │  │                               │
 └─────────────────────────────────────────┘  │                               │
 ┌ Card: Import report ────────────────────┐  │                               │
 │ 74 imported  5 changed  0 not imported  │  │                               │
 │ 79 Jotform questions became 5 pages,    │  │                               │
 │ 50 questions.                           │  │                               │
 │ ▸ Questions (79)          (Accordion)   │  │                               │
 │ ▸ Conditions                            │  │                               │
 │ ▸ Not imported                          │  │                               │
 └─────────────────────────────────────────┘  └───────────────────────────────┘
```

- **Create the draft** card: `Field` "Title" (`Input`, `contentProps(language)`), `FieldSet`
  "Form language" (`RadioGroup` English / Dhivehi, preselected from detection) with
  `FieldDescription` "Detected from the text: Dhivehi." When the choice differs from the
  detection: "Most of the text is in {detected}." Only when the Jotform form has collapsible
  sections: a horizontal `Field` with `Switch` "Collapsible sections become steps (pages)"
  (on by default when the form has no page breaks, DESIGN 13.6) and a `FieldDescription` that
  follows the choice: "Each of the {n} sections is a step with Next and Back, the way Jotform
  shows one section at a time." / "The {n} sections are shown open, one after another on the
  same page." Switching calls `PATCH /imports/{id}/options`; the report, the page count and the
  preview update in place (the switch is disabled while it saves; on failure an `Alert` "Couldn't
  change how sections are imported. Try again."). Buttons: primary "Create draft"
  (`Spinner` while saving) and ghost "Start over" (back to step 1, keeps the input).
- **Import report** card:
  - Summary: three `Badge`s with icon and word, never colour alone: `CheckIcon` "{n}
    imported" (secondary), `PencilIcon` "{n} changed" (outline), `XIcon` "{n} not imported"
    (destructive outline, only when > 0). One line under: "{q} Jotform questions became
    {pages} page(s), {fields} questions."
  - `Accordion type="multiple"`. "Changed or not imported ({n})" (only those rows) and "Not
    imported" are open by default; "All questions" opens by default only for forms of 20
    questions or fewer, so an 80-question report stays short:
    - **Changed or not imported ({n})** and **All questions ({n})**: a compact list
      (`Item size="xs"` rows in the report card) with the
      label (`bdi dir="auto"`, form language), "control_textbox → short text" in mono muted,
      a status badge and the notes as muted text. Phones: the same rows, wrapping.
    - **Conditions**: one row per Jotform condition with "Imported" / "Not imported" badge
      and the reason; or the note "The form's HTML has no conditions…".
    - **Not imported**: form-level things that never come across (theme, emails, thank-you
      page, cover image) as a plain list, then the report's notes (for collapsible sections:
      "Each of the {n} collapsible sections became a step (page) of its own…" or "Collapsible
      sections are shown open, one after another on the same page."). Each collapse row reads
      "Collapsible section became a new page" (note "Became a step…") or "…became a section".
- **Preview** card: `ToggleGroup` Phone/Desktop like Preview (PHASE-2 2.10), then the real
  `FormRenderer` in `mode="preview"` (uploads stay in the browser, nothing is posted). Phone
  frame: 390px wide, bordered.
- After "Create draft": toast "Draft created. Check it, then publish." and go to the builder.
- Errors: create failed: `Alert` in the create card "Couldn't create the draft. Try again."

## 3. Import responses (`/forms/$formId/submissions/import`)

A page inside the form layout (form tabs stay visible). Three steps; the current one is shown
as "Step 2 of 3: Match columns" (text, not a custom stepper).

### 3.1 Upload

```
 ← Submissions
 Import responses
 Step 1 of 3: Upload the export
 ┌ Card ──────────────────────────────────────────────────────────┐
 │ Jotform export (.xlsx or .csv)                                 │
 │ [ Choose file ]                                                │
 │ In Jotform open the form's Tables, then Download all, as Excel │
 │ or CSV. Up to 50 MB.                                           │
 │                                                                │
 │ Responses go into version 3, the published version.            │
 └────────────────────────────────────────────────────────────────┘
```

- Picking a file uploads it at once (`Spinner` "Reading the file…").
- Errors: "This file is empty." / "We couldn't read this file. Upload the .xlsx or .csv file
  Jotform gives you." / "The file is larger than 50 MB." / "The file has more than 100,000
  rows. Split it and import each part."
- Below the card, earlier imports into this form (if any) as `Item`s: "{file}, {n} imported,
  {date}".

### 3.2 Match columns

```
 Step 2 of 3: Match columns
 {file}, {rows} rows. We matched columns to questions by their names; check them.
 ┌ Table ─────────────────────────────────────────────────────────────┐
 │ Column in the file        Examples               Import into       │
 │ Submission Date           2025-03-14 09:12:44    [Submission date ▾]│
 │ Group Name                Riverside Volunteers   [Group Name     ▾] │
 │ Acronym                   RV                     [Don't import   ▾] │
 │ …                                                                  │
 └────────────────────────────────────────────────────────────────────┘
 Dates like 03/04/2025 are  ◉ Detect  ○ Month first  ○ Day first   (RadioGroup)
 New submissions get the status [ New ▾ ]
                                             [ Back ]  [ Preview ]
```

- Table on ≥ md; on phones each column is a `Card`-less stacked row (`Item`): header in bold,
  examples muted, `Select` full width.
- `Select` per column ("Import into"): groups "Questions" (every top-level question label,
  `bdi dir="auto"` in the form language, with its type muted), "Details" ("Submission date",
  "Jotform submission ID", "IP address"), and "Don't import". Questions already chosen by
  another column show "(already used)" and picking one shows the inline error "Two columns
  import into {label}. Choose one." (`FieldError`), which also disables Preview.
- When no column is the submission ID: `Alert` "No column holds the Jotform submission ID.
  Importing the same file twice will add the rows twice."
- Files and signatures: a note under the table when such a question is mapped: "Files and
  signatures stay on Jotform. JustForms keeps their links on each submission; Jotform links
  usually need you to be signed in to Jotform."

### 3.3 Preview and import

```
 Step 3 of 3: Check and import
 The first 20 rows, as they will be imported.
 ┌ Table (ScrollArea, sideways) ──────────────────────────────────────┐
 │ Row  Submission date   Group Name      Email         …             │
 │ 2    2025-03-14 09:12  Riverside…      hello@ex…                   │
 │ 3    2025-03-15 17:40  Hill Garden…    ⚠ Not imported: email       │
 └────────────────────────────────────────────────────────────────────┘
 1 cell in these rows can't be imported and will be left empty.
                                      [ Back ]  [ Import 4 rows ]
```

- Problem cells show `TriangleAlertIcon` + "Can't import" with the reason in a `Tooltip`
  (e.g. "Not a valid email address"), in stamp text colour; never colour alone.
- "Import {n} rows" starts the job; the page then shows a `Spinner` with "Importing {n}
  rows…" (the import runs as one transaction, so there is no partial progress to show), polls
  every 2 s, and finally shows a result `Card`:
  - "{n} submissions imported." / "{d} rows skipped: already imported." / "{e} empty rows
    skipped." / "{c} cells couldn't be imported" with the per-column counts and the first
    problem rows in a small table.
  - Buttons: primary "Go to submissions", ghost "Import another file".
- Failure: `Alert variant="destructive"` "The import failed and nothing was added. Check the
  file and try again."

### 3.4 Submission detail

Imported submissions show, at the top of the Answers tab, an `Alert` (`HistoryIcon`):
"Imported from Jotform (submission {id}), originally submitted {date}." When files were
copied in (`justforms fetch-imported-files`): "Files and signatures copied from Jotform:" and an
`ItemGroup` of outline `Item`s (thumbnail for images, `FileTextIcon` for PDFs), each with the
question label, the file name and size, and a ghost download `Button` with a `Tooltip`.
Signature images carry an outline `Badge` "Imported" and the description "Image from Jotform,
not captured by JustForms". Links not copied (yet) follow: "Not copied yet, still on Jotform:"
(or "Files and signatures stay on Jotform:" when nothing was copied) and a list "{question
label}: {link}" (links open in a new tab, `rel="noopener noreferrer"`, `bdi dir="ltr"`).
Imported signatures are not part of JustForms' signature audit trail; the Answers list shows
them as unanswered.

## 4. Accessibility and keyboard

- Every step has one `h1` and a short description; step changes move focus to the step
  heading (`tabIndex=-1`).
- Tab order follows the visual order; the report accordion is keyboard-operable (Radix).
- Status badges carry icon + word; problem cells carry icon + text.
- File inputs have visible labels; errors are `FieldError` / `Alert` announced politely.
- 44px targets on coarse pointers (`pointer-coarse:` sizes) for buttons, selects and tabs.

## 5. Self-critique

- First idea was a dialog for the form import. The preview needs the real renderer at phone
  and desktop width, and the report can be 80+ rows: a page reads better and survives a
  reload of the tab on phones.
- First idea showed the report as a `Table`. On a phone a 4-column table of long labels
  overflows; `Item` rows wrap and still scan well on desktop.
- Considered asking for the language before parsing. Detection is reliable (Thaana is easy to
  count), so the choice moved to the result with the detected value preselected.
- The column-mapping step could auto-skip when every column matched. It doesn't: imports are
  rare and irreversible enough that one look at the mapping is worth it.
