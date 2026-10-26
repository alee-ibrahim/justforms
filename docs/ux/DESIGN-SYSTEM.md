# JustForms design system

Status: v1 plan for Phase 2 (builder and renderer); v2 typography (Inter, studio scale, desktop
step-up for forms, sections 4 and 6). Owner: UI/UX.
Applies to the studio (staff building and reviewing forms) and the public form renderer
(people filling forms, mostly on phones).

Everything here is delivered through **shadcn/ui theming**: CSS variables in
`frontend/src/index.css`, the `--radius` scale, font stacks, and utility classes at the call
site. Generated files in `components/ui/` are never edited. Nothing in this document needs a
custom component kit.

---

## 1. Subject, audience, job

- **Subject.** Paper forms moving onto screens: application forms, registrations, requests,
  declarations. The vernacular is the printed form: a white sheet on a desk, ruled answer
  lines, blue ink, a carbon copy, a highlighter to mark what needs attention, a rubber stamp
  when it is received.
- **Audience.**
  1. Staff who build forms. Often non-technical, used to Word and paper. They need to see the
     form as the respondent will, and never wonder whether their work was saved.
  2. Members of the public filling forms on mid-range phones, sometimes on slow networks, in
     English or Dhivehi. Many will read the form once, slowly. Some have low vision.
  3. Staff reviewing submissions: scanning a table, opening one, changing its status.
- **Primary job.** Get a correct, complete answer from a respondent with the least friction,
  and let staff build that form without training.

## 2. Visual direction: "the sheet on the desk"

The studio is a cool grey **desk**. The form is always a white **sheet** on it, at the width
the respondent will see. Ink is blue-black. The primary action colour is **carbon** (the
blue-violet of carbon-copy paper). The one memorable device is the **marker**: a
highlighter-yellow wash that marks the thing you are working on (the selected field on the
canvas, the field a logic rule points to, a submission waiting for review). Errors and
rejections use **stamp** red.

Boldness is spent in one place: the marker. Everything else is quiet. No gradients, no
decorative shadows, no illustrations.

## 3. Colour

### 3.1 The six named colours

| Name | Hex (light) | Role | Hex (dark) |
|---|---|---|---|
| **Desk** | `#F3F5F9` | App background behind sheets and panels | `#121729` |
| **Sheet** | `#FFFFFF` | Cards, the form canvas, popovers, inputs | `#1A2038` |
| **Ink** | `#18203A` | Text, icons, primary-button text on marker | `#E6E9F2` |
| **Carbon** | `#3B3FC1` | Primary actions, links, focus ring, drop indicator, progress | `#9DA2FF` |
| **Marker** | `#FFE45C` (wash `#FFF6BF`) | Selection, "In review", logic targets, search hits | `#E8D34A` (wash `#3A3824`) |
| **Stamp** | `#C0362C` | Errors, destructive actions, "Rejected" | `#FF8A7A` |

Supporting greys are derived from Ink, never neutral grey: muted text `#5A6380`
(dark `#A3AAC2`), hairline `#DCE0EA` (dark `#2C3454`), input outline `#838AA2`
(dark `#6B7393`).

Measured contrast (WCAG 2.1):

| Pair | Ratio | Use |
|---|---|---|
| Ink on Sheet | 16.1 | body text |
| Muted on Sheet / on Desk | 5.95 / 5.45 | descriptions, help text |
| Carbon on Sheet / Sheet on Carbon | 7.87 | links, primary button |
| Stamp on Sheet | 5.52 | error text |
| Ink on Marker wash | 14.7 | selected field text |
| Carbon on Marker wash | 7.19 | link inside a selected field |
| Input outline on Sheet / on Desk | 3.44 / 3.16 | input boundary (1.4.11 needs 3:1) |
| Dark: Ink on Sheet | 13.2 | |
| Dark: Carbon on Sheet | 6.92 | |
| Dark: Stamp on Sheet | 7.01 | |
| Dark: Input outline on Sheet | 3.44 | |

Rules:
- Marker is a **background wash** only. Never marker text, never marker on a large area
  (one field, one row, one badge at a time).
- Carbon is the only saturated colour on a normal screen. Status is never colour alone:
  every status badge also has an icon and a word.
- Hairline `--border` (1.32:1) is for dividers and card edges only. Anything you type into
  uses `--input` (3:1 or more).

### 3.2 Mapping to shadcn variables

`index.css` (`:root` and `.dark`). Values in oklch to match the existing file.

| Variable | Light | Dark | Notes |
|---|---|---|---|
| `--background` | Desk `oklch(0.970 0.006 264.5)` | `oklch(0.209 0.037 271.2)` | |
| `--foreground` | Ink `oklch(0.250 0.051 269.6)` | `oklch(0.934 0.013 271.3)` | |
| `--card`, `--popover` | Sheet `oklch(1 0 0)` | `oklch(0.251 0.046 272.0)` | |
| `--card-foreground`, `--popover-foreground` | Ink | Ink (dark) | |
| `--primary` | Carbon `oklch(0.454 0.198 273.9)` | `oklch(0.746 0.133 280.3)` | |
| `--primary-foreground` | Sheet | Desk (dark) `oklch(0.209 0.037 271.2)` | |
| `--secondary` | `oklch(0.935 0.018 273)` (`#E4E6FA`, carbon tint) | `oklch(0.300 0.060 274)` | quiet buttons, selected tab |
| `--secondary-foreground` | Ink | Ink (dark) | |
| `--muted` | Desk | `oklch(0.280 0.045 272)` | |
| `--muted-foreground` | `oklch(0.503 0.048 271.2)` | `oklch(0.740 0.035 272.6)` | |
| `--accent` | Marker wash `oklch(0.967 0.071 99.8)` | `oklch(0.337 0.033 103.1)` | menu hover/highlight = marker; `menuAccent: subtle` keeps it light |
| `--accent-foreground` | Ink | Ink (dark) | |
| `--destructive` | Stamp `oklch(0.540 0.176 28.6)` | `oklch(0.758 0.145 29.0)` | |
| `--border` | `oklch(0.907 0.014 268.5)` | `oklch(0.333 0.058 272.3)` | hairlines |
| `--input` | `oklch(0.635 0.037 272.5)` | `oklch(0.561 0.051 273.7)` | input outlines, 3:1 |
| `--ring` | Carbon | Carbon (dark) | focus ring; shadcn applies `ring-ring/50`, keep 3px |
| `--chart-1..5` | Carbon, `#6E72D9`, Marker `#E8C93A`, Stamp, Muted | lightened set | only for the future analytics view |
| `--sidebar*` | Sheet / Ink / Carbon | dark equivalents | only if `sidebar` is ever added |

Extra project tokens (theme variables, not component edits):

```css
@theme inline {
  --color-marker: var(--marker);         /* #FFE45C light / #E8D34A dark: badges, search hits */
  --color-marker-edge: var(--marker-edge); /* #8F7300 light / #E8D34A dark: selected-field start bar */
  --color-marker-wash: var(--accent);    /* alias, used for selection washes */
  --color-sheet: var(--card);
}
```

Use them as utilities at call sites (`bg-marker-wash`, `border-s-marker`), never inside
`components/ui/`.

### 3.3 Form accent on the public renderer

`settings.theme.accent` (if set) replaces `--primary` and `--ring` **inside the form root
only**. The renderer checks contrast against white at runtime: if the accent is below 4.5:1 it
darkens it in oklch lightness steps until it passes. Marker, Stamp, Ink and the desk stay
fixed so every form remains legible and recognisably JustForms.

## 4. Typography

### 4.1 Families

| Role | Family | Why | Source |
|---|---|---|---|
| Latin UI and form text | **Inter** (variable, 100–900) | A clean, neutral sans with a tall x-height that stays readable at 13–15px in dense studio tables and scales up well for form questions. Its default figures are plain: the zero has no slash or dot, `1`, `4` and `7` are unambiguous, and `tnum` gives equal-width figures for columns. Atkinson Hyperlegible Next (the v1 choice) read badly in practice: its slashed zero turned `40` into "4Ø" and reference numbers like `#0040` into a row of crossed circles. Geist and IBM Plex Sans were considered: Geist's figures are narrow and its small sizes light; Plex's squarish digits and flagged `1` feel technical next to form questions. | `@fontsource-variable/inter` (SIL OFL), weight axis only (`inter/wght.css`) |
| Code-like values | **Atkinson Hyperlegible Mono** | Only for things that literally are code: field keys (`full_name`), hashes, embed snippets, version ids, env var names. Its slashed zero is right there (a hash must never be misread). Never for general small labels, references, dates or amounts. | `@fontsource-variable/atkinson-hyperlegible-mono` (SIL OFL) |
| Thaana | `Faruma, "MV Faseyha", "Noto Sans Thaana", sans-serif` | Faruma is what Dhivehi readers expect on official forms. Noto Sans Thaana is the bundled fallback. Never commit Faruma or MV files. | runtime stylesheet `JUSTFORMS_THAANA_FONT_CSS_URL` (default: dvfonts CDN; or self-hosted `/fonts/...`; or empty), operator `/fonts/fonts.css`, `@fontsource/noto-sans-thaana` |

Loading: Inter is self-hosted from the app's own assets (no font CDN). Its `@font-face` rules
carry `unicode-range`, so a Latin page downloads only the Latin file (about 47 KB of woff2, a
CSS asset, not JavaScript: the public bundle budget is unaffected); the Latin Extended,
Vietnamese, Greek and Cyrillic files are fetched only when such text appears.
`font-display: swap` with an `'Inter Fallback'` face (local Arial with Inter's metrics:
`size-adjust: 107.06%`, `ascent-override: 90.49%`, `descent-override: 22.56%`), so text does
not jump when Inter arrives.

Form themes can still pick another Latin family (FORM-THEME-SCREENS 3.1): Atkinson Hyperlegible
Next, IBM Plex Sans, Source Serif 4 and Noto Sans are `/theme-fonts/{id}.css`, fetched only by
pages whose theme uses them. The instance default is Inter; an organisation or form that chose a
font explicitly keeps it.

Server rendering (signed PDFs, link-preview images) embeds static Inter Regular and Bold
(`backend/app/pdf/fonts/`, OFL licence alongside, subset to Latin, Latin Extended, Vietnamese,
punctuation, currency and arrows; the `pyftsubset` command is in `app/pdf/faces.py`). Emails
cannot load web fonts reliably; they ask for `Inter, 'Segoe UI', Roboto, 'Helvetica Neue',
Arial, sans-serif` (Inter when installed, a system sans otherwise).

Font variables:

```css
@theme inline {
  --font-sans: 'Inter Variable', 'Inter Fallback', Roboto, 'Segoe UI', 'Helvetica Neue', Arial, Faruma, 'MV Faseyha', 'Noto Sans Thaana', sans-serif;
  --font-heading: var(--font-sans);
  --font-mono: 'Atkinson Hyperlegible Mono Variable', ui-monospace, monospace;
  --font-thaana: Faruma, 'MV Faseyha', 'Noto Sans Thaana', sans-serif;
}
```

Because Latin comes first in `--font-sans`, Thaana characters fall through to Faruma via
`unicode-range`, so mixed strings ("ID card ކާޑު") render correctly in either context.
In a `dv` form root, put the Thaana stack first: `[lang=dv] { font-family: var(--font-thaana), var(--font-sans) }`
so Thaana punctuation (`،` `؟`) and digits come from the Thaana face.

### 4.2 Scale

Two scales, because the two surfaces do different jobs. Both are Tailwind's `--text-*`
variables, so shadcn components (which hard-code `text-sm` and friends) follow without edits.

**Studio** (`@theme` in `index.css`): dense but readable, with a 15px control size.

| Token | px / line-height | Weight | Used for |
|---|---|---|---|
| `text-xs` | 13 / 16 | 500 | badges, counts, keyboard hints |
| `text-sm` | 15 / 22 | 400, 500 for labels | controls, table cells, inspector, cards |
| `text-base` | 16 / 24 | 400 | body copy, empty states |
| `text-lg` | 18 / 28 | 600 | panel and card titles |
| `text-xl` | 24 / 32 | 600, `tracking-tight` | page titles |
| `text-2xl` | 30 / 38 | 700 | large numbers |
| `text-3xl` | 36 / 44 | 700 | rare display numbers |

**Form** (every `[data-df-theme]` root: public form, builder canvas, preview, submission sheet,
approver and verify pages): minor third (1.2) from 16px, multiplied by the theme's text size
(S 0.9375, M 1, L 1.125, XL 1.25) and, on desktops, by `--df-fit` (section 6).

| Token | Latin px / line-height (M) | Latin ≥ 1024px (M) | Thaana px / line-height (M) | Weight | Used for |
|---|---|---|---|---|---|
| `text-xs` | 12 / 16 | 13.5 / 18 | 14 / 24 | 500 | counts, footer |
| `text-sm` | 14 / 20 | 15.75 / 22.5 | 16 / 28 | 400 | step counter, small help |
| `text-base` | 16 / 24 | 18 / 27 | 18 / 32 | 400 | answers, help text, descriptions |
| `text-lg` | 19 / 28 | 21.4 / 29.4 | 21 / 36 | 600 Latin, 400 Thaana | questions (field labels) |
| `text-xl` | 23 / 32 | 25.9 / 36 | 26 / 40 | 650 | page titles |
| `text-2xl` | 28 / 36 | 31.5 / 40.5 | 31 / 48 | 700 | form title (phone), success heading |
| `text-3xl` | 33 / 40 | 37.1 / 45 | 37 / 56 | 700 | form title (≥ sm), success reference number |

Thaana on desktops is multiplied the same way (body 20px, questions 23.6px at M).

### 4.2.1 Figures

- Inter's default figures: plain zero (never the slashed `zero` feature), no stylistic sets.
- **Tabular** (`font-variant-numeric: tabular-nums`, Tailwind `tabular-nums`) wherever numbers
  are compared, scanned or read back: tables (`[data-slot=table]`), badges, calendars,
  pagination, charts, `<time>`, numeric inputs (`inputmode=numeric|decimal`, `type=number`),
  reference numbers (`#0040`), dates, counts, money, step counters. A global rule in `index.css`
  covers the slots; add `tabular-nums` at call sites for the rest.
- **Proportional** everywhere else (running text, labels, descriptions).
- PDFs: the reference and submitted line and the footer page line are shaped with `tnum`;
  answers and URLs stay proportional.

Rules:
- **Thaana is set ~1.12× larger with ~1.75× line-height.** Thaana's vowel signs (fili) sit
  above and below the consonant, so Latin line-heights clip them and make lines collide.
  Implement it once, by **redefining Tailwind v4's type-scale variables inside the dv
  scope**, so shadcn components (which hard-code `text-sm` etc.) scale without being edited:

  ```css
  :lang(dv) {
    --text-xs: 0.875rem;  --text-xs--line-height: 1.5rem;
    --text-sm: 1rem;      --text-sm--line-height: 1.75rem;
    --text-base: 1.125rem; --text-base--line-height: 2rem;
    --text-lg: 1.3125rem; --text-lg--line-height: 2.25rem;
    --text-xl: 1.625rem;  --text-xl--line-height: 2.5rem;
    --text-2xl: 1.9375rem; --text-2xl--line-height: 3rem;
    --text-3xl: 2.3125rem; --text-3xl--line-height: 3.5rem;
    font-family: var(--font-thaana), var(--font-sans);
    font-synthesis-style: none;
    letter-spacing: 0;
  }
  ```

  Never size Thaana per field or per component.
- **Faruma has one weight.** Bold is synthesised by the browser and gets muddy below 20px.
  In dv, hierarchy comes from size and colour: labels stay weight 400 (Ink, `text-lg`),
  only page and form titles use 700 (synthetic bold is acceptable at that size). Noto Sans
  Thaana has a real 700, so the same rule keeps both fonts looking alike.
- **Underlines in Thaana** collide with below-base fili: links and error-summary links in a dv
  root use `underline-offset-[0.4em] decoration-1`.
- **Numbers inside Dhivehi form text** (labels, titles, options, help text) are isolated at
  display time with `isolateNumbers` from `@yashau/thaana-react`, so phone numbers and
  negatives keep their order. Stored text is unchanged.
- **Numbers and fractions in RTL** must be isolated: "Step 2 of 3" rendered as `2 / 3` inside RTL
  text flips to "3 / 2". Wrap numeric runs (`2 / 3`, `1–50`, `10 MB`, dates like
  `30/11/2026`) in `<bdi dir="ltr">`. The same applies to the "ތ / A" keyboard toggle label.
  Put the `bdi` *inside* the element (`<Toggle><bdi dir="ltr">ތ / A</bdi></Toggle>`), never on a
  flex item, or its logical margins flip and it jumps to the wrong edge.
- Thaana has no italics and no capitals. Never synthesise italic (`font-synthesis: none` in the
  dv root) and never letter-space Thaana.
- No all-caps labels anywhere, in either script. Sentence case for every string.
- Field labels on the public form are `text-lg` (weight 600 Latin, 400 Thaana): the label is the question, it is
  the most important text on the screen.
- Line length: the sheet is 40rem below 1024px and 48rem on desktops (both about 70 Latin
  characters at the body size). Descriptions max `36em`, so they widen with the type.
- Numbers in tables use `tabular-nums`.
- Western digits everywhere, including in dv forms.

### 4.3 Headline treatment

Type is the identity: the form title on the public page is large, set tight
(`tracking-tight` for Latin only), left-aligned (start-aligned in RTL), with no decoration
above it. The organisation name or logo sits in a quiet row above, in muted text. No eyebrow
labels, no single accented word.

## 5. Shape: radius, borders, elevation

- `--radius: 0.5rem`. Derived: `sm` 0.3rem (badges, checkboxes), `md` 0.4rem (inputs, buttons),
  `lg` 0.5rem (cards, popovers), `xl` 0.7rem (dialogs, sheets).
- **Hierarchy, not one radius everywhere.** The form sheet on the canvas and the public page
  sheet use `rounded-md` (paper has nearly square corners). Panels in the studio are flush
  to the desk with a hairline `border-e`/`border-s`, no radius and no shadow. Floating things
  (popover, dropdown, dialog, drag overlay) get `rounded-lg` and the single elevation below.
- **One shadow** for floating layers only: `shadow-lg` with an ink-tinted colour
  (`shadow-[0_8px_24px_-8px_oklch(0.25_0.05_270/0.25)]` via a theme token
  `--shadow-float`). Cards on the desk have no shadow: a hairline border is enough.
- The selected field on the canvas: marker wash background plus a 3px `border-s` in
  **marker edge** `#8F7300` (`oklch(0.566 0.116 91.8)`, 4.55:1 on Sheet, 4.15:1 on the wash;
  dark mode uses Marker `#E8D34A`, 10.6:1). The wash alone is too pale to signal state
  (WCAG 1.4.11), so the edge carries it. Nothing else changes on selection.

## 6. Spacing and density

Base unit 4px (Tailwind default). Two densities:

| | Studio (compact) | Public form (comfortable) |
|---|---|---|
| Control height | 32px (`h-8`, shadcn default) | 48px on phones, 44px ≥ sm (`h-12 sm:h-11`), 48px ≥ 1024px |
| Touch target | 32px with 8px gap with a mouse; ≥ 44×44px on touch screens (`pointer: coarse` rules in `index.css`) | ≥ 44×44px always |
| Field-to-field gap | 16px in inspector | 32px between questions (`gap-(--df-space)`, theme density), 36px ≥ 1024px |
| Label to input | 8px | 8px; description sits between label and input, 4px |
| Panel padding | 12–16px | sheet padding 20px phone, 40px tablet, 44px ≥ 1024px |
| Table row | 40px | n/a |

Layout widths:
- Studio shell max width: none for the builder (full-bleed three panes); 72rem for lists and
  settings pages.
- Builder panes: palette 240px (min 200), canvas flexible with the sheet at the form's
  rendered width (40rem), inspector 340px (min 300, max 480). Resizable.
- Public form: sheet max 40rem (`--df-sheet`), centred on the desk on ≥ md, 48rem on desktops;
  full-bleed sheet on phones (no desk visible, no outer radius).

**Desktop step-up (≥ 1024px).** On a desktop the phone-first form looked small and lost on the
page. Inside every form root (`[data-df-theme]`) a viewport media query sets:

- `--df-fit: 1.125`: every form `--text-*` (Latin and Thaana) is multiplied by it on top of the
  theme's text size, so S/M/L/XL keep their steps (M: body 18px, questions 21px);
- `--spacing: 0.2727rem` (x1.09): Tailwind's spacing unit inside the form only, so 44px
  controls become 48px and icons, padding and gaps grow in proportion;
- `--df-space` = `--df-gap` x `--df-fit`: the space between questions (theme density);
- `--df-sheet` = `--df-page-width` x 1.2: narrow 40.8rem, standard 48rem, wide 57.6rem.

Below 1024px nothing changes. The builder canvas, preview and submission sheet render the same
sizes as the public page at the same screen width. Studio phone previews
(`data-df-device="phone"` on the preview frame) keep phone sizes on any screen.

Alignment: everything is start-aligned (left in LTR, right in RTL). Only the success screen
centres its reference number. Never justify text (Thaana justification uses kashida-like
stretching browsers do not do well).

## 7. Iconography

Lucide (already configured). 16px in studio controls, 20px on the public form.
Directional icons (chevrons, arrows, undo/redo) flip with `rtl:rotate-180` or are chosen per
direction. Icons never stand alone without an accessible name; in the studio an icon-only
button always has a `Tooltip` with the same text as its `aria-label`.

## 8. Motion

- Respond, do not decorate. Motion answers an action and shows what changed:
  - drag and drop: the dragged field lifts into a drag overlay; the drop indicator is a 2px
    carbon line; siblings shift with dnd-kit's sortable transition (150ms, ease-out);
  - adding a field from the palette: the new field gets the marker wash and the canvas
    scrolls it into view (`scrollIntoView({block: 'nearest'})`);
  - wizard page change: content cross-fades 120ms; no sliding (sliding implies direction,
    which inverts in RTL and confuses);
  - sheets, dialogs, popovers: the shadcn/tw-animate defaults, unchanged.
- **One orchestrated moment:** after a respondent submits, the success sheet shows the
  reference number with a single 240ms scale-in (0.96 → 1) and fade, like a stamp landing.
  Nothing else on the public form animates on its own.
- No entrance animations on page load, no hover lifts on cards, no skeleton shimmer longer
  than needed (skeletons appear only after 300ms of waiting).
- `prefers-reduced-motion: reduce` turns every transition above into an instant change
  (`motion-reduce:transition-none motion-reduce:animate-none`), including dnd-kit
  (`dropAnimation={null}`).

## 9. Voice and copy

- Plain verbs, sentence case, no filler. Name things the way a non-technical builder would:
  "Show this question when…", not "visibleIf condition".
- An action keeps its name through the flow: **Publish** → toast "Published version 3".
  **Add page** → the new page is called "Page 4" until renamed.
- Errors say what happened and what to do: "Enter a phone number with 7 digits, like 7771234."
  Never "Invalid input". Never apologise.
- Empty states invite one action: "No questions on this page yet. Drag one from the left, or
  press / to search."
- No middle-dot meta strings, no arrows appended to buttons, no em-dash labels. Use separate
  elements or commas.
- All system text is English only, studio and respondent-facing alike: what JustForms supplies
  (Next, Back, the default Submit, validation messages, "Step 2 of 4", "(optional)", Yes / No,
  access and CAPTCHA steps, success / closed screens, emails, PDF labels) is English for every
  form. Dhivehi appears only in form content and answers. In a dv form the English strings are
  `<En>` runs (`<bdi dir="ltr" lang="en">`) inside the RTL sheet (DESIGN §16).

## 10. RTL and Thaana rules (renderer and canvas)

- The form root carries `lang` and `dir` from `settings.language` via `contentProps(formLanguage(form))`; wrap it in `DirectionProvider`. Inspector inputs that edit form text get the same props, so a dv form is typed RTL in Thaana inside the English studio.
  The studio chrome stays LTR English even when the canvas shows a dv form.
- Logical utilities only (`ms-`, `pe-`, `start-`, `text-start`, `border-s`).
- Wrap LTR runs inside dv text in `<bdi dir="ltr">` (emails, IDs, URLs, phone numbers,
  version numbers). Inputs that take Latin data (`email`, `phone`, `number`, `inputScript:
  latin`) get `dir="ltr"` on the input itself, but the label and error stay RTL.
- Progress bar fills from the start edge (right in RTL). Back/Next swap visual sides
  automatically because they are in a flex row; their chevrons flip.
- Phonetic keyboard toggle sits at the input's end edge.

## 11. Self-critique pass

The first draft of this plan, written quickly, was:

> Geist for everything, shadcn neutral greys, a blue primary (`#2563EB`), radius 0.625rem on
> everything, cards with soft shadows for every field on the canvas, and an uppercase
> "STEP 2 OF 4" eyebrow above page titles on the public form.

Run against the brief, every one of those choices was a default rather than a decision:
I would have produced the same plan for a CRM, a todo app or an invoicing tool. Revisions:

| Draft | Problem | Revised to | Why |
|---|---|---|---|
| Geist | The default SaaS face; says nothing about forms. | Atkinson Hyperlegible Next + Mono for code (v1); Inter + Atkinson Mono for code (v2, section 4.1) | Legibility of codes and numbers is the job of a form. v2 keeps that goal with plain figures: people found the slashed zero harder, not easier, to read. |
| Neutral grey + Tailwind blue | Generic; indistinguishable from any shadcn starter. | Desk / Sheet / Ink / Carbon / Marker / Stamp | Taken from the material of paper forms; each colour has one job. |
| One radius everywhere | SaaS card-kit tell. | Paper sheet `md`, flush panels with no radius, floating layers `lg` | Radius now encodes "is this paper, chrome or floating". |
| Soft shadow under every field card | SaaS card-kit tell, and heavy on a 30-question form. | Fields are rows on one sheet, separated by space; only floating layers get a shadow | The canvas looks like the form the respondent will see. |
| "STEP 2 OF 4" uppercase eyebrow | All-caps eyebrow tell; also uppercase means nothing in Thaana. | "Step 2 of 4" in muted `text-sm` next to the progress bar, sentence case | Same information, works in both scripts. |
| Selection as a carbon outline ring | Collides with the focus ring; keyboard users could not tell focus from selection. | Marker wash + marker start bar for selection, carbon ring for focus | Two different states now look different. Marker is the single bold element. |
| Animated page transitions sliding left/right | Direction inverts in RTL; motion for its own sake. | 120ms cross-fade | Direction-neutral. |
| Second pass ("remove one accessory"): a desk dot-grid texture behind the canvas | Decoration; adds noise behind long forms. | Removed. Plain Desk colour. | |
| Second pass: stamp-red "Required" asterisks | Red asterisks read as errors before the user has done anything. | Required fields say nothing; optional fields get "(optional)" in muted text. When most fields are optional, invert: mark required ones with "(required)". The renderer picks whichever is shorter per form. | Fewer marks, less alarm. Common public-sector form pattern. |

### 11.1 Mockup critique (third pass)

Static mockups of the builder (1440×900) and the guardian page of the example form on a
390px phone (en, dv, dv dark) were rendered and screenshotted. What they showed and what
changed in this plan:

| Seen in the screenshot | Change |
|---|---|
| dv "Step 2 of 3" rendered as "3 / 2" | Rule added: isolate numeric runs in RTL with `bdi` (§4.2) |
| The "ތ / A" toggle label reordered to "A / ތ" | Same `bdi` rule |
| Faruma at weight 600 for every label looked smeared and shouted | dv labels at 400, size carries hierarchy (§4.2) |
| Underlined Thaana links in the error summary cut through the lower vowel signs | `underline-offset-[0.4em]` in dv (§4.2) |
| Thaana button text looked smaller than its Latin twin because the button hard-codes its size | Scale Thaana by redefining `--text-*` in `:lang(dv)` instead of per-component classes (§4.2) |
| Atkinson's slashed zero in "30 November" and "+960" | Kept at the time. Reversed in v2 (section 4.1): in live use the slashed zero read as "Ø" and made references and amounts look odd |
| Marker selection wash, carbon drop line and the drag overlay are distinguishable at a glance | Kept |
| Error state: stamp start bar + inline message + tinted input ring together | Kept, but the ring tint stays subtle (20% stamp) so the bar and the message do the work |

What stays deliberately conventional: shadcn component behaviour, focus rings, table
patterns and dialogs. Staff should recognise how things work; only the identity is new.
