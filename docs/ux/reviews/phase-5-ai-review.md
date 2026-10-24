# AI assistant: UI review

Reviewer: implementer's self-review against [REVIEW-CHECKLIST.md](../REVIEW-CHECKLIST.md) and
[PHASE-5-SCREENS.md](../PHASE-5-SCREENS.md). Date: 2026-10-23.
Scope: the AI assistant button and panel, the empty-canvas entry point, streamed steps and
Stop, the suggestion card and the suggestion preview on the canvas (Suggestion / Current
form), Apply with the Undo toast, Discard, "Start from a paper form" with the blank-only
confirmation, errors, a Dhivehi form, the phone drawer with the sticky suggestion bar, and the
builder with AI turned off.

## How this review was done

Playwright (Chromium) against the API (uvicorn) and the Vite dev server, with the scripted
provider (`JUSTFORMS_AI_PROVIDER=fake`, scenarios per request) so every state could be reached
without a real key: desktop 1440×900 light and dark, tablet 768×1024, phone 390×844; an en
and a dv form. Screenshots live outside the repo. Diff skim: `components/ui/` unchanged
(nothing new was needed), logical classes only (lint), no organisation references, all
assistant text English.

## Findings

### P1 (fixed)

- **P1-1. Panel content overflowed the pane** (desktop, after a few turns). Long replies and
  the suggestion card were cut off at the end edge because the scroll area's inner wrapper
  sized to its content. Fix: the same `[data-slot=scroll-area-viewport]>div` block rule the
  canvas uses (`ai-panel.tsx`).

### P2 (fixed)

- **P2-1. The composer looked disabled whenever Send was** (desktop and phone, empty
  composer). `InputGroup` greys the whole group when any child is `disabled`. Fix: Send uses
  `aria-disabled` (still focusable, its tooltip says why) instead of `disabled`.
- **P2-2. The page heading was washed in the suggestion preview.** The preview store
  selected the page when it opened, so the marker meant "selected" and "changed" at once.
  Fix: nothing is selected when a suggestion opens; only changed questions are washed, with
  the marker edge (DESIGN-SYSTEM §5).
- **P2-3. Latin labels in a dv suggestion used the Thaana fallback face** (change list and
  steps, "Membership type"). Fix: labels shown in the English panel get `lang="dv"` only when
  they contain Thaana (`textLang`).
- **P2-4. `/meta` named a provider while AI was off.** `aiProviderLabel` is now empty when
  no provider is configured.

### P3

- **P3-1.** Drag handles still appear on hover in the read-only suggestion preview; dragging
  does nothing. Hide them in read-only stores later.
- **P3-2.** The "Changes applied" toast sits over the composer for a few seconds on desktop
  (sonner at the end edge, as everywhere else).
- **P3-3.** Latin words inside a Dhivehi form's canvas (an English label the AI wrote) still
  use the Thaana stack's Latin glyphs (same cause as the approvals review P3-2); the language
  flag in the suggestion points them out.

## Checklist verdict

| Section | Verdict | Notes |
|---|---|---|
| A. Hard rules | Pass | Official components only (InputGroup, Item, Badge, Alert, Empty, Dialog, Checkbox, Field, ToggleGroup, Drawer); studio chrome English and LTR on dv forms |
| B. Tokens | Pass | Marker wash + edge only for changed questions; badges are icon + word; dark mode legible |
| C. Typography | Pass after P2-3 | |
| D. Layout | Pass after P1-1 | Panel takes the inspector pane; phone drawer and sticky bar respect the safe area |
| E. Components | Pass | |
| F. States | Pass | Empty, working, suggestion, applied, discarded, stopped, filled-in, errors with a next step, AI off |
| G. Interaction | Pass | Nothing changes before Apply; one Undo reverts; edits and undo locked while a suggestion shows |
| H. Accessibility | Pass | `aside` landmark, `role=log` transcript, icon buttons named like their tooltips, Escape stops |
| I. Copy | Pass | "Apply changes" → "Changes applied"; errors say what to do |
