# Review changes and Discard changes

A published form shows "Unpublished changes" as soon as its draft differs from the live version.
Builders asked "what changed?" — an edit by a co-editor, a stray click on "Add page", an undo that
did not go all the way back. Review changes answers that before anyone publishes, and Discard
changes takes the draft back to what is live.

## 1. What counts as a change

Only the form document is versioned: pages, sections, repeaters, questions and content blocks,
their logic (show rules, required rules, page navigation) and the document's `settings` (title,
description, language, Next/Back/Submit button texts, the message after submitting, the legacy
theme accent). Everything stored on the form record applies at once without publishing and is
never listed: address (slug), access, CAPTCHA, saved progress, sharing, notifications, approvals,
embed origins, form theme and logo, retention, submission cards and version mappings.

Both documents are compared with their defaults filled in (a missing `required` equals
`required: false`). Elements are matched by id:

| Change | Rule |
|---|---|
| Added / removed | the id exists only in the draft / only in the live version (children of an added or removed section, repeater or page are listed too) |
| Moved | same id, different parent (page, section, repeater), or a different order among the siblings that stayed (the longest common subsequence keeps its place; the rest moved) |
| Changed | any property differs; each property is listed with before → after |
| Page | added, removed, moved (order of pages, not the page numbers that shift after an insert), or changed (title, description, show rule, navigation) |

Property names are the inspector's labels ("Help text", "Shown when", "Max size (MB)").
Options list added, removed and renamed options (same value, new label) and "Options
reordered". Rules are written as sentences with the labels of their own version ("Age is at
least 18", "If Age is at least 18, go to Adults").

## 2. API

`GET /forms/{id}/draft/changes` (owner, editor) returns `baseVersion`, `revision`, `hasChanges`,
`summary` ("1 page added, 2 questions changed"), `counts`, `language`, `settings[]` and
`pages[]` (each with its own `changes[]` and `elements[]`). Every before/after value is a list
of pieces `{text, content}`: `content` marks form-language text, so the studio isolates it with
the form's direction inside English sentences. Before the first publish `baseVersion` is null
and the lists are empty.

`POST /forms/{id}/draft/discard {baseRevision}` (owner, editor) applies the patch back to the
live version as one ordinary draft edit: one Undo restores everything, the redo stack is
dropped, the audit log gets `form.draft_discard`. A stale revision is a 409
`revision_conflict`; a form that was never published is a 409 `never_published`; a draft that
already matches is left alone.

## 3. Studio

| Where | Control |
|---|---|
| Form bar, >= 1024px | "Unpublished changes" badge (>= 1280px), `Button variant="outline" size="sm"` "Review changes" with a diff icon (icon only below 1280px, tooltip), Publish |
| Compact bar, < 1024px | Form menu item "Review changes" while there is something to publish |
| Publish dialog | for a re-publish: "Publish version N?", the summary sentence and the compact list (one line per change), "Review changes" (ghost), Cancel, Publish |

### Review changes sheet

```
┌ Review changes ─────────────────────────── ✕ ┐
│ 1 page added, 3 questions changed since      │
│ version 2, the live version.                 │
├──────────────────────────────────────────────┤
│ Form settings  (Changed)                     │
│ ┃ Submit button text                         │
│ ┃ [+ Send application]                       │
│ Page 1, About you                            │
│ ┃ Full legal name               (Changed)    │
│ ┃ Short answer                               │
│ ┃ Label                                      │
│ ┃ [− Full name]                              │
│ ┃ [+ Full legal name]                        │
│ ┃ Required   ~~Off~~ → On                    │
│ ┃ Organisation (if any)         (Removed)    │
│ Page 3, Supporting documents  (Added)        │
├──────────────────────────────────────────────┤
│              [Discard changes…]  [Publish]   │
└──────────────────────────────────────────────┘
```

- `Sheet side="right"`, full width on phones, `sm:max-w-xl` above. Header and footer stay; the
  list scrolls (`ScrollArea`). Footer buttons stack full width on phones (Publish at the bottom,
  in thumb reach).
- Each change is a card with a 4px start border and an outline `Badge`: Added (green, the
  `--added` token), Removed (destructive), Changed (primary), Moved (muted). Colour is never the
  only cue: the badge says it, values carry +/− icons and screen-reader "Before:"/"After:".
- Text values: a red row (−) for before and a green row (+) for after. Longer than 140
  characters: three lines and "Show all"/"Show less". Short English values (On/Off, numbers,
  widths) sit on one line: ~~before~~ → after.
- Form content (labels, options, titles, help text) uses `contentProps(language)`: a Dhivehi
  value is a right-to-left Thaana paragraph; rules keep the English sentence left-to-right with
  each label isolated in a `bdi`.
- The sheet saves pending edits before it loads, so the list matches the draft on screen.
- No changes: an `Empty` "No unpublished changes"; Publish and Discard are disabled.

### Discard changes

`AlertDialog`: "Discard unpublished changes?" — "The draft goes back to version N, the live
version (… will be undone). You can bring the changes back with Undo." Cancel / Discard changes
(`variant="destructive"`, spinner while working). After it: the sheet closes and a toast
"Changes discarded. The draft matches version N." offers Undo. A conflict toast asks to reload.

### Publishing from the sheet

Publish closes the sheet and publishes straight away (the changes were just shown) unless the
form has problems or approval warnings, which open the Publish dialog as before. Publish in the
form bar and Ctrl/Cmd+Enter always open the dialog with the summary.
