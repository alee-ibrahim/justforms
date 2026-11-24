/**
 * Studio-side helpers for form text direction and alignment, kept out of direction.ts so the
 * public form's bundle doesn't carry them.
 */
import { resolveAlign, textDirection, textLang, type ContentLang, type TextAlign, type TextDirection } from './direction'

/** `lang` and `dir` for an element that shows one piece of form text. */
export function textProps(
  text: string | null | undefined,
  fallback: TextDirection = 'ltr',
): { lang: ContentLang; dir: TextDirection } {
  return { lang: textLang(text), dir: textDirection(text, fallback) }
}

/**
 * Tailwind class for an alignment inside an element whose direction is `dir`. Logical classes
 * only (the lint bans text-left/text-right): left in a right-to-left block is its end.
 */
export function alignClass(
  align: TextAlign | null | undefined,
  fallback: TextAlign | null | undefined,
  dir: TextDirection,
): string {
  const side = resolveAlign(align, fallback, dir)
  if (side === 'center') return 'text-center'
  return (side === 'right') === (dir === 'rtl') ? 'text-start' : 'text-end'
}

export const ALIGN_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'left', label: 'Left' },
  { value: 'center', label: 'Center' },
  { value: 'right', label: 'Right' },
] as const satisfies readonly { value: TextAlign; label: string }[]
