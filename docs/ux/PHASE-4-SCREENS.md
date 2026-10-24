# Phase 4 screens

Additions for Phase 4 (DESIGN §20): a per-form **Settings** page (who can respond, spam
protection, email notifications, webhooks, data retention), the respondent **email code**
step on the public form, the CAPTCHA step, and the respondent email in submissions. Tokens,
type and motion come from [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with
[REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md). Conventions are the same as in
[PHASE-2-SCREENS.md](PHASE-2-SCREENS.md): **[add]** marks a shadcn component to add with the
CLI, copy in "quotes" ships as written, studio copy is English only, and form content takes
`lang`/`dir` from the form's language.

Nothing new needs adding from shadcn: `card`, `radio-group`, `switch`, `field`, `input`,
`native-select`, `checkbox`, `dialog`, `alert-dialog`, `sheet`, `table`, `badge`, `item`,
`input-group`, `input-otp`, `tooltip`, `empty`, `skeleton`, `spinner` and `sonner` are
installed.

## 1. Settings page

New tab in the form bar after Submissions: **Settings** (`/forms/$formId/settings`). A
narrow `PageContainer` like Share, with one `Card` per topic (sheet background, hairline
edge, no shadow), in this order. Everyone with access can open it; only owners can change
anything (DESIGN §7). For editors and viewers every control is disabled and the page starts
with a muted line: "Only owners can change these settings."

```
 Settings
 ┌ Who can fill in this form ─────────────────────────────────────┐
 │ (•) Anyone with the link                                        │
 │ ( ) People who confirm their email                              │
 │     They get a 6-digit code by email before they see the form.  │
 │     Allowed email domains  [example.org, example.com      ]     │
 │     Leave empty to allow any address.                           │
 │     [■] One response per email                                  │
 │ ( ) Signed-in staff only                                        │
 └─────────────────────────────────────────────────────────────────┘
 ┌ Spam protection ───────────────────────────────────────────────┐
 │ (•) Off  ( ) Always  ( ) When busy                              │
 │ "When busy" turns the check on after 1000 responses in an hour. │
 └─────────────────────────────────────────────────────────────────┘
 ┌ Email notifications ───────────────────────────────────────────┐
 │ Email me about new responses                         [■]        │
 │   Send to [owner@example.org, team@example.org  ]               │
 │   Leave empty to email the form's owners.                       │
 │   Include answers                                    [ ]        │
 │ Send respondents a receipt                           [■]        │
 │   Send to  [The confirmed email ▾]                              │
 │   Attach the signed PDF                              [■]        │
 │ Recent emails                                                   │
 │   ✓ Receipt to a•••@example.org        Today 10:14              │
 │   ✕ New response to owner@…  Couldn't send: connection refused  │
 └─────────────────────────────────────────────────────────────────┘
 ┌ Webhooks ──────────────────────────────────────────────────────┐
 │ Send each new response to another system as it arrives.         │
 │ ┌───────────────────────────────────────────────────────────┐   │
 │ │ https://hooks.example.org/forms   ● On  2 events  [Open]  │   │
 │ └───────────────────────────────────────────────────────────┘   │
 │ [+ Add webhook]                                                 │
 └─────────────────────────────────────────────────────────────────┘
 ┌ Data retention ────────────────────────────────────────────────┐
 │ Erase submissions automatically                      [■]        │
 │   After [ 365 ] days                                 [Save]     │
 │   Submissions, their files, signatures and PDFs are erased      │
 │   for good this many days after they arrive.                    │
 └─────────────────────────────────────────────────────────────────┘
```

Phone: the same cards stacked full width; switches stay at the end of their row; the
webhook row wraps (URL on its own line, truncated with the full URL in `title`).

### 1.1 Who can fill in this form

- `RadioGroup` of three `Field orientation="horizontal"` rows (radio, `FieldLabel`,
  `FieldDescription`):
  - "Anyone with the link" / "No sign-in. Use spam protection if you expect abuse."
  - "People who confirm their email" / "They get a 6-digit code by email before they see the
    form. Their address is saved with the response."
  - "Signed-in staff only" / "Only people who can sign in to JustForms can respond."
- Under the email option, only while it is selected, indented to the label:
  - `Field` "Allowed email domains", `Input` (`dir="ltr"`, placeholder
    "example.org, example.com"), `FieldDescription` "Leave empty to allow any address."
    Saved on blur; invalid entries give `FieldError` "Enter domains like example.org,
    separated by commas".
  - `Field orientation="horizontal"` "One response per email" `Switch`, description "A
    second response from the same address is refused."
- Each change saves at once; toast "Saved". Changing access while the form is live adds a
  muted note under the card title: "People who already opened the form need to reload it."

### 1.2 Spam protection

- Shown only when the install has a CAPTCHA provider (`GET /meta` →
  `captcha.provider`). Otherwise the card says "Spam protection isn't set up on this
  install. An administrator can turn it on with `JUSTFORMS_CAPTCHA_PROVIDER`." (setting name in
  mono) and nothing else.
- `RadioGroup` horizontal: "Off", "Always", "When busy"; description below names the
  provider in plain words: "Uses Cloudflare Turnstile." / "Uses hCaptcha." / "Uses a
  proof-of-work check that runs in the browser. No third party is involved."
- "When busy" description: "Turns the check on after {n} responses in an hour."

### 1.3 Email notifications

- Two `Field orientation="horizontal"` rows with a `Switch` at the end; their sub-settings
  are indented below and only shown while the switch is on.
- Owner notification:
  - "Send to" `Input` (emails, comma separated, `dir="ltr"`), description "Leave empty to
    email the form's owners." Error: "Enter email addresses like name@example.org,
    separated by commas".
  - "Include answers" `Switch`, description "Sensitive answers are never emailed."
- Respondent receipt:
  - "Send to" `NativeSelect`: "The confirmed email" (only when access is "People who
    confirm their email"), then one option per email question, label in the form's language
    (`<option>` text in `bdi`, the select gets the form's `lang`). If neither exists the
    switch is disabled with description "Add an email question, or ask people to confirm
    their email, to send receipts."
  - "Attach the signed PDF" `Switch`, description "Only for forms with a signature. The
    receipt waits until the PDF is ready."
- "Recent emails" (owners only): `ItemGroup` of up to 10 `Item size="sm"`: icon (check for
  sent, x in stamp for failed, spinner for queued), `ItemTitle` "Receipt to {masked email}"
  / "New response to {email}", `ItemDescription` the error for failures ("Couldn't send:
  {reason}. JustForms tried 5 times."), time at the end. Empty: "No emails sent yet."
- Receipts mask the respondent address in this list (`a•••@example.org`).
- Without SMTP on the install, an `Alert` at the top of the card: "Email isn't set up on
  this install, so nothing will be sent. An administrator can set the `JUSTFORMS_SMTP_*`
  settings."

### 1.4 Webhooks

List: `ItemGroup` of `Item variant="outline" size="sm"` rows: URL in mono, truncated, in
`<bdi dir="ltr">`; `Badge variant="outline"` with icon + "On" / "Off" / "Turned off after
failures" (stamp, x icon); muted "{n} events"; `Button variant="outline" size="sm"` "Open".
Empty: `Empty` "No webhooks yet" / "Add one to send new responses to another system."
Button "Add webhook" (outline, plus icon) under the list.

Add webhook `Dialog` "Add a webhook":
- `Field` "URL" (`Input type="url"`, `dir="ltr"`, placeholder
  "https://hooks.example.org/justforms"); description "Must start with https://. Addresses
  on private networks need the install's allowlist."
- `FieldSet` "Events" with a `Checkbox` per event: "New response"
  (`submission.created`, checked), "Status changed", "Comment added", "Signed PDF ready".
  Event ids under each label in muted mono.
- "Include sensitive answers" `Switch`, description "Off: sensitive answers arrive as
  [redacted]."
- [Cancel] [Add webhook]. URL errors from the server: "Use an https:// address." /
  "This address points to a private network. Ask an administrator to allow it." /
  "Enter a full address like https://hooks.example.org/justforms".
- On success the dialog switches to the signing secret step: "Copy the signing secret"
  / "You won't see it again. Your system uses it to check that requests come from JustForms."
  `InputGroup` with the `whsec_…` value (mono, read-only) and a Copy `InputGroupButton`
  ("Copied" for 2 s). [Done].

Webhook `Sheet` (end edge, `sm:max-w-xl`), opened by "Open":

```
┌ Webhook ─────────────────────────────────────────────── [✕] ┐
│ https://hooks.example.org/justforms                           │
│ [● On  ⏻]  New response, Signed PDF ready                   │
│ [Send test event] [Rotate secret] [Edit] [Delete]           │
│─────────────────────────────────────────────────────────────│
│ Deliveries                                                  │
│ Event            Result         Time          Duration      │
│ New response     ✓ 200          10:14:02      182 ms   [⋯]  │
│ New response     ✕ 503 retry 3  10:09:40      10.0 s   [⋯]  │
│ Test event       ✓ 204          10:01:11       91 ms   [⋯]  │
└─────────────────────────────────────────────────────────────┘
```

- Header: URL (mono, wraps), an "Enabled" `Switch` with label, event names.
- Actions: `Button size="sm" variant="outline"` "Send test event" (toast "Test event
  sent"), "Rotate secret" (`AlertDialog` "Rotate the signing secret?" / "Requests are
  signed with both the old and the new secret for 24 hours, so you can update your system
  without missing any." [Rotate secret]; then the copy-secret step), "Edit" (the add dialog,
  prefilled, without the secret step), "Delete" (destructive, `AlertDialog` "Delete this
  webhook?" / "JustForms stops sending to it at once. Its delivery log is deleted too.").
- Deliveries: `Table` newest first, 30 days, paged by "Load more". Columns: Event (plain
  words), Result (`Badge` with icon: check + status code; x + code or "No response" in
  stamp when failed; clock + "Retry {n} at {time}" while pending), Time (`tabular-nums`),
  Duration. Row action `DropdownMenu` (icon button "Delivery actions"): "Show details",
  "Redeliver". Details expand under the row (`Collapsible`): request body (mono `pre`,
  max 16 rem, scrolls), response code and the first 1 KB of the response.
- Empty deliveries: "No deliveries yet. Send a test event to check your endpoint."
- Auto-disabled webhook: `Alert variant="destructive"` at the top: "Turned off after 20
  failed deliveries in a row. Fix your endpoint, then turn the webhook back on."

### 1.5 Data retention

- `Field orientation="horizontal"` "Erase submissions automatically" `Switch`.
- While on: `Field` "After" `InputGroup` (`Input type="number"` min 1 max 36500 + addon
  "days"), [Save] (outline). Description: "Submissions, their files, signatures and PDFs are
  erased for good this many days after they arrive. The nightly clean-up does this."
- Lowering the period (or turning it on) opens `AlertDialog` "Erase older submissions?" /
  "Submissions older than {n} days will be erased tonight, with their files, signatures and
  PDFs. This can't be undone." [Erase after {n} days] (destructive). Toast "Retention set to {n} days" /
  "Submissions are kept until deleted".
- Error: "Enter a number of days from 1 to 36500".

## 2. Public form: email code step

For forms with access "People who confirm their email". Shown on the sheet in place of the
questions, below the form title (and org name). The form title is content (form's language
and direction); the step itself is system text, so English and left to right for every form
(`public/access-lib.ts`).

```
 ┌───────────────────────────────────────────┐
 │ Example Youth Office                      │
 │ Youth programme application               │
 │                                           │
 │ Confirm your email to continue            │  text-xl
 │ We'll send a 6-digit code to your inbox.  │
 │ Email                                     │
 │ [ name@example.org                     ]  │  48px, dir=ltr
 │ [        Send code        ]               │  primary, full width on phones
 └───────────────────────────────────────────┘
 ┌───────────────────────────────────────────┐
 │ Enter the code                            │
 │ We sent it to a••••@example.org. It works │
 │ for 10 minutes.                           │
 │ [ 1 ][ 2 ][ 3 ][ 4 ][ 5 ][ 6 ]            │  InputOTP, dir=ltr
 │ [        Continue         ]               │
 │ Send a new code (in 0:45)   Use a different email │
 └───────────────────────────────────────────┘
```

- Step 1: `Field` + `FieldLabel` "Email", `Input type="email" autocomplete="email"
  inputMode="email" dir="ltr"`, `Button` "Send code". Validation: "Enter an email address
  like name@example.com". Domain not allowed: "Use an email address from {domains}."
- Step 2: `InputOTP` (6 slots, `dir="ltr"` even in dv forms, `inputMode="numeric"`,
  `autocomplete="one-time-code"`), auto-submits on the 6th digit; `Button` "Continue".
  Wrong code: `FieldError` "That code isn't right. Check the email and try again." Too many
  tries / expired: "This code has expired. Send a new code." "Send a new code" is a link
  button, disabled for 60 s with the countdown in `bdi`. "Use a different email" returns to
  step 1.
- Rate limited: "Too many tries. Wait a few minutes and try again."
- Already responded (one response per email): `StatusScreen` "You've already responded" /
  "This form accepts one response per email address."
- After verifying, the form loads as normal; the confirmed address shows at the top of the
  first page as muted text "Responding as {email}" (email in `bdi dir="ltr"`). The token
  lives in memory only: reloading the page asks for a code again.
- Focus moves to the step heading on each step change; the code step announces "Code sent".
- The step loads lazily (its own chunk) so public-link forms don't pay for it.

### Staff-only forms

Opening one without a staff session sends the browser to the studio sign-in page with
`next` set to the form, then back. With a session, the form renders as normal and
"Responding as {email}" shows at the top.

## 3. Public form: CAPTCHA

- Turnstile / hCaptcha: the provider's widget renders above the submit button on the last
  page, in a `Field` with `FieldLabel` "Check that you're a person" (English for every form, `access-lib.ts`). Submitting
  without solving shows the error summary item "Complete the check above the submit button".
  The widget script loads only when the form needs it.
- Proof-of-work (`altcha`): no widget. Solving starts when the form opens; on submit, if it
  isn't done yet, the submit button shows `Spinner` + "Checking your browser…" and submits
  when done. Failure falls back to a `FieldError` "Couldn't finish the check. Try again."
  with a Retry link.
- A submit refused for a missing or failed check (`captcha_required` / `captcha_failed`)
  keeps answers and shows the same error.

## 4. Submissions: respondent email

- Column picker gains "Respondent email" (shown by default for email-code and staff forms).
  Table cell in `bdi dir="ltr"`, truncated.
- Detail sheet header line: "Submitted 23 Oct 2026 09:03, version 4, Dhivehi" gains
  ", by {email}" with a check icon and tooltip "Email confirmed with a code" (OTP) or
  "Signed in" (staff).
- Search matches the respondent email. Excel export has the fixed column "Respondent email".

## 5. Review fixes carried in

- People with access, add row: the role `Select` no longer turns stamp red when the email
  has an error. Only the email `Input` is marked invalid (the `Field` with `data-invalid`
  wraps the input and its error, not the select). (P3 from the Phase 3 build.)
- Submissions status tabs on phones (P3-7): the tab list scrolls inside a `ScrollArea`
  with start padding so the first tab is never cut, and it scrolls the selected tab into view.

## 6. Self-critique

| First idea | Problem | Now |
|---|---|---|
| Put notifications and webhooks on the Share page | Share is about getting the form to people; it was already long | A separate Settings tab, one card per topic |
| Webhook log as its own page | One more route for a rarely used tool | A sheet over Settings, like submission detail |
| Show the webhook secret in the list with a reveal button | Secrets would be readable later from the DB | Shown once; rotate to get a new one |
| CAPTCHA mode as a `Select` | Three short options read better side by side | Horizontal `RadioGroup` |
| Code step as a modal over the form | Hides the title, awkward on phones, focus traps | It replaces the questions on the sheet |
| "Verify" as the code button | System word | "Continue" |
| Coloured status dots for deliveries | Colour alone | Icon + status code in a badge |
