import { describe, expect, it } from 'vitest'

import { validateSubmissionsSearch } from '@/components/submissions/search'
import { filterParams } from '@/lib/api'

import { askErrorText } from './api'
import { fileName } from './png'

describe('conditions in the Submissions URL', () => {
  it('keeps valid conditions and drops anything else', () => {
    const s = validateSubmissionsSearch({
      where: [
        { field: 'areas', op: 'includes_any', values: ['disability'] },
        { field: '_status', op: 'eq', value: 'new' },
        { field: 'Bad Key', op: 'eq', value: 1 },
        { field: 'x', op: 'eq', value: { nested: true } },
        'nope',
      ],
      whereLabel: 'Topics: Disability rights',
    })
    expect(s.where).toEqual([
      { field: 'areas', op: 'includes_any', values: ['disability'] },
      { field: '_status', op: 'eq', value: 'new' },
    ])
    expect(s.whereLabel).toBe('Topics: Disability rights')
    expect(validateSubmissionsSearch({ where: [] }).where).toBeUndefined()
  })

  it('sends them to the API as one JSON parameter', () => {
    const qs = filterParams({ status: 'new', where: [{ field: 'staff', op: 'gte', value: 5 }] })
    expect(qs.get('status')).toBe('new')
    expect(JSON.parse(qs.get('where') ?? '')).toEqual({ where: [{ field: 'staff', op: 'gte', value: 5 }], whereAny: [] })
    expect(filterParams({}).has('where')).toBe(false)
  })
})

describe('Insights helpers', () => {
  it('names PNG files after the question', () => {
    expect(fileName('How useful was the last workshop?')).toBe('how-useful-was-the-last-workshop.png')
    expect(fileName('ތާނަ')).toBe('chart.png')
  })

  it('explains errors in plain words', () => {
    expect(askErrorText('ai_budget_exceeded')).toMatch(/allowance/)
    expect(askErrorText('something_else')).toBe("Couldn't get an answer. Try again.")
  })
})
