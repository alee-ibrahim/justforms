# Phase 2 screens

Screen-by-screen UX spec for Phase 2 (builder and renderer), plus the publish/share surface
and the submissions table/detail that follow in Phase 3, and the signature pad from
Phase 5, so they are designed together. Tokens, type and motion come from
[DESIGN-SYSTEM.md](DESIGN-SYSTEM.md). Review with [REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md).

Conventions in this document:
- Component names are official shadcn/ui components. **[add]** means it is not in
  `frontend/src/components/ui/` yet: add it with `pnpm dlx shadcn@latest add <name>`.
  Everything else is composed in `src/components/<feature>/`.
- Wireframes are LTR. In RTL the whole layout mirrors (start/end), except the studio chrome,
  which stays LTR English. The builder canvas follows the form's language.
- Copy in "quotes" is the exact text to ship. All system copy is English only, studio and
  respondent-facing alike: Next, Back, default Submit, "Step 2 of 3", "(optional)", validation
  messages are English for every form (one plain TS object, `renderer/messages.ts`; no i18n
  layer). Dhivehi appears only in form content and answers. In a dv form the English strings
  are rendered as `<En>` runs inside the RTL sheet (DESIGN §16).
- "Form language" means `settings.language` (`en` or `dv`). Everywhere form text is edited
  or shown (canvas, inspector text inputs, preview, renderer, submission answers) spread
  `contentProps(formLanguage(form))` from `@/schema` to get `lang`/`dir`. Nothing here needs
  side-by-side translation UI.

## 0. Component inventory

Already installed: alert, avatar, badge, button, card, dialog, direction, dropdown-menu,
empty, field, input-otp, input, label, native-select, select, separator, skeleton, sonner,
spinner, switch, table, tabs, textarea, toggle-group, toggle, tooltip.

To add for Phase 2 (one CLI call):

```sh
cd frontend && pnpm dlx shadcn@latest add resizable scroll-area sheet drawer command popover \
  alert-dialog accordion collapsible checkbox radio-group progress calendar breadcrumb \
  button-group input-group kbd item context-menu hover-card
```

To add for Phase 3 submissions: `pagination` is **not** needed (cursor paging uses Button);
add `chart` only when analytics arrive. Nothing else.

| Component | Where |
|---|---|
| resizable [add] | builder three-pane layout |
| scroll-area [add] | palette, canvas, inspector, logic list |
| sheet [add] | submission detail (desktop), logic overview |
| drawer [add] | builder palette and inspector on phones, submission filters on phones |
| command [add] | insert-field search (`/`), field picker combobox in logic editor, form switcher |
| popover [add] | combobox wrapper, date picker, filter popovers |
| alert-dialog [add] | delete page, delete field with logic references, unpublish/close form, discard |
| accordion [add] | inspector groups |
| collapsible [add] | sections and repeaters on canvas, outline tree |
| checkbox [add] | multi_choice renderer, table row selection, column picker |
| radio-group [add] | single_choice (radio), yes_no, publish access options |
| progress [add] | wizard progress, upload progress, export progress |
| calendar [add] | date field (in Popover), date-range filter |
| breadcrumb [add] | builder and submissions header |
| button-group [add] | undo/redo, device preview, page nav |
| input-group [add] | share link + copy, search, phonetic keyboard toggle, phone prefix |
| kbd [add] | shortcut hints in tooltips and empty states |
| item [add] | palette entries, uploaded file rows, version list |
| context-menu [add] | right-click on canvas field (same actions as its menu) |
| hover-card [add] | logic badge preview on canvas ("Shown when Age is less than 18") |

Do **not** add: `form` (use `field` + react-hook-form `Controller`), `sidebar` (the studio
uses a top bar), `carousel`, `navigation-menu`, `menubar`, `slider` (rating uses ToggleGroup).

---

## 1. Studio shell (context for every studio screen)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ JustForms   Forms                                         [?]  [ali@… ▾]       │  h-12, Sheet bg, border-b
├──────────────────────────────────────────────────────────────────────────────┤
│ (Desk background)                                                            │
```

- Header: brand text (no logo mark needed), `Button variant="ghost"` nav links with
  `aria-current="page"`, help `Button` (opens a Popover with keyboard shortcuts, `Kbd`),
  user `DropdownMenu`. The current language toggle goes away (studio is English only).
- Inside a form, the header gains a second row (form bar), see §2.

## 2. Builder

Route `/forms/$id/edit`. The most-used screen. Goal: a non-technical builder reproduces a
paper form page by page, sees exactly what respondents will see, and never loses work.

### 2.1 User flow

1. Open a form from the list, or create one (dialog asks title and form language, then lands
   here with one empty page).
2. Add questions: drag from the palette, click a palette item (adds after the selection), or
   press `/` and type ("phone").
3. Click a question on the canvas to select it; edit its label inline on the canvas or in the
   inspector; set required, help text, options, validation.
4. Add pages; rename them; reorder; add sections and repeaters and drop questions into them.
5. Add logic: "Show this question when…" on a field, "After this page, go to…" on a page.
6. Preview (phone and desktop width), fill it in to test logic.
7. Publish. Share.

Autosave is continuous. The builder never has a Save button.

### 2.2 Desktop wireframe (≥ 1024px)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ JustForms  Forms                                                        [?] [ali ▾]        │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ Forms / Youth programme application   ● Saved       [↶][↷]  Edit  Preview  Share  Submissions │
│                                       Unpublished changes          [ Publish ]           │
├──────────────┬───────────────────────────────────────────────────────┬───────────────────┤
│ [Add][Outline]│  ① About you   ② Guardian ⤳   ③ Documents   [+ Add page]│ Question          │
│──────────────│ ───────────────────────────────────────────────────────│ Short answer  ⋯   │
│ Search  /    │   ┌─────────────────────────────────────────────┐       │───────────────────│
│              │   │ About you                       Page 1 of 3 │       │ ▾ Question        │
│ Text         │   │                                             │       │  Label            │
│ ▭ Short answer│   │▌Full name                                   │       │  [Full name     ] │
│ ▭ Long answer │   │▌[__________________________________]       │ ← marker wash  Help text   │
│ @ Email      │   │                                             │       │  [              ] │
│ ☏ Phone      │   │ National ID number            🔒 Sensitive  │       │  Placeholder      │
│ # Number     │   │ [__________________________________]        │       │  [              ] │
│ Choice       │   │                                             │       │  Required  (•)    │
│ ◉ Single choice│  │ Age                                         │       │ ▸ Validation      │
│ ☑ Multi choice │  │ [______]                                    │       │ ▸ Logic        1  │
│ ◐ Yes / no   │   │                                             │       │ ▸ Advanced        │
│ ★ Rating     │   │ Dependents            ⤳ Conditional  ↻ Repeats│     │                   │
│ Date & time  │   │ ┌ - - - - - - - - - - - - - - - - - - - - ┐ │       │ Key               │
│ ▦ Date       │   │ ┆ Name  [____________]                    ┆ │       │ full_name  (mono) │
│ ◷ Time       │   │ ┆ Relationship [ Choose…        ▾]        ┆ │       │                   │
│ Files        │   │ ┆ Drop questions here                     ┆ │       │                   │
│ ⇪ File upload│   │ └ - - - - - - - - - - - - - - - - - - - - ┘ │       │                   │
│ Layout       │   │                                             │       │                   │
│ ▤ Section    │   │ ─────── carbon drop line while dragging ─── │       │                   │
│ ↻ Repeater   │   │                                             │       │                   │
│ ¶ Text block │   │ [ + Add question ]                          │       │                   │
│ ― Divider    │   └─────────────────────────────────────────────┘       │                   │
│ Hidden value │                                                         │                   │
├──────────────┴─────────────────────────────────────────────────────────┴───────────────────┤
```

- Three panes: `ResizablePanelGroup direction="horizontal"` with `ResizablePanel`
  (palette 18%, min 200px), canvas (flex), inspector (26%, min 300px), `ResizableHandle`
  between them. Each pane scrolls independently with `ScrollArea`.
- The canvas sheet is the real renderer in **edit mode** (same components, same spacing, same
  fonts, form `dir`), at max 40rem on the Desk. WYSIWYG is the main UX decision: builders
  think in "what the form looks like", not in property lists.

### 2.3 Form bar (second header row)

| Piece | Component | Notes |
|---|---|---|
| Breadcrumb "Forms / {title}" | `Breadcrumb` [add] | title is click-to-rename (`Input` inline on click, Enter saves, Esc cancels) |
| Save status | `Badge variant="outline"` + `Spinner` | states below; `aria-live="polite"` region |
| Undo / redo | `ButtonGroup` [add] of two icon `Button`s + `Tooltip` with `Kbd` | disabled when nothing to undo |
| Edit / Preview / Share / Submissions | `Button variant="ghost"` links with `aria-current="page"` | route nav, not Tabs (they change URL) |
| Unpublished changes | `Badge variant="secondary"` | shown when draft revision ≠ live version |
| Publish | `Button` (primary) | see §3 |

Save status copy (exactly):
- "Saved" (check icon), "Saving…" (Spinner), "Offline. Changes will save when you reconnect"
  (cloud-off icon, keeps queue), "Couldn't save" + `Button variant="link"` "Retry" (stamp).
- Revision conflict (409): `AlertDialog` "This form was changed somewhere else" /
  "Someone (or another tab) edited this form after you opened it. Reload to get the latest
  version. Your last change will be lost." / [Copy my change as JSON] [Reload].

### 2.4 Field palette

- `Tabs` at the top: "Add" | "Outline".
- "Add" tab: search `InputGroup` [add] (search icon, placeholder "Search question types",
  `Kbd` "/" hint at end) then groups ("Text", "Choice", "Date and time", "Files",
  "Layout", "Other") as small muted headings (sentence case, `text-xs font-medium`, not
  caps). Each type is an `Item` [add] (`ItemMedia` icon, `ItemTitle`) rendered as a
  `<button>`: draggable (dnd-kit `useDraggable`) and clickable.
- Signature is listed in "Other" as disabled with `Badge` "Coming soon" until Phase 5 (or
  omitted; pick one and be consistent). Hidden value lives in "Other".
- "Outline" tab: tree of pages → sections/repeaters → questions using `Collapsible` [add];
  each row is a `Button variant="ghost" size="sm"` that selects and scrolls to the element.
  Logic indicators repeat here (icon only, with `Tooltip`).

Interaction:
- Click or Enter on a palette item: inserts after the selected element (or at the end of
  the current page), selects it, focuses its label on the canvas.
- `/` anywhere in the builder (when focus is not in a text field) opens a `CommandDialog`
  [add] "Add a question" with the same list, fuzzy matched ("tel" finds Phone).
- Drag: palette item → canvas. The drag overlay is the `Item` with `shadow-float`.

### 2.5 Canvas

Each element on the sheet is a block with three visual states:

| State | Look |
|---|---|
| idle | exactly the renderer output; no borders |
| hover | `bg-muted/50`, drag handle (grip icon) appears at the start edge, outside the sheet padding |
| selected | `bg-accent` (marker wash) + `border-s-[3px] border-marker-edge`; block toolbar appears at the end edge: [⋯] `DropdownMenu` |
| focused (keyboard) | carbon focus ring (`ring-ring/50 ring-[3px]`); can be both focused and selected |

- Block menu (`DropdownMenu`, also available via `ContextMenu` [add] on right-click):
  "Duplicate" (Ctrl+D), "Move up" (Alt+↑), "Move down" (Alt+↓), "Move to page…" (submenu
  of pages), "Wrap in section", "Add logic", separator, "Delete" (Del, stamp).
- Inline editing: every piece of form text on the canvas is edited in place (a click or tap
  selects the block and edits the text in one step); see
  [INLINE-EDIT-AND-LOGO-SCREENS.md](INLINE-EDIT-AND-LOGO-SCREENS.md) §1. The inspector stays in
  sync and keeps the non-text settings.
- Inputs on the canvas are inert (`tabIndex={-1}`, `aria-hidden` on the preview control,
  `pointer-events-none`) so clicks select the block instead of typing into it.
- Indicators on a block, shown inline after the label as `Badge variant="outline"` with icon:
  "Required" is not a badge (the renderer's "(optional)" convention shows instead);
  "Conditional" (eye-off icon) when `visibleIf` exists, with `HoverCard` [add] showing the
  rule as a sentence; "Sensitive" (lock icon); "Hidden value" (eye-off) for hidden fields
  (rendered as a dashed muted row since respondents never see it).
- Sections: title as `text-lg`, children indented by `ps-4` with a hairline `border-s`.
  Collapsible via `Collapsible` (chevron at start). Nest at most two levels; the drop
  indicator refuses a third level (cursor `not-allowed`, toast not needed).
- Repeaters: dashed `border` box (`border-dashed rounded-md`) titled with the repeater label
  and a "Repeats" badge (repeat icon), showing one sample row and a disabled
  "Add dependent" button exactly as respondents will see it. Signature and other repeaters
  cannot be dropped inside (drop indicator refuses; tooltip on the palette item explains
  "Repeaters can't contain repeaters").
- Empty page: `Empty` with `EmptyMedia` (plus icon), `EmptyTitle` "No questions on this page
  yet", `EmptyDescription` "Drag a question here from the left, or press / to search.",
  `EmptyContent` [Add question] button.
- Bottom of every page: `Button variant="outline"` "Add question" (opens the same
  CommandDialog, inserts at the end).

Drag and drop (dnd-kit `@dnd-kit/core` + `@dnd-kit/sortable`):
- Sensors: Pointer (activation distance 6px), Touch (press 250ms, tolerance 5px), Keyboard
  (`sortableKeyboardCoordinates`).
- Drop indicator: 2px carbon line spanning the sheet, with 8px circles at both ends, placed
  between blocks or inside a section/repeater's body.
- Sections and repeaters are droppable containers. Cross-page move: drop on a page chip in
  the page strip (the chip highlights with marker wash; hold 600ms to switch to that page).
- Screen-reader announcements (`DndContext accessibility.announcements`), exact copy:
  - pick up: "Picked up {label}. Use arrow keys to move, Space to drop, Escape to cancel."
  - over: "{label} will move to position {n} of {total} on {page}."
  - drop: "{label} moved to position {n} on {page}."
  - cancel: "Move cancelled. {label} is back at position {n}."

### 2.6 Pages

Page strip above the sheet: a horizontal row of page chips. Pages are a real sequence, so
they are numbered.

- Each chip: `Button variant="ghost" size="sm"` with number + title; current page uses
  `variant="secondary"` and `aria-current="page"`. Overflow scrolls horizontally inside
  `ScrollArea` with a `ScrollBar orientation="horizontal"`.
- Chip indicators: `⤳` icon if the page has `next` jump rules, eye-off icon if the page has
  `visibleIf`. Tooltip: "Has jump rules" / "Shown only when…".
- Chip `DropdownMenu` (on the chip's own ⋯ or right-click): "Rename", "Page settings"
  (selects the page so the inspector shows page props and page logic), "Duplicate",
  "Move left", "Move right" (labels follow direction: in a dv form canvas they read the same
  because studio chrome is LTR), "Delete page".
- Reorder chips by drag (horizontal sortable).
- "Add page" `Button variant="ghost"` with plus icon: appends "Page {n}", selects it.
- Delete page: if it has questions, `AlertDialog` "Delete page {n} and its {count}
  questions?" / "You can undo this right after." / [Cancel] [Delete page] (destructive).
  If questions on it are referenced by logic elsewhere: add "{count} rules on other pages use
  these questions. Those rules will be removed." and list them.
- Single-page form: the strip still shows one chip plus "Add page", so the concept is
  discoverable.

### 2.7 Inspector

The right pane edits the selection: a field, a section, a repeater, a content block, a page,
or (nothing selected) the form.

Header: element type with its icon (`text-sm font-medium`), the ⋯ block menu, and nothing
else. Body: `Accordion type="multiple"` [add], first group open by default, the open set is
remembered per element type in localStorage.

**Field**
- Group "Question" (open):
  - "Label" `Input` (required; error "Add a label so people know what to answer").
  - "Help text" `Textarea` rows 2, `FieldDescription` "Shown under the label. Bold, italic,
    links and lists are allowed."
  - "Placeholder" `Input` (hidden for choice, yes/no, rating, file).
  - "Required" `Switch` in `Field orientation="horizontal"`.
  - Type-specific:
    - choices: options editor = list of `Input`s (one per option) with drag handle and remove
      icon button, "Add option" ghost button, "Paste several" `Button variant="link"`
      opening a `Dialog` with a `Textarea` (one option per line). Single choice: "Show as"
      `ToggleGroup` "Buttons" | "Dropdown". "Allow 'Other'" `Switch`.
    - multi choice: "At least" / "At most" number `Input`s side by side.
    - rating: "Scale" `NativeSelect` 3–10.
    - number: "Whole numbers only" `Switch`; "Min" / "Max" / "Step".
    - date: "Earliest" / "Latest" each a `Select` (No limit, Today, Today plus N days, A date)
      plus `Popover`+`Calendar` for "A date".
    - phone: "Default country" `NativeSelect`.
    - text: "Typing" `ToggleGroup` "Auto" | "Latin" | "Thaana" with `FieldDescription`
      "Thaana turns on the phonetic keyboard for this question."
    - file: "Accepted files" `ToggleGroup type="multiple"` (PDF, Images, Word, Excel), "Max
      files" and "Max size (MB)" number inputs.
    - hidden: "Fill from link parameter" `Input` with mono font; preview of the link
      `?{param}=value`.
- Group "Validation": "Max length", "Pattern" (`Input` mono) with "Message when it doesn't
  match" (`Input`), only for text. Show an example row: "Test" `Input` + live Badge
  "Matches" / "Doesn't match".
- Group "Logic": see §2.8. The accordion trigger shows a count `Badge` of rules.
- Group "Advanced": "Key" `Input` mono, `FieldDescription` "Used in exports and
  integrations. Locked after the form is first published." (disabled + lock icon after first
  publish), "Sensitive" `Switch` ("Masked in tables and left out of emails and webhooks"),
  "Width" `ToggleGroup` "Full" | "Half", "Prefill parameter".

**Page**: "Title", "Description", group "Logic" (show page when…, after this page go to…).
**Section**: "Title", "Description", "Logic". **Repeater**: "Label", "Add button text",
"Minimum rows", "Maximum rows", "Logic". **Content**: text block uses `Textarea` with the
same Markdown note; divider has no props; image (if in scope) uses the upload pattern.
**Nothing selected (form)**: "Title", "Description", "Form language" (`RadioGroup`
"English" | "Dhivehi", with a note "Changing the language changes text direction.
Existing text is kept."), "Submit button text", "Message after submitting".

Mobile and narrow widths: see §2.11.

### 2.8 Logic editor

Two places, one component:

1. Inspector "Logic" group for the selection.
2. "Logic" overview: `Sheet` [add] from the end edge, opened from the form bar menu ("View
   all logic"), listing every rule in the form as a sentence, grouped by page, each with
   "Edit" (selects the element and opens its Logic group) and a warning icon if broken.

Rule editor (composed: `Card` + `Select` + `Input` + `Button` + `Popover`/`Command`):

```
 Show this question                                           [Always ▾]
 ┌──────────────────────────────────────────────────────────────────────┐
 │ when  [all ▾] of these are true                                      │
 │ ┌─────────────────┐ ┌──────────────┐ ┌────────────┐                  │
 │ │ Age           ▾ │ │ is less than▾│ │ 18         │   [🗑]            │
 │ └─────────────────┘ └──────────────┘ └────────────┘                  │
 │ ┌─────────────────┐ ┌──────────────┐ ┌────────────┐                  │
 │ │ Has dependents▾ │ │ is          ▾│ │ (•)Yes ( )No│  [🗑]           │
 │ └─────────────────┘ └──────────────┘ └────────────┘                  │
 │ [+ Add condition]                                                    │
 └──────────────────────────────────────────────────────────────────────┘
 Make required        [Always / Never / When… ▾]
```

- Top `Select`: "Always" (no rule) | "Only when…". Choosing "Only when…" reveals the card
  with one empty condition. For required: "Never" | "Always" | "When…", which replaces the
  Required switch semantics (the Switch and this Select stay in sync).
- "all"/"any" `Select` (small, inline in the sentence): "all" | "any". Only one level of
  grouping in the UI. Deeper nesting created elsewhere renders as a read-only sentence with
  `Alert` "This rule is too complex to edit here." and a "Remove rule" button.
- Field picker: `Popover` + `Command` [add] combobox, grouped by page, showing label and
  key (mono, muted). Only value-producing fields that may be referenced (scope rules from
  DESIGN §5.3) are listed; repeater children outside the repeater are not offered.
  Fields defined after the current one are allowed and marked "later in the form".
- Operator `Select` lists only operators valid for the field type, in words:
  "is", "is not", "is one of", "is not one of", "is more than", "is at least",
  "is less than", "is at most", "contains", "doesn't contain", "is empty", "is not empty",
  "has exactly", "has at least", "has at most" (count ops, for multi choice/files/repeaters,
  value input gets suffix "selected"/"files"/"rows").
- Value control follows the field: choice → `Select` of its options (multi for "is one of");
  yes/no → `RadioGroup` Yes/No; number → `Input type=number`; date → `Popover`+`Calendar`;
  text → `Input`. Hidden for empty/not empty.
- Live sentence under the card in muted text: "Shown when Age is less than 18 and Has
  dependents is Yes."
- Page jumps ("After this page"): list of rows "If [condition] go to [page ▾]" + "Otherwise
  go to the next page". Target `Select` lists only later pages plus "Submit the form"
  (DESIGN §5.3 forward-only rule), so invalid jumps cannot be built.
- Cycle and reference errors: validated on change against the TS engine. Inline `Alert
  variant="destructive"` in the Logic group: "This creates a loop: Age depends on
  Guardian name, which depends on Age. Change one of these rules." Publish is blocked until
  fixed (§3).
- When a referenced field is deleted: its conditions show `Badge` "Missing question" in stamp
  and the rule's sentence reads "…when (deleted question) is…". Delete confirmation warns first
  (§2.6 pattern).
- Hovering or focusing a condition row washes the referenced field on the canvas with marker
  (if on the current page) to make the dependency visible.

### 2.9 Undo and redo

- Server undo/redo (`POST /draft/undo|redo`) drives the history; the client also keeps an
  optimistic local stack so the button reacts instantly.
- Shortcuts: Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z and Ctrl+Y redo. When focus is inside a text
  input, the browser's native text undo runs first; the builder handles it only when the field
  has no native history left (i.e. intercept only when focus is outside editable elements).
- After destructive actions (delete field/page, remove rule) a `sonner` toast: "Deleted
  “Full name”" with action "Undo" (5s). Undo selects and scrolls to the restored element.
- Tooltip text: "Undo (Ctrl+Z)" / "Redo (Ctrl+Shift+Z)" with `Kbd`; on macOS show ⌘.

### 2.10 Preview

Route `/forms/$id/preview` (the "Preview" nav item). Full width Desk, no panes.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Forms / Youth programme…  ● Saved   [↶][↷]  Edit  Preview  Share  Submissions [Publish] │
├──────────────────────────────────────────────────────────────────────────────┤
│ ⓘ Preview of your latest changes. Answers aren't saved.  [Phone|Desktop] [Restart] │
│                                                                              │
│                     ┌──────────── 390px ────────────┐                        │
│                     │  real renderer, draft schema  │                        │
│                     │                               │                        │
│                     └───────────────────────────────┘                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

- `Alert` (info, not destructive) as a slim bar; `ToggleGroup type="single"` "Phone" |
  "Desktop" (device icons + text); `Button variant="outline"` "Restart".
- The renderer mounts with the draft schema and a `preview` flag: submit shows the success
  screen with reference "Preview" and nothing is posted; uploads are accepted locally only.
- Phone mode: 390px wide container with a hairline border and `rounded-xl`; no fake phone
  bezel.
- A collapsible "Logic trace" `Collapsible` under the device frame (studio only): lists which
  questions are hidden and why, current page path ("Pages: 1, 3. Page 2 skipped because Age
  is 18 or more"). Helps builders debug without reading JSON.

### 2.11 Builder on phones and narrow screens

The builder is a desktop tool, but staff will open it on a phone to fix a typo.

- < 1024px: palette pane collapses; a `Button` "Add question" sits at the bottom of the canvas
  and opens a `Drawer` [add] with the palette (search + list).
- < 768px: inspector becomes a `Drawer` that opens when a block is tapped (half height,
  draggable to full). Drag-and-drop is still available via long-press, but the primary path is
  the block menu "Move up/Move down/Move to page…".
- Form bar collapses: breadcrumb shows title only, nav becomes a `DropdownMenu` ("Edit ▾"),
  Publish stays visible.

```
┌──────────────────────────────┐
│ ‹ Youth programme…  ● Saved  │
│ [Edit ▾]  [↶][↷]  [Publish]  │
├──────────────────────────────┤
│ ① About you ② Guardian ③ D…  │
│ ┌──────────────────────────┐ │
│ │▌Full name                │ │
│ │▌[____________________]   │ │
│ │ National ID number       │ │
│ │ [____________________]   │ │
│ │ Age                      │ │
│ │ [______]                 │ │
│ └──────────────────────────┘ │
│ [      + Add question      ] │
├──────────────────────────────┤
│ ▔▔▔▔ Drawer: Question ▔▔▔▔   │
│ Label [Full name         ]   │
│ Required (•)                 │
│ ▸ Logic  ▸ Advanced          │
└──────────────────────────────┘
```

### 2.12 Builder states

| State | Treatment |
|---|---|
| Loading draft | Skeleton of the three panes (palette list of 10 `Skeleton h-8`, sheet with 4 label+input skeleton pairs, inspector 3 rows), shown after 300ms |
| Load failed | `Empty` on the desk: "Couldn't open this form" / "Check your connection and try again. If it keeps happening, the form may have been deleted." / [Try again] [Back to forms] |
| No permission | `Empty`: "You can view this form but not edit it" / "Ask an owner of this form for editor access." / [Open submissions] |
| Saving / offline / error / conflict | §2.3 |
| Empty page | §2.5 |
| Nothing selected | inspector shows form settings (§2.7) |
| Invalid element | a stamp `Badge` "Fix" on the block and a dot on its page chip; inspector field shows `FieldError` |

### 2.13 Builder keyboard map

| Keys | Action |
|---|---|
| `/` | Add a question (CommandDialog) |
| ↑ / ↓ | Select previous / next block (when canvas has focus) |
| Enter | Edit label of selected block; on a focused text, edit that text (also F2) |
| Tab | Next editable text (focusing one selects its block) |
| Enter / Esc (while editing) | Commit / cancel; Shift+Enter is a line break in multi-line text |
| Enter / Backspace (in an option) | Add the next option / remove an empty option |
| Alt+↑ / Alt+↓ (on an option) | Move the option |
| Esc | Leave label edit; then clear selection |
| Alt+↑ / Alt+↓ | Move block up / down |
| Ctrl+D | Duplicate |
| Delete / Backspace | Delete block (undo toast) |
| Space (on drag handle) | Pick up for keyboard drag; arrows move; Space drops; Esc cancels |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo |
| Ctrl+Enter | Publish dialog |
| ? | Shortcut help popover |

Accessibility notes:
- Canvas is a `role="listbox"`-free structure: each block is a `<div role="group"
  aria-label="{type}: {label}">` with a focusable wrapper (`tabIndex=0`, roving tabindex
  across blocks). Selection is announced: `aria-selected` is not used (not a listbox);
  instead the inspector heading gets focus on Enter and a polite live region says
  "Editing {label}".
- All icon buttons have `aria-label` = tooltip text. Panes are `<section aria-label=...>`
  ("Question types", "Form canvas", "Question settings"). Resizable handles are keyboard
  operable (built in) with `aria-label` "Resize panel".
- Focus is never lost: deleting a block moves focus to the next block (or previous, or the
  "Add question" button).

## 3. Publish and share

### 3.1 Publish flow

1. Click "Publish" (or Ctrl+Enter).
2. Client validates the draft (schema + cycle check). If problems: `Dialog` "Fix these before
   publishing" listing each issue as an `Item` with page/question and a "Show" button that
   closes the dialog and selects the element. No publish button in this state.
3. If clean and this is the first publish: `Dialog` "Publish this form?" with a short
   summary ("3 pages, 12 questions, 4 logic rules"), note "After publishing, question keys
   are locked so your data stays consistent.", [Cancel] [Publish].
   Subsequent publishes: no dialog; publish directly (toast is the feedback), because the
   "Unpublished changes" badge already told them.
4. Toast: "Published version 4" with action "Share". The badge disappears.
5. First publish lands on Share.

Publish errors: toast (stamp) "Couldn't publish. {server message}" + "Retry".

### 3.2 Share screen

Route `/forms/$id/share`. Settings page width (max 48rem), Desk background, cards with
hairline border, no shadow.

```
┌──────────────────────────────────────────────────────────────┐
│ Share                                                        │
│                                                              │
│ ┌ Link ────────────────────────────────────────────────────┐ │
│ │ Form is open  (•)                                         │ │
│ │ [ https://forms.example.org/youth-app ][Copy][Open]│ │
│ │ Short address  [ youth-app        ] Change               │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌ Embed on a website ──────────────────────────────────────┐ │
│ │ (•) Inline   ( ) Full page                                │ │
│ │ ┌──────────────────────────────────────────────┐ [Copy]   │ │
│ │ │ <iframe src="…?embed=1" …></iframe> (mono)    │          │ │
│ │ └──────────────────────────────────────────────┘          │ │
│ │ Allowed websites  [ example.org, intranet.example ]       │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌ Versions ────────────────────────────────────────────────┐ │
│ │ Version 4   Live      Today 14:02   by Ali     [View]     │ │
│ │ Version 3             21 Oct 09:15  by Ali     [View]     │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

| Piece | Component |
|---|---|
| Section cards | `Card` + `CardHeader`/`CardTitle`/`CardDescription`/`CardContent` |
| Open/closed | `Switch` with label "Accepting responses"; off shows `FieldDescription` "People who open the link see “This form is closed”." |
| Link | `InputGroup` [add] (readOnly `Input`, `dir="ltr"`, addons: "Copy" `Button` and "Open" icon button) |
| Short address | `Input` + `Button variant="link"` "Change"; validation inline |
| Embed mode | `RadioGroup` [add] |
| Embed code | `Textarea` readOnly mono + "Copy" `Button` |
| Allowed websites | `Input` (comma separated) with `FieldDescription` |
| Versions | `Item` list (or `Table` if > 5), "Live" `Badge` |
| Not yet published | `Empty`: "Publish to get a link" / "Your form isn't live yet. Publish it to share a link or embed it." / [Publish] |

Copy feedback: the Copy button's text changes to "Copied" with a check icon for 2s and a
polite live region announces "Link copied". No toast.

Phone: cards stack; the link `InputGroup` wraps (Copy and Open move below as full-width
buttons).

Access modes (public, email code, staff only) arrive in Phase 4 as a `RadioGroup` card
"Who can fill this in"; leave room above "Embed".

## 4. Public form renderer

Route `/{slug}` (+ `?embed=1`; old `/f/{org}/{slug}` links redirect). Mostly phones. Budget ≤ 120 KB gzip, so the renderer
imports only the components it needs, and signature pad + phonetic keyboard + calendar are
lazy chunks.

### 4.1 Flow

1. Open link. Form loads (title visible first, then fields).
2. Fill page 1. Tap "Next". Page is validated; errors are summarised and focused.
3. Logic hides/shows questions live and decides the next page.
4. Last page: "Submit" (form's own submit text). Review step is not added (forms can be long,
   and a review page doubles the length on phones).
5. Success screen with a reference number.

### 4.2 Mobile wireframe, English (LTR), 390px

```
┌──────────────────────────────────┐
│ Organisation name (muted)        │  text-sm muted, logo 24px if set
│                                  │
│ Youth programme                  │  text-2xl 700
│ application                      │
│ Applications close on 30 Nov.    │  text-base muted
│                                  │
│ Step 2 of 3                      │  text-sm muted, aria-live
│ ████████████░░░░░░               │  Progress (carbon)
│──────────────────────────────────│
│ Guardian                         │  page title text-xl
│                                  │
│ ┌ ⚠ There are 2 problems ──────┐ │  Alert destructive, focused
│ │ • Enter the guardian's name  │ │  links jump to fields
│ │ • Enter a phone number…      │ │
│ └──────────────────────────────┘ │
│                                  │
│ Guardian's name                  │  text-lg 600
│ ┃Enter the guardian's name      │  FieldError stamp, start bar
│ ┃[__________________________]   │  h-12, aria-invalid
│                                  │
│ Phone                            │
│ ┃Enter a phone number with 7 …  │
│ ┃[+960 ▾][___________________]  │  InputGroup
│                                  │
│ Email (optional)                 │
│ [__________________________]     │
│                                  │
├──────────────────────────────────┤
│ [ ‹ Back ]        [   Next  › ]  │  sticky bottom bar, h-12 buttons
└──────────────────────────────────┘
```

### 4.3 Mobile wireframe, Dhivehi (RTL), 390px

```
┌──────────────────────────────────┐
│                 (org name, muted) │
│                                  │
│    ޒުވާނުންގެ ޕްރޮގްރާމަށް ހުށަހަޅާ │  title, Faruma, 31px / 48px
│                             ފޯމު │
│                                  │
│                      Step 2 of 3 │  English run (<En>), right-aligned
│               ░░░░░░████████████ │  fills from the right
│──────────────────────────────────│
│                       ބެލެނިވެރިޔާ │
│                                  │
│          ބެލެނިވެރިޔާގެ ނަން │  label right-aligned, 21/36
│ [____________________________ ތ/A]│  phonetic toggle at end (left)
│                                  │
│                    ފޯނު ނަންބަރު │
│ [ +960 7771234        ]          │  input dir=ltr, label stays rtl
│                                  │
├──────────────────────────────────┤
│ [ ‹ Next ]             [ Back › ] │  Back at start (right), Next at end (left)
└──────────────────────────────────┘
```

(Dhivehi strings above are form content; system strings such as "Step 2 of 3", "Next" and
"Back" are English for every form, isolated as left-to-right runs inside the RTL sheet.)

### 4.4 Desktop wireframe (≥ 768px)

```
┌──────────────────────────── Desk ────────────────────────────┐
│                                                              │
│        ┌────────────── Sheet 40rem ──────────────┐          │
│        │ org name                                │          │
│        │ Youth programme application             │  text-3xl│
│        │ Applications close on 30 November.      │          │
│        │ Step 2 of 3   ██████████████░░░░░░░     │          │
│        │─────────────────────────────────────────│          │
│        │ Guardian                                │          │
│        │                                         │          │
│        │ Guardian's name                         │          │
│        │ [_____________________________________] │          │
│        │                                         │          │
│        │ Phone                    Email (optional)│ half-width fields pair up
│        │ [+960][___________]      [_____________] │          │
│        │                                         │          │
│        │ [ ‹ Back ]                   [ Next › ] │  not sticky│
│        └─────────────────────────────────────────┘          │
│                    Made with JustForms (muted, xs)            │
└──────────────────────────────────────────────────────────────┘
```

Embed mode (`?embed=1`): no Desk, transparent background, no outer padding, no footer credit,
sheet without border; posts height to parent via `postMessage` on every layout change.

### 4.5 Components per field type

All controls use the comfortable size: `className="h-12 text-base sm:h-11"` on inputs and
buttons in the renderer (call-site classes, not component edits). Wrap each question in
`Field` (`FieldLabel`, `FieldDescription`, control, `FieldError`); groups of options use
`FieldSet` + `FieldLegend`.

| Type | Component | Notes |
|---|---|---|
| short_text | `Input` | `autocomplete` from key heuristics (name, email, tel); `maxLength` counter as `FieldDescription` "45 of 120" only after 80% |
| long_text | `Textarea` | `rows` from schema, auto-grow |
| email | `Input type="email" inputMode="email" dir="ltr"` | |
| phone | `InputGroup` [add]: `InputGroupAddon` with country code `NativeSelect` (small) + `InputGroupInput type="tel" inputMode="tel" dir="ltr"` | country default from schema |
| number | `Input inputMode="decimal"` (`numeric` if integer), `dir="ltr"` | no spinners on phones; min/max in description "Between 15 and 35" |
| date | `Popover` + `Calendar` [add] behind a `Button variant="outline"` that shows the date; on phones prefer native `Input type="date"` (better UX, smaller bundle). Decision: **native date input on touch devices, Calendar on pointer devices** | dv month names where available |
| time | `Input type="time"` | |
| single_choice (buttons) | `RadioGroup` [add] with each option as a full-width bordered row (`FieldLabel` wrapping `Field orientation="horizontal"` with the item: shadcn "choice card" pattern) | 48px rows, whole row tappable |
| single_choice (dropdown) | `NativeSelect` | native picker on phones; first option "Choose…" disabled |
| allowOther | extra radio "Other" revealing an `Input` | |
| multi_choice | `Checkbox` [add] rows, same choice-card pattern | description "Choose up to 3"; after max, remaining options disable with that reason |
| yes_no | `RadioGroup` with two choice-card rows side by side ("Yes" / "No"), stacked < 360px | not a Switch: a switch has no "unanswered" state |
| rating | `ToggleGroup type="single"` of numbered `ToggleGroupItem`s (1..max), `aria-label` "{n} of {max}"; ends labelled in description if provided | wraps on small screens |
| file | see §4.8 | |
| signature | see §4.9 (Phase 5) | |
| hidden | nothing rendered | |
| content: heading / paragraph / divider / image | `h2`/`p` with restricted Markdown; `Separator`; `img` with alt | |
| section | `FieldSet` + `FieldLegend` (`text-lg`) + `FieldGroup`, `border-s` hairline indent on ≥ sm only | |
| repeater | see §4.7 | |

Text-script inputs with the phonetic keyboard: `InputGroup` with `InputGroupAddon
align="inline-end"` holding a `Toggle size="sm"` labelled "ތ / A" (`aria-label` "Thaana
keyboard", `aria-pressed`). Pressed state uses `bg-secondary`. The keyboard itself is
`attachKeyboard` / `useThaanaKeyboard` from `@yashau/thaana-react` attached to the shadcn
`InputGroupInput`/`InputGroupTextarea` (never the package's own input components). The builder
uses the same composition for every input that edits form text in a `dv` form.

"(optional)" convention: if most questions are required, optional ones get " (optional)" in
muted after the label; otherwise required ones get " (required)". Never a red asterisk alone.
Both are English for every form (an `<En>` run after a Dhivehi label).

### 4.6 Validation

- Validate a field on blur once it has been touched, and the whole page on "Next"/"Submit".
  Do not validate while typing (except clearing an error once the value becomes valid).
- On failed Next: render an **error summary** `Alert variant="destructive"` at the top of the
  page: title "There's a problem" (1 error) / "There are {n} problems", body a list of links
  ("Enter the guardian's name"), each moving focus to the field. Move focus to the summary
  (`tabIndex=-1`, `role="alert"` not needed since focus moves) and scroll it into view.
- Inline: `FieldError` under the label, above the control, with a 3px stamp `border-s` on
  the field block; control gets `aria-invalid` + `aria-describedby`.
- Messages are specific (examples, exact copy):
  - required text: "Enter {label lowercased}" (fallback "Answer this question")
  - required email, phone, number, date or time: the same message as an invalid answer of that
    type (below), so it says what to enter
  - required choice: "Choose an option"; required file: "Upload a file"; required signature:
    "Sign in the box". The summary names the question, so the label is never spliced in
  - multi min/max: "Choose at least 1" / "Choose no more than 3"
  - email: "Enter an email address like name@example.com"
  - phone: "Enter a phone number with 7 digits, like 7771234"
  - number range: "Enter a number between 15 and 35"
  - integer: "Enter a whole number"
  - pattern: the field's `patternMessage`, else "Check the format"
  - date: "Enter a date on or after 1 January 2026"
  - file too large: "“scan.pdf” is larger than 10 MB. Choose a smaller file."
  - file type: "“photo.heic” isn't allowed. Upload a PDF, JPG or PNG."
- Server errors on submit map to the same fields and the same summary.

### 4.7 Repeater

```
 Dependents
 Add each person you look after.
 ┌────────────────────────────────────┐
 │ Dependent 1                [Remove]│  text-base 600; Remove = ghost, stamp text
 │ Name                               │
 │ [______________________________]   │
 │ Relationship                       │
 │ [Choose…                     ▾]    │
 └────────────────────────────────────┘
 ┌────────────────────────────────────┐
 │ Dependent 2                [Remove]│
 │ …                                  │
 └────────────────────────────────────┘
 [ + Add dependent ]                     Button outline, full width on phones
 You can add up to 10.                   muted, shown when near max
```

- Each row is a `Card` (hairline, no shadow, `rounded-md`) titled "{singular} {n}"; the
  singular comes from the `addLabel` (fallback "Entry {n}").
- Adding a row moves focus to its first input. Removing a row: no dialog if the row is empty;
  otherwise inline confirm by turning "Remove" into "Remove dependent 2?" [Remove] [Keep] for
  5s (no modal on phones). Focus moves to the next row's title or the Add button.
- minRows rows are present from the start; their Remove is hidden.

### 4.8 File upload (Phase 3 backend; UI built in Phase 2 preview mode)

```
 Copy of ID card
 PDF, JPG or PNG. Up to 2 files, 10 MB each.
 ┌ - - - - - - - - - - - - - - - - - - ┐
 ┆   ⇪  Drag files here or              ┆   Empty (dashed) on pointer devices
 ┆      [ Choose files ]                ┆   phones: just the button, full width
 └ - - - - - - - - - - - - - - - - - - ┘
 ┌──────────────────────────────────────┐
 │ 📄 id-front.pdf   1.2 MB     [✕]    │  Item: media icon, title, description, action
 │ ███████████░░░░░ 64%                 │  Progress while uploading
 └──────────────────────────────────────┘
 ┌──────────────────────────────────────┐
 │ 📄 id-back.jpg    Couldn't upload. [Retry] [✕] │  stamp text
 └──────────────────────────────────────┘
```

- Composition: `Empty` (dashed border variant) with `EmptyMedia` + `EmptyDescription` and a
  `Button` that triggers a visually hidden `<input type="file" multiple accept=…>`; files as
  `Item` [add] rows (`ItemMedia` file-type icon, `ItemTitle` name in `<bdi>`, `ItemDescription`
  size or status, `ItemActions` remove/retry) with `Progress` [add].
- Uploads start immediately on select. "Next" is disabled with reason ("Wait for uploads to
  finish") while any upload is in flight.
- After max files, the drop area is replaced by muted text "You've added 2 files, the most
  allowed. Remove one to add another."
- Keyboard: the button is the focus target; the drop zone is pointer-only enhancement.
- Image files show a 40px thumbnail in `ItemMedia variant="image"`.

### 4.9 Signature pad (Phase 5)

```
 Signature
 I sign this application.                    attestation, text-base
 ┌──────────────────────────────────────┐
 │                                      │   Card, bare <canvas>, 180px tall (phones)
 │          ~~~ signature ~~~           │   220px ≥ sm; aspect stays with width
 │ ──────────────────────────────────── │   baseline hairline at 70% height
 │ Sign with your finger or mouse       │   muted, disappears after first stroke
 └──────────────────────────────────────┘
 [ ↶ Undo stroke ]  [ Clear ]                Button outline / ghost
```

- `Card` + `CardContent` around the `<canvas>`; buttons `Button variant="outline" size="sm"`.
  Canvas has `touch-action: none` so drawing does not scroll the page; the rest of the page
  still scrolls normally.
- Ink colour is Ink (dark mode: light ink); line width scales with DPR and pressure.
- Not RTL-mirrored (drawing is direction-free), but the buttons and attestation follow `dir`.
- Accessibility: canvas `role="img"` with `aria-label` "Signature pad. Signed" / "…Empty";
  a keyboard-only or screen-reader user gets the instruction "If you can't draw a signature,
  contact the form owner" (alternative capture is out of scope for v1, note in a11y report).
- Errors: "Sign in the box" (empty), "Your signature is too small. Sign across the box."
  (server bounding-box rule).
- Landscape hint on phones narrower than 360px: muted text "Turn your phone sideways for
  more room." No forced rotation.

### 4.10 Navigation bar and progress

- Bottom bar on phones: `sticky bottom-0` with Sheet background, hairline `border-t`,
  `pb-[env(safe-area-inset-bottom)]`. Contains `Button variant="outline"` "Back" (hidden on
  first page) and primary `Button` "Next" / submit text, both `h-12`, Next takes the
  remaining width. On ≥ md the bar is inline at the end of the sheet, not sticky.
- Chevron icons flip in RTL (`rtl:rotate-180`).
- Progress: `Progress` [add] value = index in the evaluated path / path length. Because logic
  can change the path, the label is "Step {n} of {total}" recomputed live (numbers wrapped in
  `<bdi dir="ltr">` so RTL does not reverse them); never show a
  percentage. Single-page forms show no progress.
- Back keeps answers. Leaving the page with answers entered triggers the browser's
  `beforeunload` prompt.
- Page change: scroll to top of the sheet, move focus to the page title (`tabIndex=-1`),
  announce "Step {n} of {total}: {page title}".

### 4.11 Success, closed and error screens

- **Success**: sheet with check icon (carbon, 32px), `text-2xl` the form's success message
  (default "Thanks. We've received your answers."), then "Your reference" (muted) and the
  number `#0042` in `text-3xl tabular-nums` with the one stamp-landing animation; [Copy
  reference] ghost button. If the form allows another response: [Submit another response].
  Start-aligned except the reference block, which is centred.
- **Closed (410)**: "This form is closed" / "It's no longer accepting responses. Contact the
  organisation that sent you the link if you need help."
- **Not found (404)**: "We can't find this form" / "Check the link. It may have been
  mistyped or the form may have been removed."
- **Submit failed (network)**: inline `Alert variant="destructive"` above the nav bar:
  "Couldn't send your answers. Check your connection and try again. Your answers are still
  here." + the Submit button stays enabled. Never clear the form.
- **Version changed (409)**: `Alert` (info): "This form was updated while you were filling it
  in. We kept your answers. Check the highlighted questions and submit again." Changed or new
  questions get the marker wash.
- **Loading**: render the sheet frame with title skeleton and 3 field skeletons after 300ms;
  no spinner overlay.
- All of these use `Empty` (`EmptyHeader`, `EmptyTitle`, `EmptyDescription`) inside the sheet.

### 4.12 Renderer accessibility and RTL checklist

- Form root: `<main lang dir>` wrapped in `DirectionProvider`; `<h1>` is the form title; page
  title is `<h2>`; sections are `<fieldset>`/`<legend>`.
- Every control has a visible `<label>`; groups use `fieldset`/`legend` (RadioGroup,
  checkboxes, rating, yes/no).
- Focus ring visible on every control (carbon, 3px), including choice-card rows.
- Text resizes to 200% without loss; layout reflows at 320px width (WCAG 1.4.10).
- Touch targets ≥ 44×44px.
- Logic-driven show/hide: newly shown questions are not announced individually (noisy);
  instead, after a change that reveals questions, a polite live region says "{n} more
  questions" once.
- Thaana: `lang="dv"` on root; inputs that accept Latin data `dir="ltr"`; mixed content in
  `bdi`.

## 5. Submissions (Phase 3, designed now)

Route `/forms/$id/submissions`. Staff triage: find, open, decide, export.

### 5.1 Flow

1. Open Submissions from the form bar. Default view: status "New", newest first.
2. Scan the table; search or filter.
3. Click a row: detail opens in a `Sheet` from the end edge (table stays visible behind).
4. Read answers, open files, set status, comment. Next/Previous moves through the filtered
   list without closing.
5. Select rows for bulk status change or export.

### 5.2 Desktop wireframe

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Forms / Youth programme application      Edit  Preview  Share  Submissions           │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ Submissions                                                          [Export ▾]      │
│ [New 12][In review 4][Approved 30][Rejected 2][All 48]                               │
│ [🔍 Search answers        ] [+ Filter] [Submitted: Any time ▾] [Columns ▾]            │
│ ┌────────────────────────────────────────────────────────────────────────────────┐   │
│ │ ☐ │ #   │ Submitted ▾     │ Status       │ Full name      │ National ID │ Age │   │
│ │───┼─────┼─────────────────┼──────────────┼────────────────┼─────────────┼─────│   │
│ │ ☐ │ 48  │ Today 14:12     │ ● New        │ Aminath Ali    │ ••••567     │ 19  │   │
│ │ ☐ │ 47  │ Today 09:03     │ ◐ In review  │ މުޙައްމަދު ޙަސަން │ ••••221     │ 24  │   │
│ │ ☐ │ 46  │ 21 Oct 16:40    │ ✓ Approved   │ Ibrahim Naseer │ ••••903     │ 31  │   │
│ └────────────────────────────────────────────────────────────────────────────────┘   │
│ Showing 1–50                                              [‹ Newer] [Older ›]        │
└──────────────────────────────────────────────────────────────────────────────────────┘
 With rows selected, a bar replaces the filter row:
 │ 3 selected   [Change status ▾] [Export selected] [Delete]          [Clear selection] │
```

| Piece | Component |
|---|---|
| Status tabs with counts | `Tabs` (`TabsList`, `TabsTrigger` with count `Badge variant="secondary"`) |
| Search | `InputGroup` [add] with search icon; debounced 300ms; `Kbd` "/" hint |
| Filters | `Popover` [add] "Filter" building chips: field `Command` → operator `Select` → value; active filters as `Badge variant="outline"` with remove button |
| Date range | `Popover` + `Calendar mode="range"` [add] with presets (Today, Last 7 days, Last 30 days, Any time) |
| Columns | `DropdownMenu` with `DropdownMenuCheckboxItem`s; persisted per user per form |
| Table | `Table` + TanStack Table; sticky header; first two columns sticky at start on scroll |
| Row select | `Checkbox` [add]; header checkbox selects page |
| Status cell | `Badge`: New = carbon `default` + dot; In review = marker wash (`bg-accent text-accent-foreground`) + half-circle icon; Approved = `outline` + check; Rejected = `destructive` + x. Icon + word always |
| Sensitive cells | masked `••••567` in mono-free tabular text, lock icon, `Tooltip` "Sensitive. Open the submission to view." |
| Thaana cells | each cell sets `dir="auto"` and Thaana font via `:lang`/`dir=auto` handling so mixed rows align correctly |
| Paging | `Button variant="outline"` Newer/Older (cursor), "Showing 1–50" |
| Bulk bar | `ButtonGroup`, `DropdownMenu` for status, `AlertDialog` for delete |
| Export | `DropdownMenu` "Export all matching (48)", "Export selected"; then `Dialog` "Export to Excel" (fixed headers are English; question labels are in the form's language) and [Export]; progress `Progress` + toast "Export ready" with "Download" |

### 5.3 Detail (Sheet)

```
┌──────────────────────── Sheet (end edge, 40rem) ────────────────────────┐
│ #47   ◐ In review                      [‹ Prev] [Next ›]  [✕]            │
│ Submitted 23 Oct 2026 09:03, version 4, Dhivehi                         │
│ ✓ Integrity verified                                                    │
│ [Status: In review ▾]                       [Download PDF] [⋯]           │
│─────────────────────────────────────────────────────────────────────────│
│ [Answers] [Activity 3]                                                  │
│                                                                         │
│ About you                                       (page title, muted)     │
│   Full name            މުޙައްމަދު ޙަސަން                                  │
│   National ID number   ••••221  [Show]                                  │
│   Age                  24                                               │
│   Dependents           ┌ # │ Name     │ Relationship ┐                  │
│                        │ 1 │ Aisha    │ Child        │                  │
│                        └───┴──────────┴──────────────┘                  │
│ Documents                                                               │
│   Copy of ID card      [📄 id-front.pdf 1.2 MB] [🖼 id-back.jpg]          │
│                                                                         │
│─────────────────────────────────────────────────────────────────────────│
│ Add a comment                                                           │
│ [______________________________________________] [Comment]              │
└─────────────────────────────────────────────────────────────────────────┘
```

- `Sheet` [add] side "right" (resolves to the end edge via `DirectionProvider`), width
  `sm:max-w-2xl`. `SheetHeader` with `SheetTitle` "#47" and status `Badge`.
- Metadata line: separate `<span>`s with commas, not middle dots.
- Integrity: `Badge variant="outline"` with check "Integrity verified" or `destructive`
  "Integrity check failed" + `HoverCard` explaining.
- Status control: `Select` with the four statuses. Choosing "Rejected" opens an inline
  required `Textarea` "Reason (sent to the activity log)" + [Reject] [Cancel]; other changes
  apply immediately with toast "Status changed to Approved" + Undo.
- `Tabs`: "Answers" | "Activity {n}".
- Answers: rendered with the **submission's** schema version and language. The answers
  block gets `lang`/`dir` of the submission; labels and values in a two-column
  `<dl>` grid on ≥ sm, stacked on phones. Hidden/unanswered visible questions show
  "No answer" in muted. Repeaters as `Table`. Files as `Item` rows with download action,
  image thumbnails, PDF icon. Sensitive values masked with a `Button variant="link"` "Show"
  (logged; tooltip "Viewing is recorded").
- Activity: timeline list (`Item` rows with icon per event: created, status changed,
  comment, viewed, PDF generated, exported), newest first, comments inline.
- Keyboard: J / K next/previous submission, Esc closes, focus returns to the row.
- Phones: detail is a full route `/forms/$id/submissions/$sid` (not a Sheet); table becomes a
  list of `Item`s (reference, name/first text answer, status badge, time).

```
┌──────────────────────────────┐
│ ‹ Youth programme…           │
│ Submissions        [Export]  │
│ [New 12][In review 4][All…]→ │  Tabs scroll horizontally
│ [🔍 Search          ][Filter]│
│ ┌──────────────────────────┐ │
│ │ #48 Aminath Ali   ● New  │ │  Item
│ │ Today 14:12              │ │
│ ├──────────────────────────┤ │
│ │ #47 މުޙައްމަދު ޙަސަން ◐ In review│ │
│ │ Today 09:03              │ │
│ └──────────────────────────┘ │
│ [ Load older ]               │
└──────────────────────────────┘
```

### 5.4 Submissions states

| State | Treatment |
|---|---|
| Never published | `Empty`: "No submissions yet" / "Publish your form and share the link to start collecting responses." / [Go to Share] |
| Published, none yet | `Empty`: "No submissions yet" / "Responses appear here as soon as someone submits the form." / [Copy form link] |
| Filter matches nothing | inline in the table body: "No submissions match these filters." [Clear filters] |
| Loading | 8 `Skeleton` rows at row height, after 300ms |
| Error | `Alert variant="destructive"` above the table: "Couldn't load submissions. {reason}" [Try again] |
| Viewer role | status `Select` and bulk actions not rendered (not just disabled); a muted note "You can view submissions. Ask an owner to change status." |

## 6. Forms list (touch-up for consistency)

Superseded by [FORMS-LIST-SCREENS.md](FORMS-LIST-SCREENS.md) (owner, activity, filters, sorting).
Not a Phase 2 deliverable but it is the entry point:
- Page heading "Forms" + primary `Button` "New form".
- `Table` (not cards): Title, Status (`Badge`: Draft / Live / Closed), Submissions (new
  count), Updated, row `DropdownMenu` (Open, Duplicate, Share, Delete).
- Empty: `Empty` "Create your first form" / "Start from a blank form. You can add pages,
  questions and logic in the builder." [New form].
- Create dialog: "Title", "Form language" `RadioGroup` (English / Dhivehi), [Create form].

## 7. Copy glossary (keep names consistent)

| Concept | Use | Don't use |
|---|---|---|
| a field | question | field, input, element (except "Hidden value", "Text block") |
| page | page | step (except respondent progress "Step 2 of 3") |
| visibleIf | "Show this question when…" | condition, visibility rule |
| requiredIf | "Make required when…" | |
| page next | "After this page, go to…" | jump, skip logic |
| publish | Publish / Published | deploy, release, go live |
| draft | Unpublished changes | draft revision |
| version | Version 4 | v4, revision |
| key | Key | id, slug, name |
| submission | submission (staff), your answers (respondent) | entry, record, response (except "Accepting responses") |
| reference | reference `#0042` | seq, id |
