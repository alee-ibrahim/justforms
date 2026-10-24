/** Answers as short text for tables and the detail view. */
import type { FieldElement, FormLanguage } from '@/schema'

export function answerText(field: FieldElement, value: unknown, language: FormLanguage): string {
  if (value === undefined || value === null) return ''
  switch (field.type) {
    case 'yes_no':
      // "Yes" / "No" are system words, so English for every form.
      return value === true ? 'Yes' : value === false ? 'No' : ''
    case 'single_choice':
      return field.options.find((o) => o.value === value)?.label ?? String(value)
    case 'multi_choice':
      return Array.isArray(value)
        ? value.map((v) => field.options.find((o) => o.value === v)?.label ?? String(v)).join(language === 'dv' ? '، ' : ', ')
        : String(value)
    case 'file':
      return Array.isArray(value) ? value.map((f: { name?: string }) => f.name ?? 'file').join(', ') : ''
    case 'signature':
      return 'Signed'
    case 'phone':
      return formatPhone(String(value))
    default:
      return typeof value === 'object' ? JSON.stringify(value) : String(value)
  }
}

/**
 * A phone number grouped for reading: "+960 777 1234" for the 7-digit numbers the form's
 * default country code takes. Other numbers show as entered (their grouping varies by country).
 * Display only: stored answers, exports and search keep the raw "+9607771234".
 */
export function formatPhone(value: string): string {
  const m = /^\+960(\d{3})(\d{4})$/.exec(value)
  return m ? `+960 ${m[1]} ${m[2]}` : value
}
