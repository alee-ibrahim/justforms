# Sharing preview (link cards)

When someone pastes a form's address into a chat app or a social site, the app shows a card:
an image, a title, a line or two of description and the site. JustForms gives every published
form its own card, generated from the form, and lets editors change the text and upload their
own image.

## 1. Page tags

Link-preview crawlers don't run scripts, so the public form page (`/{slug}`, also
`?embed=1`, closed forms) carries the tags in its HTML:

| Tag | Value |
|---|---|
| `<title>`, `og:title`, `twitter:title` | Share title, else the live form title |
| `description`, `og:description`, `twitter:description` | Share description, else the form description as plain text (Markdown removed), cut at 200 characters on a word |
| `og:image`, `twitter:image` | Absolute URL of the image, versioned (`?v=`), with `og:image:type`, `:width`, `:height`, `:alt` (the title) |
| `og:url`, `<link rel="canonical">` | `{public URL}/{slug}` (no query) |
| `og:type` | `website` |
| `og:site_name` | The organisation's display name (branding) |
| `og:locale` | `en_US` or `dv_MV` from the form language |
| `twitter:card` | `summary_large_image` |

- **How.** nginx already asks the API for every public form page (`auth_request` to
  `/api/v1/public/frame-ancestors`, which returns the form's framing sites). The same answer
  carries the tags in `X-JustForms-Head`; nginx `sub_filter` swaps the page's placeholder
  `<title>Form</title>` for them. No answer (older API, error): the placeholder stays. The API
  down: the plain page is served (`error_page` fallback), as before the form app shows its own
  error. The page stays `Cache-Control: no-cache` (always revalidated, about 2 KB).
- **Safety.** Every value is HTML-escaped and every non-ASCII character is written as a
  character reference (`&#1932;`), so the header is ASCII without line breaks and user text
  can't close a tag or add a header.
- **Unknown, unpublished and archived addresses** get the site's tags only: the default
  organisation's name as title and site name, the site card image, no description, no URL.
  Nothing about the form (not even its title) is sent before it is published.
- Studio pages keep their own static tags.

## 2. Generated image

1200 × 630 PNG (about 50–120 KB), drawn as a one-page PDF with fpdf2 and HarfBuzz
(uharfbuzz), as the signed PDFs are, and rasterised with pdfium. No system libraries: Pillow's
own complex text layout needs libraqm and FriBiDi, which slim containers lack.

```
┌──────────────────────────────────────────────────────────────┐
│  [logo]  Organisation name                                   │  72 px margins
│                                                              │
│  Form title in bold, as large as fits                        │  76 → 44 px, ≤ 3 lines
│  in up to three lines…                                       │
│  Description in muted text, up to two lines…                 │  30 px, ≤ 2 lines
│                                                              │
│  forms.example.org/form-address                              │  26 px, muted
█████████████████████████████████████████████████████████████████  14 px primary band
└──────────────────────────────────────────────────────────────┘
```

- **Direction.** Dhivehi forms mirror: logo at the top right, name to its left, text
  right-aligned and shaped right to left in Noto Sans Thaana (×1.12, line height 1.45). The
  address is always left to right.
- **Fit.** The title and description are centred in the space between the header and the
  address. The title takes the largest size at which it fits three lines with the
  description; if it can't, the description drops to one line, then none; at the smallest size
  the third line ends with an ellipsis.
- **Theme.** Card background, text, muted text and primary band from the form theme's light
  values (contrast already checked by the theme, DESIGN 18.3). Latin text is always Atkinson
  Hyperlegible Next (the theme's other Latin fonts are web fonts only).
- **Logo.** The form's own logo, else the organisation's logo, else its icon; none when the
  theme hides the logo. PNG or the sanitised SVG.
- **Cache.** Stored at `og/{form_id}/{version}.png`. `version` hashes everything drawn
  (title, description, organisation name, address, direction, colours, logo hash, renderer
  version), so publishing a new title, a branding or theme change, or a new share title gives a
  new image at a new address, made on first request; the previous file is deleted.
  `GET /api/v1/public/forms/{slug}/og.png?v={version}` answers with a year's immutable cache,
  an `ETag` (304 on `If-None-Match`), `Cross-Origin-Resource-Policy: cross-origin` and a
  sandbox CSP; another or no `v` gets a 5-minute cache. Unpublished and archived forms: 404.
- **Site card.** `/api/v1/public/og/site.png`: the organisation name as the title, with its logo.

## 3. Settings › Sharing preview

A section of the form's Settings, after Appearance. Viewers see it read-only; editors and
owners change it (like Appearance).

```
┌ Sharing preview ─────────────────────────────┐  ┌ Preview ───────────────────────┐
│ What chat apps and social sites show when    │  │ [Chat app|Social feed|Short post]│
│ someone shares this form's link. …           │  │        ┌──────────────────────┐ │
│ (i) This form isn't published yet. …          │  │        │ [image 1.91:1]       │ │
│ Title                                        │  │        │ Title (2 lines)      │ │
│ [ placeholder: the form title            ]   │  │        │ Description (2 lines)│ │
│ Leave empty to use the form title.           │  │        │ forms.example.org    │ │
│ Description                                  │  │        └──────────────────────┘ │
│ [                                        ]   │  │        https://…/form-address  │
│ Leave empty to use the form's description.   │  └────────────────────────────────┘
│ Image  (Generated)                           │
│ [thumb]  [⇪ Upload image]                    │
│ Made from the title, … It updates when you   │
│ save. PNG, JPEG or WebP up to 5 MB; …        │
├──────────────────────────────────────────────┤
│                         [Discard]  [Save]    │
└──────────────────────────────────────────────┘
```

- Components: `Card`, `Field`/`FieldLabel`/`FieldDescription`/`FieldError`, `Input`,
  `Textarea`, `Badge` (Generated / Uploaded), `Button` (outline Upload / Replace, ghost "Use
  generated image"), `Alert`, `Tabs`, `Spinner`, `Skeleton`. Nothing new to add.
- Title and description inputs carry the form language (`contentProps`), so Thaana types and
  reads right to left; the placeholders show the form's own text. Limits 120 and 300
  characters; whitespace is collapsed on save; empty goes back to the form's text.
- Text saves with **Save** (toast "Sharing preview saved"); the image saves on upload (toast
  "Image uploaded") and **Use generated image** removes the upload (toast "Using the generated
  image"). The generated thumbnail and the preview's image update after Save.
- Upload: PNG, JPEG or WebP, ≤ 5 MB and 8000 px; decoded with Pillow, metadata dropped,
  transparency flattened on white, cropped to 1.91:1 from the centre, scaled down to
  1200 × 630 (never up; at least 200 × 105) and re-encoded as JPEG under ~300 KB. Stored at
  `og/{form_id}/custom-{sha16}.jpg`; served at `/api/v1/public/forms/{slug}/og.jpg?v=c…`.
- Preview tabs (composition of tokens, `aria-hidden`, with an `sr-only` summary): **Chat app**
  (a message bubble with the card and the link), **Social feed** (image, then site, title and
  one line of description on a muted band), **Short post** (image with the title over its
  bottom start, "From {site}" below). Card text uses the form language's direction.
- Errors (`FieldError` under the image): "That file isn't a PNG, JPEG or WebP image.", "The
  file is larger than 5 MB.", "The image is larger than 8000 pixels on a side.", "The image is
  too small. Use one of 1200 × 630 pixels." (under 200 × 105)
- Not published: an `Alert` "This form isn't published yet. Until it is, its link shows only the
  site's name." The preview uses the draft's title meanwhile.
- API: `GET/PUT /forms/{id}/sharing`, `PUT/DELETE /forms/{id}/sharing/image` (raw body),
  `GET /forms/{id}/sharing/image?v=` (the current image for the studio, private cache).
  Stored in `forms.settings["sharing"]`; not copied by Duplicate (a key not under the form's
  own id is ignored).

## 4. Caching outside JustForms

Chat apps and social sites keep their own copy of a card for days. A changed title or image
shows in new shares once their cache expires; most sites offer a "debug"/"scrape again" tool
to refresh one address. A CDN in front of JustForms may cache the image (its URL is versioned,
so that is safe) but must not cache the HTML page beyond its `no-cache`.
