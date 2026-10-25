# Saved progress on the respondent's device

Respondents fill long forms on phones and lose them to a closed tab, a dead battery or a
reload. The public form keeps their answers in the browser's local storage while they type
and puts them back when the form is opened again on the same device and browser.

## 1. Behaviour

- **When it saves.** 500 ms after the last change, straight away on a page change, and when
  the page is hidden or closed (`visibilitychange` hidden, `pagehide`). Nothing is saved until
  the respondent changes something (opening a form with prefilled link parameters saves
  nothing). Only the live public form saves; the studio preview never does.
- **What it saves.** The answers and the current page, under one key per form
  (`justforms:progress:{formId}`). Email-code and staff-only forms add a hash of the
  respondent's confirmed email to the key, so two people on one browser never see each
  other's answers. The record holds the published version, the type of every saved question,
  the time it was saved and an expiry time.
- **What it never saves.** Questions marked **sensitive**, signatures (drawings), files
  (uploads belong to one page load's upload session, so their references cannot be reused
  after a reload) and hidden questions (they come from the link). Repeater rows are saved
  with the same rules for the questions inside them.
- **Restore.** When the form opens and a saved record exists, the form starts with those
  answers (link parameters still win) on the saved page, if that page is still on the
  respondent's path. A record saved for another version restores only answers whose question
  still exists with the same type, and starts on the first page.
- **Clear.** After a successful submit, on **Start over**, when the record has expired
  (default 7 days, per form) and when the owner has turned the setting off.
- **Fails quietly.** No storage (private mode, blocked third-party storage in an embed,
  sandboxed frame), a full quota or a broken record: the form works as before and the
  respondent sees nothing.

## 2. Restored notice

An `Alert` under the form title (the `notice` slot, after "Responding as" on email-code forms).
It sits in a polite live region, filled one frame after the form renders, so screen readers
announce it without focus moving.

```
┌───────────────────────────────────────────────────────┐
│ (i) We restored your progress from 2 hours ago.       │
│     Files and signatures aren't saved on this         │
│     device, so add them again.                        │
│     [ Start over ]  Dismiss                           │
└───────────────────────────────────────────────────────┘
```

Copy (English system text, through `<En>` in dv forms):

| Case | Text |
|---|---|
| Restored | We restored your progress from {time}. |
| Form changed | The form has changed since, so check your answers. |
| Form changed, answers dropped | The form has changed since, and some answers no longer apply. |
| Not kept | Files, signatures and private answers aren't saved on this device, so add them again. (only the kinds that had answers, e.g. "Files aren't saved…, so attach them again.") |
| Confirm | Clear your saved answers and start from the beginning? [Clear answers] [Keep my answers] |
| Cleared | Your saved answers were cleared. |

`{time}` is `Intl.RelativeTimeFormat('en', { numeric: 'auto' })`: "a moment ago" under a
minute, then "5 minutes ago", "2 hours ago", "yesterday".

Components: `Alert` + `AlertDescription`, `Button` (Start over outline, Dismiss ghost, both
44px, in a wrapping row under the text so the text keeps the full width at 320px). The short
"cleared" alert uses a ghost icon button (`aria-label="Dismiss"`) in `AlertAction`. Start over confirms **inline** in the same alert
instead of an `AlertDialog`: the form can be embedded in an iframe that is as tall as the form,
where a centred modal opens out of the respondent's view. The confirm step moves focus to
"Keep my answers" (the safe choice); "Clear answers" uses the destructive variant. After
clearing, the form starts again on page 1 and the alert reads "Your saved answers were
cleared." with focus on it.

The notice code is in the lazy `autosave` chunk, fetched in parallel with the form request,
so the public bundle does not grow.

## 3. Form setting

Settings › Access, card **Saved progress**:

- `Switch` "Save progress on this device" (on by default). Description: "Answers are kept in
  the respondent's browser so they can close the page and carry on later. They stay on that
  device and browser only and are not synced. Turn this off for forms filled in on shared or
  kiosk devices."
- `NativeSelect` "Keep saved progress for": 1, 3, 7 (default), 14 or 30 days. Hidden while the
  switch is off.

Changes apply right away (form settings, not the published version). Turning it off also
removes saved progress the next time the form opens on a device.

## 4. Review notes

- Notice: 390 and 1440, light and dark, en and dv, embed; confirm step; cleared state;
  keyboard focus; mobile audit.
- dv: restored Thaana answers render unchanged; the notice is LTR English inside the RTL sheet.
