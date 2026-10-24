/**
 * Phonetic Thaana typing on a standard shadcn Input/Textarea, provided by @yashau/thaana
 * (MIT, standard Divehi Phonetic layout). Loaded lazily by the public renderer.
 * Paste, IME composition and real Dhivehi keyboards pass through; native undo is kept.
 */
import { attachKeyboard } from '@yashau/thaana-react'

/** Attach phonetic typing to `el`; returns a function that detaches it. */
export function attachPhonetic(el: HTMLInputElement | HTMLTextAreaElement): () => void {
  return attachKeyboard(el)
}
