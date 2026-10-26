# Insights and "Ask your submissions"

A second view of a form's submissions: a summary of every question, and (when the install has
an AI provider) a question box that answers from the submissions by counting them. Works for
any form; nothing is configured per form except whether the AI may read the text of answers.

Builds on [SUBMISSIONS-VIEWER-SCREENS.md](SUBMISSIONS-VIEWER-SCREENS.md) and
[PHASE-3-SCREENS.md](PHASE-3-SCREENS.md) §4 (filters). Tokens, type and motion come from
[DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with [REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md).
Copy in "quotes" ships as written, English only; form content (labels, options, answers) keeps
the form's language (`lang`, `dir="auto"`; Thaana gets its font through `:lang(dv)`).
Backend: DESIGN §15.4 (Insights) and §12.6 (Ask your submissions).

New from shadcn: **chart** (`corepack pnpm dlx shadcn@latest add chart`, Recharts). Everything
else is installed: `tabs` (line variant), `card`, `table`, `dropdown-menu`, `collapsible`,
`select`, `switch`, `alert-dialog`, `input-group`, `badge`, `empty`, `skeleton`, `spinner`.

## 1. Route and switch

- Route `/forms/$formId/submissions/insights`, loaded lazily (it carries the charts). It takes
  the same search params as the Submissions list (status, dates, version, question filters,
  `where` conditions), so switching keeps the filters.
- Under the "Submissions" heading, a line-variant `Tabs`: **Responses** | **Insights**. The
  form bar's Submissions item stays current on both.
- Viewers, editors and owners see Insights. "Ask your submissions" appears only when
  `GET /meta` reports `features.ai`.

## 2. Insights page

### 2.1 Desktop (≥ lg)

```
Submissions
Responses  Insights
─────────────────
[All statuses ▾] [Filter] [Submitted: Any time] [Version ▾]
(chips: question filters, "Topics: Disability rights" ×)  Clear filters
┌ Ask your submissions ─────────────────────────────────────── [new chat] ┐
│ Answers are counted from this form's submissions. …go to <provider>…    │
│ Try asking: [How many ticked “X”?] [What is the average “Y”?] [...]     │
│ [ Ask a question about the submissions…                          (↑) ] │
└─────────────────────────────────────────────────────────────────────────┘
Summary of 42 submissions
┌ Atoll ──────────────── … ┐ ┌ Topics ─────────────────── … ┐
│ 42 of 42 submissions answered│ 36 of 42 submissions answered │
│ Malé                      │ │ Disability rights            │
│ ███████████████  10 (23.8%)│ │ ██████████  14 (38.9%)       │
│ Other                     │ │ …                            │
│ ▓▓▓▓▓▓  6 (14.3%)          │ │ People could tick more than… │
│ “Other” answers (6) ▾     │ │                              │
└───────────────────────────┘ └──────────────────────────────┘
Board members                       (repeater section)
94 rows in 42 submissions, 2.24 on average
[cards for its questions, counted per row]
```

Two columns of question cards from `lg`, one below. Cards are paper-flat (`rounded-md`,
hairline border, no shadow), in form order; repeaters follow as their own sections.

### 2.2 Phone

One column; the filter row is the Submissions one (Filter and dates collapse to icon
buttons); the Ask card sits above the summary; charts fill the card width.

### 2.3 Card content by question type

| Type | Shows |
|---|---|
| Single/multi choice, yes/no | Horizontal bars, the option text above its bar (form language), count and share of those who answered at the end. "Other" is a muted bar; "“Other” answers (n)" opens the most common texts. Multi choice: "People could tick more than one, so the shares add up to more than 100%." |
| Number, rating | Lowest / Average / Median / Highest, then a histogram (ratings: one bar per star) |
| Date | Bars per month, per year when the answers span more than three years; "By month, from … to …." |
| Text, email, phone | The newest three answers, each a full-width row linking to its submission (`#12` + text), and "Show the N submissions" |
| Sensitive | "Sensitive" badge, "Answers to sensitive questions stay hidden here." and masked examples (`••••567`) |
| File, signature | Answered count, "Files are counted, not shown here." |

Description line: "{n} of {total} submissions answered" ("rows" inside a repeater); with
several versions, "Version 2 only" / "Versions 1–3" for questions not asked by all.

Card menu (`…`, "More for {question}"): "Show as table" / "Show as chart", "Download as PNG"
(chart view), "Show submissions that answered".

### 2.4 Into the list

Clicking a bar (or an answer in the table view) opens **Responses** with the page's filters
plus that bar's conditions (`where`) and a chip naming it ("Atoll: Malé" ×). The chip removes
the conditions; "Clear filters" clears everything. The same chip shows conditions opened from
an AI answer, labelled with the query in words.

### 2.5 States

- Loading: four card skeletons after the usual delay.
- No submissions: `Empty` "No submissions yet" / "A summary of every question appears here
  once people respond." With filters: "No submissions match these filters" + "Clear filters".
- Error: destructive `Alert` "Couldn't load the summary. Check your connection." + "Try again".
- Never published: the Submissions empty state with "Go to Share".

## 3. Charts

Official shadcn `ChartContainer` + Recharts; colours from `--chart-1` (carbon) and `--chart-5`
(muted, "Other"); the bar track uses `--muted`. No legends (one series), no grid. The chart is
`role="img"` with an `aria-label` listing every answer and count; the table view is the
keyboard path (each answer is a button). Charts stay left to right in dv forms (studio chrome);
labels inside them are Thaana with the Thaana font. "Download as PNG" draws the chart with its
computed colours on the card background with the question as title, 2x.

## 4. Ask your submissions

- Card "Ask your submissions", description naming the provider and what is sent:
  - reading answers off: "Answers are counted from this form's submissions. Your question, the
    form's questions and counts go to {provider}; the text of answers doesn't."
  - on: "…Your question, the form's questions, counts and, when needed, the text of answers go
    to {provider}."
- Empty chat: "Try asking:" with up to three questions built from the form (first multi-choice
  option, a number's average, submissions per month; a summary of a long-text question when
  reading answers is on). A chip sends at once.
- Composer: `InputGroupTextarea` "Ask a question about the submissions…", Enter sends,
  Shift+Enter new line, Esc stops; the send button turns into "Stop" while answering. Over
  2,000 characters: "Keep questions under 2,000 characters."
- While answering: the question bubble (end side, `bg-secondary`), then each count as it runs
  ("Submissions where … : 14 submissions") and "Counting…" with a spinner (`aria-live`).
- Answer: the reply text (`dir="auto"`), any chart/table the AI asked for (drawn from the
  counted result, never from the AI's words), then:
  - "Show these N submissions" (link button): Responses filtered to the main query.
  - "How this was calculated" (collapsible): each query in words with its count and
    "Show them"; reading steps say which questions were read and for how many submissions.
- Errors (plain, in place): allowance used up, too many questions, too slow, provider down,
  "The AI couldn't work out how to count that. Try asking it another way."
- Last three exchanges show; "Show N earlier questions" reveals the rest. "New chat" (icon,
  tooltip) starts over. Chats are personal and kept 90 days.
- Owners with reading off see: "To let the AI summarise written answers, turn on Settings › AI."

## 5. Settings › AI

A section shown only when the install has an AI provider (`#ai`). Card "AI": "“Ask your
submissions” on the Insights page answers questions by counting this form’s submissions.
Anyone who can see the submissions can ask."

Switch **Allow AI to read answers** (off by default, owners only) with the description:
off "Off: {provider} only gets the questions, counts and numbers, never the text of answers."
/ on "On: to summarise answers or find themes, the text of answers is sent to {provider}." and
always "Sensitive questions, files, signatures, email addresses, phone numbers and
respondents’ IP addresses are never sent."

Turning it on asks first (`AlertDialog`): "Send answers to {provider}?" / "When someone asks
for a summary, the text of up to 200 submissions’ answers goes to {provider}. … You can turn
this off at any time." Buttons "Cancel", "Allow AI to read answers". Turning it off is
immediate. Toasts: "AI can read answers" / "AI no longer reads answers".

## 6. Self-critique

- First idea was a dashboard of big-number tiles over a chart grid. Dropped: tiles repeat what
  the card description says, and the brief's job is answering questions about the answers, so
  the question box leads and the cards read like the form, in its order.
- Bars with labels on a left axis truncate badly on phones and with Thaana; labels sit above
  each bar instead, full width.
- Colour stays quiet: carbon bars, a muted "Other", no marker wash (that means "selected" or
  "in review" elsewhere).
- The AI's numbers are never trusted for display: charts come from stored query results, and
  every answer links to the exact submissions it counted.
