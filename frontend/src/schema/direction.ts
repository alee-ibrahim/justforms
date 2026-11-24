/**
 * Direction of form content (docs/DESIGN.md §16). Kept free of zod and the JSON spec so the
 * public renderer bundle can import it cheaply.
 *
 * A form has no language: English and Dhivehi can sit side by side, even in one label. Each
 * piece of text takes its direction from its first strong character (Unicode bidi rule P2):
 * Thaana reads right to left, Latin left to right. Alignment is an optional override
 * (`align` on elements and pages, `settings.align` as the form default). Twin of
 * backend/app/schemas/direction.py; both run spec/direction/vectors.json.
 */
import type { JustFormsForm as Form } from './generated/form'

export type TextDirection = 'ltr' | 'rtl'
export type TextAlign = 'auto' | 'left' | 'center' | 'right'
export type ContentLang = 'dv' | 'en'

const THAANA = /[\u0780-\u07BF]/
// Strong right-to-left letters: Hebrew, Arabic, Syriac, Thaana, NKo and their extensions.
const RTL_LETTER = /[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]|[\u{10800}-\u{10FFF}\u{1E800}-\u{1EFFF}]/u
const LETTER = /\p{L}/u

export function hasThaana(text: string | null | undefined): boolean {
  return !!text && THAANA.test(text)
}

/** Direction of `text` from its first strong character; `fallback` when it has none. */
export function textDirection(text: string | null | undefined, fallback: TextDirection = 'ltr'): TextDirection {
  for (const ch of text ?? '') {
    if (!LETTER.test(ch)) continue
    return RTL_LETTER.test(ch) ? 'rtl' : 'ltr'
  }
  return fallback
}

/** `lang` for a piece of form text: `dv` when it reads right to left in Thaana. */
export function textLang(text: string | null | undefined): ContentLang {
  return textDirection(text) === 'rtl' && hasThaana(text) ? 'dv' : 'en'
}

/**
 * Direction of the form sheet's own layout (progress, Back/Next order): the form title's.
 * A form whose title is Dhivehi lays out right to left, as before the per-text model.
 */
export function formDirection(form: Pick<Form, 'settings'>): TextDirection {
  return textDirection(form.settings.title)
}

/**
 * Physical alignment of a text: an explicit left/center/right wins (the element's own, then
 * the form default); `auto` (or nothing) follows the text's direction.
 */
export function resolveAlign(
  align: TextAlign | null | undefined,
  fallback: TextAlign | null | undefined,
  dir: TextDirection,
): 'left' | 'center' | 'right' {
  for (const value of [align, fallback]) {
    if (value === 'left' || value === 'center' || value === 'right') return value
    if (value === 'auto') break
  }
  return dir === 'rtl' ? 'right' : 'left'
}
