# Branding (white-label)

Each organisation can replace JustForms' identity with its own: name, logo, icon, primary
colour, a support link and whether "Powered by JustForms" shows. An instance sets defaults
through environment variables (or Helm values); an organisation's own settings win over them;
JustForms' identity is the fallback when nothing is set (DESIGN §18.2). Tokens, type and motion
come from [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md); review with
[REVIEW-CHECKLIST.md](REVIEW-CHECKLIST.md). Copy in "quotes" ships as written, English only.

Nothing new from shadcn: `card`, `field`, `input`, `switch`, `button`, `alert`, `tabs`,
`toggle-group`, `badge`, `separator`, `skeleton`, `spinner`, `empty`, `tooltip` and
`dropdown-menu` are installed.

## 1. What an organisation can set

| Setting | Rules | Fallback |
|---|---|---|
| Display name | 1–80 characters | the organisation's name |
| Logo (light) | PNG or SVG, ≤ 512 KB, ≤ 4096 px a side; shown ≤ 32 px tall in headers | instance logo, then the JustForms wordmark |
| Logo for dark mode | optional, same rules | the light logo |
| Icon | square PNG (≥ 64 px, ≤ 1024 px) or square SVG; favicon, app icon, email/PDF mark | instance icon, then the JustForms mark |
| Primary colour | `#RRGGBB` | instance colour, then Carbon |
| Support link | `https://…` or `mailto:…`, ≤ 300 characters | instance link, else none |
| Hide "Powered by JustForms" | switch; disabled with an explanation when the instance forces it | shown |

SVGs are sanitised on upload (only shape, text, gradient and clip elements; no scripts, event
handlers, `<style>`, `<foreignObject>`, external references, `javascript:` or remote
`url()`); anything that can't be cleaned is refused. Files go through the storage
abstraction and are served from the app's own origin with `Content-Security-Policy:
default-src 'none'; style-src 'unsafe-inline'; sandbox`, `nosniff` and a content-hash
version in the URL (cached a year).

The colour becomes a token set (`--primary`, `--primary-foreground`, `--ring`,
`--sidebar-primary`, `--chart-1` for light and dark). The server checks contrast and adjusts:
light `--primary` must reach 4.5:1 on the sheet (white) and the desk; dark `--primary` 4.5:1
on the dark sheet and desk; `--primary-foreground` is white or ink, whichever reads at ≥ 4.5:1
on the primary. If the chosen colour had to be darkened or lightened the form says so and
shows the colour that will be used. Marker (selection wash) and Stamp (errors) stay JustForms':
they carry meaning, not brand.

## 2. Where it shows

- Studio header (logo or icon + name), sign-in page, browser tab title ("Forms – Example
  Youth Office"), favicon, web app manifest (`/api/v1/public/branding/{org}/manifest.webmanifest`).
  The default organisation's icon is also served at `/favicon.ico`, `/favicon.svg` and
  `/apple-touch-icon.png` (and its manifest at the root manifest paths), so the first page load
  shows it with no flash of the JustForms mark.
- Public form: logo (or name) above the form title; footer under the sheet with the support
  link and "Powered by JustForms". Tab title "{form title} – {name}", favicon and manifest.
- Approver page and verify page: same header and footer; verify says "Issued by {name}".
- Emails: sender display name (`"{name}" <address from JUSTFORMS_SMTP_FROM>`), a header with the
  PNG logo (or the name in text when the logo is an SVG: mail clients don't show SVG), footer
  "Sent by {name}." + support link + "Powered by JustForms".
- PDF: header logo (PNG or SVG) + name at the top of page 1; footer "{name}" next to the page
  number. Layout and margins don't change.
- Excel export: workbook properties (creator and description name the organisation, title =
  the form title).

Sign-in has no organisation yet: it uses the **default organisation's** branding (the one new
users join, `JUSTFORMS_DEFAULT_ORG_SLUG`), which itself falls back to the instance defaults.
The studio uses the signed-in user's organisation.

Theme tokens arrive as a stylesheet (`/api/v1/public/branding/{org}/theme.css?v=…`) linked
at start-up, so the public bundle only gains a few lines of JS; there is no flash of the
JustForms colour on a cached load. Embedded forms (`?embed=1`) skip the header logo and footer
(the host page carries the brand) but keep the colour.

## 3. Settings: Organisation settings › Branding

Route `/settings`, reached from the account menu ("Organisation settings", org admins and
superadmins only; members don't see the item and get "Only organisation admins can change
branding." if they open the URL). The page uses `PageContainer` (wide) with a two-column grid
on ≥ lg: the form card on the start side, the sticky live preview on the end side. Below lg
the preview follows the form.

```
 Organisation settings                                       (h1, text-xl)
 ┌ Branding ───────────────────────────────┐ ┌ Preview ───────────────────┐
 │ Your name, logo and colour on the studio,│ │ [Light|Dark]   [Phone|Desk]│
 │ forms, emails and PDFs.                  │ │ ┌───────────────────────┐ │
 │ Display name [ Example Youth Office    ] │ │ │ ▣ Example Youth Office│ │
 │ Logo        [▣ preview] [Upload] [Remove]│ │ │ Youth programme       │ │
 │   PNG or SVG, up to 512 KB.              │ │ │ [ Full name        ]  │ │
 │ Logo for dark mode [Upload]              │ │ │ [  Next  ] (primary)  │ │
 │ Icon        [▣] [Upload]                 │ │ │ Help · Powered by …   │ │
 │   Square PNG or SVG. Used as the favicon.│ │ └───────────────────────┘ │
 │ Primary colour [■][ #0F766E ]            │ └────────────────────────────┘
 │   ⚠ Darkened to #0D6B63 so text on it    │
 │     reads at 4.5:1. (Alert, not stamp)   │
 │ Support link [ https://example.org/help ]│
 │ Hide "Powered by JustForms"          [ ]   │
 │                     [Discard] [Save]     │
 └──────────────────────────────────────────┘
```

- `Card` "Branding", `CardDescription` "Your name, logo and colour on the studio, your forms,
  emails and PDFs. Empty fields use the defaults."
- Text fields: `Field` + `FieldLabel` + `Input` + `FieldDescription`; errors in `FieldError`.
- Each image row: a 40 px tall thumbnail on a checkerboard-free `bg-muted` box (`rounded-md
  border`), an `Input type="file"` (accept `image/png,image/svg+xml`) behind a `Button
  variant="outline"` label "Upload logo" / "Replace", and a ghost "Remove". Upload starts at
  once and shows a `Spinner` in the button; errors appear under the row:
  "That file isn't a PNG or SVG.", "The file is larger than 512 KB.", "The icon must be
  square.", "This SVG contains scripts or external content and can't be used."
- Colour: `Input type="color"` (44 px swatch) next to a hex `Input` (`dir="ltr"`, mono).
  Invalid hex: "Enter a colour like #0F766E." When adjusted: `Alert` (default variant, info
  icon) "Adjusted to {hex} so text stays readable (contrast {ratio}:1)." Two swatches show
  chosen and used colour.
- Support link: `Input type="url"`, description "Shown at the bottom of your forms and emails."
  Error: "Enter a link starting with https:// or mailto:."
- Powered by: `Field orientation="horizontal"` + `Switch` "Hide "Powered by JustForms"". When
  the instance forces it: disabled, description "This server always shows it."
- Footer actions `Discard` (outline) and `Save branding`; toast "Branding saved". Images save
  on upload (toast "Logo uploaded"), the rest on Save.
- Loading: `Skeleton` rows after 300 ms. Load error: `Alert` "Couldn't load branding. Reload
  the page." with "Try again".

### Live preview

A `Card` "Preview" with `Tabs` "Light" / "Dark" and a `ToggleGroup` "Phone" / "Desktop"
(icons + labels). It renders a miniature of the public form sheet (header with logo or name,
a title, one input, the primary button, the footer) and the studio header strip, scoped by
CSS variables on the preview container (`.dark` class for the dark tab), using the draft
values before saving. Phone is a 360 px wide frame, desktop the full card width. The preview
is `aria-hidden` with a visually hidden summary ("Preview of your forms with these
settings").

Phone layout (< lg): single column; preview below the form card; Save stays at the bottom
of the form card. All controls ≥ 44 px on touch.

## 4. Self-critique

- First idea: a separate "Brand" page per form. Dropped: branding is an organisation fact; per
  form only the accent stays (already exists, it overrides the org primary inside the form).
- First idea: let the colour pass unchecked with a warning. Changed: AA is a hard rule here,
  so the server adjusts and says so; the builder still sees their choice next to the result.
- First idea: rasterise SVG uploads server-side. Changed: sanitising keeps them crisp and
  small; email (no SVG support in mail clients) falls back to the name in text, and the form
  hints "Upload a PNG logo to show it in emails".
- Avoided generated-design tells: no gradient preview frame, no shadowed card grid, no
  uppercase eyebrows; the preview reuses the real sheet styles.
