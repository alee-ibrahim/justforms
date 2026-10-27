# Insights and "Ask your submissions"

A second view of a form's submissions: a summary of every question, and (when the install has
an AI provider) a question box that answers from the submissions by counting them. Works for
any form; nothing is configured per form except whether the AI may read answers.

Builds on [SUBMISSIONS-VIEWER-SCREENS.md](SUBMISSIONS-VIEWER-SCREENS.md) and
[PHASE-3-SCREENS.md](PHASE-3-SCREENS.md) §4 (filters). Tokens, type and motion come from
[DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with [REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md).
Copy in "quotes" ships as written, English only; form content (labels, options, answers) keeps
the form's language (`lang`, `dir="auto"`; Thaana gets its font through `:lang(dv)`).
Backend: DESIGN §15.4 (Insights) and §12.6 (Ask your submissions).

New from shadcn: **chart** (`corepack pnpm dlx shadcn@latest add chart`, Recharts). Everything
else is installed: `tabs` (line variant), `card`, `table`, `dropdown-menu`, `collapsible`,
`select`, `switch`, `alert-dialog`, `input-group`, `badge`, `empty`, `skeleton`, `spinner`,
`button-group` (the list's Copy / CSV).

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
| Sensitive | "Sensitive" badge and the newest three answers as given |
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

### 4.1 Where it lives

- One panel for the whole Submissions area (Responses, Insights, a submission), built like the
  builder's assistant panel: a header (title, "New chat", close), the conversation, and the
  composer with a one-line note at the bottom.
- From 1024px it is docked at the end of the page under the form bar (`aside`, 26rem, 28rem
  from `xl`); the page stays usable beside it, so "Show these N submissions" filters the list
  while the chat stays open. Below 1024px it is a full-height `Sheet` (right, full width,
  `max-w-md` from `sm`); opening a list closes it.
- The form bar's AI button says what it does on each page: **Ask about submissions** on
  Submissions (opens or closes this panel; tooltip "Ask questions about these submissions"),
  **Edit with AI** elsewhere (the builder's assistant, going to Edit first). On phones the
  form menu has the same item ("Close Ask your submissions" while open). Viewers get the
  Ask entry too.
- Insights shows a short card "Ask your submissions" ("Ask in your own words. Answers are
  counted from the submissions and link to them."), a question box that opens the panel and up
  to three example questions that open it and ask at once. Hidden while the panel is open.
- Shown only when `GET /meta` reports `features.ai` and the form has been published.

### 4.2 Conversation

- Empty chat: "Ask about this form's submissions" / "Answers are counted from the
  submissions, and every answer links to the ones it counted.", then "Try asking" with up to
  four questions built from the form's choice questions ("How many ticked “<option>”?",
  "List the contact details of every submission" when the form has a name question and a
  phone or email question, "Who ticked “<option>”?" when the form has a name question,
  "Breakdown by “<question>”"), a
  number's average, submissions per month (and a summary of a long text when reading answers
  is on). Long labels are cut at a word with "…". A chip asks at once.
- Composer: `InputGroupTextarea` "Ask a question about the submissions…", hint "Enter to send,
  Shift+Enter for a new line" (hidden on phones), Enter sends, Shift+Enter new line, Esc
  stops; the send button turns into "Stop" while answering. Over 2,000 characters: "Keep
  questions under 2,000 characters." Focus returns to the composer after each answer.
- No data notice under the composer: what goes to the AI service is explained once, next to
  the switch in Settings › AI. The provider is never named anywhere in the studio.
- Question: bubble at the end side (`bg-secondary`).
- While answering: a card with each count as it runs ("Submissions where … : 14
  submissions"), the reply when it arrives, and "Reading your question…" / "Counting…" with a
  spinner (`aria-busy` on the log). The log follows new content unless the person scrolled
  up; when the answer lands its question scrolls to the top.
- Answer card (flat, hairline border): the counted number large (`text-3xl`, tabular) with
  "of N submissions" when the answer is one count; the reply text (`dir="auto"`); any chart,
  table or list (drawn from the counted result, never from the AI's words); "How this was
  calculated" (collapsible: each query in words with its count and "Show them"; reading steps
  say which questions were read for how many submissions). Footer: **Show these N
  submissions** (outline button: Responses filtered to exactly what the answer counted, with
  the chip naming it) and "Copy answer" (icon, tooltip; "Copied" for two seconds).
- Lists ("contact number of all CSOs", "who ticked …"): read on the server from the
  database (`list_submissions`), never typed by the AI. Above them "N submissions" ("
  (newest of M)" when capped) and outline buttons: **Sort** (only in the stacked layout) and a
  `ButtonGroup` of **Copy** (tab-separated, for spreadsheets; "Copied" for two seconds) and
  **CSV** (UTF-8 with a byte-order mark, so Thaana opens in spreadsheets; cells that would run
  as a formula are defused, phone numbers kept; file named after the list title). Copy and
  CSV carry the exact stored values.
  - Up to two questions: a compact table, "Number" (`#12`, a link to the submission) plus the
    questions; every header is a ghost sort button (arrow icon, `aria-sort`).
  - Three or more (e.g. name, phone, email): the panel is too narrow for a table, so each
    submission stacks: `#12` and the first question (the name) in medium weight, then a
    two-column list of the other questions' labels (muted) and answers, indented under the
    name from `sm`. **Sort** is a `DropdownMenu` with radio items ("Newest first", "Number",
    each question) and, once a column is chosen, "A to Z, low to high" / "Z to A, high to
    low".
  - Unanswered cells say "No answer" (muted) and sort last. Phone numbers read grouped on one
    line (`+960 777 1234`); emails may break before "@"; other text wraps.
  - The first 10 submissions show, then **Show all N** / **Show the first 10**. Up to 500;
    beyond that "The newest 500 of N are listed. Export on the Responses page has them all."
  - Sensitive answers show as given (everyone who can see submissions sees them). The AI gets
    the counts (and the values only when the form allows AI to read answers), so it replies
    e.g. "40 organisations are listed below. 36 of them gave a contact number." "How this was
    calculated" says "Listed “…”, “…”. Submissions where …: N submissions".
- Errors in place: the reason (allowance used up, too many questions, too slow, provider
  down, "The AI couldn't work out how to count that. Try asking it another way.", "Something
  went wrong while counting. Try again.") and **Try again**; a stopped answer says "Stopped
  before an answer." with **Ask again**.
- Last three exchanges show; "Show N earlier questions" reveals the rest. "New chat" starts
  over. Chats are personal and kept 90 days.

### 4.3 Which submissions an answer links to

The server picks them from the reply: the first whole number in it that is the count of a
query, or of one group of a grouped query, wins ("16 of 40 ticked X" links to the 16, not the
40; groups with the same count go to the one the reply names). A reply quoting two or more
groups of one query is a breakdown and links to that query. Otherwise the newest query with
conditions, else the newest query.

### 4.4 Loose wording

People ask in their own words ("who want to know about human rights"). The AI is told to match
questions and options by meaning, to count the best match and say which option of which
question it counted, and to name close alternatives in one line. On the server a choice value
that is not an option's value or label matches the one option whose label contains its words
(with a note the AI repeats); several such options are an error naming them, for the AI to
choose.

## 5. Settings › AI

A section shown only when the install has an AI provider (`#ai`). Card "AI": "“Ask your
submissions” answers questions by counting this form’s submissions and can list answers for
you. Anyone who can see the submissions can ask."

Switch **Allow AI to read answers** (off by default for every form, owners only) with the
description: off "Off: the AI service only gets the questions, counts and numbers, never the
answers. Lists of answers you ask for are still shown to you." / on "On: answers, including
contact details and fields marked sensitive, are sent to the AI service when someone asks a
question." and always "Files, signatures and respondents’ IP addresses are never sent."

Turning it on asks first (`AlertDialog`): "Send answers to the AI service?" / "Answers,
including contact details and fields marked sensitive, are sent to the AI service when
someone asks a question (up to 500 submissions per question). Files, signatures and IP
addresses are never sent. You can turn this off at any time." Buttons "Cancel", "Allow AI to
read answers". Turning it off is immediate. Toasts: "AI can read answers" / "AI no longer
reads answers". The provider is never named (no product names anywhere in the studio).

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
