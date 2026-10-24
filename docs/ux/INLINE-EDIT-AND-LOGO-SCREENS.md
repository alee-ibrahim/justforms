# Inline editing on the canvas, and a logo per form

Two changes that make the builder feel like editing the form itself:

1. **Inline editing.** Every piece of form text is typed where it shows on the canvas: the form
   title and description, page titles and descriptions, question labels, help text,
   placeholders, choice options, headings and paragraphs, section and repeater text, the
   Back / Next / Submit buttons and the message after submitting. The inspector stays for
   everything that isn't text (and still edits text too; both stay in sync).
2. **A logo per form.** Form Settings › Appearance can give one form its own logo instead of
   the organisation's, with a size, a position and an optional link. The Jotform importer
   brings the form's logo across.

Tokens, type and motion come from [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); the canvas from
[PHASE-2-SCREENS.md](PHASE-2-SCREENS.md) §2.5; the Appearance card from
[FORM-THEME-SCREENS.md](FORM-THEME-SCREENS.md) §3.3; review with
[REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md). Copy in "quotes" ships as written, English only.
Nothing new from shadcn: `input`, `textarea`, `input-group`, `toggle`, `button`, `checkbox`,
`radio-group`, `native-select`, `toggle-group`, `field`, `badge`, `tooltip` and `spinner` are
installed. `components/ui` is not edited.

## 1. Inline editing

### 1.1 The one rule

**Text you can read on the canvas is text you can edit there.** A click (or tap) on any piece of
form text selects its block and puts a caret in that text, in one step. Everything else on a
block (its empty space, the inert answer control) only selects it. Drag starts only from the
grip handle, so a click on text never starts a drag.

### 1.2 States of an editable text

| State | Look | Notes |
|---|---|---|
| idle | exactly the renderer's text | the canvas stays WYSIWYG |
| hover (pointer) | `cursor-text` and a 1px dashed `outline-input` 2px outside the text, `rounded-xs` | tells a mouse user the text is editable without changing layout |
| focused (keyboard) | the carbon focus ring (`ring-3 ring-ring/50`) on the text | Tab reaches every editable text |
| editing | an official shadcn `Input` (one line) or `Textarea` (`field-sizing-content`, several lines) with the text's own size, weight and font, transparent background and the `--input` outline; dv forms get the `InputGroup` with the "ތ / A" `Toggle` at the end edge | one quiet box, so it's clear what is being typed into |
| empty, optional | a muted English prompt, only on the **selected** block (or the selected form / page header) | idle canvas shows nothing extra, exactly like the live form |
| empty, required (label, title, option) | the existing muted placeholder ("Untitled question", "Untitled form", "Page 2", "Option 3") | plus the stamp "Fix" badge for a missing label, unchanged |

Prompts (exact copy): "Add a description…" (form, page, section, repeater), "Add help
text…" (question), "Add placeholder text…" (inside the answer box of text, email, phone and
number questions), "Add text…" (empty heading or paragraph). Prompts are `lang="en"
dir="ltr"` runs inside `bdi`, so they read correctly inside a dv sheet.

### 1.3 Commit, cancel and undo

- **Enter** commits a one-line text. In a multi-line text (descriptions, help text, paragraphs,
  the message after submitting) **Enter** also commits; **Shift+Enter** adds a line break
  (Ctrl/Cmd+Enter commits too).
- Moving focus away (blur, a tap elsewhere) commits.
- **Esc** cancels: the text goes back to what it was and focus returns to the text (a second
  Esc goes to the block, a third clears the selection, as today).
- Each commit is **one** change: one undo step, one autosave patch, checked by the same schema
  validation as every other edit. Nothing is saved while typing; an unchanged commit is a
  no-op. Ctrl+Z while typing is the browser's own text undo.
- Optional texts that end up empty are removed from the draft (as the inspector does); a
  question label left empty keeps the "Fix" badge.
- A Latin label still names the question's key while the key is the automatic one.

### 1.4 Choice options

```
 Favourite colour                                     (label: edit in place)
 Pick one.                                            (help text)
 ⠿ ( ) Red                       [×]                  ⠿ grip on hover/focus; × remove
 ⠿ ( ) Green|                    [×]     ← editing: Enter adds the next option below
 ⠿ ( ) Option 3 (muted)          [×]
   ( ) Other                     [×]     ← only when "Other" is on; English, not editable
 [+ Add option]  [+ Add "Other"]          (ghost buttons, selected block only)
```

- Each option row looks like the renderer's choice row (the same inert `RadioGroupItem` /
  `Checkbox` visual), with its label as an editable text ("Edit option 2").
- In an option: **Enter** commits it and opens a new empty option right below, with the caret
  in it; committing that new option adds it (one undo step); leaving it empty adds nothing.
  **Backspace** in an empty option removes it (one undo step) and puts the caret at the end of
  the option above. A question keeps at least one option.
- Reorder: drag an option by its grip (a nested dnd-kit sortable, like the inspector's
  list), or **Alt+↑ / Alt+↓** on a focused or edited option. The grip (start edge) and ×
  (end edge) show on the selected block only, in the row's flow, so the idle canvas is exactly
  the live form and nothing hangs outside the sheet on phones.
- "Add option" appends one and edits it. "Add "Other"" turns on `allowOther`; the "Other" row
  then has × to turn it off. The "Other" text is English system text ("Other") like on the
  live form.
- Dropdown questions show the inert dropdown; once selected, the same option rows follow it
  under a muted caption "Options in the list", so they can be edited without opening the
  inspector.
- Option values never change when a label is edited; new options get `option_{n}` values.

### 1.5 Where each text is edited

| Text | On the canvas | Kind |
|---|---|---|
| Form title / description | the sheet's header | one line / several |
| Page title / description | the page heading under the header | one line / several |
| Question label | the label | one line |
| Help text | under the label | several (Markdown shown rendered when idle, typed as plain text) |
| Placeholder | inside the inert answer box | one line |
| Options | see 1.4 | one line each |
| Section title / description, repeater label / description | their headings | one line / several |
| Repeater add-button text | the (disabled-looking) "Add entry" button | one line |
| Heading / paragraph block | the block | one line / several |
| Back / Next / Submit | a row of buttons at the bottom of the sheet, as on the live page: Back on pages after the first, Next on every page but the last, Submit on the last | one line each |
| Message after submitting | under the buttons on the last page: a dashed `rounded-md` box with the muted caption "Shown after submitting" and the message in the success screen's heading style | several |

Back and Next become form content like Submit already is: `settings.backLabel` and
`settings.nextLabel` (form language, optional). When empty the live form shows the English
"Back" / "Next" (and the canvas shows them in muted text as the placeholder).

### 1.6 Selection, keyboard, screen readers

- **Click / tap text**: selects the block (or the form / page) and edits the text.
- **Click elsewhere on a block**: selects it (no editing), as today.
- **Tab** moves through every editable text in reading order; focusing a text selects its
  block, so the block's prompts appear and are reached next. **Enter** (or F2) on a focused
  text starts editing; typing does not. ↑/↓ on a block still move between blocks; Enter on a
  selected block edits its label.
- Each editable text is a focusable element with `role="button"` and an accessible name that
  says what it edits and what it says now: "Edit question label: Full name", "Edit help text",
  "Edit placeholder", "Edit option 2: Green", "Edit form title", "Edit form description",
  "Edit page title", "Edit Next button text", "Edit message after submitting" (and so on).
  While editing, the input has the same name without the value.
- The live region announces nothing per keystroke; commits are visible through the save
  status ("Saving…", "Saved").
- Studio chrome stays English and LTR. Editing inputs carry the form's `lang`/`dir`
  (`contentProps`), so a dv form is typed right to left in Thaana; the phonetic keyboard is on
  by default and the "ތ / A" toggle sits at the end edge of the box.

### 1.7 Touch and phones

- A tap on text selects and edits in one go and opens the phone keyboard (the input is focused
  inside the tap, which iOS requires). `enterKeyHint="done"` on one-line inputs, `"enter"` on
  multi-line ones; `autoCapitalize="sentences"`; inputs are at least 16px so iOS doesn't zoom.
- On phones the inspector drawer opens when a block is tapped **outside** its text; editing
  text never opens it, and finishing an edit doesn't open it either.
- Editable text gets a 44px tap area on coarse pointers through an absolutely placed
  `::before` (10px around the text), so the idle layout doesn't move; the editing box is at
  least 44px tall on touch screens.
- While one of a block's texts is being typed in, the block's ⋯ menu button steps aside so it
  doesn't cover the end of the box.

## 2. Logo per form

### 2.1 What can be set

| Setting | Choices | Inherits from |
|---|---|---|
| Logo | PNG or SVG, ≤ 512 KB, ≤ 4096 px a side (same checks as branding: PNG re-encoded, SVG rebuilt from an allow-list) | the organisation's logo (branding) |
| Logo size | Small, Medium, Large (24, 32, 56 px tall; Medium is today's size) | organisation form theme, then Medium |
| Logo position | Start, Centre, End, Hidden (logical: Start is right in a dv form) | organisation form theme, then Start |
| Logo link | `http://` or `https://` address, ≤ 500 characters, opens in a new tab | organisation form theme, else none |

Size, position and link are form-theme values (organisation defaults, per-form overrides).
The logo file itself is set per form only (the organisation's logo lives in Branding). It is
stored through the storage abstraction under `form-logos/{form}/` and served from this origin
with the branding image headers (sandbox CSP, `nosniff`, a year's cache on the hashed name).

### 2.2 Form › Settings › Appearance › Page

The "Page" group of the Appearance card gains, before "Logo position":

```
 Logo                                          [Organisation]   (or: [↶ Use organisation logo])
 [ ▣ 40px thumbnail ]  [⇪ Upload logo]                          (Replace when the form has one)
 PNG or SVG, up to 512 KB. Shown above the form title, on its emails and PDFs.
 Logo size        [Small|Medium|Large]
 Logo position    [Start|Centre|End|Hidden]
 Logo link        [ https://example.org                ]
                  Opens when someone taps the logo. Leave empty for no link.
```

- Thumbnail: `rounded-md border bg-muted` box 40px tall showing the effective logo (the form's,
  else the organisation's; an image icon when there is none).
- Upload: a hidden file input behind an outline `Button` "Upload logo" / "Replace"
  (`accept="image/png,image/svg+xml"`), `Spinner` while uploading; it saves at once (toast
  "Logo uploaded"). "Use organisation logo" (ghost, `Undo2`) removes the form's own logo at
  once (toast "Using the organisation logo"). Editors only; viewers see the row read-only.
- Errors under the row (`FieldError`): "That file isn't a PNG or SVG.", "The file is larger
  than 512 KB.", "The image is larger than 4096 pixels on a side.", "This SVG contains scripts
  or external content and can't be used.", "This SVG has no size. Add a viewBox and try
  again."
- An SVG form logo adds the note "Emails show the organisation logo: mail apps can't show SVG.
  Upload a PNG to use this logo in emails too."
- Size and position: the usual `ToggleGroup` rows with the "Organisation" badge / "Use
  organisation setting". Link: `Input type="url"` (`dir="ltr"`, `inputMode="url"`); error
  "Enter a link starting with https:// or http://." These save with "Save appearance".
- Organisation settings › Form theme shows the same size, position and link rows (no logo
  upload: that is Branding).

### 2.3 Where it shows

- **Public form** (not in embeds, as today), **approver page** and **verify page**: above the
  title at the chosen size and position; with a link it is an `<a target="_blank"
  rel="noopener noreferrer">` named "{alt}, opens in a new tab". `alt` is the form title.
- **Builder canvas** and the Appearance preview: the same, so the sheet stays WYSIWYG.
- **Emails about the form**: the form's PNG logo in the header (an SVG falls back to the
  organisation's email header).
- **Signed PDF**: the form's logo instead of the organisation's, at the chosen size and
  position (Hidden prints no logo); the rest of the layout is unchanged.
- **Jotform import**: the form's logo is downloaded (Jotform's own hosts only, through the SSRF
  guard, ≤ 512 KB) and becomes the new draft's logo. The import report's "Not imported" list no
  longer lists it; the report's summary says "Logo imported." or, when it couldn't be, gives
  the reason under "Not imported".

## 3. Self-critique

| First idea | Problem | Changed to |
|---|---|---|
| Always-on transparent inputs for every text | Raw Markdown in help text and paragraphs; inputs everywhere make the canvas a property sheet again; screen readers hear dozens of text boxes | Rendered text that turns into an input on click, Enter or tap |
| contentEditable for true in-place editing | Thaana phonetic keyboard, IME, paste and RTL caret bugs; would need a hand-made editor | Official `Input`/`Textarea` swapped in, styled with the text's own typography |
| Commit on every keystroke (the old inline label) | One undo step per letter; autosave churn | Commit on Enter/blur, one undo step |
| Prompts on every empty text all the time | The idle canvas no longer looks like the live form | Prompts only on the selected block |
| Separate "Edit" pencil buttons next to texts | Two targets per text; clutter; a pencil tell | The text itself is the target; dashed hover outline and the focus ring signal it |
| A per-form logo inside the form schema | Needs a publish; branding and themes apply on save | Stored on the form record like the form theme |
| Logo size in pixels | An open number invites distorted headers | Three sizes, Medium = today |
