import { describe, expect, it } from 'vitest'

import type { FieldElement } from '@/schema'

import { answerText, formatPhone } from './format'

describe('formatPhone', () => {
  it('groups a 7-digit number after +960 and leaves others as entered', () => {
    expect(formatPhone('+9607771234')).toBe('+960 777 1234')
    expect(formatPhone('+447700900123')).toBe('+447700900123')
    expect(formatPhone('+96077712345')).toBe('+96077712345')
  })

  it('formats phone answers for display', () => {
    const phone = { kind: 'field', id: 'p', label: 'Phone', type: 'phone' } as FieldElement
    expect(answerText(phone, '+9607771234')).toBe('+960 777 1234')
  })

  it('joins multi-choice labels with the comma of their script', () => {
    const field = (labels: string[]) =>
      ({ kind: 'field', id: 'm', label: 'Pick', type: 'multi_choice', options: labels.map((label, i) => ({ value: `o${i}`, label })) }) as FieldElement
    expect(answerText(field(['Red', 'Blue']), ['o0', 'o1'])).toBe('Red, Blue')
    expect(answerText(field(['ރަތް', 'ނޫ']), ['o0', 'o1'])).toBe('ރަތް، ނޫ')
    expect(answerText(field(['Red', 'ނޫ']), ['o0', 'o1'])).toBe('Red, ނޫ')
  })
})
