# Studio header and form bar on phones

Staff open the studio on a phone to check submissions or fix a typo. Before this change a form
page on a 412px phone spent about a fifth of the screen (a third with the browser's address
bar) on chrome: the app header (logo, help, account), then a form bar of two rows (back and
title with a "Saved" badge; undo/redo, the page switcher, "…" and Publish). Only the app header
was sticky, so on scroll the useful row (where am I, Publish, switch page) scrolled away and the
logo stayed. On a 320px phone the form bar took three rows.

Supersedes the phone notes in PHASE-2-SCREENS 2.3 and 2.11 ("Form bar collapses").

## 1. Breakpoints

| Width | App header | Form bar |
|---|---|---|
| < 640px (phones) | hidden on form pages; shown elsewhere (forms list, organisation settings) | compact, the only bar, sticky at top 0 |
| 640–1023px (tablets) | shown, sticky | compact, sticky under the header |
| >= 1024px | shown, sticky | full (as before, one row), sticky under the header |

Form pages are `/forms/{id}/…` (Edit, Preview, Share, Submissions and a submission's page,
Settings, the responses import); `/forms/import/jotform` is not one.

## 2. Compact form bar (< 1024px)

```
┌────────────────────────────────────────┐
│ ‹  Community sports and youth d…   ✓  ⋮ │  h-14, Sheet bg, border-b
│    Submissions                          │
└────────────────────────────────────────┘
with something to publish:
┌────────────────────────────────────────┐
│ ‹  Venue booking re…   ✓  [Publish]  ⋮ │
│    Edit                                 │
└────────────────────────────────────────┘
```

| Piece | Component | Notes |
|---|---|---|
| Back | `Button variant="ghost" size="icon"` + `Link` | "Back to forms" (aria-label) |
| Title over page name | text | title truncates (`bdi dir="auto"`, form language); the second line is the current page ("Submissions") |
| Save state | icon in a `role="status"` region | check (Saved), `Spinner` (Saving…), cloud-off (Offline…); words as sr-only text and hover title. Error: a destructive ghost icon `Button` "Couldn't save. Retry" that retries |
| Publish | `Button size="sm"` (primary) | only while there is something to publish (draft differs, or never published) |
| Menu | `DropdownMenu`, trigger "Form menu" (vertical ellipsis) | see below |

Menu: label "Go to", then `DropdownMenuRadioGroup` with Edit / Preview / Share / Submissions /
Settings (icons; current one checked; viewers see Share, Submissions, Settings); separator;
Undo, Redo (the menu stays open so they repeat; disabled with "Apply or discard the suggestion
first" while an AI suggestion is shown); AI assistant (when on); View all logic; when there is
nothing to publish, a disabled "Publish" with "No changes since version N".

The title is not click-to-rename here; the title block on the canvas is editable.

On phones there is no account menu on form pages: Back leads to the forms list, which has it.

## 3. Sticky behaviour

- The app header and the form bar publish their heights as `--app-bar-h` and `--form-bar-h`
  on `<html>` (`useHeightVar`, ResizeObserver; 0 when hidden). `--studio-top` is their sum.
- The form bar is `sticky; top: var(--app-bar-h)`, z-20 under the header's z-30, solid
  `bg-card` (nothing shows through). No hide-on-scroll: one 56px bar does not need it, and
  nothing moves while reading (no motion to reduce).
- Side panels that stick (submission page Details/Activity, settings section nav, theme and
  sharing previews) use `top: calc(var(--studio-top) + 1rem)` (the submission panel:
  `top: var(--studio-top)`, `max-height: calc(100dvh - var(--studio-top))`).
- `html { scroll-padding-top: calc(var(--studio-top) + 0.5rem) }`: focusing a control or
  scrolling to an anchor never leaves it under the bars (WCAG 2.4.11).
- The builder keeps its full-height layout: `height: calc(100dvh - var(--app-bar-h))`, the
  form bar on top (not sticky there), the canvas scrolls inside. `dvh` follows the phone's
  address bar.

## 4. Submissions page header on phones

```
Submissions                [Export ▾] [⋯]
In review 0 · Approved 13 · Rejected 0 · All 40     (tabs scroll sideways)
[🔍 Search answers            ] [≡] [📅]
```

- "Import responses" and "Check a PDF" move into a "More submission actions" `DropdownMenu`
  (outline icon button) next to Export; Export stays primary. From 640px all three are
  buttons, as before.
- The filter row is one line: search grows to fill, Filter and the date range are icon buttons
  (their words stay as the accessible name). A chosen date range shows its words again. The
  `/` shortcut hint is hidden on touch screens.

## 5. Accessibility

- Every bar control is at least 44x44px on touch (`pointer: coarse` rules in `index.css`).
- One `nav aria-label="Form"` in either layout (the hidden one is `display: none`).
- Menus are Radix: arrow keys, Home/End, typeahead, Esc returns focus to the trigger. Dialogs
  opened from a menu (View all logic, Check a PDF) return focus to the menu's trigger.
- Visible focus ring on every control (shadcn defaults).

## 6. Checks

`just mobile-audit` swipes each form page with a touch gesture and fails (`sticky`) when the
form bar is not right under the app header (top 0 on phones), when the page did not scroll,
or when a keyboard-focused control ends up under the bar.

## 7. Self-critique

- First idea: hide the app header on scroll-down and show it on scroll-up. Dropped: two bars
  that move independently are what made scrolling feel broken, and it adds motion. On form
  pages a phone needs the form's context, not the logo.
- Undo/redo as icon buttons in the bar: dropped for width (320px leaves ~120px for the title);
  undo on a phone is rare and stays two taps away, with the menu kept open for repeats.
- The page switcher as its own "Submissions ▾" button: dropped; the page name now sits under
  the title, and switching lives in the one menu.
