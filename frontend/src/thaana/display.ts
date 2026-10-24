/**
 * Display helpers for form text in Dhivehi (from @yashau/thaana): numbers, phone numbers and
 * percentages inside RTL text are wrapped in Unicode isolates so they don't scramble.
 * Display only: stored text is never changed.
 */
import { isolateNumbers } from '@yashau/thaana-react'

import type { FormLanguage } from '@/schema/language'

export function displayText(text: string, language: FormLanguage): string {
  return language === 'dv' ? isolateNumbers(text, true) : text
}
