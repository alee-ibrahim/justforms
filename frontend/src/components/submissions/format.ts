/** Answers as short text for tables and the detail view. */
import type { FieldElement, FormLanguage, Option } from '@/schema'

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

/** The options a choice answer picked, in the form's order, and any typed "Other" answers. */
export function chosenOptions(field: FieldElement, value: unknown): { chosen: Option[]; other: string[] } {
  if (field.type !== 'single_choice' && field.type !== 'multi_choice') return { chosen: [], other: [] }
  const values = (Array.isArray(value) ? value : [value]).filter((v) => v !== undefined && v !== null && v !== '').map(String)
  const chosen = field.options.filter((o) => values.includes(o.value))
  const other = values.filter((v) => !field.options.some((o) => o.value === v))
  return { chosen, other }
}

const answerDate = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
  numberingSystem: 'latn',
})

/** A date answer ("2004-02-03") as "3 Feb 2004": the day as entered, whatever the time zone. */
export function formatAnswerDate(value: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!m) return value
  return answerDate.format(new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))))
}
