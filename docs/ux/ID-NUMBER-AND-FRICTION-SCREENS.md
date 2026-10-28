# ID number question and "Where people get stuck"

## 1. ID number question

A short answer with an identity-number format. Palette: **Text › ID number** (keywords: id,
card, identity, national, passport). New blocks get the first preset, the label is empty like
every new question, and **Sensitive** starts on when the preset says so (the owner can turn it
off under Advanced).

**Inspector › Question › ID format** (`NativeSelect`): one entry per preset, written
"*Label* (*example*)", e.g. *Maldives national ID card (A123456)*, then **Custom**.

- **A preset** brings the pattern, the error message, the maximum length and the normalising.
  The Validation group is hidden; the description under the select says what happens:
  "Checks the format A123456, removes spaces and uses capital letters. Typing is always Latin."
  The Placeholder field shows the preset's placeholder as its own placeholder; leaving it empty
  keeps the preset's, and the canvas shows it too.
- **Custom** shows the Validation group (pattern, message, max length, test box). Switching from
  a preset to Custom copies the preset's pattern, message, length and placeholder in, so the
  owner edits rather than retypes.

**Presets are data**: `backend/app/schemas/id_presets.json` (exported to
`spec/id-presets.v1.json` and the frontend). Each entry: `id`, `label`, `example`, `pattern`,
`placeholder`, `message`, `maxLength`, `uppercase`, `stripSpaces`, `sensitive`. Adding a
country is adding an entry.

**Respondent.** Latin input (never the Thaana keyboard, also on Dhivehi forms), left to right,
`autocapitalize="characters"`, no autocomplete or spellcheck, tabular figures. What is typed
is normalised on every keystroke (`a123 456` becomes `A123456`); the length counter appears at
80 % of the maximum. A wrong format shows the preset's message on blur ("Enter the ID card
number, e.g. A123456"). The server normalises and checks again (same shared cases,
`spec/validation/answers.json`) and stores the normalised value.

Exports, Insights and Ask see a short answer (masked where the question is sensitive).

## 2. Insights › Where people get stuck

A card on the Insights page under "Ask your submissions", independent of the submission
filters: last 30 days, all versions.

```
┌ Where people get stuck ──────────────────────────────────────────┐
│ Last 30 days, all versions. Anonymous counts from the form: no   │
│ answers and nothing about who.                                   │
│ How far people got                                               │
│ Opened the form                                            40    │
│ ████████████████████████████████████████████████████████████    │
│ Started answering                                     34 · 85%   │
│ Reached Contact details                               26 · 65%   │
│ Submitted                                             15 · 38%   │
│ Questions with the most problems                                 │
│ Question                          Page              Visits       │
│ ID card number                    About you            31        │
│ [Wrong format 22] [Left empty 9]                                 │
│ Kinds of problems                                                │
│ [Wrong format 22] [Phone not valid 14] [Left empty 13] ...       │
└──────────────────────────────────────────────────────────────────┘
```

- **How far people got**: opened (visits of the first page), started answering, reached each
  later page (the page title, or "Page n"), submitted; count and share of opened, with a
  `Progress` bar labelled for screen readers.
- **Questions with the most problems** (`Table`, top 10): label (form language, `bdi`), the
  kinds of problems as badges with counts, page (hidden on phones), visits shown a problem.
- **Kinds of problems**: problem codes merged under plain names (Left empty, Wrong format, Too
  long, Email not valid, Phone not valid, Not a number, Out of range, Date or time not valid,
  Date out of range, Too many chosen, File problem, Signature problem, Not accepted).
- Empty: "Nothing recorded yet. Counts appear here as people open and fill in the form."
  Turned off with nothing recorded: a link to Settings › Access; turned off with earlier
  counts: they still show, with a note.

## 3. Settings › Access › Where people get stuck

A card under Saved progress with one `Switch`, **Count where people get stuck** (on by default,
owners only): "The form counts which pages people reach and which questions show them a
problem (for example a wrong format), so Insights can show where they give up. Only counts are
kept: never answers, and nothing that identifies anyone. No cookies are used."

## 4. What the public form sends

`POST /api/v1/public/forms/{slug}/friction`, batched every 3 s and on page hide, no
credentials: `{versionId, visit, events: [{type: "page", page} | {type: "start"} |
{type: "error", field, code}]}`. Each event once per visit. `visit` is random, kept in the
tab's `sessionStorage`. Submissions are counted by the server. Details and privacy:
[Security](../security.md#where-people-get-stuck-respondent-friction).
