# People, invitations and organisation roles

Organisation admins see who can sign in to their organisation, invite people by email, change
what they can do and remove them. A form owner who shares a form with someone outside the
organisation can invite them in the same step when they are an admin. Tokens, type and motion
come from [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with
[REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md). Copy in "quotes" ships as written, English only.
Data model, API and rules: DESIGN §6, §7, §8 and §17.

Nothing new from shadcn: `table`, `dialog`, `alert-dialog`, `dropdown-menu`, `radio-group`,
`textarea`, `input`, `field`, `badge`, `avatar`, `item`, `empty`, `skeleton`, `spinner`,
`tooltip`, `alert`, `native-select`, `card` and `button` are installed.

## 1. Roles

Three organisation roles. The word in the UI is on the left; the stored value in brackets.

| Role | Can | Can't |
|---|---|---|
| **Admin** (`admin`) | Everything: organisation settings, branding, form theme, people. Acts as owner of every form. | |
| **Form creator** (`creator`) | Create and import forms (they become the owner), duplicate forms they can edit. Sees forms they created and forms shared with them. | Organisation settings, people, other people's forms unless shared. |
| **Member** (`member`) | Open the forms shared with them, in the role they were given (submissions viewer, editor, owner). | Create, import or duplicate forms; organisation settings. |

Form roles (owner, editor, viewer) don't change; `viewer` reads "Submissions viewer" in the UI. Superadmins act as admins of every
organisation. One-line descriptions, used wherever a role is picked:

- Admin: "Everything, including organisation settings and people. Owner of every form."
- Form creator: "Creates forms. Sees the forms they created or that are shared with them."
- Member: "Sees only the forms shared with them. Can't create forms."

Upgrade: everyone who was a `member` before this change could create forms, so they become
**Form creator**; nobody loses access. New people default to **Member**.

## 2. Where it lives: Organisation settings

`/settings` becomes a page with sections, the same pattern as form Settings (PHASE-4-SCREENS
and REVIEW P2-12): a section list at the start edge on ≥ lg, a `NativeSelect` "Section" on
smaller screens. Each section is its own route so it can be linked:

| Section | Route | Content |
|---|---|---|
| Branding | `/settings` | `BrandingCard` (BRANDING-SCREENS 3) |
| Form theme | `/settings/form-theme` | `OrgFormThemeCard` (FORM-THEME-SCREENS 3.2) |
| People | `/settings/people` | this document |

When the signed-in person belongs to more than one organisation (superadmins always see every
organisation), an "Organisation" `NativeSelect` sits under the page heading and the choice is
kept in the URL (`?org=<id>`). With one organisation nothing extra shows.

The account menu item "Organisation settings" stays admin-only. A non-admin who opens
`/settings/people` sees `Alert` "Only organisation admins can manage people."

## 3. People section

```
 Organisation settings                                              (h1)
 ┌────────────┐  People                                  [+ Invite people]
 │ Branding   │  Who can sign in to Example Office and what they can do.
 │ Form theme │  [🔍 Search by name or email            ]
 │▌People     │  ┌──────────────────────────────────────────────────────────┐
 └────────────┘  │ Person                 Role          Status        Last sign-in  ⋯ │
                 │ (AE) Aisha Example     Admin         ● Active      24 Oct 2026   ⋯ │
                 │      aisha@example.org                                          │
                 │ (BE) bob@example.org   Form creator  ✉ Invited     Expires 7 Nov ⋯ │
                 │ (CR) Chen Rivera       Member        ◌ Never signed in   -       ⋯ │
                 │ (DK) dee@example.org   Member        ⏱ Invite expired   -       ⋯ │
                 └──────────────────────────────────────────────────────────┘
                 Roles
                 Admin: Everything, including …
                 Form creator: Creates forms. …
                 Member: Sees only the forms shared with them. …
```

Phone (< sm): the table keeps two columns, "Person" and the actions menu. Under the email,
the role and the status badge sit on one wrapping row (role as plain muted text, status as
a badge), and "Last sign-in" is folded into the actions sheet. "Invite people" becomes a full-width button under
the description. Search stays full width.

- Heading `h2` "People" (`text-lg font-semibold`), description in muted `text-sm`:
  "Who can sign in to {organisation} and what they can do." (`bdi dir="auto"` around the name).
- **Search**: `InputGroup` with a search icon, placeholder "Search by name or email",
  `type="search"`, filters client-side (lists are small; the API returns everyone). No
  results: a table row "No one matches “{query}”." with a "Clear search" link button.
- **Table** (`Table` inside `rounded-md border bg-card`, rows 40 px, 44 px on touch):
  - Person: `Avatar` (initials) + name (or email when there is no name) + email under it in
    muted text. Emails in `bdi dir="ltr"`. "(you)" after your own name in muted text.
  - Role: plain text ("Admin", "Form creator", "Member"). For people whose role comes from
    sign-in groups (OIDC group mapping, DESIGN §7) a muted "Set by sign-in groups" line sits
    under it.
  - Status: `Badge` with icon + word, never colour alone:
    - "Active" (`CircleCheck`, `secondary`): has signed in.
    - "Never signed in" (`CircleDashed`, `outline`): a member who hasn't signed in yet
      (added by the command line or the API).
    - "Invited" (`Mail`, `outline`): a pending invitation.
    - "Invite expired" (`Clock`, `outline`).
    - "Email not sent" (`MailX`, `destructive`): the invitation email failed; tooltip with
      the reason ("Email isn't set up on this server.").
  - Last sign-in: date (`formatDate`, tabular figures); for invitations "Expires {date}" or
    "Expired {date}"; "-" when never.
  - Actions: `DropdownMenu` on a ghost icon button, `aria-label` "Actions for {name}"
    (tooltip with the same text). Members: "Change role", separator, "Remove from
    organisation" (`variant="destructive"`). Invitations: "Change role", "Resend invite",
    separator, "Cancel invite" (destructive). For yourself the remove item reads "Leave
    organisation".
- Order: pending and expired invitations first (newest first), then members by name.
- **Roles** legend under the table: a `dl` with the three role names (medium weight) and
  their one-line descriptions, muted. It answers "what does Form creator mean" without a
  tooltip hunt.

### 3.1 Invite people dialog

`Dialog` (scrolls inside when taller than the screen; the footer with the buttons is sticky
at the bottom so Send stays reachable on a phone; no custom drawer). Title "Invite people", description "They get an email with a link to join
{organisation}. The link works for 14 days."

```
 Invite people                                        ✕
 They get an email with a link to join Example Office. …
 Email addresses
 ┌─────────────────────────────────────────────┐
 │ ana@example.org, ben@example.org            │
 │                                             │
 └─────────────────────────────────────────────┘
 Separate addresses with commas, spaces or new lines. Up to 20 at a time.
 Role
 (•) Member         Sees only the forms shared with them. Can't create forms.
 ( ) Form creator   Creates forms. Sees the forms they created or …
 ( ) Admin          Everything, including organisation settings and people. …
                                           [Cancel] [Send 2 invites]
```

- `Field` + `FieldLabel` "Email addresses" + the member combobox (6.2) + `FieldDescription`
  "Type a name to find people already here, or paste addresses separated by commas, spaces or
  new lines. Up to 20 at a time." (Was a `Textarea`; replaced by chips so members can be
  spotted while typing.) Finished addresses (followed by a comma, space, semicolon or new
  line, pasted lists, Enter, or the "Invite {email}" row) become chips above the input (so
  the suggestion list never covers them): a
  secondary `Button size="sm"` per address with an `X` icon, `aria-label` "Remove {email}"
  (destructive variant when it isn't an address). Backspace in the empty input removes the
  last chip.
- Role: `RadioGroup` of three `Field orientation="horizontal"` rows with `FieldLabel` and
  `FieldDescription` (choice-card style from shadcn `Field` docs); default Member.
- Submit button text counts the valid addresses: "Send invite" / "Send {n} invites";
  disabled with none. `Spinner` while sending.
- Validation (client, then server): "Enter at least one email address." / "Check these
  addresses: {list}." / "Invite up to 20 people at a time." Errors in `FieldError`.
- When email isn't set up on the server (`meta.features.email` false): `Alert` above the
  buttons "Email isn't set up on this server, so no invitation email goes out. Invited
  people can still join by signing in with this address." (single sign-on), or "…
  Ask your server administrator to set up email." (email-code sign-in, where they can't get
  a code either).
- Result: all invited → dialog closes, toast "Invited {n} people" / "Invited
  ana@example.org". Some skipped → the dialog stays open with an `Alert`: "Invited 1.
  Already in Example Office: ben@example.org." and the textarea is cleared of the invited
  ones. Re-inviting someone with a pending invitation sends a fresh email and is reported
  as "Invited" (the role is updated). 429 → `FieldError` "You've sent a lot of invitations.
  Try again in {minutes} minutes."

### 3.2 Change role dialog

`Dialog` "Change role", description "{name} ({email})". The same `RadioGroup` as the invite
dialog, current role selected. Buttons "Cancel" / "Save role"; toast "Changed {name}'s role to
Form creator". For the last admin, the other options are disabled and a `FieldDescription`
says "Example Office needs at least one admin. Make someone else an admin first." Changing
your own role away from admin shows `Alert` "You'll lose access to organisation settings and
to forms that aren't shared with you." For roles set by sign-in groups: `Alert` "This
person's role is set by your sign-in groups. It changes back the next time they sign in."

### 3.3 Remove from organisation

`AlertDialog` "Remove {name} from {organisation}?" with "They can no longer open
{organisation}'s forms. Their access to the {n} forms shared with them is removed. Forms they
own stay, and admins can still manage them." Action "Remove from organisation"
(destructive), toast "Removed {name}". For yourself: "Leave {organisation}?" / "Leave
organisation". The last admin can't be removed: the menu item is disabled and says why under
its label, "{organisation} needs at least one admin." (a tooltip on a disabled menu item is
unreachable on touch screens).

What removal does (DESIGN §7): deletes the membership and every form grant the person had in
that organisation's forms, and cancels nothing else (their submissions comments and versions
keep their name). They keep their account; signing in shows "You aren't a member of any
organisation yet." if it was their only one.

### 3.4 Invitations: resend and cancel

- "Resend invite": sends a new email with a new link (the old link stops working) and resets
  the 14-day expiry. Toast "Sent a new invite to {email}". At most 3 per invitation per hour:
  toast "You've resent this invite a few times. Try again later."
- "Cancel invite": `AlertDialog` "Cancel the invite for {email}?" / "The link in their email
  stops working." Action "Cancel invite" (destructive), cancel button "Keep invite". Toast
  "Cancelled the invite for {email}".

### 3.5 States

- Loading: 4 `Skeleton` rows after 300 ms.
- Error: `Alert` destructive "Couldn't load people. Check your connection and try again."
  with "Try again".
- Only you: the table shows your row and an `Empty`-style muted line under it: "Invite the
  people you work with. They'll see only what you share with them unless you make them
  form creators or admins."

## 4. The invitation email

English, organisation branding (`EmailBrand`: logo/name header, button colour, footer
"Sent by {name}." + support link + "Powered by JustForms").

- Subject: "You've been invited to {organisation} on {product}" where product is the
  instance brand name (`JUSTFORMS_BRAND_NAME`, else "JustForms"); when both names are the
  same: "You've been invited to {organisation}".
- Body: heading "Join {organisation}". "{inviter} invited you to {organisation} as {a form
  creator | a member | an admin}." When forms were shared: "They shared these forms with
  you:" and one bold line per title (each with the form's `lang`/`dir` and alignment; no
  bullets, which land on the wrong side of a right-to-left title in a left-to-right email). Button "Accept the
  invitation". Then muted: "You'll sign in with a code we email to {email}." (email-code
  install) or "You'll sign in with your organisation account." (single sign-on). "The link
  works until {date}. If you weren't expecting this, you can ignore this email."
- The link is `/login/invite/{token}`; the token is stored only as a SHA-256 hash and is
  minted by the worker right before sending, committed first (the approval-email pattern,
  DESIGN §11.1). A resend replaces it.

## 5. Accepting: `/login/invite/{token}`

A studio route (same shell and branding as sign-in, using the inviting organisation's
branding). One `Card`, `max-w-sm`, like the sign-in page.

```
 ┌ Join Example Office ───────────────────────┐
 │ Aisha Example invited you as a form creator. │
 │ Email                                       │
 │ [ bob@example.org              ] (read-only)│
 │ [ Email me a sign-in code ]                 │
 └─────────────────────────────────────────────┘
```

- Pending, not signed in, email-code install: title "Join {organisation}", description
  "{inviter} invited you as {role phrase}." The email field is filled in and read-only
  ("This invitation is for this address."); the rest is the normal code flow. After the
  code is accepted the invitation is accepted on the server and the studio opens `/forms`
  with toast "You joined {organisation}".
- Pending, single sign-on with automatic sign-in (the default, DESIGN §8.1): no card, only
  "Signing you in…" while the browser goes to the IdP (next = this page, `login_hint` = the
  invited address). Not right after signing out, with `?manual=1`, or within 30 s of an
  attempt: then the card below.
- Pending, single sign-on: same card with "Sign in with single sign-on" (next = this page).
  The server accepts invitations when an IdP sign-in's email matches (case-insensitive,
  `email_verified` not false). Back on this page, already accepted and a member → `/forms`
  + toast "You joined {organisation}".
- Signed in as the invited address: accepted at once (`POST /invitations/{token}/accept`),
  then `/forms` + toast.
- Signed in as someone else: "This invitation is for bob@example.org" / "You're signed in as
  ana@example.org. Sign out, then open the link again or sign in as bob@example.org." Button
  "Sign out".
- Expired: title "This invitation has expired", text "Ask {inviter} or another admin of
  {organisation} to send a new one." Button "Go to sign-in".
- Already accepted: "This invitation was already accepted" / "Sign in with
  {email} to open {organisation}." Button "Sign in".
- Cancelled, replaced or unknown: "This invitation link doesn't work" / "It may have been
  cancelled, or a newer invitation email replaced it. Ask an admin of the organisation for
  a new one." Button "Go to sign-in".
- Loading: `Skeleton` card. 429: "Too many attempts. Wait a minute and try again."

People with a pending invitation can also simply sign in with that address on `/login`
without the link (the email code proves the address); pending invitations for it are
accepted then.

## 6. Sharing a form with someone new (Share › People with access)

When an owner adds an email that isn't in the organisation:

- **Org admin (or superadmin)**: under the email row an `Alert` (not destructive):
  "{email} isn't in {organisation} yet." with a button "Invite and share". Description
  under it: "They join as a member and get {role} access to this form when they accept."
  Clicking sends an invitation with the form grant (or adds the grant to their pending
  invitation) and adds a row to the list.
- **Other owners**: `FieldError` "{email} isn't in {organisation} yet. Ask an organisation
  admin to invite them." Only admins invite: inviting brings a person into the whole
  organisation, which is an admin decision.
- Pending people show in the list with their initials, email, an "Invited" `Badge`
  (`Mail` icon) and the form role they will get. Owners can remove that pending access
  (x button, "Remove the invited access for {email}"), which only drops this form from the
  invitation.

### 6.1 Notify by email

Adding a member to a form used to be silent; only invitations sent email. Now the owner can
email the person, with an optional note, when they get a role or a higher one.

**Add someone by email.** Under the email/role/Add row:

```
Add someone by email
[ name@example.org              ] [ Submissions viewer v ] [ Add ]
[x] Notify by email
    Message (optional)
    [ Add a note to the email                                  ]
    Plain text. Replies come to your email address.      0/500
A submissions viewer can view and export submissions, ...
```

Phone (390): the row wraps (email full width, then role and Add); the checkbox, message and
counter stack full width below it. Nothing scrolls sideways.

- `Checkbox` + `FieldLabel` "Notify by email" in a horizontal `Field`, **ticked by default**.
  The `Textarea` "Message (optional)" (2 rows, `maxLength` 500) shows only while it is ticked.
  `FieldDescription`: "Plain text. Replies come to your email address." with a live
  "{n}/500" counter (`tabular-nums`) at the end.
- The choice stays ticked after Add; the message clears after a successful save.
- Toast after Add: "Added {email} and emailed them" when an email was queued, else
  "Access updated". Adding someone already listed with the same or a lower role emails nobody.

**Raising someone's role.** Choosing a higher role in a row's `Select` (viewer to editor,
editor to owner) opens a `Dialog` instead of saving straight away:

```
Make Ibrahim Naseer an editor?
Can edit and publish the form and change submission status.
[x] Notify by email
    Message (optional)  [ ...                         ]  0/500
                                     [ Cancel ] [ Change role ]
```

- Cancel (or Escape) keeps the old role; the `Select` shows it again.
- Lowering a role, removing someone and changing your own role save at once and never email
  (removing your own owner role keeps its confirmation).
- Toast: "Changed the role of {name} and emailed them" or "Access updated".

**Email not set up** (`smtpEnabled: false`): the checkbox is disabled and unticked, with the
description "Email is not set up on this server."; no message box; role changes save at once
without the dialog.

**Errors.** Too many emails (429): toast "You've emailed a lot of people. Try again later, or
untick Notify by email." Nothing is saved in that case.

**The email** (worker, organisation branding, From = organisation name, Reply-To = the
sharer's address), English:

- Subject: "{sharer} shared “{form title}” with you"; for a raised role "{sharer} changed your
  access to “{form title}”". The title is isolated (FSI/PDI) when the form is Dhivehi.
- Body: muted "Shared with you" (or "Access changed"), the form title as the heading in the
  form's language and direction, then "{sharer} shared this form with you. You're now {an
  editor: you can edit the form and manage submissions | a submissions viewer: you can view
  and export submissions | an owner: you can edit the form, manage submissions and decide who
  has access}." The note, when given: muted "{sharer} wrote:" and the text (escaped, line
  breaks kept, `dir="auto"`, a hairline start border). Button "Open the form" (editors and
  owners, the builder) or "Open the submissions" (viewers). Muted footer: "You're getting this
  email because {sharer} changed who has access to this form. Replies go to them."
- Never sent to the sharer, to organisation admins (already owners), for removals or lower
  roles. The role is read when the email is sent: if access was removed meanwhile, nothing goes
  out.

Self-critique: the first idea was a single "Share" dialog with people chips (the Google Drive
pattern). Changed: the card already has an inline add row that works on phones; the checkbox
and note slot under it without a new surface. The note is hidden while unticked so the card
stays short. A dialog for raised roles was chosen over an inline checkbox in the row, which
would not fit at 320 px and would be easy to miss.

### 6.2 Suggesting people while typing

Both "Add someone by email" (Share) and "Email addresses" (Invite people) suggest existing
members of the organisation as you type a name or an address. People can still type any full
address.

```
Add someone by email
[ ibra                         ] [ Submissions viewer v ] [ Add ]
┌──────────────────────────────────────────┐
│ People in your organisation              │
│ (IN) Ibrahim Naseer                      │
│      ibrahim@example.org                 │
│      Already has access (Editor)         │  dimmed text, not selectable
│ (IH) Ibrahima Hassan                     │  highlighted: Enter picks
│      ibrahima@example.org                │
└──────────────────────────────────────────┘

[ new@example.org              ]
┌──────────────────────────────────────────┐
│ ✉ Invite new@example.org to Example Office│  org admins
└──────────────────────────────────────────┘
  or, for other owners, a note: "new@example.org isn't in Example Office yet. Ask an
  organisation admin to invite them."
```

- **Composition**: the official combobox pattern, `Popover` + `Command` (no new primitive).
  `CommandInput` is the field (anchored with `PopoverAnchor`; the popover is as wide as the
  field, at least 256 px); `CommandList` / `CommandGroup` "People in your organisation" /
  `CommandItem` rows with `Avatar size="sm"` initials, name (`bdi dir="auto"`) and email
  (`bdi dir="ltr"`). The server filters (`shouldFilter={false}`).
- **Search**: from 2 characters, debounced 200 ms, up to 8 people: name or email, case and
  common accents ignored; exact matches first, then names or emails starting with it, then a
  word of the name, then anywhere. Only the organisation's members.
  `GET /orgs/{id}/members/search?q=&limit=8` (org admins) or with `&form_id=` (that form's
  owners; each match carries `formRole`). Rate limited per user.
- **Share**: picking a member fills in their address and closes the list; Enter (or Add)
  then adds them with the chosen role, so a stray Enter never shares and emails at once.
  People who already have access are listed but not selectable: "Already has access
  (Editor)", "Already has access (Owner, organisation admin)". A typed full address that is
  not a member gives "Invite {email} to {organisation}" (org admins; it opens the existing
  "Invite and share" alert) or the note above; an address already invited to this form:
  "Already invited. They get {role} access when they accept."
- **Invite people**: matching members are listed as "Already a member" (not selectable); a
  typed full address gives "Invite {email}", which adds a chip; an address already in the
  chips: "Already in the list."
- **States**: "Searching…" with a `Spinner` before the first answer (earlier results stay
  while the next request runs); "No one in your organisation matches. Type their full email
  address."; on errors "Couldn't look up people. You can still type a full email address."
- **Keyboard and screen readers**: cmdk gives `role="combobox"` on the input, `listbox` /
  `option` rows and `aria-activedescendant`; `aria-expanded` follows the list. Up/Down move,
  Enter picks, Escape closes the list (inside the Invite dialog, only the list). With no row
  to choose, Enter is the field's own action (Add on Share, a new chip in Invite). The visible
  label names the input and focuses it when clicked. Focus and the phone keyboard stay in the
  input while choosing.
- **Phones**: rows reach 44 px on coarse pointers (global rule for `command-item`); the
  popover opens under the field and flips above when there is no room; names and emails
  truncate, the access note wraps.

Self-critique: the first idea was to share the moment a member is picked (one step). Changed:
on Share that also sends the "Notify by email" email, so picking only fills the field and Add
stays the commit. First idea for Invite was to keep the textarea with a list under it; a
combobox needs a single-line input, and chips show what will be sent better than a block of
text, while pasting a list still works.

## 7. Studio changes for members

- Forms page for a **member**: no "Create form" or "Import from Jotform" buttons. Empty state:
  title "No forms shared with you yet", description "When someone shares a form with you,
  it shows up here." No action.
- Row menu: "Duplicate" only for creators and admins.
- Jotform import page for a member: `Alert` "Only form creators and admins can import
  forms."

## 8. Accessibility and keyboard

- Every icon-only button (row actions) has an `aria-label` and matching tooltip.
- Dialogs return focus to the menu trigger; the first field is focused on open.
- Status badges carry icon + text; dates use `tabular-nums`.
- Search announces "{n} people" in a polite live region when it changes.
- Touch: rows and the actions button reach 44 px on coarse pointers.

## 9. Self-critique

- First idea: inline role `Select` in every table row (as on the Share page). Changed: an org
  role change is weightier than a form role (admin = everything), and inline selects in a
  table are easy to change by accident on a phone. A dialog with descriptions makes the
  consequence visible; the Share page keeps its quick select.
- First idea: invitations in a separate tab. Changed: one list with a status column; admins
  think "who is in", not "which table". Pending rows come first because they need action.
- First idea: one email input per row with "Add another". Changed: a textarea; people paste
  lists from email or a spreadsheet.
- First idea: let any form owner invite outsiders from Share. Changed: inviting adds a person
  to the organisation, so it stays an admin action; others get a clear message.
- First idea: a separate "/invite/{token}" page. Changed: `/login/invite/{token}` reuses the
  sign-in card, routing and CSP, and needs no new top-level path or reserved slug.
- Avoided tells: no uppercase eyebrows, no middle-dot meta strings, no shadowed card grid of
  people; status is a badge with an icon and a word.
