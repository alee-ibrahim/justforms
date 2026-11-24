/**
 * Display helpers for form text (from @yashau/thaana): numbers, phone numbers and percentages
 * inside right-to-left text are wrapped in Unicode isolates so they don't scramble.
 * Display only: stored text is never changed.
 */
import { isolateNumbers } from '@yashau/thaana-react'

import { textDirection } from '@/schema/direction'

export function displayText(text: string): string {
  return textDirection(text) === 'rtl' ? isolateNumbers(text, true) : text
}
