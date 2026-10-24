# Approvals, clean PDF and verify page

Screens for the approval workflow and the clean respondent PDF with its public verify page
(DESIGN §9.5, §15.1, §21 "Planned next"). Tokens, type and motion come from
[DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with [REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md).
Conventions are the same as in [PHASE-2-SCREENS.md](PHASE-2-SCREENS.md): copy in "quotes"
ships as written, and **all of it is English for every form**, including what a respondent
or approver reads (approver page, verify page, their emails, the PDF's fixed labels). Only
form content (the form title, step names, questions and answers) is in the form's language
and direction: the approver page and the emails are English and left to right with that
content in its own `lang`/`dir` block, and a Dhivehi PDF starts every line at the right with
English labels as left-to-right runs (DESIGN §16).

Nothing new needs adding from shadcn: `card`, `field`, `input`, `textarea`, `radio-group`,
`native-select`, `switch`, `button`, `tooltip`, `alert`, `alert-dialog`, `item`, `badge`,
`input-otp`, `empty`, `skeleton`, `spinner`, `table` and `separator` are installed.

## 1. Settings: Approvals card

New card on the Settings page between "Email notifications" and "Webhooks". Owners edit;
everyone else sees it disabled (same rule as the rest of Settings).

```
 ┌ Approvals ─────────────────────────────────────────────────────────┐
 │ Send each new response to people who approve or reject it, in order.│
 │ Ask for approval                                           [■]      │
 │ ┌ Step 1 ──────────────────────────────────────── [↑] [↓] [🗑] ┐    │
 │ │ Step name  [ Supervisor                          ]           │    │
 │ │ Approver   (•) The answer to an email question               │    │
 │ │                [ Supervisor's email ▾ ]   (form language)    │    │
 │ │            ( ) Always this address                           │    │
 │ │                [ director@example.org ]                      │    │
 │ │ ⚠ This question is optional. Responses without an answer     │    │
 │ │   wait until someone stops the approval. Make it required.   │    │
 │ └──────────────────────────────────────────────────────────────┘    │
 │ ┌ Step 2 … ┐                                                        │
 │ [+ Add step]                       (hidden at 3 steps)              │
 │ ─────────────────────────────────────────────────────────────────── │
 │ Email the respondent the outcome                           [■]      │
 │   Send to  [ The confirmed email ▾ ]                                │
 │   The email has the final signed PDF attached.                      │
 │                                     [Discard]  [Save approvals]     │
 └─────────────────────────────────────────────────────────────────────┘
```

- Card header: `CardTitle` "Approvals", `CardDescription` "Send each new response to people
  who approve or reject it, in order. Approvers confirm their email with a code; they don't
  need an account."
- "Ask for approval" `Field orientation="horizontal"` + `Switch`, description "New responses
  stay In review until the last step decides." Turning it on with no steps adds step 1.
- "Step name" has the description "Approvers and respondents see this name."
- Each step is a `FieldSet` on a hairline-bordered block (`rounded-md border p-4`, no
  shadow), `FieldLegend` "Step {n}". Actions at the end of the legend row: icon `Button
  size="icon-sm" variant="ghost"` "Move up", "Move down" (chevrons, `Tooltip` with the same
  text) and "Remove step" (trash).
  - `Field` "Step name" `Input` (max 60, placeholder "Supervisor"). It is form content: the
    approver and respondent read it, so the input takes the form's `lang`/`dir`.
  - `RadioGroup` "Approver": "The answer to an email question" with a `NativeSelect` of the
    form's top-level email questions (labels in the form's language, `<select>` with
    `contentProps`), and "Always this address" with an `Input type="email" dir="ltr"`.
    No email questions: the first option is disabled with description "Add an email
    question to the form to use this."
  - Warnings under the step (`Alert`, triangle icon, not destructive): the question is
    optional ("This question is optional. Responses without an answer wait until someone
    stops the approval. Make it required."), or only shown on some paths ("This question is
    only shown to some respondents. Responses that skip it wait until someone stops the
    approval."). Errors (`FieldError`): "Choose a question", "Enter an email address like
    name@example.org", "This question isn't in the form any more. Choose another."
- "Add step" (outline, plus icon) under the steps; hidden at 3.
- "Email the respondent the outcome" `Switch`, then "Send to" `NativeSelect` (as the
  receipt: "The confirmed email" for email-code and staff forms, then email questions) and
  the description "The email has the final signed PDF attached."
- Editing is local until "Save approvals" (primary) — several inputs change together, so
  per-field saving would store half-made steps. "Discard" (ghost) appears while there are
  unsaved changes. Toast "Approvals saved". Server errors map to the step field.
- Changes apply to new responses only; responses already in approval keep the steps they
  started with. Muted line under the save row while the form is live: "Changes apply to new
  responses. Responses already waiting keep their steps."

## 2. Publish dialog

- Blocking problems (the "Fix these before publishing" list): "Approval step {n} uses a
  question that isn't in the form" and "Approval step {n} uses a question that isn't an
  email question". Their action button is "Open settings" (goes to Settings).
- Warnings (not blocking) show in the publish confirmation, as an `Alert` above the
  buttons: "Approval step {n} uses an optional question" / "… a question only some
  respondents see". If there are warnings the confirmation opens even after the first
  publish.

## 3. Submissions

### 3.1 Table

The Status cell keeps the badge; a running approval adds muted `text-xs` after it:
"Step 1 of 2" (`tabular-nums`). On phones the same text joins the description line.

### 3.2 Detail sheet

Built: the Approval block sits at the top of the Answers tab (it scrolls with the answers, so
the sheet header stays short on phones), not in the header as first sketched.

```
 #0042  ◐ In review                                [Prev] [Next] [✕]
 Submitted …
 [✓ Integrity verified] [Download PDF]
 ┌ Approval ──────────────────────────────────────────────────────┐
 │ ✓ 1  Supervisor   Approved by Aminath Ali, a•@example.org      │
 │                   23 Oct 2026 10:14                            │
 │ ◷ 2  Director     Waiting for director@example.org since 10:14 │
 │                   [Send the email again]  [Stop approval]      │
 └────────────────────────────────────────────────────────────────┘
 Status: In review ▾  (disabled)  "The status changes when the approval finishes."
```

- `ItemGroup` of `Item size="sm"`, one per step, inside a bordered block with the heading
  "Approval" (`text-sm font-medium`). Icon per state, never colour alone: check (approved),
  x in stamp (rejected), clock (waiting), circle-dashed (not started), triangle (no
  approver), slash-circle (stopped).
- Titles: "{n}. {step name}" (step name in the form's language, `bdi`). Descriptions:
  "Approved by {name} ({email}), {time}", "Rejected by {name} ({email}), {time}" plus the
  comment on its own line, "Waiting for {email} since {time}", "Not started",
  "No approver: the answer to "{question}" is empty", "Stopped".
- Actions for editors and owners, on the current step only: "Send the email again"
  (outline, toast "Email sent again") and "Stop approval" (ghost, destructive text) which
  opens an `AlertDialog` "Stop this approval?" / "The approver's link stops working. You can
  then set the status yourself." with a required `Textarea` "Reason" and [Stop approval].
- While an approval runs, the status `Select` is disabled with the muted line "The status
  changes when the approval finishes." After it finishes (or is stopped) the status works as
  before; changing it records a status change but never edits the approval record.
- Activity tab gains: "Approval requested from {email} (step {n}, {name})", "{who} approved
  (step {n}, {name})", "{who} rejected (step {n}, {name})" + comment, "{who} stopped the
  approval" + reason, "Approval waiting: no approver for step {n}".

### 3.3 Staff audit details

The audit data the clean PDF no longer prints stays in the detail sheet: signature IP,
device and stroke hash (unchanged), plus an "Audit" disclosure at the end of the Answers tab
(`Collapsible`, trigger "Audit details") listing content hash, form version hash, activity
log head and the PDF's SHA-256 (mono, first and last 4 digits like the signature's stroke
hash, with a `Tooltip` for the full value).

## 4. Approver page (`/a/{token}`)

Public, no account, in the form's language and direction. Same sheet-on-desk frame as the
public form (sheet max 40rem, full-bleed on phones). Its own entry (`doc.html`), loaded
lazily from the verify entry so the public form bundle is untouched.

```
 Example Youth Office                               (muted, org name)
 Youth programme application                        (text-2xl, form title)
 ┌ step 1: confirm ───────────────────────────────────────────────┐
 │ Approval needed: Supervisor                     text-xl        │
 │ Response #0042, submitted 23 Oct 2026. Step 1 of 2.            │
 │ To open it, confirm it's you. We'll email a 6-digit code to    │
 │ s•••@example.org.                                              │
 │ [            Send code            ]                            │
 └────────────────────────────────────────────────────────────────┘
 ┌ step 2: code ── same as the respondent code step (InputOTP, dir=ltr) ┐
 ┌ step 3: review ────────────────────────────────────────────────┐
 │ Approval needed: Supervisor                                    │
 │ Response #0042 …                                               │
 │ ── answers ──                                                  │
 │ Full name            Aishath Ali                               │
 │ National ID          Hidden                                    │
 │ Copy of ID card      [file] id.pdf 183 KB  [Download]          │
 │ Signature            [signature image on white]                │
 │ ── Your decision ──                                            │
 │ Your name     [                         ]                      │
 │ Comment       [                         ]                      │
 │               Needed to reject. The respondent sees it.        │
 │ [ Approve ]  [ Reject ]                                        │
 └────────────────────────────────────────────────────────────────┘
```

- Step 1: heading "Approval needed: {step name}", line "Response {ref}, submitted {date}.
  Step {n} of {total}." (`bdi` around the reference, date and fraction), body "To open it,
  confirm it's you. We'll email a 6-digit code to {masked email}." `Button` "Send code"
  (full width on phones, 48px).
- Step 2: "Enter the code" / "We sent it to {masked email}. It works for 10 minutes."
  `InputOTP` (6 slots, `dir="ltr"`), "Continue"; "Send a new code" link button with a 60 s
  countdown. Errors as on the respondent code step.
- Step 3: answers as a `dl` (label, value), pages as small headings, repeaters as a `Table`.
  Sensitive answers show "Hidden" (muted, lock icon): approvers never see them, and the
  page says so once under the answers: "Answers marked hidden are sensitive and only staff
  can see them." Files: `Item variant="outline"` with name, size and a Download button
  (fetched with the approver token). Signatures: the server image on a white `Card`.
- Decision: `Field` "Your name" (`Input`, required, autocomplete name), `Field` "Comment"
  (`Textarea`, max 2000) with description "Needed to reject. The respondent sees it."
  Buttons: "Approve" (primary) and "Reject" (outline, stamp text). Each opens an
  `AlertDialog`: "Approve this response?" / "{next}" where next is "It goes to the next
  approver." or "This is the last step: the respondent is told it's approved." — and
  "Reject this response?" / "This ends the approval. The respondent is told it was rejected,
  with your comment." Errors: "Enter your name", "Write why you're rejecting it".
- Done: `StatusScreen` "Approved" / "Rejected" with "Thank you. You can close this page."
- Link states (`StatusScreen`): already decided "This approval is done" / "{outcome} on
  {date}. You can close this page."; stopped "This approval was stopped" / "Someone at the
  organisation stopped it, so there's nothing to do."; not found or expired "This link
  doesn't work" / "Ask the person who sent it for a new one." ; rate limited "Too many
  tries. Wait a few minutes and try again."
- Focus moves to each step heading; "Code sent" is announced.

## 5. Verify page (`/v/{token}`)

Status only. Never shows answers, names or emails. Tiny: plain elements and two shadcn
components (`Button`, `Alert`), no router, no query cache, no renderer.

```
 ┌───────────────────────────────────────────────────────────┐
 │ (✓)  Genuine document                        text-2xl     │
 │ Issued by Example Youth Office                            │
 │ Reference    #0042                                        │
 │ Issued       23 Oct 2026                                  │
 │ Approval     Approved on 24 Oct 2026                      │
 │ ───────────────────────────────────────────────────────── │
 │ This page confirms the document came from this system and │
 │ that its record hasn't changed since it was signed. It    │
 │ never shows the answers.                                  │
 │ Check your copy  [Choose PDF]                             │
 │ (✓) This file is genuine and unchanged.                   │
 └───────────────────────────────────────────────────────────┘
```

- States (icon + heading, never colour alone): "Genuine document" (check, carbon);
  "This document was changed" (x, stamp): "The record behind this document no longer matches
  what was signed. Don't rely on it; contact the organisation that issued it."; "Document
  not found" (circle-question, muted): "This link doesn't match any document. Check that
  you scanned the code on the document itself."
- Rows (`dl`): "Reference", "Issued" (date of the latest signed PDF), "Approval" only when
  the form uses approvals: "Approved on {date}", "Rejected on {date}", "In progress
  (step {n} of {total})", "Stopped".
- "Check your copy": a file button; the result is an `Alert`: "This file is genuine and
  unchanged." / "This file was changed after it was signed." (destructive) / "This file is a
  different document." (destructive) / "This isn't a signed PDF from this system."
  (destructive). An older signed copy that is otherwise genuine says "This file is genuine.
  A newer signed copy was issued on {date}."
- English and left to right for every form (system text only; an organisation name in Thaana
  gets the Thaana face). `<meta name="robots" content="noindex">`,
  `Referrer-Policy: no-referrer`.

## 6. The clean respondent PDF

```
 ┌──────────────────────────────────────────────┐
 │ Youth programme application        (17pt)    │
 │ Reference #0042   Submitted 23 Oct 2026 09:03│
 │ ──────────────────────────────────────────── │
 │ Page title                                   │
 │ Label                                        │
 │ Answer                                       │
 │ …                                            │
 │ Signature (statement, image, baseline)       │
 │ ──────────────────────────────────────────── │
 │ Approval                                     │
 │ 1. Supervisor  Approved  Aminath Ali         │
 │                a@example.org, 23 Oct 2026    │
 │ 2. Director    Approved  …                   │
 │                                              │
 │ [QR]  Digitally signed. Verify at           │
 │       forms.example.org/v/Xk3…               │
 │       #0042, page 1 of 2                     │
 └──────────────────────────────────────────────┘
```

- Only: form title, answers (signature images with the statement shown to the signer),
  reference number, submitted date, the approval record when there is one, and the footer.
  No organisation header, version, IP address, device, stroke hash, file hashes or audit
  page. Those stay in the studio and in the PDF's signed metadata.
- Footer on every page: a 14 mm QR code to the verify URL at the start edge, then "Digitally
  signed. Verify at {url}" and "{ref}, page {n} of {total}", English for every form. In dv the
  page is right-aligned and each English line is drawn as one LTR run against the right edge,
  so bidi can't reorder it (this fixes "# …0001" coming out scrambled).
- The approval record lists every decided step: number, step name, outcome, approver name
  and email, date. Stopped approvals print "Stopped" without names. Comments are not
  printed (they are in the outcome email and the studio).

## 7. Emails

- **Approval request** (to the approver, English; title and step name in the form's language): subject "Approval needed: {title}
  ({ref})"; body: "{step name}: please approve or reject response {ref} to {title}. It was
  submitted on {date}." button "Open the response" (the `/a/{token}` link), then "You'll
  confirm your email with a code first. The link works for {days} days." No answers in the
  email.
- **Outcome** (to the respondent, English; title in the form's language): subject "Approved: {title} ({ref})" /
  "Not approved: {title} ({ref})"; body "Your response {ref} was approved." / "Your response
  {ref} was not approved." plus "Comment: {comment}" for a rejection, and "The signed PDF is
  attached." when it is.

## 8. Copy glossary additions

| Term | Use | Not |
|---|---|---|
| Approval | the whole workflow on a response | review chain, workflow |
| Step | one approver in order | stage, level |
| Approver | the person deciding a step | reviewer, signatory |
| Ask for approval | turn approvals on | enable workflow |
| Stop approval | end a running approval | cancel, abort |
| Send the email again | resend the approver link | resend notification |
| Genuine document | the verify page's good state | valid, authentic |

## 9. Self-critique

| First idea | Problem | Now |
|---|---|---|
| Approval steps inside the builder's form settings, versioned with the schema | The public form receives the schema, so fixed approver addresses would leak to every respondent; and editing an approver would need a publish | Steps live on the Settings page (not public), are checked against the draft at publish, and are copied onto each response when it arrives |
| Approver page as part of the public form bundle | The bundle is at 119.3 of 120 KB | A separate `doc.html` entry; the approver chunk loads lazily so the verify page stays tiny |
| Showing approvers every answer including sensitive ones | Approvers are outside the studio's role model; sensitive answers never leave the app in emails or webhooks either | Sensitive answers are "Hidden" for approvers |
| One "Decide" dropdown | Two different consequences behind one control | Two buttons, each with its own confirmation that says what happens next |
| Status set by hand while an approval runs | Two sources of truth for Approved | Status is locked while running; "Stop approval" hands control back |
| Footer text "Verified ✓" with a green tick on the PDF | A printed tick proves nothing; anyone can print one | The footer says it is digitally signed and where to check |
| Verify page listing the form title | Can reveal what someone applied for | Issuer, reference, dates and approval outcome only |
