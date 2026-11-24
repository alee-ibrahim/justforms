/**
 * Direction of form content (docs/DESIGN.md §16). Kept free of zod and the JSON spec so the
 * public renderer bundle can import it cheaply.
 *
 * A form has no language: English and Dhivehi can sit side by side, even in one label. Each
 * piece of text (each line of multi-line text) takes its direction from its dominant script
 * (more Thaana or more Latin words; a tie goes to the first strong character): Thaana reads
 * right to left, Latin left to right. Alignment is an optional override
 * (`align` on elements and pages, `settings.align` as the form default). Twin of
 * backend/app/schemas/direction.py; both run spec/direction/vectors.json.
 */
import type { CSSProperties } from 'react'

import type { JustFormsForm as Form } from './generated/form'

export type TextDirection = 'ltr' | 'rtl'
export type TextAlign = 'auto' | 'left' | 'center' | 'right' | 'justify'
export type ContentLang = 'dv' | 'en'

const THAANA = /[\u0780-\u07BF]/
// Strong right-to-left letters: Hebrew, Arabic, Syriac, Thaana, NKo and their extensions.
const RTL_LETTER = /[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]|[\u{10800}-\u{10FFF}\u{1E800}-\u{1EFFF}]/u
const LETTER = /\p{L}/u

export function hasThaana(text: string | null | undefined): boolean {
  return !!text && THAANA.test(text)
}

const MARK = /\p{M}/u

/**
 * Direction of `text` from its **dominant script**: the script with more words (runs of strong
 * letters, combining marks included) wins, so a Dhivehi line that starts with a Latin acronym
 * or a number ("PPY ގެ ބައިވެރިން ކޮބާ؟", "2026 ވަނަ އަހަރު.") still reads right to left and an
 * English line that starts with a Thaana word reads left to right. Words, not characters, are
 * counted: Thaana vowels are separate marks and English words are longer, so character counts
 * would skew bilingual labels. A tie ("Name / ނަން") goes to the first strong character
 * (Unicode bidi rule P2); `fallback` when the text has no letters.
 */
export function textDirection(text: string | null | undefined, fallback: TextDirection = 'ltr'): TextDirection {
  let first: TextDirection | null = null
  let rtl = 0
  let ltr = 0
  let run: TextDirection | null = null
  for (const ch of text ?? '') {
    if (LETTER.test(ch)) {
      const dir: TextDirection = RTL_LETTER.test(ch) ? 'rtl' : 'ltr'
      first ??= dir
      if (dir !== run) {
        if (dir === 'rtl') rtl++
        else ltr++
        run = dir
      }
    } else if (!MARK.test(ch)) {
      run = null
    }
  }
  if (rtl !== ltr) return rtl > ltr ? 'rtl' : 'ltr'
  return first ?? fallback
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
 * break-separated paragraph takes its own direction from its dominant script, so an
 * English paragraph followed by Dhivehi ones reads left to right, then right to left. A line with no strong character (blank, figures) takes the
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
 * Dhivehi lines after it each start at their own edge while typing. The browser picks each
 * typed line's direction by its first strong character (it can't count words); the saved text
 * is shown by the dominant-script rule.
 */
export const PER_LINE = '[unicode-bidi:plaintext] text-start'

/**
 * `lang` for a box where (possibly multi-line) form text is typed: one `lang` covers every
 * line, so it is `dv` only when every line with letters is Dhivehi. An English line keeps the
 * Latin face (Thaana still renders from the font stack) instead of the Thaana face's Latin glyphs.
 */
export function boxLang(text: string | null | undefined): ContentLang {
  if (!isMultiline(text)) return textLang(text)
  const lines = textLines(text).filter((l) => LETTER.test(l.text))
  return lines.length && lines.every((l) => l.lang === 'dv') ? 'dv' : 'en'
}

/** True when `text` holds a line break (render it with per-line direction). */
export function isMultiline(text: string | null | undefined): boolean {
  return !!text && /[\r\n]/.test(text)
}

/**
 * The explicit left/center/right/justify a text resolves to (the element's own, then the form
 * default), or `null` for `auto`: each paragraph then aligns to its own direction. `justify` is
 * relative to each paragraph's direction too (its last line sits at the start edge).
 */
export function explicitAlign(
  align: TextAlign | null | undefined,
  fallback: TextAlign | null | undefined,
): 'left' | 'center' | 'right' | 'justify' | null {
  for (const value of [align, fallback]) {
    if (value === 'left' || value === 'center' || value === 'right' || value === 'justify') return value
    if (value === 'auto') break
  }
  return null
}

/**
 * Physical alignment of a text: an explicit left/center/right wins (the element's own, then
 * the form default); `auto` (or nothing) follows the text's direction, and so does `justify`
 * (a single line, or the last line of a justified paragraph, sits at its start edge).
 */
export function resolveAlign(
  align: TextAlign | null | undefined,
  fallback: TextAlign | null | undefined,
  dir: TextDirection,
): 'left' | 'center' | 'right' {
  const side = explicitAlign(align, fallback)
  if (side && side !== 'justify') return side
  // auto, and justify for a single line: the text's start edge.
  return dir === 'rtl' ? 'right' : 'left'
}

/**
 * Style of one paragraph of multi-line form text. `auto` aligns it to its own start edge
 * (`text-align: start` resolves against the paragraph's own `dir`); left/center/right apply to
 * every paragraph. `measure`: the paragraph is width-capped, so its box also moves to that side
 * (for `auto`, the end margin of its own direction).
 */
export function paragraphStyle(align: TextAlign, measure = false): CSSProperties {
  // Justify follows each paragraph's direction: its last line ends at the paragraph's start
  // edge (right for Dhivehi, left for English), so short lines never get stretched gaps.
  if (align === 'justify')
    return measure
      ? { textAlign: 'justify', textAlignLast: 'start', marginInlineEnd: 'auto' }
      : { textAlign: 'justify', textAlignLast: 'start' }
  if (align === 'auto') return measure ? { textAlign: 'start', marginInlineEnd: 'auto' } : { textAlign: 'start' }
  if (!measure) return { textAlign: align }
  if (align === 'center') return { textAlign: align, marginInline: 'auto' }
  return { textAlign: align, [align === 'left' ? 'marginRight' : 'marginLeft']: 'auto' }
}
