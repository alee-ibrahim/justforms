# Phase 2 UI review

Reviewer: UI/UX agent (review mode, `.claude/agents/ui-ux.md`). Date: 2026-10-23.
Scope: builder, preview, share, public renderer (en and dv), submissions, forms list.
Sources: [REVIEW-CHECKLIST.md](../REVIEW-CHECKLIST.md), [DESIGN-SYSTEM.md](../DESIGN-SYSTEM.md),
[PHASE-2-SCREENS.md](../PHASE-2-SCREENS.md).

## How this review was done

- **Screenshots.** The 126-shot set from the build (light and dark; 390×844, 768×1024,
  1440×900; en and dv; 320px at 2× for zoom) was read image by image. After the fixes, the set
  was re-shot with the same script, plus extra shots for the items the first set did not cover
  (collapsed section, half-width drag handle, keyboard focus and keyboard drag, never-published
  submissions, studio at 200% zoom, dv form at 320px). Screenshots live outside the repo.
- **Contrast audit.** Every token pair in `index.css` (`:root` and `.dark`) was computed with
  the WCAG 2.1 relative-luminance formula from the oklch values, including alpha-blended
  states (dark input fill, `ring/50` focus ring, disabled buttons). Results below.
- **Reflow.** Public form at 320px wide (en, dv, the every-question-type form); studio pages
  (forms list, builder, preview, share, submissions) at 640×450 CSS px, which is 1280×900 at
  200% zoom; builder and submissions also at 320px. Horizontal overflow was measured, not
  eyeballed.
- **Keyboard.** Playwright drove Tab order on the builder (from the top of the page) and the
  public form; error-summary focus and links; page-change focus; canvas arrow keys, Enter, Esc,
  Alt+↓; keyboard drag and drop on a drag handle (Space, arrows, Space; and Esc to cancel) with
  the dnd-kit live region read after each step; focus return when sheets, dialogs and menus
  close.
- **Code.** Diff skim for hard rules: `components/ui/` only ever gained files (CLI output, no
  edits), no physical direction classes outside `components/ui/` (lint script passes), no
  hard-coded colours in feature code, no deploying-organisation references.

## Contrast audit (theme tokens)

Light / dark. "Need" is 4.5 for text, 3 for non-text (WCAG 1.4.3, 1.4.11).

| Pair | Light | Dark | Need | Result |
|---|---|---|---|---|
| Ink on Desk / on Sheet | 14.75 / 16.09 | 14.66 / 13.20 | 4.5 | pass |
| Muted text on Sheet / Desk | 5.96 / 5.46 | 6.93 / 7.70 | 4.5 | pass |
| Muted text on secondary (tab list, count badges) | 4.91 | 5.95 | 4.5 | pass |
| Muted text on marker wash (help text in a selected block) | 5.44 | 5.12 | 4.5 | pass |
| Carbon link on Sheet; primary button text | 7.86; 7.86 | 6.91; 7.68 | 4.5 | pass |
| Carbon on marker wash | 7.18 | 5.11 | 4.5 | pass |
| Stamp on Sheet / Desk | 5.53 / 5.07 | 7.00 / 7.77 | 4.5 | pass |
| Ink on marker wash | 14.70 | 9.75 | 4.5 | pass |
| Placeholder (muted) on dark input fill | n/a | 4.91 | 4.5 | pass |
| Input outline on Sheet | 3.26 → **3.44** | 3.44 | 3 | pass |
| Input outline on Desk | **2.99 → 3.16** | 3.82 | 3 | **failed, fixed** (P2-10) |
| Marker edge bar on Sheet / on wash | 4.55 / 4.16 | 10.58 / 7.81 | 3 | pass |
| Carbon (progress fill, drop line) on Desk | 7.21 | 7.68 | 3 | pass |
| Toggle "on" fill (`bg-muted`) vs Sheet | **1.09** | **1.09** | 3 | **failed, fixed** (P1-1) |
| Focus ring `ring/50` (3px) over Sheet | 2.48 | 2.78 | (3) | AA has no focus-contrast minimum in 2.1; see P3-1 |
| Marker wash vs Sheet | 1.09 | 1.35 | n/a | by design: the 3px marker edge carries selection (4.55:1) |
| Progress track vs Sheet | 1.21 | 1.16 | n/a | the carbon fill carries progress (7.2:1 against the track) |

## Findings

Format: `[P] screen @ viewport, mode, language: what is wrong. Expected. Fix.` Each has the
before screenshot (`screenshots/`) and, where re-shot, the after (`screenshots-after-review/`),
both under the review work directory. Status: **Fixed** or **Backlog**.

### P1 (block merge)

**P1-1. Toggle groups and toggles have no visible "on" state.** Builder inspector ("Show as",
"Typing", "Accepted files", "Width"), preview device switch (Phone / Desktop), and the "ތ / A"
phonetic toggle on dv inputs (studio and public form) @ all viewports, light and dark, en and
dv. The generated Toggle marks "on" with `bg-muted` (Desk on Sheet, 1.09:1), so nobody can
tell which option is chosen or whether the Thaana keyboard is on.
Expected: state indicators ≥ 3:1 (checklist H), status never by a near-invisible tint (B).
Fix: `src/lib/toggle.ts` exports call-site classes (`toggleGroupOn` on the `ToggleGroup`,
`toggleOn` on a single `Toggle`) that add a carbon edge (7.9:1) and carbon-tint fill; the
public rating control already used carbon fill and is unchanged. `components/ui/` untouched.
Before: `builder-selected-inspector-desktop-light.png`, `preview-phone-desktop-dark.png`,
`public-phonetic-dv-phone-dark.png`. After: same names, plus
`builder-advanced-toggles-desktop-*.png`. **Fixed.**

**P1-2. Focus is dropped to `<body>` when a sheet closes.** Builder "All logic" sheet (opened
from the ⋯ form menu) and the submission detail sheet @ desktop, both modes. Radix returns
focus to the element focused before opening: a menu item that no longer exists, or a table
row the sheet then re-rendered. Keyboard users land at the top of the page.
Expected: focus returns to the trigger when sheets close (checklist H).
Fix: `logic-overview.tsx` takes a `returnFocus` ref (the ⋯ trigger, from `form-bar.tsx`) and
uses `onCloseAutoFocus`; after "Edit" it moves focus to the inspector's Logic group instead.
`detail-sheet.tsx` focuses the row (desktop) or list item (phone) of the submission that was
open last, so Prev/Next are respected (`data-submission` on both). Verified with Playwright.
**Fixed.**

**P1-3. Enter on a submissions row opens the wrong submission.** Submissions table @ desktop.
The row's Enter handler opened the sheet, focus moved into it, and the same keypress then
activated the sheet's first button (Next), so Enter on #4 showed #3. Status changes made from
there would hit the wrong record (data-loss risk).
Expected: Enter opens the focused row (PHASE-2-SCREENS 5.2).
Fix: `form-submissions.tsx` row `onKeyDown` calls `preventDefault()` before opening.
Verified: Enter on #4 now shows #0004. **Fixed.**

### P2 (fix before release)

**P2-1. Org name in a dv form renders in a serif face.** Public form @ phone and desktop,
light and dark, dv ("Example Youth Office" above the title). The element is correctly
`lang="en"`, but it inherits the Thaana-first stack from the dv root and falls through to
Faruma's serif Latin glyphs.
Expected: Latin text is Atkinson Hyperlegible Next (checklist C; DESIGN-SYSTEM 4.1).
Fix: `index.css` adds `:lang(dv) [lang='en']` (and descendants) to the existing Latin-face
rule. Before: `public-page1-dv-phone-light.png`. After: same name. **Fixed.**

**P2-2. dv form scrolls sideways by 1px at 320px.** Public form @ 320px, dv. The `sr-only`
live region has no inline anchor, so in RTL its static position is past the right edge.
Expected: no horizontal scroll at 320px (checklist D).
Fix: `form-view.tsx` live region gets `start-0 top-0`. Measured scrollWidth 321 → 320.
After: `public-dv-320-zoom-*.png`. **Fixed.**

**P2-3. Error summary repeats identical links.** Public form @ all, en and dv. en: "Choose an
option" twice; dv: "މި ސުވާލަށް ޖަވާބު ދެއްވާ" four times. Links that read the same do not say
which question they jump to.
Expected: summary links that identify the problem (PHASE-2-SCREENS 4.6; checklist I).
Fix: when a message does not already name the question, the summary link reads
"{label}: {message}" (new `summaryItem` message in en and dv, dv draft like the rest). Inline
errors under labels are unchanged. Before: `public-errors-en-desktop-light.png`,
`public-errors-dv-phone-dark.png`. **Fixed.**

**P2-4. "Add page" is clipped with four pages.** Builder page strip @ desktop and tablet. The
button sat inside the chip scroll area and was cut to "+ /" at the sheet edge; the scrollbar
only shows on hover, so the action looked missing.
Expected: "Add page" always available (PHASE-2-SCREENS 2.6).
Fix: `page-strip.tsx` keeps the chips in the `ScrollArea` and puts "Add page" after it,
outside the scroll. Before: `builder-every-type-desktop-light.png`. After: same name. **Fixed.**

**P2-5. Half-width block's drag handle covers its neighbour.** Builder canvas @ desktop. The
handle sits 36px before the block's start edge, which for the second half-width block is on
top of the first block's input.
Expected: handle at the start edge, outside content (PHASE-2-SCREENS 2.5) without covering
other blocks.
Fix: `canvas.tsx` puts a half-width block's handle on its top edge at the start (mirroring the
actions button at the end), with a card background. After: `builder-half-handle-desktop-*.png`.
**Fixed.**

**P2-6. Sections cannot collapse on the canvas.** Builder @ all.
Expected: sections collapsible via `Collapsible`, chevron at the start (PHASE-2-SCREENS 2.5).
Fix: `canvas.tsx` wraps sections in the official `Collapsible`; an icon button with tooltip
("Collapse section" / "Expand section") sits before the title, the chevron turns toward the
inline end when closed (mirrored in RTL), and a collapsed section says how many questions it
hides. After: `builder-section-collapsed-desktop-*.png`. **Fixed.**

**P2-7. Keyboard drag announcements give the wrong position.** Builder, keyboard drag.
Moving "Full name" down one place: "will move to position 1 of 17" then "moved to position 3"
while it actually landed at 2. The "over" message used the previous slot (stale state) and
neither message allowed for the block leaving its old place.
Expected: exact copy and correct numbers (PHASE-2-SCREENS 2.5; checklist H).
Fix: `dnd.tsx` works out the slot in the announcement from the `over` event, and a
`landing()` helper corrects the index and total for moves within one list. Refused drops say
"{label} can't go there. Nothing moved."; drops on a page chip say where it went.
Verified: "will move to position 2 of 16" → "moved to position 2". Keyboard drag itself works
(Space, arrows, Space; Esc cancels and restores). **Fixed.**

**P2-8. "Add a jump" copy.** Builder inspector, page logic.
Expected: glossary says "After this page, go to…", never "jump" (PHASE-2-SCREENS 7).
Fix: "Add a rule" under the "After this page" heading; icon button "Remove rule"; delete
dialog lists "after-this-page rule". **Fixed.** Spec note: §2.6 still asks for the chip
tooltip "Has jump rules"; proposed edit below.

**P2-9. Icon-only buttons without tooltips.** Builder: option reorder and remove, inspector
page and question ⋯ menus, page chip ⋯, remove-rule, outline show/hide chevrons; forms list
row ⋯.
Expected: every studio icon-only button has a `Tooltip` matching its `aria-label`
(DESIGN-SYSTEM 7).
Fix: wrapped in the official `Tooltip`; the disabled "Remove option" explains why ("A question
needs at least one option"). **Fixed.**

**P2-10. Input outline below 3:1 on the desk.** Light mode, inputs that sit on Desk rather than
a sheet (submissions search, palette search, share inputs on phones): 2.99:1.
Expected: input boundaries ≥ 3:1 (DESIGN-SYSTEM 3.1, checklist H).
Fix: `--input` light `oklch(0.649 …)` → `oklch(0.635 0.037 272.5)` (3.44 on Sheet, 3.16 on
Desk); DESIGN-SYSTEM 3.1/3.2 updated. **Fixed.**

### P3 (backlog)

- **P3-1.** Focus ring is `ring/50` (2.48:1 light, 2.78:1 dark over Sheet). Passes WCAG 2.1 AA
  (no focus-contrast minimum) but not 2.2's focus-appearance guidance. Consider `--ring` at
  full strength via a theme change, not component edits.
- **P3-2.** Keyboard drag moves 25px per arrow press (dnd-kit default), so passing a tall
  question takes several presses. Add a `coordinateGetter` that snaps to the next block.
- **P3-3.** No sibling-shift animation while dragging. The builder uses `@dnd-kit/core` with
  the drop line, not sortable lists, so the drop line carries position. Proposed spec edit to
  DESIGN-SYSTEM 8: "the drop line shows where the block lands; siblings do not shift".
- **P3-4.** Radio and checkbox marks in choice cards sit about 3px above the label's optical
  centre (`public-choices-en-phone-light.png`).
- **P3-5.** On error, `FieldLabel` turns stamp but `FieldLegend` (choice questions) stays ink,
  so errored questions look inconsistent (`public-errors-en-desktop-light.png`).
- **P3-6.** Enter on a canvas block moves focus to the inspector's Label input (works) but the
  spec's polite "Editing {label}" announcement is missing.
- **P3-7.** Submissions status tabs on phones scroll with the first tab cut ("n review") and no
  edge cue (`submissions-phone-phone-light.png`).
- **P3-8.** Phone answers show as "+9607771234"; empty table cells show "-" while the detail
  sheet says "No answer". Format phones with a space after the country code and use one empty
  marker.
- **P3-9.** Forms list shows a Version column; PHASE-2-SCREENS 6 asks for Submissions (new
  count). **Fixed in Phase 3** (new count badge plus total, links to Submissions).
- **P3-10.** Closed and not-found screens on phones: the sheet ends after the text and the desk
  fills the rest of the screen (`public-closed-phone-light.png`). Let the sheet fill the
  viewport height on phones.
- **P3-11.** Builder at 768px: the canvas sheet is about 380px wide, narrower than the 40rem
  respondent sheet, so it is not WYSIWYG at tablet width (it does match the phone layout).
- **P3-12.** Font-loading layout shift and the network waterfall for lazy chunks were not
  measured in this pass (bundle size was).

## Proposed spec edits

- PHASE-2-SCREENS 2.6: chip tooltip "Has jump rules" → "Goes to another page after this one",
  to match the glossary.
- DESIGN-SYSTEM 8: replace "siblings shift with dnd-kit's sortable transition" with "the drop
  line shows where the block lands; siblings do not shift" (P3-3).
- DESIGN-SYSTEM 3.1: input outline values updated with this review (done).

## Checklist verdict (after fixes)

| Section | Verdict | Notes |
|---|---|---|
| A. Hard rules | Pass | `components/ui/` only CLI-added files; lint and logical-class script pass; dv RTL from the form root; studio chrome LTR English |
| B. Tokens and identity | Pass | toggle states fixed (P1-1); marker only as wash + edge; stamp only for errors/destructive/Rejected; status badges icon + word |
| C. Typography | Pass | org-name face fixed (P2-1); Thaana scale via `:lang(dv)` variables; `bdi` on step counter and "ތ / A" |
| D. Layout and density | Pass | 320px dv overflow fixed (P2-2); studio reflows at 200%; half-width pairs stack on phones |
| E. Components | Pass | tooltips added (P2-9); Collapsible sections (P2-6) |
| F. States | Pass | save states, publish problems, upload Retry, submit failure, closed/not found, submissions empty states present |
| G. Interaction and motion | Pass with backlog | keyboard and pointer DnD verified; P3-2, P3-3 |
| H. Accessibility | Pass with backlog | P1-2, P1-3, P2-7 fixed; focus ring strength P3-1 |
| I. Copy | Pass | "jump" removed (P2-8); summary links name questions (P2-3) |
| J. Performance | Pass | public bundle 118.5 KB gzip (budget 120; was 118.4) |

Counts: **P1 3** (all fixed), **P2 10** (all fixed), **P3 12** (backlog).

## Before and after

Both sets sit in the review work directory, outside the repo: `screenshots/` (before, 126
shots) and `screenshots-after-review/` (the same 126 re-shot with the same script, plus 22
extra shots).

| Finding | Before | After |
|---|---|---|
| P1-1 toggle state | "Buttons" / "Dropdown" look the same; Phone / Desktop look the same; "ތ / A" looks the same on and off | Chosen option has a carbon edge and tint in both modes (`builder-selected-inspector-*`, `preview-phone-*`, `public-phonetic-dv-*`) |
| P1-2 focus return | Esc on "All logic" or the submission sheet left focus on `<body>` | Focus lands on the ⋯ form menu / the submission's row (Playwright check) |
| P1-3 row Enter | Enter on #4 opened #0003 | Enter on #4 opens #0004 (Playwright check) |
| P2-1 org name face | "Example Youth Office" in a serif face in dv | Atkinson Hyperlegible Next (`public-page1-dv-*`, `public-phonetic-dv-*`) |
| P2-2 dv at 320px | scrollWidth 321 | 320 (`public-dv-320-zoom-*`) |
| P2-3 error summary | dv: four identical "answer this question" links | Each link starts with its question label (`public-errors-dv-*`, `public-errors-en-*`) |
| P2-4 Add page | "+ /" cut off at the sheet edge with 4 pages | "Add page" always visible after the chips (`builder-every-type-*`, `builder-zoom200-zoom-*`) |
| P2-5 half-width handle | grip over the email input | grip on the phone question's top edge (`builder-half-handle-*`) |
| P2-6 sections | always open | chevron collapses; "2 questions hidden while collapsed" (`builder-section-collapsed-*`) |
| P2-7 drag announcements | "position 1 of 17" then "moved to position 3" | "position 2 of 16" then "moved to position 2" (`builder-keyboard-drag-*` shows the drag) |
| P2-8 to P2-10 | copy, tooltips, input outline | as described above; visible in the re-shot builder and submissions screens |

Checks after the fixes: frontend `pnpm lint`, `pnpm typecheck`, `pnpm test` (227 passed),
`pnpm build`, `pnpm check:bundle` (118.5 KB gzip of 120); backend `ruff check`,
`ruff format --check`, `mypy` (no issues), `pytest` (321 passed). Pointer drag and drop
regression (palette drop, reorder, drop into a repeater, nested repeater refused, undo) passes.
