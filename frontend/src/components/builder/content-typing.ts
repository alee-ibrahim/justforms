import { useState } from 'react'

import { textDirection, textLang, type TextDirection } from '@/schema/direction'

/** Keyboard state and `dir`/`lang` for a box editing form text. */
export function useContentTyping(value: unknown, hint: TextDirection = 'ltr') {
  const text = typeof value === 'string' ? value : ''
  const [thaana, setThaana] = useState(() => (text.trim() ? textLang(text) === 'dv' : hint === 'rtl'))
  const empty = !text.trim()
  const attrs = {
    dir: empty ? (thaana ? 'rtl' : hint) : textDirection(text, hint),
    // Empty boxes show English prompts ("Add placeholder text…"), so they keep the Latin face.
    lang: empty ? 'en' : textLang(text),
  } as const
  return { thaana, setThaana, attrs }
}
