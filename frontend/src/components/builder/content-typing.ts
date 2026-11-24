import { boxLang, textDirection, type TextDirection } from '@/schema/direction'

/** `dir`/`lang` for a box editing form text: they follow what is typed. */
export function contentTyping(value: unknown, hint: TextDirection = 'ltr') {
  const text = typeof value === 'string' ? value : ''
  const empty = !text.trim()
  return {
    dir: empty ? hint : textDirection(text, hint),
    // Empty boxes show English prompts ("Add placeholder text…"), so they keep the Latin face.
    lang: empty ? 'en' : boxLang(text),
  } as const
}
