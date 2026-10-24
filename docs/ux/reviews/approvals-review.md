# Approvals, clean PDF and verify page: UI review

Reviewer: implementer's self-review against [REVIEW-CHECKLIST.md](../REVIEW-CHECKLIST.md) and
[APPROVALS-SCREENS.md](../APPROVALS-SCREENS.md). Date: 2026-10-23.
Scope: the Approvals card on Settings, approval problems and warnings in the publish dialog,
"Step n of N" in the submissions table, the Approval block, "Audit details" and approval
events in the detail sheet, the approver page (en and dv, phone and desktop), the verify page
(en and dv), the approval request and outcome emails, the clean signed PDF (en, dv,
rejected), and the two carried-over P3s from the Phase 4 review.

## How this review was done

Playwright (Chromium) against the full `docker compose --profile dev` stack: desktop
1440×900 light and dark, phone 390×844; an en and a dv form, each with a two-step approval
(step 1 from an email question, step 2 a fixed address), plus a rejected path. Emails were
read in Mailpit, the outcome PDFs downloaded from it and rasterised. Screenshots live outside
the repo. Diff skim: `components/ui/` unchanged (nothing new was needed), logical classes only
(lint), no organisation references, dv strings marked as drafts.

## Findings

### P1

None.

### P2 (fixed)

- **P2-1. Latin text in a serif face on dv document pages** (approver and verify, phone, dv).
  The organisation name, dates and reference inherited the Thaana stack and picked up
  Faruma's Latin glyphs (same cause as Phase 2 P2-1). Fix: the org name gets `lang` from its
  script, and dates and references are `bdi dir="ltr"` runs (`doc/verify.tsx`,
  `doc/approver.tsx`, `[[...]]` runs in the messages).
- **P2-2. "Step 1 of 2" split across lines in dv** (approver, phone). The fraction broke at
  its spaces and read "/ 1" then "2". Fix: no-break spaces inside the isolated run in the en
  and dv messages.
- **P2-3. Gaps inside activity titles** (detail sheet, Activity, desktop). "(step 2,
  Director )" had stray spaces because `ItemTitle` is a flex row and spaced out the text and
  `bdi` runs. Fix: one `span` around the title in `activity.tsx` and `approval-block.tsx`.
- **P2-4. Document pages ended after the content on phones** (verify, phone). The desk showed
  under a short sheet. Fix: the sheet is at least the screen height on phones (`doc/page.tsx`).

### P3

- **P3-1 (fixed).** The approver's status screens used a `div` title, so "Approved" was not a
  heading for screen readers. Now an `h1` that takes focus.
- **P3-2.** Latin words inside dv copy ("PDF" in "PDF އިޚްތިޔާރުކުރައްވާ") still use Faruma's
  Latin glyphs. The copy is a draft; a Dhivehi editor may drop the Latin word.
- **P3-3 (seen, not from this change).** The file question says "You've added 1 files, the
  most allowed" on a one-file question (plural).
- **P3-4.** The approver page's dates use English month names in dv (`Intl` has no `dv`
  locale); Western digits as everywhere else.

### Carried over from earlier reviews (fixed)

- Phase 4 P3-3: a one-response email-code form no longer offers "Submit another response".
- Phase 4 P3-4: lifting the pen after a stroke no longer brings back "Sign in the box".

## Checklist verdict

| Section | Verdict | Notes |
|---|---|---|
| A. Hard rules | Pass | shadcn components only (Card, Field, RadioGroup, NativeSelect, Switch, Item, Table, AlertDialog, InputOTP, Collapsible, Alert, Empty); dv pages RTL from their root; studio stays English/LTR |
| B. Tokens | Pass | step states are icon + words; stamp only for rejected, destructive actions and failed copy checks |
| C. Typography | Pass after P2-1, P2-2 | references, dates, emails and fractions isolated; dv sizes from the `:lang(dv)` scale |
| D. Layout | Pass after P2-4 | Settings steps stack on phones; approver decision buttons 48px |
| E. Components | Pass | approval steps are `FieldSet`s on hairline blocks, no shadows |
| F. States | Pass | no email questions, no SMTP, unsaved changes, link done/stopped/invalid, code errors, verify changed/not found, copy-check results |
| G. Motion | Pass | nothing new animates on its own |
| H. Accessibility | Pass after P3-1 | labels on every control, focus moves to step headings, "Code sent" announced, icon buttons have tooltips and names |
| I. Copy | Pass | glossary terms (Approval, Step, Approver, Stop approval, Genuine document); errors say how to fix |
| J. Performance | Pass | public form 119.4 KB of 120; document pages 85.5 KB of 95 (separate build); approver page lazy |
