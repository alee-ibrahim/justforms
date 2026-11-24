/**
 * Display helpers for form text: numbers, phone numbers and percentages inside right-to-left
 * text are wrapped in Unicode isolates so they don't scramble. Display only: stored text is
 * never changed.
 */
import { textDirection } from '@/schema/direction'

// "-5", "+960 333-1234", "9:00", "1,000", "50%" between spaces, punctuation or the ends.
// Adapted from @yashau/thaana (MIT, https://github.com/yashau/fonts.mv).
const NUMBER_TOKEN = /(^|[\s\p{P}\p{S}])(\+\d[\d -]*\d|[+\-\u2212]?\d(?:[\d.,:/-]*\d)?%?)(?=$|[\s\p{P}\p{S}])/gu

/** Wrap numbers in left-to-right isolates (brackets around a number stay outside). */
export function isolateNumbers(text: string): string {
  return text.replace(NUMBER_TOKEN, (_m, prefix: string, token: string) => `${prefix}\u2066${token}\u2069`)
}

export function displayText(text: string): string {
  return textDirection(text) === 'rtl' ? isolateNumbers(text) : text
}
