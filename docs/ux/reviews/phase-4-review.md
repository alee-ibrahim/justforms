# Phase 4 UI review

Reviewer: implementer's self-review against [REVIEW-CHECKLIST.md](../REVIEW-CHECKLIST.md) and
[PHASE-4-SCREENS.md](../PHASE-4-SCREENS.md). Date: 2026-10-23.
Scope: the Settings page (who can respond, spam protection, email notifications, webhooks and
their delivery sheet, data retention), the public email-code step (dv, phone), "Responding
as", the proof-of-work CAPTCHA on submit, the respondent email in submissions, and the two
carried-over P3s.

## How this review was done

Playwright (Chromium) against the full `docker compose --profile dev` stack: desktop
1440×900 light and dark, phone 390×844; an en form with a signature and an email-code dv
form. The same run submitted a response with the CAPTCHA on, read the owner email and the
receipt (with the signed PDF) in Mailpit, received both webhooks on a local receiver and
checked their signatures with `docs/webhooks/verify.py`. Screenshots live outside the repo.
Diff skim: `components/ui/` unchanged (no new components were needed), logical classes only
(lint), no organisation references, dv strings marked as drafts.

## Findings

### P1

None.

### P2 (fixed)

- **P2-1. Org name in a serif face on the email-code step** (public, dv, phone, light). The
  gate header showed "JustForms" through the Thaana stack (Faruma's Latin glyphs). Same cause as
  Phase 2 P2-1. Fix: `public/protected.tsx` sets `lang` on the org name like `FormHeader`.
- **P2-2. Recent emails cut the address on phones** (Settings, 390px). The time at the end
  squeezed the title to "Receipt to a•••@example". Fix: on phones the time moves under the
  address (`notifications-card.tsx`), the address may wrap.

### P3

- **P3-1 (fixed).** Emails said "Sent by JustForms for JustForms" when the organisation is still
  called JustForms; times in emails now carry the time zone.
- **P3-2.** Status tabs on phones: the first tab is no longer cut (Phase 2 P3-7, fixed); the
  last tab is cut at the end edge as the scroll cue, and the scrollbar shows on scroll only.
- **P3-3.** A one-response email-code form still offers "Submit another response" on the
  success screen; the second try ends on "You've already responded". Hide the button when
  `otp.oneResponse` is on.
- **P3-4.** The signature question can show "Sign in the box" after the respondent has drawn,
  until they submit (seen on the en form; Phase 3 behaviour).
- **P3-5.** Sheets on phones still end after the content (Phase 2 P3-10), now also on the
  email-code step.

### Carried over from earlier reviews

- "Add someone" error no longer turns the role select red: only the email input is marked
  invalid (`access-card.tsx`). Verified on phone.

## Checklist verdict

| Section | Verdict | Notes |
|---|---|---|
| A. Hard rules | Pass | shadcn components only; dv gate RTL from its root; studio chrome English/LTR |
| B. Tokens | Pass | delivery states are icon + code; stamp only for failures and Delete |
| C. Typography | Pass after P2-1 | email, code countdown and domains isolated in `bdi`; code input LTR |
| D. Layout | Pass after P2-2 | Settings cards stack on phones |
| E. Components | Pass | RadioGroup, Switch, NativeSelect, InputOTP, Dialog, AlertDialog, Sheet, Table |
| F. States | Pass | empty webhooks, no SMTP, no CAPTCHA provider, loading skeletons, errors with fixes |
| G. Motion | Pass | nothing new animates on its own |
| H. Accessibility | Pass | labels on every control, focus moves to step headings, live "Code sent" |
| I. Copy | Pass | glossary terms; errors say how to fix |
| J. Performance | Pass | public bundle 119.3 KB gzip; access and CAPTCHA code in a lazy chunk |
