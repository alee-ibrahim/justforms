# AI assistant screens

Screens for the AI assistant in the builder (DESIGN §12): describe a form and get a draft,
change a form by chatting, and recreate a **blank** paper form from a PDF or photo. Tokens,
type and motion come from [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with
[REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md). Conventions are the same as in
[PHASE-2-SCREENS.md](PHASE-2-SCREENS.md): copy in "quotes" ships as written, studio copy is
English only, and form content (labels, options, titles the AI writes) follows the **form's
language** with `contentProps`.

Nothing new needs adding from shadcn: `input-group` (with `InputGroupTextarea`), `button`,
`tooltip`, `alert`, `item`, `badge`, `empty`, `spinner`, `scroll-area`, `toggle-group`,
`dialog`, `checkbox`, `field`, `input`, `drawer` and `sonner` are installed.

## 0. Rules the screens enforce

- **Nothing changes the draft until Apply.** The AI's work is a *suggestion*. The canvas
  shows it as a preview; the draft, autosave and undo history are untouched until the person
  presses "Apply changes". Apply is one entry in the draft history, so one Undo reverts it.
- **Hidden when off.** With no provider configured (`features.ai = false` in `/meta`) there
  is no button, no empty-state hint, no menu item and no shortcut. Viewers never see it (they
  have no builder). The paper entry point is hidden when the model can't read images
  (`features.aiVision = false`).
- **Only the form goes to the provider.** The panel says so once, in its footer: "The AI sees
  this form's questions, never its responses." Submissions never leave the server.
- **Blank paper forms only.** The upload dialog says that pages are sent to the provider, and
  "Read the form" stays disabled until the person ticks "This form is blank".
- **Dhivehi is a draft.** On a `dv` form every suggestion carries "Check the Dhivehi wording
  before you publish." (Alert, not destructive).

## 1. Entry points

| Where | What | When |
|---|---|---|
| Form bar, before Undo/Redo | `Button variant="outline" size="sm"` with `SparklesIcon` and "Edit with AI" (on Submissions pages the same place holds "Ask about submissions", INSIGHTS-SCREENS 4.1). `aria-pressed` while the panel is open. Below `xl` it is icon-only with a `Tooltip` "Change this form with the AI assistant". | editors and owners, `features.ai` |
| Empty canvas (`Empty` "No questions on this page yet") | Second action next to "Add question": `Button variant="outline"` "Describe your form" | first page empty, `features.ai` |
| Panel empty state | "Start from a paper form" (`FileScanIcon`) | `features.aiVision` |

Shortcut: none (the builder already uses `/` and `?`). The panel is reached by Tab from the
form bar.

## 2. Panel placement

### 2.1 Desktop and tablet (≥ 768px)

The AI panel takes the inspector's pane (same `ResizablePanel`, same width, `border-s`), so
the canvas never shrinks further. Closing it brings the inspector back with the same
selection. Selecting a question on the canvas while the panel is open does not close it.

```
┌ Forms / Volunteer sign-up   ✓ Saved     [✦ Edit with AI] [↶][↷]  Edit Preview …  [Publish] ┐
├────────────┬───────────────────────────────────────────┬──────────────────────────────────┤
│ Palette    │ ┌ Suggestion ─────────────────────────┐   │ AI assistant               [✕]   │
│ (inert     │ │ ⓘ Showing the AI's suggestion.      │   │ ──────────────────────────────── │
│ while a    │ │   Changed questions are marked.     │   │ You  Add a phone number question │
│ suggestion │ │            [Suggestion|Current form]│   │      after email and make it     │
│ is shown)  │ └─────────────────────────────────────┘   │      required                    │
│            │  Page strip                               │ ✓ Added "Phone number"           │
│            │  ┌ sheet ─────────────────────────────┐   │ ✓ Moved "Phone number"           │
│            │  │ Volunteer sign-up                  │   │ AI   I added a required phone    │
│            │  │ Full name   [______________]       │   │      question after Email.       │
│            │  │ Email       [______________]       │   │ ┌ Suggested changes ──────────┐  │
│            │  │▌Phone number [_____________] ←wash │   │ │ + Phone number  Added        │  │
│            │  │ Availability ( ) ( )               │   │ │ [Apply changes] [Discard]   │  │
│            │  └────────────────────────────────────┘   │ └─────────────────────────────┘  │
│            │                                           │ ┌──────────────────────────────┐ │
│            │                                           │ │ Ask for a change…            │ │
│            │                                           │ │                     [Send ↑] │ │
│            │                                           │ └──────────────────────────────┘ │
│            │                                           │ The AI sees this form's          │
│            │                                           │ questions, never its responses.  │
└────────────┴───────────────────────────────────────────┴──────────────────────────────────┘
```

### 2.2 Phones (< 768px)

The panel is a `Drawer` (bottom, `max-h-[85vh]`). When a suggestion arrives the drawer shows
it with "Preview on the form"; that closes the drawer and the canvas shows the suggestion,
with a sticky bottom bar (sheet colour, hairline top border, safe-area padding):

```
┌──────────────────────────────┐
│ ‹ Volunteer sign-up   [✦]    │
│ ⓘ Showing the AI's suggestion│
│ ┌ sheet ───────────────────┐ │
│ │▌Phone number [_________] │ │
│ └──────────────────────────┘ │
├──────────────────────────────┤
│ [Discard] [Back to chat] [Apply changes] │
└──────────────────────────────┘
```

## 3. Panel anatomy

Header: `h2` "AI assistant" (`text-base font-medium`), close icon button "Close AI assistant"
(`XIcon`, Tooltip). On phones the drawer title is the same text.

### 3.1 Empty state (no messages yet)

`Empty` inside the panel, no icon art:

- Empty draft: title "Describe your form", description "Say who fills it in and what you
  need to know. The AI drafts the questions; you check them before anything changes."
  Example prompts as `Button variant="outline" size="sm"` (they fill the composer, they
  don't send): "A volunteer sign-up form with name, phone and availability", "A leave
  request with dates, reason and a manager's email", "An event feedback form with a 1 to 5
  rating".
- Draft with questions: title "Ask for a change", description "For example: add a phone
  question after email, or show page 2 only to people who answered Yes." Examples: "Add a
  phone number question", "Make every question on page 1 required", "Split this into two
  pages".
- Then, when `features.aiVision`: `Button variant="outline"` "Start from a paper form"
  (`FileScanIcon`) with the muted line "Upload a blank PDF or photo; the AI recreates the
  questions."
- On a `dv` form: muted line "This form is in Dhivehi. The AI writes in Dhivehi; check the
  wording before you publish."

### 3.2 Transcript

`ScrollArea` with `role="log"` and `aria-live="polite"`; it sticks to the bottom while new
content arrives unless the person has scrolled up.

- **Person's message.** Start-aligned block, `bg-secondary rounded-lg px-3 py-2 text-sm`,
  `whitespace-pre-wrap`, preceded by the visually hidden "You said". It may contain Thaana:
  `dir="auto"`.
- **Tool steps.** `ItemGroup` of `Item size="sm"` without borders: `CheckIcon` (muted) and
  a plain sentence per tool call, e.g. "Added "Phone number"", "Changed "Email"", "Moved
  "Phone number"", "Removed "Fax"", "Added page 2", "Set "Show this question when…" on
  "Spouse's name"", "Flagged "Date of birth": the box was hard to read". Question labels are
  `bdi` with the form's `lang`. A step the server rejected shows `RotateCcwIcon` and "Fixed a
  problem: {short reason}" in muted text; the AI retries on its own, so it is not an error.
- **AI reply.** Plain text block (no bubble), `text-sm`, `dir="auto"`.
- **Working.** While streaming: `Spinner` + "Working on it…" as the last row, and the
  composer's Send button becomes "Stop" (`SquareIcon`, outline). Stop cancels the turn; the
  row becomes muted "Stopped. Nothing from this request was kept."
- **Errors.** `Alert variant="destructive"` in the transcript, with the next step:
  - provider down / timeout: "The AI service didn't answer. Try again in a minute." +
    `Button size="sm" variant="outline"` "Try again" (resends the last message);
  - too many requests (429 `too_many_requests`): "You've sent a lot of requests. Try again in
    {n} minutes.";
  - daily allowance used (429 `ai_budget_exceeded`): "You've used today's AI allowance. It
    resets tomorrow.";
  - no valid suggestion after the tool limit: "The AI couldn't finish this change. Try a
    smaller request, like one page at a time.";
  - form too large (413 `form_too_large`): "This form is too large for the AI assistant.
    Edit it by hand, or split it into smaller forms.";
  - message too long: the composer shows `FieldError` "Keep requests under 4,000
    characters." and Send is disabled.

### 3.3 Suggestion card

Appears after the AI's reply whenever the session has a suggestion. Bordered block
(`rounded-md border p-3`, no shadow), heading "Suggested changes" (`text-sm font-medium`):

- Change list (`ItemGroup`, `Item size="sm"`): one row per changed question or page, with a
  `Badge` that has an icon **and** a word: `Added` (`PlusIcon`, secondary), `Changed`
  (`PencilIcon`, outline), `Removed` (`MinusIcon`, outline with `text-destructive` icon),
  `Moved` (`MoveIcon`, outline). Labels in the form's language (`bdi`). Clicking a row on
  desktop shows that page of the suggestion and selects the question (the canvas scrolls it
  into view). Settings changes read "Form title and settings" `Changed`.
- Flags from the paper import (and the language check) under the list as one `Alert`
  (`TriangleAlertIcon`, not destructive): title "Check these", list "{label}: {note}".
- On `dv` forms: `Alert` "Check the Dhivehi wording before you publish. The AI's Dhivehi is
  a draft." (`LanguagesIcon`).
- Actions: primary "Apply changes", ghost "Discard". On phones also "Preview on the form".
  While applying: Spinner in the button, "Applying…".
- After Apply: the card collapses to the muted line "Applied." The canvas leaves preview
  mode; toast "Changes applied" with action "Undo" (calls the builder undo). The marker
  wash stays on the changed questions until the next click on the canvas.
- After Discard: muted line "Discarded." Toast none (nothing happened to the draft).
- Apply conflict (409 `proposal_stale`, the form changed in the same places since):
  `Alert` "The form changed while the AI was working, in the same places. Ask again to get a
  fresh suggestion." + "Ask again" (resends the last message from the current draft).

A follow-up message while a suggestion is pending refines that suggestion (the AI keeps
working on it); the card updates in place and still needs one Apply.

### 3.4 Composer

`InputGroup` with `InputGroupTextarea` (2–8 rows, autosize, placeholder "Describe your form…"
on an empty draft, "Ask for a change…" otherwise, `dir="auto"`, phonetic Thaana keyboard
**off**: people write requests in either script with their own keyboard) and an
`InputGroupAddon align="block-end"` holding `InputGroupButton` "Send" (`ArrowUpIcon`,
`size="icon-sm"`, Tooltip "Send (Enter)"). Enter sends, Shift+Enter is a new line. Disabled
with the reason in the tooltip while a request runs ("Wait for the AI to finish, or stop
it") or while the builder can't save ("Reconnect to save your changes first").

Footer line (muted `text-xs`): "The AI sees this form's questions, never its responses.
Nothing changes until you apply it." When a suggestion is shown on the canvas, also a
`ToggleGroup` on the canvas (not the panel) "Suggestion" / "Current form".

## 4. Canvas while a suggestion is shown

- An `Alert` above the page strip (`InfoIcon`): "Showing the AI's suggestion. Changed
  questions are marked. Apply or discard it to keep editing." with the `ToggleGroup`
  ("Suggestion" | "Current form", `variant="outline" size="sm"`) at its end.
- The canvas renders the suggested form with the same canvas components (WYSIWYG). Added and
  changed questions get the marker wash and marker edge (the existing selection look,
  DESIGN-SYSTEM §5); pages switch in the page strip as usual. Nothing can be edited: the
  palette pane is `inert`, inline editing, drag and drop, menus and Undo/Redo are off.
  Undo/Redo buttons show the tooltip "Apply or discard the suggestion first".
- "Current form" shows the real draft, still read-only, so the person can compare.
- Removed questions don't appear in the suggestion; they are listed as `Removed` in the
  suggestion card.

## 5. Start from a paper form

`Dialog` (max-w-lg), opened from the panel.

```
┌ Start from a paper form ───────────────────────────────── [✕] ┐
│ The AI reads the questions on a blank form and recreates them  │
│ here. You check the result before anything changes.            │
│                                                                │
│ ⓘ Only upload blank forms                                      │
│   The pages are sent to Google Gemini to read them. Never      │
│   upload a form someone has filled in: their answers would be  │
│   sent too.                                                    │
│                                                                │
│ File  [Choose file] blank-leave-form.pdf (2 pages, 1.2 MB)     │
│       PDF, JPG, PNG or WebP, up to 20 MB and 10 pages.         │
│                                                                │
│ [■] This form is blank. It has no one's answers, names or      │
│     signatures on it.                                          │
│                                                                │
│                               [Cancel]  [Read the form]        │
└────────────────────────────────────────────────────────────────┘
```

- `DialogTitle` "Start from a paper form"; `DialogDescription` as above.
- `Alert` (`ShieldAlertIcon`, default variant, not destructive: it's guidance, not an
  error), title "Only upload blank forms", text "The pages are sent to {provider} to read
  them. Never upload a form someone has filled in: their answers would be sent too."
  `{provider}` is `features.aiProviderLabel` ("Google Gemini", "Anthropic Claude", or the
  operator's label for an OpenAI-compatible service).
- `Field` "File": `Input type="file" accept=".pdf,image/jpeg,image/png,image/webp"`, with
  `FieldDescription` "PDF, JPG, PNG or WebP, up to 20 MB and 10 pages." Errors
  (`FieldError`): "Choose a PDF, JPG, PNG or WebP file.", "This file is larger than 20 MB.
  Scan it at a lower resolution."
- `Field orientation="horizontal"` with `Checkbox` "This form is blank. It has no one's
  answers, names or signatures on it." Required: unticked when the dialog opens, **every
  time**, and reset when a new file is chosen.
- "Read the form" (primary) is disabled until a file is chosen and the box is ticked; the
  reason shows as `FieldDescription` under the checkbox while it is unticked: "Tick this to
  confirm the form is blank." "Cancel" (outline).
- After "Read the form" the dialog closes and the transcript shows the person's turn as
  "Read blank-leave-form.pdf (2 pages)" (`FileScanIcon`), then the usual steps, reply and
  suggestion card. Flagged items show in "Check these".
- If the AI reports the document is filled in: `Alert` (`TriangleAlertIcon`) "This looks
  like a filled-in form, so nothing was added. Upload a blank copy." No suggestion.
- The file is read in memory for this request and never stored.
- The panel's empty-state button is the only entry point; a draft with questions also offers
  it (the suggestion then adds pages to the end of the form).

## 6. States summary

| State | Panel | Canvas |
|---|---|---|
| AI off (`features.ai` false) | not rendered | normal |
| No messages | Empty (3.1) | normal |
| Working | transcript + "Working on it…", Stop | normal (the draft stays editable while the AI works; the suggestion is based on the draft when it was sent) |
| Suggestion | card (3.3) | suggestion preview (4) |
| Applied | "Applied." | normal, washed changes |
| Error | destructive Alert with next step | normal |
| Offline / can't save | composer disabled with reason | normal |

## 7. Accessibility and keyboard

- The panel is a landmark: `aside aria-label="AI assistant"`. Opening it moves focus to the
  composer; closing returns focus to the form-bar button.
- The transcript is `role="log"`; new AI replies and "Suggested changes" are announced once
  (polite). The working row is `aria-busy` on the log.
- Enter sends, Shift+Enter is a newline, Escape in the composer while working = Stop.
- Every icon-only button has an `aria-label` equal to its Tooltip.
- Badges in the change list are icon + word (never colour alone).
- The upload checkbox is a real `Checkbox` with its label; the disabled "Read the form" has
  its reason in text next to it.

## 8. Self-critique

| First idea | Problem | Changed to |
|---|---|---|
| A floating chat bubble in the corner, like support widgets | Reads as a support chat bolted on; covers the canvas on phones; one more floating layer | The panel takes the inspector's pane: the builder keeps three panes and the AI sits where editing controls already live |
| A diff of JSON in the panel | Builders don't read JSON (DESIGN-SYSTEM §1) | Plain change list with Added/Changed/Removed/Moved badges + the real canvas showing the suggestion with the marker wash |
| Applying each tool call to the draft as it streams, with Undo | Breaks "nothing changes until Apply"; autosave would save half-made forms | A suggestion that previews on the canvas; one Apply, one Undo |
| Sparkle gradients and a purple AI accent | Generated-design tell; Carbon is the only saturated colour | Plain outline button with a Lucide icon; the marker wash is reused for "changed" |
| "I agree" checkbox buried in terms for paper uploads | People tick it without reading | Specific statement about this document ("This form is blank…"), reset every time, with the provider named in the alert above it |
| Chat bubbles for both sides | Two columns of bubbles waste the narrow pane | Only the person's message has a tint; AI replies are plain text, tool steps are compact rows |
