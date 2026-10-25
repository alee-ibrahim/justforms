# UI review checklist

Used by the UI/UX reviewer on Playwright screenshots (and a short live click-through) of every
UI change. Source of truth: [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md) and
[PHASE-2-SCREENS.md](PHASE-2-SCREENS.md).

## How to review

1. Capture the screen set below in **light and dark**, at **390×844** (phone) and
   **1440×900** (desktop), plus **768×1024** for the builder and submissions. For every
   public-form screen capture an **en** form and a **dv** form.
2. Also capture: keyboard focus on a few controls (Tab through, screenshot with focus
   visible), an error state, an empty state, a loading state (throttle or mock), and the
   page at 200% zoom (phone width 320px).
3. Run the mobile audit (`just mobile-audit <base> <email>`, see `frontend/scripts/mobile-audit.mjs`):
   it drives every screen with real phone emulation (320, 360, 390, 412, 768 and a landscape
   phone, light and dark) and fails on sideways scroll, controls cut off, clipped text, squashed
   forms/cards/dialogs and tap targets under 44px. Every failure is a P1. Look at its
   screenshots too: it cannot judge layout quality.
4. Walk the checklist. Every failed item becomes a finding:
   `[P1|P2|P3] screen @ viewport, mode: what is wrong. Expected: what the spec says (doc §).
   Fix: concrete change (file/component/class/variable).`
   - **P1** blocks merge: broken layout, unreadable text, wrong direction, missing focus,
     accessibility failure, hand-rolled component, org reference, data loss risk.
   - **P2** should fix before release: inconsistency with spec, weak copy, wrong component.
   - **P3** polish.
5. Re-review only the failed items after fixes, with fresh screenshots.

### Screen set

| Area | Screens |
|---|---|
| Builder | empty page; page with every field type; selected field + inspector; section and repeater; logic group open with 2 conditions; logic overview sheet; drag in progress (drop line visible); page strip with 4 pages; insert-question command; save states (saving, offline, error); conflict dialog; publish problems dialog; narrow (768) and phone builder with drawers |
| Preview | phone and desktop toggle; logic trace open |
| Share | unpublished empty; published with versions; copy feedback |
| Public form | page 1 clean; page with error summary; choice cards; multi choice at max; repeater with 2 rows; file upload (uploading, done, error); phonetic toggle on; date; last page; success; closed; not found; submit failed; embed mode; restored progress notice (with version change and skipped files), Start over confirm and cleared |
| Submissions | table with mixed en/dv rows; cards (en and dv, card fields picker); filters open; selection bar; empty states; submission page as the form (en and dv, every question type, skipped questions shown, Details, Activity, file preview, print); imported submission with copied files and a long Jotform id at 320px; reject with reason; phone cards and submission page |
| Form theme | Organisation settings › Form theme with preview (light/dark, phone/desktop, en/dv), adjusted-colour note, image upload errors; form Settings › Appearance with inherited and overridden values; themed public form (en, dv, embed, outline buttons, underlined inputs), approver and verify pages; builder canvas in the form's theme; account menu Appearance (light, dark, match device) |
| Branding | Organisation settings with preview (light/dark, phone/desktop), adjusted-colour note, upload errors; branded studio header and sign-in at 320px; branded public form (en, dv, embed), approver and verify pages; the same screens with nothing branded (JustForms fallback) |
| Inline editing and form logo | label, help text, placeholder, option (Enter adds, Backspace removes), Back/Next/Submit and message after submitting being edited, en and dv (Thaana toggle), phone and desktop, keyboard focus on an editable text; prompts on the selected block only; form Settings › Appearance logo row (form logo, organisation logo, SVG note, errors); public form, approver and verify pages with a form logo at each size and position, linked |
| Forms list | table with owner (you and someone else), live with unpublished changes, dv form, imported form, awaiting approval, never submitted; each sort; owner and status filters; no matches; phone cards at 320 and 390 |
| People | Organisation settings › People (members, invitations, search with no results, only you); invite dialog (several addresses, invalid ones, already a member, email not set up); change role (last admin, own role, set by sign-in groups); remove and leave; cancel invite; invitation page (pending, single sign-on, signed in as someone else, expired, accepted, invalid); Share › invite and share, pending access, notify by email (ticked with a message, email not set up, raise-role dialog); forms page as a member and as a form creator |
| Studio bars | phone (320, 412) form pages: one compact form bar at top 0, scrolled half-way down (bar still at top, nothing under it), form menu open, save states as icons, Publish shown only with changes; Submissions header with Export + more-actions menu and the one-line filter row; tablet (768) header + compact bar; desktop 1024 and 1440 full form bar on one row, sticky under the header, submission page side panel under both (STUDIO-HEADER-MOBILE) |
| Sharing preview | form Settings › Sharing preview (generated and uploaded image, unpublished notice, read-only for viewers, upload error), each preview tab, en and dv, phone 320 and desktop; the generated image itself for an en and a dv form (long title, no description, with and without logo) |

## A. Hard rules (any failure is P1)

- [ ] Every UI primitive comes from `components/ui/` (shadcn CLI). No look-alike markup
      (hand-made buttons, selects, dialogs, tabs, badges, checkboxes). Custom code is only
      composition, canvas, or input behaviour.
- [ ] No edits to generated files in `components/ui/` (check the diff, not just screenshots).
- [ ] No deploying-organisation name, domain, logo or internal tool anywhere in UI, copy,
      fixtures or screenshots' sample data.
- [ ] Logical properties only: no `ml-/mr-/pl-/pr-/left-/right-/text-left/text-right` in the
      diff; lint passes.
- [ ] dv form renders RTL from the form root, with Thaana font (Faruma if available, otherwise
      Noto Sans Thaana). No Latin fallback glyphs for Thaana, no boxes/tofu.
- [ ] Studio chrome stays English and LTR even while editing a dv form.

## B. Tokens and identity

- [ ] Background is Desk, sheets/cards are Sheet, text is Ink. No pure neutral greys from the
      shadcn default palette remain (check `index.css`).
- [ ] Carbon (or the organisation's brand primary, DESIGN 18.2) is the only saturated colour on a normal screen (primary buttons, links, focus,
      progress, drop line).
- [ ] Marker appears only as a wash for selection, "In review", logic targets, search hits,
      changed questions. Never as text colour, never on large areas.
- [ ] Selected canvas block has marker wash **and** the marker-edge start bar; keyboard focus
      is a separate carbon ring. Both visible when both apply.
- [ ] Stamp only for errors, destructive actions and "Rejected".
- [ ] Status is never colour alone: icon + word on every status badge.
- [ ] Radius hierarchy: paper sheets `rounded-md`, studio panels flush (no radius, hairline
      edge), floating layers `rounded-lg`/`xl`. Not one radius on everything.
- [ ] Shadow only on floating layers (popover, dropdown, dialog, sheet, drag overlay). No
      shadows on cards, field blocks or table rows.
- [ ] No gradients, decorative textures, illustrations or emoji.
- [ ] Dark mode: every screen legible, no hard-coded light colours, marker wash and stamp use
      dark values, focus visible.

## C. Typography

- [ ] Latin text is Atkinson Hyperlegible Next; code-like values (keys, hashes, embed code)
      use Atkinson Hyperlegible Mono and nothing else does.
- [ ] Thaana is visibly larger than adjacent Latin (≈1.12×) with generous line-height; fili
      (vowel marks) never clip or collide between lines, including in inputs, buttons,
      badges, table cells, selects and toasts.
- [ ] No italic or letter-spacing on Thaana; no synthetic italic.
- [ ] In dv, numbers inside Dhivehi content and the "ތ / A" toggle read in the right order
      (isolated with `bdi`); English system strings ("Step 2 of 3", errors ending in a full
      stop) read left to right with punctuation at the end; Thaana link underlines do not cut
      through vowel signs.
- [ ] Thaana inside shadcn controls (buttons, badges, selects, toasts) is as large as body
      Thaana, i.e. the `:lang(dv)` `--text-*` override is in place.
- [ ] Sentence case everywhere. No all-caps labels or eyebrows.
- [ ] Public field labels `text-lg` (600 Latin, 400 Thaana); page title `text-xl`; form title `text-2xl`/`3xl`.
      Hierarchy readable at a glance on a phone.
- [ ] Line length ≤ ~70 characters for descriptions and paragraphs.
- [ ] Numbers in tables and the reference number use tabular figures; digits are Western in
      both languages.
- [ ] Mixed-direction strings (email, ID, phone, URL, version in dv text) are isolated with
      `bdi`/`dir="ltr"` and read in the correct order.

## D. Layout and density

- [ ] Public form: sheet max 40rem centred on desktop; full-bleed on phones; start-aligned
      text; nothing centred except the success reference block.
- [ ] Public controls ≥ 44px tall (48px on phones); choice rows fully tappable; 32px between
      questions.
- [ ] Studio controls compact (32px) and aligned on a 4px grid; panels don't wobble when the
      selection changes.
- [ ] Builder canvas sheet is the same width and spacing as the public form (WYSIWYG).
- [ ] No horizontal scroll at 320px on the public form; at 200% zoom the content reflows.
- [ ] Sticky phone nav bar respects the safe area and never covers the focused input or the
      last question (bottom padding equals bar height).
- [ ] Half-width fields pair on ≥ sm and stack on phones.
- [ ] In RTL: layout mirrors (labels right, progress fills from right, Back on the right,
      chevrons point the right way, drawers/sheets come from the correct edge, icons with
      direction flip). Signature canvas is not mirrored.

## E. Components used as specified

- [ ] Builder panes use `Resizable`; panes scroll independently via `ScrollArea`.
- [ ] Inspector uses `Accordion` groups; logic editor is `Select`/`Command` combobox/`Input`/
      `Button` in a `Card`, not a custom widget.
- [ ] Phones use `Drawer` for palette and inspector; desktop submission detail uses `Sheet`.
- [ ] Destructive confirmations use `AlertDialog`; reversible deletes use an Undo toast
      instead of a dialog.
- [ ] Single choice uses `RadioGroup`, multi choice `Checkbox`, yes/no `RadioGroup` (not a
      Switch), rating `ToggleGroup`, dropdown `NativeSelect`, phone `InputGroup`.
- [ ] Every question is wrapped in `Field` with `FieldLabel`, `FieldDescription`, `FieldError`;
      groups use `FieldSet`/`FieldLegend`.
- [ ] Empty states use `Empty`; loading uses `Skeleton` (after ~300ms) or `Spinner` inline,
      never a full-page spinner overlay.
- [ ] Toasts via `sonner`, positioned at the end edge.

## F. States

- [ ] Every data screen has designed empty, loading and error states with the spec copy.
- [ ] Builder save status always visible and truthful (Saved / Saving… / Offline / Couldn't
      save + Retry); conflict dialog appears on 409.
- [ ] Publish blocked with a clear list when the draft has problems; each problem links to the
      element.
- [ ] Public form: error summary at top, focused, with links; inline errors under labels;
      submit failure keeps answers; closed/not-found screens are friendly and specific.
- [ ] Uploads show progress, errors with Retry, and block Next until done.
- [ ] Disabled controls explain why (tooltip or description), not just grey out.

## G. Interaction and motion

- [ ] Drag and drop shows a carbon drop line, refuses invalid targets (nested repeater,
      signature in repeater, third-level section) without errors.
- [ ] Undo/redo work from buttons and shortcuts; destructive actions offer Undo in a toast.
- [ ] Logic edits show the live sentence and highlight referenced questions on the canvas.
- [ ] Only the success "stamp" animates on its own; page changes cross-fade (no slide);
      nothing animates on page load.
- [ ] With `prefers-reduced-motion`, transitions and drag animations are instant.

## H. Accessibility (WCAG 2.1 AA)

- [ ] Visible focus on every interactive element, including choice cards, page chips, canvas
      blocks, table rows, drag handles.
- [ ] Logical tab order; no focus traps outside dialogs/sheets; focus returns to the trigger
      when they close; focus moves to the page title on wizard page change.
- [ ] Every icon-only button has an accessible name matching its tooltip.
- [ ] Contrast: text ≥ 4.5:1 (large ≥ 3:1), input borders and state indicators ≥ 3:1. Check
      muted text on Desk, placeholder text, disabled text that conveys info, dark mode.
- [ ] Inputs have `autocomplete`/`inputMode` appropriate to type; `aria-invalid` and
      `aria-describedby` on errors.
- [ ] Live regions: save status, step changes, copy confirmations, revealed questions count.
- [ ] Keyboard drag and drop works and announcements use the spec copy.
- [ ] `lang` set correctly on the form root (and on mixed-language snippets in the studio).

## I. Copy

- [ ] Sentence case, plain verbs, specific buttons ("Publish", "Add page", "Export to Excel",
      not "Submit"/"OK"/"Confirm" in the studio).
- [ ] Actions keep their name through the flow (button → toast).
- [ ] Error messages say what's wrong and how to fix it, with an example where useful; no
      "Invalid", no apologies, no vague "Something went wrong" without a next step.
- [ ] Terms match the glossary in PHASE-2-SCREENS §7 (question, page, key, version,
      submission, reference).
- [ ] No template tells: no "→" appended to buttons, no "A · B · C" meta strings, no
      "WORD — fragment" labels, no eyebrow labels above headings.
- [ ] No Dhivehi system strings anywhere: buttons, progress, errors, access steps, approver
      and verify pages, emails and PDF labels are English for every form; Dhivehi only in form
      content and answers.

## J. Performance hints visible in review

- [ ] Public form shows the title before fields finish loading; no layout shift when fonts
      load (font-display swap with matching fallback metrics, or size-adjust).
- [ ] Signature pad, phonetic keyboard and calendar load lazily (check network panel /
      bundle report ≤ 120 KB gzip initial).
