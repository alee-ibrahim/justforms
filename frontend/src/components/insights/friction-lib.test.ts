import { describe, expect, it } from 'vitest'

import type { Form } from '@/schema'

import { funnel, kinds, problemKind } from './friction-lib'

const schema = {
  schemaVersion: '1',
  settings: { language: 'en', title: 'T' },
  pages: [{ id: 'about', elements: [] }, { id: 'contact', title: 'Contact', elements: [] }, { id: 'review', elements: [] }],
} as Form

describe('where people get stuck', () => {
  it('builds the funnel in form order from page visits', () => {
    const steps = funnel(
      {
        enabled: true,
        from: '2026-10-01',
        to: '2026-10-30',
        days: 30,
        pages: [{ page: 'contact', visits: 6 }, { page: 'about', visits: 10 }],
        started: 8,
        submitted: 4,
        fields: [],
        codes: [],
      },
      schema,
    )
    expect(steps.map((s) => [s.label, s.count])).toEqual([
      ['Opened the form', 10],
      ['Started answering', 8],
      ['Contact', 6],
      ['Page 3', 0],
      ['Submitted', 4],
    ])
  })

  it('merges codes under plain names', () => {
    expect(problemKind('pattern')).toBe('Wrong format')
    expect(kinds({ phone: 2, phone_mv: 3, required: 1 })).toEqual([
      { kind: 'Phone not valid', count: 5 },
      { kind: 'Left empty', count: 1 },
    ])
  })
})
