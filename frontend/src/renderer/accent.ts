/**
 * Form accent (settings.theme.accent): replaces --primary and --ring inside the form root
 * only. If the colour is below 4.5:1 against white it is darkened in OKLCH lightness steps
 * until it passes (DESIGN-SYSTEM 3.3).
 */

type RGB = [number, number, number]

const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const toGamma = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055)

function parseHex(hex: string): RGB | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex)
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255) as RGB
}

function toHex(rgb: RGB): string {
  return (
    '#' +
    rgb
      .map((v) =>
        Math.round(Math.min(1, Math.max(0, v)) * 255)
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')
  )
}

function luminance(rgb: RGB): number {
  const [r, g, b] = rgb.map(toLinear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrastWithWhite(rgb: RGB): number {
  return 1.05 / (luminance(rgb) + 0.05)
}

function rgbToOklab([r, g, b]: RGB): RGB {
  const [lr, lg, lb] = [r, g, b].map(toLinear)
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb)
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb)
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

function oklabToRgb([L, a, b]: RGB): RGB {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map((v) => toGamma(Math.min(1, Math.max(0, v)))) as RGB
}

/** The accent as a hex colour that has at least 4.5:1 contrast with white, or null. */
export function legibleAccent(hex: string | null | undefined): string | null {
  const rgb = hex ? parseHex(hex) : null
  if (!rgb) return null
  let lab = rgbToOklab(rgb)
  let out = rgb
  for (let i = 0; i < 60 && contrastWithWhite(out) < 4.5; i++) {
    lab = [lab[0] - 0.02, lab[1], lab[2]]
    out = oklabToRgb(lab)
  }
  return toHex(out)
}
