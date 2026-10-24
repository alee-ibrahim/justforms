/**
 * Client-side validation for one answer (DESIGN 18, PHASE-2-SCREENS 4.6). `checkAnswer`
 * returns a problem code with params; `problemMessage` turns it into a specific English message
 * (system text is English for every form). The server (`backend/app/validation/answers.py`) returns the same codes and
 * both run the shared cases in `spec/validation/answers.json`.
 */
import { isMissing } from '@/logic/engine'
import type { FieldElement } from '@/schema'

import { fmt, MSG as msgs } from './messages'

export interface FileRef {
  fileId: string
  name: string
  size: number
  mime: string
}

export interface Problem {
  code: string
  params?: Record<string, string | number>
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/
const DATE = /^\d{4}-\d{2}-\d{2}$/
const SHORT_TEXT_CAP = 10_000
const LONG_TEXT_CAP = 100_000
const OTHER_CAP = 500

const pad = (n: number) => String(n).padStart(2, '0')

/** Resolve a date bound ("2026-01-01", "today", "today+30") to YYYY-MM-DD. */
export function resolveDateBound(bound: string | null | undefined, now = new Date()): string | null {
  if (!bound) return null
  if (DATE.test(bound)) return bound
  const m = /^today([+-]\d{1,4})?$/.exec(bound)
  if (!m) return null
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + Number(m[1] ?? 0))
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** A real calendar date in YYYY-MM-DD form. */
function isDate(s: string): boolean {
  if (!DATE.test(s)) return false
  const [y, m, d] = s.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d
}

/** "1 January 2026": system text, so English for every form. */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    numberingSystem: 'latn',
  }).format(new Date(y, m - 1, d))
}

export function phoneDigitsRule(country: string | null | undefined): number | null {
  return country === 'MV' || !country ? 7 : null
}

/** A JSON number both sides agree on (and the server can hash): finite, within ±2^53. */
const isNum = (v: unknown): v is number =>
  typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= Number.MAX_SAFE_INTEGER

/** The problem with one answer, or null. `today` resolves relative date limits. */
export function checkAnswer(
  field: FieldElement,
  value: unknown,
  required: boolean,
  today = new Date(),
): Problem | null {
  if (isMissing(value)) {
    if (!required) return null
    return field.type === 'multi_choice'
      ? { code: 'required', params: { n: Math.max(1, field.minSelected ?? 1) } }
      : { code: 'required' }
  }
  const problem = (code: string, params?: Problem['params']): Problem => ({ code, params })
  switch (field.type) {
    case 'short_text':
    case 'long_text': {
      if (typeof value !== 'string') return problem('invalid')
      const cap = field.maxLength ?? (field.type === 'short_text' ? SHORT_TEXT_CAP : LONG_TEXT_CAP)
      if (value.length > cap) return problem('too_long', { max: cap })
      if (field.type === 'short_text' && field.pattern) {
        try {
          if (!new RegExp(field.pattern, 'u').test(value)) return problem('pattern')
        } catch {
          return null // an invalid pattern is a builder problem, not the respondent's
        }
      }
      return null
    }
    case 'email':
      return typeof value === 'string' && value.length <= 320 && EMAIL.test(value.trim())
        ? null
        : problem('email')
    case 'phone': {
      const s = typeof value === 'string' ? value : ''
      if (s.startsWith('+960')) return /^\+960\d{7}$/.test(s) ? null : problem('phone_mv')
      return /^\+\d{6,15}$/.test(s) ? null : problem('phone')
    }
    case 'number': {
      if (!isNum(value)) return problem('number')
      if (field.integer && !Number.isInteger(value)) return problem('integer')
      const { min, max } = field
      if (!((min != null && value < min) || (max != null && value > max))) return null
      if (min != null && max != null) return problem('between', { min, max })
      return min != null ? problem('at_least', { min }) : problem('at_most', { max: max! })
    }
    case 'date': {
      if (typeof value !== 'string' || !isDate(value)) return problem('date')
      const lo = resolveDateBound(field.minDate, today)
      const hi = resolveDateBound(field.maxDate, today)
      if (lo && value < lo) return problem('date_from', { date: lo })
      if (hi && value > hi) return problem('date_to', { date: hi })
      return null
    }
    case 'time':
      return typeof value === 'string' && TIME.test(value) ? null : problem('time')
    case 'single_choice': {
      if (typeof value !== 'string') return problem('option')
      if (field.options.some((o) => o.value === value)) return null
      return field.allowOther && field.display !== 'dropdown' && value.length <= OTHER_CAP
        ? null
        : problem('option')
    }
    case 'multi_choice': {
      if (!Array.isArray(value) || !value.every((v) => typeof v === 'string')) return problem('option')
      const others = value.filter((v) => !field.options.some((o) => o.value === v))
      if (
        new Set(value).size !== value.length ||
        (others.length && (!field.allowOther || others.length > 1 || others[0].length > OTHER_CAP))
      )
        return problem('option')
      if (field.minSelected != null && value.length < field.minSelected)
        return problem('choose_at_least', { n: field.minSelected })
      if (field.maxSelected != null && value.length > field.maxSelected)
        return problem('choose_at_most', { n: field.maxSelected })
      return null
    }
    case 'yes_no':
      return typeof value === 'boolean' ? null : problem('option')
    case 'rating':
      return Number.isInteger(value) && (value as number) >= 1 && (value as number) <= (field.max ?? 5)
        ? null
        : problem('option')
    case 'file':
      if (
        !Array.isArray(value) ||
        !value.every((v) => typeof (v as Partial<FileRef> | null)?.fileId === 'string')
      )
        return problem('file_invalid')
      return value.length > (field.maxFiles ?? 1) ? problem('too_many_files', { n: field.maxFiles ?? 1 }) : null
    case 'signature': {
      const strokes = (value as { strokes?: unknown } | null)?.strokes
      return Array.isArray(strokes) && strokes.length ? null : problem('signature_invalid')
    }
    case 'hidden':
      return (typeof value === 'string' && value.length <= SHORT_TEXT_CAP) ||
        isNum(value) ||
        typeof value === 'boolean'
        ? null
        : problem('invalid')
  }
}

/**
 * What to do for a missing required answer, per type ("Enter a phone number with 7 digits, like
 * 7771234"). Text questions use "Enter full name" from the label when that reads naturally; a
 * label in Thaana (a Dhivehi form) never goes inside the English sentence.
 */
function requiredText(field: FieldElement, n: string | number = 1): string {
  switch (field.type) {
    case 'single_choice':
    case 'yes_no':
    case 'rating':
      return msgs.chooseOption
    case 'multi_choice':
      return fmt(msgs.chooseAtLeast, { n })
    case 'signature':
      return msgs.signRequired
    case 'file':
      return msgs.uploadFile
    case 'email':
    case 'number':
    case 'date':
    case 'time':
      return msgs[field.type]
    case 'phone':
      return phoneDigitsRule(field.defaultCountry) ? msgs.phoneMv : msgs.phone
  }
  const label = field.label.trim()
  if (!label || /[ހ-޿]/.test(label) || label.length > 40 || /[?:]/.test(label))
    return msgs.answerThis
  return fmt(msgs.enterLabel, { label: label.charAt(0).toLowerCase() + label.slice(1) })
}

/** A specific message for a problem (client or server codes). */
export function problemMessage(field: FieldElement, p: Problem): string {
  const v = p.params ?? {}
  switch (p.code) {
    case 'required':
      return requiredText(field, v.n)
    case 'too_long':
      return fmt(msgs.tooLong, v)
    case 'pattern':
      return (field.type === 'short_text' && field.patternMessage?.trim()) || msgs.checkFormat
    case 'email':
    case 'number':
    case 'integer':
    case 'date':
    case 'time':
      return msgs[p.code]
    case 'phone_mv':
      return msgs.phoneMv
    case 'phone':
      return msgs.phone
    case 'between':
      return fmt(msgs.between, v)
    case 'at_least':
      return fmt(msgs.atLeast, v)
    case 'at_most':
      return fmt(msgs.atMost, v)
    case 'date_from':
      return fmt(msgs.dateFrom, { date: formatDate(String(v.date)) })
    case 'date_to':
      return fmt(msgs.dateTo, { date: formatDate(String(v.date)) })
    case 'choose_at_least':
      return fmt(msgs.chooseAtLeast, v)
    case 'choose_at_most':
      return fmt(msgs.chooseAtMost, v)
    case 'option':
      return msgs.chooseOption
    case 'too_many_files':
      return fmt(msgs.filesMaxed, v)
    case 'file_missing':
    case 'file_invalid':
      return msgs.fileAgain
    case 'file_type':
    case 'file_too_large':
      return msgs.fileRejected
    case 'signature_small':
      return msgs.signatureSmall
    case 'signature_invalid':
      return msgs.signRequired
    default:
      return msgs.answerThis
  }
}

export function validateAnswer(
  field: FieldElement,
  value: unknown,
  required: boolean,
): string | null {
  const p = checkAnswer(field, value, required)
  return p && problemMessage(field, p)
}
