# UI/UX review (ui-ux-pro-max lens), 24 Oct 2026

Reviewer: an independent read-only review of the studio and public pages on a demo instance
(sample organisation "Example Youth Office", teal form theme, IBM Plex Sans and Faruma), against
[REVIEW-CHECKLIST.md](../REVIEW-CHECKLIST.md), [DESIGN-SYSTEM.md](../DESIGN-SYSTEM.md) and the
ui-ux-pro-max skill. Playwright Chromium at desktop 1440x900, tablet 768x1024, Pixel 7 and
iPhone 14, light and dark, plus 320 px for the public form, with automated WCAG contrast, target
size and accessible-name checks for each capture. Screenshots live outside the repository; the
evidence names below are capture file names (`<screen>-<state>-<viewport>-<scheme>.png`).

Counts: P1 2, P2 18, P3 17.

## Status

All P1 and P2 findings are fixed; the deferred parts say why. The public form's initial
JavaScript went from 119.9 KB to 117.5 KB gzip (budget 120 KB): the outcome screens, rating,
multiple choice, phone, repeaters and the Thaana input became lazy chunks, prefetched for the
form being filled.

| ID | Finding | Status | What changed |
|---|---|---|---|
| P1-1 | Sticky Next/Submit bar covers the focused field on phones | Fixed | Bar height measured into `--df-bar-h` feeding `scroll-padding-bottom`; a field focused under the bar is scrolled to the centre (`form-view.tsx`, `index.css`). |
| P1-2 | Inactive tab labels 4.2:1 | Fixed | Unhovered inactive `tabs-trigger` uses `--muted-foreground` (5.45:1 on the desk) from `index.css`; dark mode already did. |
| P2-1 | Inputs narrow in the error state | Fixed | The error marker is a `before:` pseudo-element in the gutter; no padding or margin change, no layout shift. |
| P2-2 | Half-width pairs misalign | Fixed | Half-width questions fill their grid cell and push the control to the bottom (`mt-auto`), in the renderer and on the canvas. |
| P2-3 | Generic validation copy, "?:" join | Fixed | Per-type messages in `renderer/validation.ts` ("Enter an email address like name@example.com", "Enter a phone number with 7 digits, like 7771234", "Upload a file", "Sign in the box", "Choose an option"). The API sends codes only, so `answers.py` and the shared cases keep their codes. The summary drops the colon after a label ending in punctuation. |
| P2-4 | Premature errors | Fixed | Builder: the inspector error shows after the label input was left once or Publish was tried; the Fix badge stays. Renderer: choice groups validate when focus leaves the group. |
| P2-5 | Upload failure is a dead end | Fixed | Refusal codes map to plain reasons (type, size, empty, rate limit, connection); refused files offer no Retry; failed files do not count toward the limit; Choose files stays neutral. |
| P2-6 | Signature error styling, small controls | Fixed | Only the label and message turn red; the statement keeps the ink colour; Undo stroke and Clear are 44px. |
| P2-7 | Primary hover 3.74:1 | Fixed | Hover inside a form root mixes the primary towards black (towards white in dark mode) instead of 80% opacity, so it is never less legible than at rest (4.5:1 or more for the label). |
| P2-8 | Latin rendered in Faruma's Latin glyphs | Fixed | Named Latin fallbacks (Roboto, Segoe UI, Helvetica Neue, Arial) sit before the Thaana faces in every Latin-first stack. A preload of the theme font was not added: its file names live inside the theme stylesheet. |
| P2-9 | Builder on phones: no entry to question settings | Fixed | A selected block shows a Settings button that opens the inspector Drawer. |
| P2-10 | Builder on phones: page strip clips | Fixed | A horizontal ScrollBar shows when chips overflow, with an end fade until scrolled; the stray dot was a clipped chip menu button. |
| P2-11 | Publish problems rows identical | Fixed | Rows read "Page 1, question 2 (Email)"; the list sits in a ScrollArea with a count. |
| P2-12 | Form Settings is one long page | Fixed | One section at a time (sticky section list on desktop, NativeSelect on phones, kept in the URL hash); the Appearance preview sits in a sticky column beside the controls from `xl`; each card states how it saves. |
| P2-13 | Bulk Delete looks like Export | Fixed (partly) | Delete is outside the group, destructive, with the AlertDialog; the header checkbox shows a dash when some rows are selected. Deferred: an Undo toast, because deleting submissions has no undo API. |
| P2-14 | Sign-in errors | Fixed | `noValidate` and an inline FieldError; wrong code: FieldError under the code input, slots cleared, "Send a new code" with a 60 s cool-down. |
| P2-15 | Thaana labels small and pale outside the renderer | Fixed | Approver page labels in ink at the Thaana scale; PDF labels darker and 1.15x in dv; email dv cells 16/18 px with the Thaana stack. |
| P2-16 | Signed PDF layout | Fixed | Signature label, statement and image are kept together; the footer reads "Digitally signed. Verify at"; the effective logo was already drawn (checked on a fresh PDF). |
| P2-17 | Jotform import preview and type ids | Fixed | The preview uses the org form theme; the report is in plain words; raw ids are in a "Technical details" Collapsible. |
| P2-18 | Canvas preview controls unnamed | Fixed | The control pictures were already `inert`; the canvas now passes explicit `inert aria-hidden` controls for every type not edited in place. |
| P3-1 | Rating has no end labels | Deferred | Needs new schema fields (low and high labels) plus importer, PDF and inline-edit support; not a cheap change. |
| P3-2 | Outcome screens lose branding | Fixed (partly) | Success and in-form closed screens keep the form logo and title. Deferred: branding on closed and not-found pages opened directly, because the API returns no organisation for a closed or unknown form. |
| P3-3 | Drag overlay shows the key | Fixed | Shows the label, or "Untitled question (Email)". |
| P3-4 | Tooltip reopens after a menu closes | Fixed | `use-menu-tooltip` keeps it closed when focus returns. |
| P3-5 | Create form dialog dead space, silent disabled button | Fixed | "Enter a title to create the form." hint, linked to the button. |
| P3-6 | Heading order | Fixed | Palette groups are labelled groups, not h3s; sign-in has an h1; the settings preview was already `inert aria-hidden`. |
| P3-7 | Inconsistent back navigation on import pages | Fixed | Breadcrumbs. |
| P3-8 | Share link shown twice | Fixed | The address line repeats the URL only while it is being edited. |
| P3-9 | Logic-hidden questions show "No answer" | Fixed | Detail: "Skipped (not shown to the respondent)", unreached pages left out; the approver page leaves out empty sections. |
| P3-10 | Submissions open on an empty tab | Fixed | First non-empty tab, else All. |
| P3-11 | Stray scrollbar thumb on status tabs | Fixed | The rows scroll sideways only. |
| P3-12 | Faint ToggleGroup selected state | Fixed | Selected toggles are also semibold, on top of the carbon edge and tint. |
| P3-13 | Upload dropzone centred | Fixed | Start-aligned. |
| P3-14 | Disabled Publish gives no reason | Fixed | Tooltip "No changes since version N". |
| P3-15 | No typed-name signature alternative | Deferred | Needs a new answer shape, validation twins, PDF rendering and integrity rules; signatures are likely exempt under 2.5.7. |
| P3-16 | Demo data typos | Fixed (data) | Demo data, not code: the organisation's account and display names were corrected in the demo database. Organisation settings now shows the branding display name under its heading (the account name only as a fallback). |
| P3-17 | Raw phone numbers | Fixed | +960 numbers display as "+960 777 1234" in the studio, approver page, PDF and emails; stored values and exports are unchanged. |

## Scorecard

| Screen | Verdict | Main reasons |
|---|---|---|
| Sign-in (email, code, errors) | Minor issues | Native browser bubble instead of a FieldError; the wrong-code alert is neutral, has no icon, sits apart from the code input and offers no resend (P2-14). No heading (P3-6) |
| Forms list | OK | Clear table, status = icon + word. The 0-count links are 9 px wide (P3) |
| Create form dialog | Minor issues | Dead space under Title; Create is disabled with no hint (P3-5) |
| Builder, desktop | Minor issues | Fine overall: marker wash + edge, Fix badges, save state. Issues: the inspector flags new questions as errors at once (P2-4), canvas controls are exposed to screen readers unnamed (P2-18), a tooltip lingers over the header (P3-4) |
| Builder, tablet 768 | OK | Two-pane layout works; the inspector is reachable |
| Builder, phones | Needs work | The question settings drawer has no visible entry point (P2-9); the page strip clips (P2-10) |
| Logic editor / logic overview | OK | Plain sentences ("Show this question: Always"); the logic trace in preview is clear |
| Insert command (`/`), drag | Minor issues | The drag overlay shows the key "email", not the label (P3-3) |
| Publish problems dialog | Minor issues | Five identical rows (P2-11) |
| Preview (phone/desktop, logic trace) | OK | |
| Share and access | OK | Clear; the URL is shown twice (P3-8) |
| Form settings (all sections incl. Appearance) | Needs work | 6,600 px single page, preview below the controls, mixed save models (P2-12) |
| Organisation settings (branding, form theme) | Minor issues | Good: preview side by side, "Adjusted for contrast" note. The toggle-group selected state is faint (P3-12); inactive tab contrast (P1-2) |
| Account menu / appearance | OK | |
| Submissions table, tabs, filters, columns | Minor issues | Tab contrast (P1-2); lands on an empty "New" tab (P3-10) |
| Bulk selection | Minor issues | Delete is not styled as destructive and is grouped with Export; select-all shows checked, not indeterminate (P2-13) |
| Export / Check a PDF dialogs | OK | The sensitive-data warning in Export is good |
| Submission detail (approvals, activity, audit details) | OK | Clear approval steps, audit details are progressive. Logic-hidden questions show "No answer" (P3-9) |
| Jotform import (link/source/file/API, check result) | Minor issues | Preview ignores the org theme; internal type ids shown (P2-17) |
| Submissions import (upload, match) | OK | Clear 3-step flow, nothing written before confirm |
| Public form EN, desktop/tablet | Minor issues | Paired fields misalign (P2-2), the error state shrinks inputs (P2-1), weak error copy (P2-3) |
| Public form EN, phones | Needs work | The sticky bar hides the focused field (P1-1) |
| Public form DV (RTL) | Minor issues | Direction, progress, chevrons, bdi digits and "(optional)" are all correct. Same layout issues as EN; errors read "Answer this question: ..." |
| Error summary and inline errors | Needs work | Inputs change width, red is applied inconsistently, premature errors (P2-1, P2-3, P2-4, P2-6) |
| Upload and signature | Needs work | Failed upload gives no reason and uses a slot; signature error styling; 24 px Undo/Clear (P2-5, P2-6) |
| Success | OK | Good stamp-style reference block; loses form context (P3-2) |
| Closed / not found | Minor issues | No branding or next step (P3-2); font fallback seen once (P2-8) |
| Approver page (EN, DV, code, reject) | Minor issues | Thaana labels small and pale (P2-15); empty section headings (P3-9) |
| Verify page | OK | Clear and calm, the right amount of information |
| Emails (receipt EN/DV, approval request) | Minor issues | Thaana labels tiny in DV (P2-15) |
| Signed PDF (EN, DV) | Minor issues | Signature split from its statement; no logo; Thaana labels small; middle dot (P2-15, P2-16) |

**Counts:** P1 2, P2 18, P3 17.

### What is working well

The studio is clean, uses official shadcn components and has no template tells (no gradients,
emoji or eyebrow labels). Status badges are icon + word. Checking the scheme of every studio screen
found English-only, LTR chrome even while editing a DV form. RTL in the renderer is correct:
mirrored layout, progress filling from the right, "Step 1 of 2" isolated, the ތ / A toggle in the
right order, Back and Next swapping sides with flipped chevrons. The error summary is focused and
linked, `aria-invalid` and `aria-describedby` are wired, and inputs have the right
`autocomplete`/`inputmode`. The empty states (no submissions, empty page) each invite one action.

## Findings

Format: **ID. Screen, viewport.** Problem. *Evidence:* screenshot. *Fix:* how, naming the official
shadcn component or theme-level approach (no edits to `components/ui/`).

### P1 (accessibility failures)

**P1-1. Public form on phones: the sticky Next/Submit bar covers the focused field.** When a field near
the bottom of the viewport gets focus (by Tab, or by tapping the field above), the browser scrolls it
only to the viewport edge, and the fixed action bar then hides it completely. This fails WCAG 2.2
2.4.11 Focus Not Obscured (AA); the skill rates it High ("offset sticky UI with scroll-padding").
*Evidence:* `pub-en-16-phone-viewport-focus-email-light.png` (the Email input is under the Next bar).
*Fix:* in the public renderer's CSS add
`html { scroll-padding-bottom: calc(var(--df-bar-h) + env(safe-area-inset-bottom) + 16px) }`, with the
bar height as a CSS variable. Also call `scrollIntoView({ block: 'center' })` in the focus handler for
inputs inside the form root. The content already has bottom padding; this only fixes focus.

**P1-2. Studio: inactive Tabs labels are 4.2:1 on the desk background (WCAG 1.4.3 needs 4.5:1).**
This affects the builder Add/Outline tabs, the submissions status tabs (New, In review, Approved,
Rejected, All), the detail sheet Answers/Activity tabs, the Jotform import Link/Source code/File/API
key tabs and the org preview Light/Dark tabs. The measured colour is `foreground / 60%` on
`#F3F5F9`. *Evidence:* `subs-03-all-desktop-light.png`, `builder-01-en-desktop-light.png`,
`import-01-jotform-desktop-light.png`, and `_scripts/audit.jsonl`. *Fix:* keep the generated `TabsTrigger` and
theme it from `index.css`: `[data-slot=tabs-trigger]:not([data-state=active]) { color: var(--muted-foreground) }`
(5.45:1 on Desk per DESIGN-SYSTEM §3.1). Do the same for dark mode.

### P2 (fix before release)

**P2-1. Public form, all viewports: inputs in the error state get narrower.** The red start bar plus
padding make the input shrink at the end edge (about 15 px), so errored inputs no longer line up with
the choice cards and the layout shifts on submit, in both EN and DV.
*Evidence:* `pub-en-02-page1-errors-desktop-light.png`, `pub-dv-02-page1-errors-desktop-light.png`.
*Fix:* draw the error marker with `border-s-[3px]` plus a negative start margin (`-ms-[15px] ps-3`)
or a `before:` pseudo-element positioned in the gutter, so the content box keeps its width. Use the
same treatment for text and choice questions.

**P2-2. Public form and canvas: half-width pairs misalign vertically.** Help text ("Between 15 and 35",
"We send your signed copy…") or the Sensitive badge pushes one input down, so ID/Age and Email/Phone
are ragged. *Evidence:* `pub-en-01-page1-desktop-light.png`, `builder-01-en-desktop-light.png`.
*Fix:* make the pair a CSS grid with `grid-template-rows: subgrid` (label / description / control /
error rows), or align the controls to the row end (`items-end` on the row, `Field` stays the wrapper).

**P2-3. Validation copy is generic and sometimes ungrammatical.** Examples: "Enter phone",
"Enter email", "Enter copy of ID card" (for an upload), "Which track interests you most?: Choose an
option" (`?:`), and in DV "Answer this question: …". DESIGN-SYSTEM §9 asks for what happened plus how
to fix it, with an example. *Evidence:* `pub-en-02-page1-errors-desktop-light.png`,
`pub-en-06-upload-error-pixel7-light.png`, `pub-dv-02-page1-errors-desktop-light.png`.
*Fix:* add per-type messages in both validation twins (`renderer/validation.ts`, `validation/answers.py`):
"Enter a phone number, like 7771234", "Upload a copy of your ID card", "Choose a track". For the
summary, drop the "label: message" join when the message already names the question.

**P2-4. Errors appear before the user has acted.**
- The builder inspector shows a red "Add a label so people know what to answer" the moment a question is added.
- On the public form, the "Choose an option" error appeared as soon as keyboard focus entered the
  choice question.

The skill's `inline-validation` rule says to validate after the user finishes. *Evidence:*
`builder-05-selected-desktop-light.png`, `pub-en-14-focus-radio-desktop-light.png`.
*Fix:* in the builder, keep the quiet "Fix" badge and show the `FieldError` only after the label
input has been blurred once or Publish was tried. In the renderer, validate a RadioGroup on group blur
(focus leaving the fieldset), not on focus.

**P2-5. File upload failure is a dead end.**
- "Couldn't upload." gives no reason (type, size or network).
- The failed file still counts toward the limit ("You've added 2 files, the most allowed").
- The Choose files button turns red and looks destructive.

*Evidence:* `pub-en-06-upload-error-pixel7-light.png`, `pub-en-09-submit-failed-desktop-light.png`.
*Fix:* map the refusal codes to plain reasons ("This file type isn't allowed. Upload a PDF, JPG or
PNG."). Exclude failed items from the count. Keep the `Button variant="outline"` neutral and put the
error in `FieldError`.

**P2-6. Signature in the error state; small controls.**
- The whole field turns red, including the signing statement ("I confirm…"), which then reads as an
  error message. The "Undo stroke" and "Clear" buttons also turn red.
- Those two buttons are about 24 px tall on the public form, where the spec asks for at least 44 px.

*Evidence:* `pub-en-06-upload-error-pixel7-light.png`, `pub-en-04-page2-desktop-light.png`.
*Fix:* colour only the label and the `FieldError`; keep the statement as `FieldDescription`. Use
`Button size="sm"` with `min-h-11` (public density) for Undo/Clear.

**P2-7. Public primary button hover state is 3.74:1.** The hover colour is primary at 80% (white on
`rgb(62,144,139)`) and fails 4.5:1 for the 16–20 px label. *Evidence:* hover captures in
`pub-dv-02-page1-errors-pixel7-light.png` and `pub-en-02-page1-errors-iphone14-light.png`, and
`_scripts/audit.jsonl`. *Fix:* in the form-theme CSS, derive a `--primary-hover` that is darker
(oklch L −0.06), not translucent, and apply it with
`[data-slot=button][data-variant=default]:hover { background: var(--primary-hover) }` inside the
form root. The contrast checker that already adjusts the accent should check this pair too.

**P2-8. Latin text can render in Faruma's Latin glyphs.** On a Pixel 7 the closed screen showed the
body in a serif face with "·" for full stops. The theme stack puts Faruma before the generic fallback,
so while IBM Plex is still loading, Latin falls through to Faruma. This is intermittent: one of five
devices. *Evidence:* `pub-en-11-closed-mock-pixel7-light.png`; compare `pub-en-11-closed-mock-iphone14-light.png`.
*Fix:* add an `@font-face` alias for the Thaana faces with `unicode-range: U+0780-07BF, U+FDF2, U+FDFD`
(the Thaana block) so they never cover Latin. Alternatively, order the stack
`Latin, system-ui, sans-serif, Thaana` in non-DV roots. Preload the Latin face for the public bundle.

**P2-9. Builder on phones: question settings have no visible entry point.** The settings drawer opens
only when you tap a block *outside its text*, but almost every part of a block is inline-editable
text. In testing, tapping beside the label opened inline editing of an option instead. Required,
Logic, Validation and Advanced are hard to reach for a non-technical builder.
*Evidence:* `builder-18-inspector-drawer-pixel7-light.png`, `builder-17-selected-pixel7-light.png`.
*Fix:* when a block is selected on narrow screens, show a visible "Settings" `Button` (icon + label)
in the block's action row, and/or a bottom bar with Settings and Add question. It should open the
existing `Drawer`.

**P2-10. Builder on phones: the page strip clips.** The third page ("Documents and signature") is cut
off and leaves a stray "·" before "Add page". There is no scroll cue or overflow menu.
*Evidence:* `builder-01-en-pixel7-light.png`, `builder-02-dv-pixel7-light.png`.
*Fix:* wrap the strip in `ScrollArea` with a horizontal `ScrollBar` and an end fade. Alternatively, on
phones replace it with a `Select` or `DropdownMenu` page switcher ("Page 1 of 3: About you").

**P2-11. Publish problems dialog: the rows can't be told apart.** Five rows read "Add a label so
people know what to answer / Page 1, untitled question". *Evidence:*
`builder-15-publish-dialog-desktop-light.png`. *Fix:* identify each question by its position and type
("Page 1, question 2 (Email)"), keep the Show buttons, and use the `Item` list inside `ScrollArea`
with a visible count of hidden rows.

**P2-12. Form Settings is one 6,600 px page.**
- The Appearance preview sits *below* the controls on desktop, while Organisation settings has it
  side by side, so you can't see a change as you make it.
- Each card has its own save model: Appearance has Save/Discard, the switches apply instantly.

*Evidence:* `fsettings-01-en-desktop-light.png`, `org-01-settings-desktop-light.png`.
*Fix:* put the Appearance preview in a sticky right column, as on org settings. Add section navigation:
a left list of anchors on desktop and a `Select` on phones (Appearance, Access, Spam, Notifications,
Approvals, Webhooks, Retention). State the save behaviour once per card in its `CardDescription`.

**P2-13. Bulk selection: Delete looks like Export.** "Delete" is a neutral button inside the same
`ButtonGroup` as Change status and Export selected, and the header checkbox shows a tick (not
indeterminate) when 2 of 4 rows are selected. *Evidence:* `subs-10-bulk-desktop-light.png`.
*Fix:* move Delete out of the group, use `variant="destructive"` (or outline with destructive text)
followed by `AlertDialog` with an Undo toast, and set `checked="indeterminate"` on the header `Checkbox`.

**P2-14. Sign-in errors.**
- An invalid email shows Chrome's native bubble ("Please include an '@'…") instead of the app's error
  style.
- A wrong code shows a neutral `Alert` above the field, with no icon, not linked to the OTP input,
  and with no "Send a new code" action. The approver page has one.

*Evidence:* `auth-03-signin-bad-email-desktop-light.png`, `auth-06-signin-wrong-code-desktop-light.png`.
*Fix:* add `noValidate` to the form and render `FieldError` under the input with
`aria-invalid`. Use `Alert variant="destructive"` with an icon, or a `FieldError` under the
`InputOTP`. Clear the slots and add a "Send a new code" link with a cool-down, as on `/a/`.

**P2-15. Thaana labels are too small and pale outside the renderer.** In the DV approver page, the
signed PDF and the receipt email, question labels are tiny muted Thaana, smaller than the answers
below them, which inverts the hierarchy. DESIGN-SYSTEM §4.2 sets Thaana at about 1.12× the Latin size,
and these places miss it. *Evidence:* `approver-dv-04-review-pixel7-light.png`, `pdf-dv-p1.png`,
`email-receipt-dv-phone.png`. *Fix:*
- Approver page: apply the same `:lang(dv)` type-scale override to the label element (it is
  probably missing `lang="dv"`).
- PDF: raise DV label size about 1.15× in `app/pdf`, using ink-muted, not light grey.
- Email: give `td[lang=dv]` a 16 px label and 18 px answer with the Thaana font stack.

**P2-16. Signed PDF layout.**
- (EN) The signature image is pushed to page 2, away from its statement, while page 1 has room to
  spare.
- The footer uses a middle dot ("Digitally signed · verify at"), which DESIGN-SYSTEM §9 bans.
- No organisation or form logo, although the Logo setting says it is "shown … on its emails and PDFs".
  The sample was signed on 23 Oct, before the per-form logo, so check a fresh one.

*Evidence:* `pdf-en-p1.png`, `pdf-en-p2.png`. *Fix:* keep the signature block together (if it doesn't
fit, break before the statement). Write "Digitally signed. Verify at …". Draw the effective logo in
the header.

**P2-17. Jotform import "Check the result".**
- The preview renders in the default carbon/blue theme, not the org's teal form theme the draft will
  actually get.
- The report shows internal type ids ("fullname → section", "matrix → nothing", "auto").

*Evidence:* `import-06-check-result-desktop-light.png`. *Fix:* render the preview inside the org
form-theme provider used by Form settings › Appearance. Replace the ids with plain names ("Full name
became a section with one question per part"); show raw ids only in a `Collapsible` "Technical details".

**P2-18. Builder canvas: the preview controls are in the accessibility tree without names.** Canvas
radio items (`value="x"`, yes/no) are focusable-looking `role=radio` elements with no accessible name.
A screen reader user tabbing the canvas meets unnamed radios inside an editor. *Evidence:*
`builder-01-en-desktop-light.png`, `_scripts/audit.jsonl` (builder rows). *Fix:* mark the rendered
control area of each block `inert` (and `aria-hidden`), and keep the block's own button ("Edit
question label: …") as the interactive element.

### P3 (polish)

- **P3-1.** Rating "How did you find this form?" shows 1–5 with no end labels; the builder should
  prompt for low/high labels. *Evidence:* `pub-en-04-page2-desktop-light.png`.
- **P3-2.** The closed, not-found and success screens drop the org/form branding and title. Closed
  and not-found offer no next step (support link, "Go to [org]").
  *Evidence:* `pub-en-11-closed-mock-desktop-light.png`, `pub-12-not-found-pixel7-light.png`,
  `pub-en-10-success-desktop-light.png`.
- **P3-3.** The drag overlay shows the key ("email") instead of the label.
  *Evidence:* `builder-10-drag-desktop-light.png`.
- **P3-4.** After a menu closes, the trigger's `Tooltip` reopens on focus return and covers the header
  (it blocked clicking Keyboard shortcuts). Use `Tooltip` with `delayDuration` and close it on
  `onCloseAutoFocus`.
- **P3-5.** The create-form dialog has about 40 px of dead space under Title. Create form is disabled
  with no hint ("Enter a title"). *Evidence:* `create-01-dialog-desktop-light.png`.
- **P3-6.** Heading order:
  - Builder palette `h3`s come before the page `h1`.
  - Settings pages have two `h1`s because the preview's form title is an `h1`.
  - Sign-in has no heading at all (`CardTitle` renders a div).

  Render the preview title as a `div role="heading" aria-level=2` or with `aria-hidden` on previews.
- **P3-7.** Back navigation is inconsistent: "← Forms" / "← Submissions" links on the import pages
  versus the `Breadcrumb` everywhere else.
- **P3-8.** Share › Link shows the full URL twice (Link input and the Address preview line).
  *Evidence:* `share-01-en-desktop-light.png`.
- **P3-9.** In the submission detail and on the approver page, questions hidden by logic show as
  "No answer". The approver page shows empty section headings. Show "Skipped (not shown to the
  respondent)" or omit them. *Evidence:* `subs-11-detail-desktop-light.png`,
  `approver-04-review-desktop-light.png`.
- **P3-10.** Submissions opens on the "New" tab even when it is empty (all 4 are In review), showing
  "No submissions match these filters". Default to the first non-empty tab or All.
  *Evidence:* `subs-01-table-en-desktop-light.png`.
- **P3-11.** A stray scrollbar thumb shows at the end of the status tabs row on desktop.
  *Evidence:* `subs-03-all-desktop-light.png`.
- **P3-12.** The `ToggleGroup` selected state (Typing Auto/Latin/Thaana, Text size, Corners…) is a faint
  tint plus border. Strengthen it via theme (`[data-state=on]` background `--secondary` plus 600
  weight). *Evidence:* `builder-05-selected-desktop-light.png`, `org-01-settings-desktop-light.png`.
- **P3-13.** The upload dropzone content is centred while everything else is start-aligned
  (DESIGN-SYSTEM §6). *Evidence:* `pub-en-04-page2-desktop-light.png`.
- **P3-14.** The disabled pale-green "Publish" on unchanged live forms gives no reason. Add a `Tooltip`
  "No changes since version 1". *Evidence:* `builder-01-en-desktop-light.png`.
- **P3-15.** Signature: offer a typed-name alternative alongside the pad. 2.5.7 likely exempts
  signatures as essential, but "contact the form owner" is a weak fallback.
- **P3-16.** Demo data: the org display name is "Example Youth Officedsdwdw" (typo) while the logo
  says "Example Youth Office", and org settings shows the slug name "Dotform" under the heading.
  Tidy this before showing the demo.
- **P3-17.** Phone numbers show raw (`+9607771234`) in the detail, approver page and PDF; format them as
  `+960 777 1234`.
