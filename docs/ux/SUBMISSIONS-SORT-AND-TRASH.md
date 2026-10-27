# Sorting, the trash and undo on Edit

Three studio changes that share the submissions screen:

1. The submissions table sorts by any column.
2. Deleted submissions and forms go to a **trash** and can be restored; deleting shows an
   Undo toast.
3. The form bar's undo and redo show only on the builder (Edit).

Backend: DESIGN 7 (permissions), 14.5 (retention and deletion), 15.1 (dashboard), 17 (API).

## 1. Sorting the submissions table

**Flow.** Click a column header: the table sorts by it; click again: the other direction.
Unset is **Submitted, newest first** (the header shows a down arrow). The order lives in the
URL (`sort=<column>&dir=asc|desc`), so Back, links, "Show these N submissions" from Ask and
Insights, filters, the status tabs and the submission page's Previous / Next all keep it.
Sorting is done by the server; "Load older" continues in the same order.

**Columns.** `#` (reference), Submitted, Status, Approval (only when some row has an approval),
Respondent email, and every answer column except files and signatures.

| Kind | Order | First click |
|---|---|---|
| Reference, Submitted | number, time | newest first |
| Text, email, hidden | alphabetical, case-insensitive (Unicode collation; Thaana in alphabet order) | A to Z |
| Number, rating | numeric | low to high |
| Date, time | chronological | oldest first |
| Single choice | option order; "Other" answers after the options | option order |
| Multiple choice | the first chosen option, in option order | option order |
| Yes/no | No, then Yes | No first |
| Phone | by its digits | low to high |
| Status | New, In review, Approved, Rejected | first to last |

Empty answers always come last, in both directions. Ties keep a stable order (newest first).

**Components.** Table header: `TableHead` with `aria-sort` holding a ghost `Button`
(`size="sm"`): the label and an arrow (`ArrowUp`/`ArrowDown`; `ArrowUpDown` muted when the
column is not sorted). The button's title says what the next click does ("Sort: High to
low"). Keyboard: Tab to the header button, Enter or Space.

Cards (and phones, which always show cards) get a **Sort** menu (`DropdownMenu`) after the
date filter: "Direction" (`DropdownMenuRadioGroup`, words by kind: "A to Z", "Newest first",
"Low to high", "Option order") and "Sort by" (radio list of the columns above). On phones it
is an icon button (`ArrowDownUp`) labelled "Sort: <column>, <direction>". Cards sorted by an
answer they don't show add that answer to each card.

**Export.** Exports stay oldest first by reference number. When the table is sorted, the
Export dialog offers "Keep the order the table is sorted in (otherwise oldest first)"
(`Checkbox` in a horizontal `Field`).

```
 #  ↑↓  Submitted ↓   Status ↑↓   Full name ↑↓   Amount requested ↑↓
```

## 2. Deleting with Undo

Deleting is reversible now, so it has **no confirmation dialog** (REVIEW-CHECKLIST E): the
items leave the list at once and a toast offers Undo for 10 seconds.

- Submissions (selection bar › Delete): "Deleted 3 submissions" / "In Deleted for 30 days."
  [Undo]. Undo restores the same submissions; then "Restored 3 submissions".
- Forms (forms list › row menu › Delete): "Moved the form to Trash" / "Restorable for 30
  days, with its submissions." [Undo]. When another form took its address in the meantime,
  Undo says "Its address was taken meanwhile" [Open Trash].

## 3. Submissions › Deleted

Owners (whoever may delete may restore; organisation admins and superadmins are owners of
every form) see a **Deleted** tab after All, with its count, while the form has deleted
submissions (or while it is open). Others never see it; `?status=deleted` falls back to All
for them.

```
New 3  In review 0  Approved 0  Rejected 0  All 5   Deleted 3
Deleted submissions are kept for 30 days, then erased for good with their files.
┌──┬────┬──────────────┬───────────────────┬───────────────────┬────────────────────────┬──────────┐
│☐ │ #  │ Answer       │ Submitted         │ Deleted           │ Permanently deleted on │          │
│☐ │ 8  │ Mohamed Riyaz│ 27 Oct 2026, 11:54│ 27 Oct 2026, 11:54│ 26 Nov 2026            │ [Restore]│
│  │    │              │                   │ by you            │                        │          │
└──┴────┴──────────────┴───────────────────┴───────────────────┴────────────────────────┴──────────┘
```

- **Answer** is the first card field with an answer (the submission's own words).
- The note under the tabs says how long they stay; with a form retention period it adds "This
  form keeps submissions for N days, so some may go sooner." The date per row is the earlier
  of the two.
- Selecting rows swaps the note for a selection bar: "N selected", **Restore**, **Delete
  permanently…** (destructive), Clear selection.
- Below 1024px: `Item` rows (checkbox, "#0008 Mohamed Riyaz", "Deleted <date> by <who>",
  "Permanently deleted on <date>", Restore).
- Deleted submissions cannot be opened; restore one to see it.
- Empty: `Empty` with a trash icon, "Nothing deleted", "Deleted submissions stay here for 30
  days, so you can restore them."
- Restored submissions keep their reference number, answers, files and activity log; the log
  gains "<who> restored this submission".

### 3.4 Delete permanently

`AlertDialog` with a typed confirmation (`Field` + `Input`): "Permanently delete 2
submissions?" / "Their answers, files, signatures and signed PDFs are erased now and can't be
restored. A record that they existed stays in the audit log." / Type "delete" to confirm /
"This can't be undone." / [Cancel] [Delete 2 permanently] (disabled until the word matches).

## 4. Forms › Trash

The forms page header gets a ghost **Trash** link (icon only on phones). `/forms/trash`
lists deleted forms the person may restore: their own, or every form of the organisation for
admins and superadmins. Most recently deleted first.

```
‹ Forms
Trash
Deleted forms stay here for 30 days with their submissions, then they are erased for good.
┌──────────────────────────────┬───────────────────┬─────────────┬────────────────────────┬────────────────┐
│ Form                         │ Deleted           │ Submissions │ Permanently deleted on │                │
│ Volunteer sign-up            │ 27 Oct 2026, 11:59│ 2           │ 26 Nov 2026            │ [Restore] [⋯]  │
│ /volunteer-sign-up           │ by you            │             │                        │                │
└──────────────────────────────┴───────────────────┴─────────────┴────────────────────────┴────────────────┘
```

- **Restore** brings back the form, its link, versions, settings and submissions (those
  deleted on their own before stay in its Deleted tab). Toast "Restored <title>" [Open].
- **Address taken.** When another form now uses the address, the row says "(now used by
  another form)" and Restore opens "Restore at a new address": the address field (an
  `InputGroup` with the host as prefix) prefilled with a free suggestion, checked live as in
  Share › Address.
- **⋯ › Delete permanently…**: the typed confirmation (3.4) naming the form and how many
  submissions go with it.
- Phones: `Item` rows; below `lg` the table becomes these rows.
- Empty: "The trash is empty" / "Forms you delete stay here for 30 days, so you can restore
  them." [Back to forms].

## 5. Undo and redo only on Edit

The form-level undo and redo change the draft, which is only on screen in the builder. They
show **only on Edit**: the desktop form bar's history buttons, the phone form menu's Undo and
Redo items, and the Ctrl/⌘+Z, Ctrl/⌘+Shift+Z and Ctrl/⌘+Y shortcuts. Preview, Share,
Submissions (Responses, Insights, a submission), Settings and the import pages have none. The
save state, Review changes and Publish stay on every form page where they were.

## 6. Self-critique

- First idea: a "Show deleted" switch on the list. A tab with a count is easier to find, keeps
  the trash out of filters and exports, and matches the status tabs.
- First idea: a confirmation dialog before deleting plus a toast. The checklist asks for one
  or the other; since deleting can be undone, the toast alone is faster and the dialog moved
  to the one action that can't be undone (Delete permanently), with a typed word.
- The forms trash first showed each form's status badge: "Live" next to a deleted form
  confused; dropped.
