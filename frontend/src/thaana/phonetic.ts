/**
 * Phonetic Thaana typing on a standard shadcn Input/Textarea, provided by @yashau/thaana
 * (MIT, standard Divehi Phonetic layout). Loaded lazily by the public renderer.
 * Paste, IME composition and real Dhivehi keyboards pass through; native undo is kept.
 */
import { attachKeyboard } from '@yashau/thaana-react'

/** Attach phonetic typing to `el`; returns a function that detaches it. The box's `dir` is
 * left to its component, which follows the typed text's first strong character. */
export function attachPhonetic(el: HTMLInputElement | HTMLTextAreaElement): () => void {
  return attachKeyboard(el, { autoDirection: false })
}
