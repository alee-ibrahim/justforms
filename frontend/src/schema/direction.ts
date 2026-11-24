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
import type { CSSProperties } from 'react'

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

export interface TextLine {
  text: string
  dir: TextDirection
  lang: ContentLang
}

/**
 * Multi-line text (descriptions, paragraphs, long answers) line by line: each line
 * break-separated paragraph takes its own direction from its first strong character, so an
 * English paragraph followed by Dhivehi ones reads left to right, then right to left (as CSS
 * `unicode-bidi: plaintext`). A line with no strong character (blank, figures) takes the
 * direction of the whole text.
 */
export function textLines(text: string | null | undefined, fallback: TextDirection = 'ltr'): TextLine[] {
  const base = textDirection(text, fallback)
  return (text ?? '').split(/\r\n|\r|\n/).map((line) => ({
    text: line,
    dir: textDirection(line, base),
    lang: textLang(line),
  }))
}

/**
 * Class for boxes where multi-line form text is typed (textareas): each line break-separated
 * paragraph takes its direction from its own first strong character (`unicode-bidi:
 * plaintext`) and `text-align: start` resolves per paragraph, so an English line and the
 * Dhivehi lines after it each start at their own edge while typing.
 */
export const PER_LINE = '[unicode-bidi:plaintext] text-start'

/** True when `text` holds a line break (render it with per-line direction). */
export function isMultiline(text: string | null | undefined): boolean {
  return !!text && /[\r\n]/.test(text)
}

/**
 * The explicit left/center/right a text resolves to (the element's own, then the form
 * default), or `null` for `auto`: each paragraph then aligns to its own direction.
 */
export function explicitAlign(
  align: TextAlign | null | undefined,
  fallback: TextAlign | null | undefined,
): 'left' | 'center' | 'right' | null {
  for (const value of [align, fallback]) {
    if (value === 'left' || value === 'center' || value === 'right') return value
    if (value === 'auto') break
  }
  return null
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
  return explicitAlign(align, fallback) ?? (dir === 'rtl' ? 'right' : 'left')
}

/**
 * Style of one paragraph of multi-line form text. `auto` aligns it to its own start edge
 * (`text-align: start` resolves against the paragraph's own `dir`); left/center/right apply to
 * every paragraph. `measure`: the paragraph is width-capped, so its box also moves to that side
 * (for `auto`, the end margin of its own direction).
 */
export function paragraphStyle(align: TextAlign, measure = false): CSSProperties {
  if (align === 'auto') return measure ? { textAlign: 'start', marginInlineEnd: 'auto' } : { textAlign: 'start' }
  if (!measure) return { textAlign: align }
  if (align === 'center') return { textAlign: align, marginInline: 'auto' }
  return { textAlign: align, [align === 'left' ? 'marginRight' : 'marginLeft']: 'auto' }
}
