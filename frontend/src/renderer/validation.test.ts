import { describe, expect, it } from 'vitest'

import type { FieldElement } from '@/schema'

import { loadSpecFile } from '@/logic/spec-files'

import { MSG as en } from './messages'
import { checkAnswer, problemMessage, resolveDateBound, validateAnswer, type Problem } from './validation'

const v = (field: Partial<FieldElement> & { type: FieldElement['type'] }, value: unknown, required = false) =>
  validateAnswer(
    { kind: 'field', id: 'q', label: 'Full name', ...field } as FieldElement,
    value,
    required,
  )

describe('validateAnswer', () => {
  it('asks for missing required answers in plain words', () => {
    expect(v({ type: 'short_text' }, undefined, true)).toBe('Enter full name')
    expect(v({ type: 'short_text', label: 'What is your name?' }, '', true)).toBe('Answer this question')
    expect(v({ type: 'single_choice', options: [{ value: 'a', label: 'A' }] }, undefined, true)).toBe(
      'Choose an option',
    )
    expect(v({ type: 'short_text' }, undefined, false)).toBeNull()
  })

  it('checks email, phone and number ranges', () => {
    expect(v({ type: 'email' }, 'nope')).toBe(en.email)
    expect(v({ type: 'email' }, 'name@example.com')).toBeNull()
    expect(v({ type: 'phone' }, '+960777123')).toBe(en.phoneMv)
    expect(v({ type: 'phone' }, '+9607771234')).toBeNull()
    expect(v({ type: 'number', min: 15, max: 35 }, 40)).toBe('Enter a number between 15 and 35')
    expect(v({ type: 'number', integer: true }, 1.5)).toBe(en.integer)
    expect(v({ type: 'number' }, 'abc')).toBe(en.number)
  })

  it('uses the pattern message and length limit', () => {
    const f = { type: 'short_text' as const, pattern: '^A[0-9]{6}$', patternMessage: 'Like A123456' }
    expect(v(f, 'B1')).toBe('Like A123456')
    expect(v(f, 'A123456')).toBeNull()
    expect(v({ type: 'short_text', maxLength: 3 }, 'abcd')).toBe('Use 3 characters or fewer')
  })

  it('checks multi choice counts and date bounds', () => {
    const opts: [{ value: string; label: string }, { value: string; label: string }] = [
      { value: 'a', label: 'A' },
      { value: 'b', label: 'B' },
    ]
    expect(v({ type: 'multi_choice', options: opts, maxSelected: 1 }, ['a', 'b'])).toBe(
      'Choose no more than 1',
    )
    expect(v({ type: 'date', minDate: '2026-01-01' }, '2025-12-31')).toBe(
      'Enter a date on or after 1 January 2026',
    )
  })

  it('resolves relative date bounds', () => {
    expect(resolveDateBound('today+1', new Date(2026, 11, 31))).toBe('2027-01-01')
    expect(resolveDateBound('2026-05-05')).toBe('2026-05-05')
  })

  it('turns server codes into specific messages', () => {
    const field = { kind: 'field', id: 'q', label: 'Copy of ID', type: 'file' } as FieldElement
    expect(problemMessage(field, { code: 'file_missing' })).toBe(en.fileAgain)
    expect(problemMessage(field, { code: 'file_type' })).toBe(en.fileRejected)
    const date = { kind: 'field', id: 'd', label: 'Start', type: 'date' } as FieldElement
    expect(problemMessage(date, { code: 'date_to', params: { date: '2026-12-31' } })).toBe(
      'Enter a date on or before 31 December 2026',
    )
    expect(problemMessage(field, { code: 'something_new' })).toBe(en.answerThis)
  })

  it('says what to do for each type of missing answer', () => {
    const msg = (field: Partial<FieldElement> & { type: FieldElement['type'] }) => v(field, undefined, true)
    expect(msg({ type: 'email', label: 'Email' })).toBe('Enter an email address like name@example.com')
    expect(msg({ type: 'phone', label: 'Phone' })).toBe('Enter a phone number with 7 digits, like 7771234')
    expect(msg({ type: 'phone', defaultCountry: 'GB' })).toBe(en.phone)
    expect(msg({ type: 'number' })).toBe(en.number)
    expect(msg({ type: 'date' })).toBe(en.date)
    expect(msg({ type: 'file', label: 'Copy of ID card' })).toBe('Upload a file')
    expect(msg({ type: 'signature' })).toBe('Sign in the box')
    expect(msg({ type: 'yes_no', label: 'Do you look after anyone?' })).toBe('Choose an option')
    expect(problemMessage({ kind: 'field', id: 'f', label: 'ID', type: 'file', maxFiles: 2 } as FieldElement, {
      code: 'too_many_files',
      params: { n: 2 },
    })).toBe("You've added 2 files, the most allowed. Remove one to add another.")
  })

  it('keeps a Dhivehi label out of the English message', () => {
    expect(v({ type: 'short_text', label: 'ފުރިހަމަ ނަން' }, '', true)).toBe('Answer this question')
  })
})

interface SharedCase {
  name: string
  field: Partial<FieldElement> & { type: FieldElement['type'] }
  value?: unknown
  required?: boolean
  expect: Problem | null
}

const shared = loadSpecFile<{ today: string; cases: SharedCase[] }>('validation/answers.json')
const [ty, tm, td] = shared.today.split('-').map(Number)

describe('shared answer cases (spec/validation/answers.json, also run by pytest)', () => {
  it.each(shared.cases.map((c) => [c.name, c] as const))('%s', (_, c) => {
    const field = { kind: 'field', id: 'q', label: 'Q', ...c.field } as FieldElement
    const got = checkAnswer(field, c.value, c.required ?? false, new Date(ty, tm - 1, td))
    if (c.expect === null) expect(got).toBeNull()
    else expect({ code: got?.code, params: got?.params ?? {} }).toEqual({ code: c.expect.code, params: c.expect.params ?? {} })
  })
})
