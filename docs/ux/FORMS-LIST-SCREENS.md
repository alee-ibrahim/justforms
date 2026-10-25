# Forms list

The forms list (`/forms`) is where staff start every session. It answers, per form: whose is it,
is it taking submissions, is anything waiting for me, and when did something last happen.
Tokens, type and motion come from [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with
[REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md). Copy in "quotes" ships as written, English only.
Replaces the touch-up in [PHASE-2-SCREENS.md](PHASE-2-SCREENS.md) §6.

Nothing new from shadcn: `table`, `item`, `avatar`, `badge`, `native-select`, `input-group`,
`dropdown-menu`, `tooltip`, `empty`, `skeleton` and `alert` are installed.

## 1. What a row shows

Everything comes from one list request (`GET /orgs/{id}/forms`, one SQL query with per-form
aggregates). A row only carries what anyone with a role on the form may already see: owners and
editors are on the form's Share page, counts are on its Submissions page.

| Fact | Source | Shown as |
|---|---|---|
| Title | form title, in the form's language | opens Submissions once the form has any (always for submissions viewers), else the builder; `lang`/`dir` from the form |
| Owner | the form's creator while they are an owner, else the earliest owner | `Avatar` initials + name; "You" for the viewer; more owners: "+2" with the names in the row's accessible text |
| Status | `draft` / `live` / `closed` / `archived` | `FormStatusBadge` (Draft / Live / Closed / Archived, icon + word) |
| Unpublished changes | published form whose draft differs from the live version | muted "Unpublished changes" with `FilePenLineIcon` under the badge |
| Language | `settings.language` | `Badge variant="outline"` "Dhivehi" for dv forms only |
| Who can fill it in | access mode | icon + short label: `GlobeIcon` "Anyone", `MailCheckIcon` "Email code", `BuildingIcon` "Staff only" |
| Submissions | not deleted | count; `Badge` "{n} new" (status New); muted "{n} in last 7 days" |
| Waiting for approval | when the form's approval workflow is on | `Badge variant="secondary"` with `ClockIcon` "{n} awaiting approval" |
| Last submission | latest `submitted_at` | relative ("2 hours ago"); full date in `title`; "-" when none |
| Last edited | latest draft edit (or creation) and who did it | relative time, "by {name}" / "by you" below |
| Imported | form imported from Jotform | muted `FileInputIcon` "Imported from Jotform" |

## 2. Toolbar

```
Forms                                         [Import from Jotform] [New form]
[⌕ Search forms            ] [Owner ▾ Everyone] [Status ▾ All] [Sort ▾ Last edited]
```

- Search: `InputGroup` with `SearchIcon`, placeholder "Search forms", matches title and owner.
- Owner: `NativeSelect` "Everyone" / "Owned by me" (explicit owner grants; admins own every form
  implicitly, so "Owned by me" means the forms they were made owner of).
- Status: `NativeSelect` "All statuses" / Draft / Live / Closed / Archived.
- Sort: `NativeSelect` "Last edited" (newest first, default), "Last submission" (newest first,
  never-submitted last), "Name" (A to Z), "Submissions" (most first).
- Every select has a visible label on ≥ sm and an `aria-label`; all four live in the URL
  (`?q=&owner=mine&status=live&sort=name`) so Back and shared links keep the view.
- Phone: search full width, labelled selects below in three columns (two under 400px, Sort on
  its own row), 44px tall.
- The sorted column's header carries `aria-sort`.

## 3. Desktop (≥ lg): table

```
Form                          Owner             Status            Submissions          Last submission  Last edited       ⋯
Youth grant application       (AA) You          (●) Live          128  [3 new]         2 hours ago      Yesterday         ⋯
 Anyone  Dhivehi                                Unpublished        5 in last 7 days                     by Aminath Ali
                                                changes            [◷ 2 awaiting approval]
Staff survey                  (IN) Ibrahim N.   (✎) Draft          -                    -                3 days ago        ⋯
 Staff only  Imported from Jotform  +1                                                                  by you
```

- Columns: Form, Owner, Status, Submissions, Last submission (≥ xl), Last edited, menu. Below lg
  the table does not fit next to the badges (768px tablets overflowed), so tablets get cards too.
- The submissions cell links to Submissions, as before. Row height grows to two lines; no
  zebra stripes, no shadows; hairline row borders only.
- Times are relative (`Intl.RelativeTimeFormat`, "just now" under a minute, "yesterday"),
  English, Western digits, with the full date and time in a `title`.

## 4. Phones and tablets (< lg): cards

One `Item variant="outline"` per form inside an `ItemGroup`, four facts only:

```
┌──────────────────────────────────────────┐
│ Youth grant application              ⋯   │
│ (●) Live  [3 new]  128 submissions       │
│ (AA) You     Last submission 2 hours ago │
└──────────────────────────────────────────┘
```

Title (link), status badge + new badge + count, owner + last submission. Awaiting approval
replaces the count line's tail when non-zero ("2 awaiting approval"). Language, access mode
and edit details stay on the desktop table.

## 5. Opening a form

- A click anywhere on a row (table) or card opens the form where the title link goes: its
  Submissions when it has any, else the builder. Clicks on links, buttons and the menu keep
  their own action; selecting text doesn't navigate. Keyboard users use the title link (same
  destination), so nothing is reachable by mouse only.
- The row menu always offers Edit (editors and owners), Submissions, Share, Duplicate and
  Delete (owners), so both destinations are always one step away.

## 6. States

| State | Copy |
|---|---|
| Loading | 4 `Skeleton` rows after 300ms |
| Error | `Alert variant="destructive"` "Couldn't load your forms. Check your connection and reload the page." |
| No forms | unchanged `Empty` states (creator / member) |
| Filters match nothing | inline: "No forms match these filters." [Clear filters] |

## 7. Self-critique

| First idea | Problem | Changed to |
|---|---|---|
| A card grid with a thumbnail per form | SaaS-kit tell; thumbnails of form sheets look identical | Table on desktop, compact cards only on phones |
| Owner column with avatar, name and email on two lines | Too wide next to six other columns | Name only; email is on the Share page |
| Coloured status pills (green live, grey draft) | Status by colour alone; second saturated colour | Existing icon + word badge |
| Sortable column headers | Hidden affordance on phones, where there are no headers | One "Sort" select that works the same everywhere, plus `aria-sort` |
| "New since you last looked" | Needs per-person read tracking for a list-level hint | "New" (status) badge plus "in last 7 days" |
