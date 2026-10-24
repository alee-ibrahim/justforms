# JustForms brand

The logo is the word **justforms** in Atkinson Hyperlegible Next Bold (the UI typeface), set as
outlines with the font's own kerning. The o of "forms" is a selected radio button: a ring and a
filled dot, drawn to the o's height, width and weight. Where the word doesn't fit, that radio o
stands alone on a carbon tile.

## Files

| File | Use |
|---|---|
| `justforms-logo.svg` / `.png` | Full colour on light backgrounds: ink letters, carbon dot |
| `justforms-logo-dark.svg` / `.png` | Full colour on dark backgrounds |
| `justforms-logo-mono-ink.svg` | One colour, ink (print, fax, stamps, light photos) |
| `justforms-logo-mono-white.svg` | One colour, white (on carbon or dark photos) |
| `justforms-mark.svg`, `justforms-mark-dark.svg` | The radio o alone, without a tile |
| `justforms-icon.svg`, `justforms-icon-512.png` | App icon: carbon tile, white ring, marker dot |
| `justforms-icon-maskable.svg`, `justforms-icon-maskable-512.png` | PWA maskable icon (full bleed, mark inside the 80% safe zone) |
| `justforms-apple-touch-icon.png` | 180 px home-screen icon (full bleed; iOS rounds the corners) |
| `favicon.svg` | Favicon, drawn on a 16 px grid so the ring and dot land on whole pixels |
| `social-preview.png` | 1280 × 640 repository social preview |

The app serves its own copies from `frontend/public/` (favicons, touch icon, PWA icons and
manifests). The studio header and the public form footer draw the logo inline
(`frontend/src/components/brand/`), so the letters follow the text colour and the dot follows
`--primary` in light and dark mode.

## Colours

| Name | Light | Dark | Used for |
|---|---|---|---|
| Ink | `#18203A` | `#E6E9F2` | Letters and ring |
| Carbon | `#3B3FC1` | `#9DA2FF` | Radio dot; icon tile |
| Marker | `#FFE45C` | | Radio dot on the icon tile only |
| Desk | `#F3F5F9` | `#121729` | Preferred background |

These are the design-system colours (`docs/ux/DESIGN-SYSTEM.md` §3).

## Rules

- **Clear space:** keep at least the height of the radio o free on every side of the
  wordmark, and a quarter of the tile's width around the icon.
- **Minimum size:** wordmark 14 px tall on screen (about 70 px wide) or 18 mm wide in print.
  Below that, use the icon. The favicon is made for 16 px; use the app icon from 48 px up.
- Keep the dot inside the ring and the ring the same weight as the letters. Don't redraw the
  o as a plain letter, add a separate radio symbol in front of the word, or set "justforms" in
  live text.
- Lower case only. Write the name as "JustForms" in running text.
- Don't stretch, rotate, outline, add shadows or gradients, or recolour beyond the variants
  above. On photos or busy backgrounds use a one-colour version.
- The marker-yellow dot belongs to the icon tile. In the wordmark the dot is carbon (or the
  single colour of a mono version).

## Regenerating

The SVGs are generated from the font (HarfBuzz shaping, fontTools outlines), not drawn by hand.
Radio geometry in font units at weight 700: centred on the o's bounding box, outer radius = the
o's half height (≈ 261.5), ring stroke 112, dot radius 96.
