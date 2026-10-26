# Form addresses, appearance and form themes

Three related changes to how forms look and where they live:

1. **Clean form addresses.** A public form is `https://<host>/<slug>`; slugs are unique across
   the install.
2. **Light by default, with a per-person appearance choice** for the studio.
3. **Form theme.** An organisation sets how its forms look (colours, type, shape, controls,
   page); each form can override any of it.

Tokens, type and motion come from [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); branding from
[BRANDING-SCREENS.md](BRANDING-SCREENS.md); review with [REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md).
Copy in "quotes" ships as written, English only. Nothing new from shadcn: `card`, `field`,
`input`, `select`, `native-select`, `toggle-group`, `radio-group`, `switch`, `button`, `badge`,
`alert`, `tabs`, `dropdown-menu`, `skeleton`, `spinner` and `separator` are installed.

## 1. Form addresses

### 1.1 Rules

- A form lives at `/<slug>`; embedded at `/<slug>?embed=1`. Old links `/f/<org>/<slug>` answer
  with a permanent redirect (301) to `/<slug>`, keeping the query string.
- Slugs are unique across the install among forms that are not deleted: lower-case letters,
  digits and hyphens, starting with a letter or digit, up to 100 characters.
- Reserved words can't be slugs because the app uses them: `a`, `about`, `account`, `admin`,
  `api`, `app`, `appearance`, `approve`, `approvals`, `assets`, `auth`, `branding`, `callback`, `docs`,
  `justforms`, `embed`, `f`, `favicon`, `files`, `fonts`, `forms`, `health`, `healthz`,
  `help`, `index`, `login`, `logout`, `manifest`, `me`, `metrics`, `new`, `oauth`, `profile`,
  `public`, `readyz`, `robots`, `settings`, `sitemap`, `static`, `status`, `theme-fonts`,
  `uploads`, `v`, `verify`, `www` (the list lives in `app/services/slugs.py`).
- A new form takes its slug from its title; a taken or reserved slug gets `-2`, `-3`... A
  migration does the same for existing forms when two organisations used the same slug.
- Unknown addresses show the public "We couldn't find this form" screen: HTTP 404 for paths that
  can't be a form, from the public app for a well-formed address nobody uses.

### 1.2 Share › Link › Short address

The existing "Short address" row becomes the form's address:

```
 Address
 [ forms.example.org/ ][ youth-app                 ] [Save] [Cancel]
 ✓ Available                                 (or)  ✗ Another form already uses this address.
 Changing it breaks links you already shared.
```

- `InputGroup` with an `InputGroupAddon` (`InputGroupText` host + "/", `dir="ltr"`, muted) and
  `InputGroupInput` (mono, `dir="ltr"`, `autoCapitalize="none"`, `spellCheck=false`).
- While editing, the address is checked 300 ms after typing stops
  (`GET /forms/slug-check?slug=&formId=`). The result is a `FieldDescription` with an icon,
  announced politely:
  - "Checking…" (with `Spinner`), "Available" (check icon, `text-foreground`),
  - "Another form already uses this address." / "This address is used by JustForms itself.
    Try another." / "Use lower-case letters, digits and hyphens, like youth-app." (stamp,
    `FieldError`), with "Try {suggestion}" as a link-style `Button` when there is one.
- **Save** is disabled until the check says available. The API checks again (409 `slug_taken`,
  422 `slug_reserved`).
- New form dialog: under the title, a read-only line "Address: forms.example.org/youth-app"
  (muted, `bdi dir="ltr"`) shows the slug the form will get, checked the same way.

## 2. Appearance (studio)

- The studio is **light** unless the person chooses otherwise. Choices: **Light** (default),
  **Dark**, **Match device**. Stored on the user (`users.appearance`), cached in
  `localStorage` (`justforms:appearance`) and applied by a tiny blocking script in `<head>`
  (`/appearance.js`, same origin, so the CSP stays `script-src 'self'`) before the first
  paint. On sign-in the server value wins and refreshes the cache.
- Account menu (`DropdownMenu`), under the email label:

```
 ali@example.org
 ─────────────
 Appearance
   ◉ Light
   ○ Dark
   ○ Match device
 ─────────────
 ⚙ Organisation settings
 ⇥ Sign out
```

  `DropdownMenuLabel` "Appearance" + `DropdownMenuRadioGroup` with three
  `DropdownMenuRadioItem`s (icons Sun, Moon, Monitor). Choosing applies at once, saves with
  `PATCH /auth/me` and keeps the menu open; failure: toast "Couldn't save your appearance
  choice. It applies on this device only."
- Public form, approver and verify pages have no viewer profile: they are **light** unless the
  form's theme says "Dark" or "Match device" (section 3).

## 3. Form theme

### 3.1 What can be set

Every value is **inherit** (empty) or a choice. A form inherits from its organisation, the
organisation from JustForms' defaults (and the instance brand colour).

| Group | Setting | Choices | JustForms default |
|---|---|---|---|
| Colours | Primary (buttons, links, focus, progress) | `#RRGGBB` | brand colour, else Carbon |
| | Page background (the desk) | `#RRGGBB` | Desk |
| | Sheet (the form card) | `#RRGGBB` | Sheet |
| | Text | `#RRGGBB` | Ink |
| | Muted text (descriptions, help) | `#RRGGBB` | derived from text |
| | Borders (dividers, card edge) | `#RRGGBB` | derived from text |
| | Errors | `#RRGGBB` | Stamp |
| Text | Latin font | Inter, Atkinson Hyperlegible Next, IBM Plex Sans, Source Serif 4, Noto Sans | Inter |
| | Thaana font | the install's list (Faruma, MV Faseyha, MV Waheed, …) | Faruma |
| | Text size | Small, Medium, Large, Extra large (0.9375, 1, 1.125, 1.25×) | Medium |
| | Headings | Compact, Standard, Large (0.875, 1, 1.15× of the title sizes) | Standard |
| Shape | Corners | Square, Small, Medium, Large (`--radius` 0, 0.25, 0.5, 0.875rem) | Medium |
| | Spacing | Compact, Comfortable, Roomy (gap between questions 1.5, 2, 2.75rem) | Comfortable |
| | Page width | Narrow, Standard, Wide (34, 40, 48rem) | Standard |
| Controls | Buttons | Filled, Outline | Filled |
| | Full-width buttons on phones | on/off | on |
| | Inputs | Outlined, Filled, Underlined | Outlined |
| | Progress | Bar, Steps text only, Hidden | Bar |
| Page | Colour mode for people filling it in | Light, Dark, Match device | Light |
| | Logo position | Start, Centre, Hidden | Start |
| | Header image | PNG/JPEG/WebP, ≤ 2 MB, ≤ 4096 px | none |
| | Background image | same | none |

Colours are chosen for light mode. Dark values are generated from them (same hue, dark
lightness), and every colour is checked like the brand colour: text, muted text, primary and
error must read at **4.5:1** on the sheet and the page background, input outlines (derived
from the border colour) at **3:1**, the primary's label at 4.5:1. Anything that fails is
darkened or lightened until it passes, and the settings say so ("Text adjusted to #2B2B2B so
it reads at 4.5:1 on the sheet."). Marker (selection) stays JustForms'.

Images are decoded and re-encoded as WebP (metadata dropped), stored through the storage
abstraction under `theme/{org}/{sha}.webp` and served same-origin (`img-src 'self'`). Errors:
"That file isn't a PNG, JPEG or WebP image.", "The image is larger than 2 MB.", "The image is
larger than 4096 pixels on a side."

### 3.2 Organisation settings › Form theme

Below Branding on `/settings`, same two-column layout (form on the start side, sticky preview
on the end side ≥ lg; stacked below lg).

```
 ┌ Form theme ───────────────────────────────┐ ┌ Preview ─────────────────────┐
 │ How your forms look to the people filling │ │ [Light|Dark] [Phone|Desktop] │
 │ them in. Every form uses these unless its │ │ [English|Dhivehi]            │
 │ own settings change them.                 │ │ ┌──────────────────────────┐ │
 │ Colours                                   │ │ │ (logo)                   │ │
 │  Primary      [■][#0F766E]      Reset     │ │ │ Youth programme          │ │
 │  Page background [■][        ]  (default) │ │ │ Step 1 of 2  ▬▬▬▬▬▭▭▭▭  │ │
 │  …                                        │ │ │ Full name                │ │
 │  ⓘ Text adjusted to … (Alert)             │ │ │ [                    ]   │ │
 │ Text                                      │ │ │ ( ) Child ( ) Parent     │ │
 │  Latin font   [Inter            ▾]        │ │ │ [        Next        ]   │ │
 │  Thaana font  [MV Faseyha       ▾]        │ │ └──────────────────────────┘ │
 │  Text size    [S|M|L|XL]                  │ └──────────────────────────────┘
 │  Headings     [Compact|Standard|Large]    │
 │ Shape and spacing / Controls / Page …     │
 │                     [Discard] [Save theme]│
 └───────────────────────────────────────────┘
```

- `Card` "Form theme", `CardDescription` as above. Each group is a `FieldSet` with a
  `FieldLegend` ("Colours", "Text", "Shape and spacing", "Controls", "Page") and a
  `FieldSeparator` between groups.
- Colour row: `Field orientation="horizontal"` on ≥ sm: label + description start, then
  `Input type="color"` (44 px) and a hex `Input` (`dir="ltr"`, mono, placeholder shows the
  default in muted text), then a ghost `Button` "Reset" when set. Invalid hex: "Enter a colour
  like #0F766E."
- Fonts: `Select` with each option set in its own face once loaded ("Inter"), Thaana options
  show the name in Latin plus a Thaana sample "ހަކުރު" set in the face. Description under the
  Thaana select: "Fonts come from {host}." (or "Fonts are served by this site.").
- Size, headings, corners, spacing, width, buttons, inputs, progress, logo: `ToggleGroup
  type="single" variant="outline"` (wraps on phones). Colour mode: `RadioGroup` with
  descriptions.
- Full-width buttons: `Field orientation="horizontal"` + `Switch`.
- Images: like branding image rows (thumbnail box, "Upload", "Remove"), saved on upload.
- Adjustments: one `Alert` under the colours listing each adjusted colour with chosen and used
  swatches.
- `Discard` (outline) and `Save theme`; toast "Form theme saved". Members see everything
  disabled with "Only organisation admins can change the form theme."
- Loading: `Skeleton` after 300 ms; error: `Alert` "Couldn't load the form theme. Reload the
  page." with "Try again".

### 3.3 Form › Settings › Appearance

A card "Appearance" first on the form's Settings page (owners and editors change it; viewers
read).

- Same controls and groups as 3.2, showing the **effective** value. A value the form inherits
  carries a muted `Badge variant="outline"` "Organisation" next to its label; a value the form
  changes shows a ghost `Button` "Use organisation setting" (icon `Undo2`) instead. Changing a
  control makes it an override; the button removes the override.
- The card description: "Changes here apply to this form only and show on the live form as
  soon as you save. Everything else follows the organisation's form theme." with a link
  "Edit the organisation theme" for admins.
- Footer: `Discard`, `Save appearance`; toast "Appearance saved".
- The preview card sits under the controls (the settings page is narrow) and uses the same
  samples, starting on the form's language.

### 3.4 Live preview

- `Card` "Preview": `Tabs` Light / Dark (switches the generated tokens; the respondent's
  colour mode setting decides what people actually see), `ToggleGroup` Phone / Desktop and
  `ToggleGroup` English / Dhivehi (a sample form in each language).
- Renders the real `FormRenderer` (mode `preview`, nothing is posted) with a two-page sample
  inside a themed container: phone = 360 px frame, full-bleed sheet; desktop = the page
  background with the sheet at the chosen width. Draft values apply ~250 ms after a change
  (`POST /themes/preview` returns light and dark tokens, font stylesheets and adjustments).
- `aria-hidden` + `inert` with a visually hidden summary "Preview of a sample form with these
  settings." Popovers inside it are not reachable.

### 3.5 Where the theme applies

- **Public form** (and embeds): the page links
  `/api/v1/public/forms/{slug}/theme.css` before the form loads. It holds `@import`s for the
  chosen Latin font (`/theme-fonts/{id}.css`, built from the OFL packages, only fetched when
  used) and Thaana font (the install's font stylesheet for that family) and the CSS variables
  (`:root` and `.dark`). Options that need markup (button/input style, progress, logo position,
  header image, colour mode) come with the form response and become `data-df-*` attributes on
  the form root; `index.css` styles them, so `components/ui` stays untouched.
- **Approver and verify pages**: the same stylesheet and colour mode, linked through the
  form's `brand.themeUrl`.
- **Builder canvas and preview**: the same tokens, scoped to the sheet (inline variables on the
  canvas root). The canvas follows the form's colour mode (Light/Dark); "Match device" follows
  the studio.
- **PDF**: the primary colour for the title rule and section headings, nothing else; fonts stay
  Inter and Noto Sans Thaana (embedded, licensed for it). The PDF stays a
  clean document.
- **Emails** about a form (receipt, approval requests, outcome, owner notification): the
  button uses the form's primary.

### 3.6 RTL

Logical properties only. Logo position "Start" is right in a dv form. Underlined inputs draw a
bottom border only. Thaana sizes keep the 1.12× / 1.75 line-height rule and are multiplied by
the text size; never sized per component.

## 4. Self-critique

| First idea | Problem | Changed to |
|---|---|---|
| A free font picker (any Google font) | Third-party requests from every respondent, CSP holes, unreadable picks | A curated list of OFL fonts served from this origin, plus the install's Thaana list |
| Theme stored in the versioned form schema | Appearance changes would need a publish while the organisation theme applies at once; two mental models | Per-form overrides on the form record, applied when saved |
| Let admins pick dark-mode colours too | Doubles the controls; most admins never check dark | Generated dark values with the same AA checks |
| A palette-style "theme gallery" of presets | Generated-design tell; the job is "make it ours", not "pick a mood" | Plain controls, live preview of a real form |
| Per-row inherit checkboxes | Twice the controls on a long card | Effective value + "Organisation" badge, "Use organisation setting" to undo |
| `/f/{org}/{slug}` kept as the canonical link | Long and leaks the org slug | `/{slug}`, old links redirect |
