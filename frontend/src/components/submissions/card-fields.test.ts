import { describe, expect, it } from 'vitest'

import type { FieldElement } from '@/schema'

import { attachments, autoCardFields, cardFields, MAX_CARD_FIELDS } from './card-fields'
import { listSearch, neighbours } from './list-query'

const f = (id: string, type: string, label = id) => ({ kind: 'field', id, type, label }) as FieldElement

describe('card fields', () => {
  const fields = [
    f('notes', 'long_text'),
    f('school', 'short_text', 'School'),
    f('applicant', 'short_text', 'Applicant name'),
    f('track', 'single_choice', 'Track'),
    f('id_copy', 'file'),
    f('mail', 'email'),
    f('mobile', 'phone'),
    f('age', 'number'),
  ]

  it('picks a name, email, phone and a choice, in form order', () => {
    expect(autoCardFields(fields)).toEqual(['applicant', 'track', 'mail', 'mobile'])
  })

  it('fills up to four with the next short questions, never long text or files', () => {
    expect(autoCardFields([f('a', 'long_text'), f('b', 'short_text'), f('c', 'number'), f('d', 'file'), f('e', 'date'), f('g', 'time')])).toEqual([
      'b',
      'c',
      'e',
      'g',
    ])
  })

  it('uses the saved choice, dropping questions that left the form', () => {
    expect(cardFields(fields, ['age', 'gone', 'school']).map((x) => x.id)).toEqual(['age', 'school'])
    expect(cardFields(fields, ['gone']).map((x) => x.id)).toEqual(['applicant', 'track', 'mail', 'mobile'])
    expect(cardFields(fields, null).map((x) => x.id)).toEqual(['applicant', 'track', 'mail', 'mobile'])
    const many = Array.from({ length: 9 }, (_, i) => f(`q${i}`, 'short_text'))
    expect(cardFields(many, many.map((x) => x.id))).toHaveLength(MAX_CARD_FIELDS)
  })

  it('counts files and spots a signature', () => {
    const withSig = [...fields, f('sign', 'signature')]
    expect(attachments(withSig, { id_copy: [{}, {}], sign: 'sig-1' })).toEqual({ files: 2, signed: true })
    expect(attachments(withSig, {})).toEqual({ files: 0, signed: false })
  })
})

describe('moving through the list', () => {
  const rows = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]

  it('finds newer and older neighbours', () => {
    expect(neighbours(rows, 'b')).toEqual({ index: 1, prev: rows[0], next: rows[2], atEnd: false })
    expect(neighbours(rows, 'a')).toMatchObject({ prev: undefined, next: rows[1] })
    expect(neighbours(rows, 'c')).toMatchObject({ next: undefined, atEnd: true })
    expect(neighbours(rows, 'x')).toEqual({ index: -1, prev: undefined, next: undefined, atEnd: false })
  })

  it("keeps the list's view state without the one-off open link", () => {
    expect(listSearch({ status: 'new', q: 'ali', open: '0190-…' })).toEqual({ status: 'new', q: 'ali' })
  })
})
