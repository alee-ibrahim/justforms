import { describe, expect, it } from 'vitest'

import type { FormListItem } from '@/lib/api'
import { formatRelative } from '@/lib/format'

import { applyFormsView, isFiltered, openPath, validateFormsSearch } from './forms-view'
import { listItem } from './list-item.fixture'

const forms = [
  listItem({ id: 'a', title: 'Zebra survey', submissionCount: 3, lastEditedAt: '2026-10-20T09:00:00Z', lastSubmissionAt: '2026-10-10T09:00:00Z' }),
  listItem({ id: 'b', title: 'apple form', submissionCount: 40, status: 'draft', lastEditedAt: '2026-10-22T09:00:00Z' }),
  listItem({
    id: 'c',
    title: 'Form 10',
    submissionCount: 12,
    ownedByMe: false,
    owner: { id: 'u2', name: 'Ibrahim Naseer', email: 'ibrahim@example.org' },
    lastEditedAt: '2026-10-21T09:00:00Z',
    lastSubmissionAt: '2026-10-24T09:00:00Z',
  }),
  listItem({ id: 'd', title: 'Form 9', status: 'closed', lastEditedAt: '2026-10-01T09:00:00Z' }),
  listItem({ id: 'e', title: '', lastEditedAt: '2026-10-02T09:00:00Z' }),
]
const ids = (rows: FormListItem[]) => rows.map((r) => r.id)

describe('applyFormsView', () => {
  it('sorts by last edited, newest first, by default', () => {
    expect(ids(applyFormsView(forms, {}))).toEqual(['b', 'c', 'a', 'e', 'd'])
  })

  it('sorts by last submission with never-submitted forms last', () => {
    expect(ids(applyFormsView(forms, { sort: 'submission' }))).toEqual(['c', 'a', 'b', 'e', 'd'])
  })

  it('sorts by name A to Z, case-insensitive and numeric, untitled last', () => {
    expect(ids(applyFormsView(forms, { sort: 'name' }))).toEqual(['b', 'd', 'c', 'a', 'e'])
  })

  it('sorts by submission count, most first', () => {
    expect(ids(applyFormsView(forms, { sort: 'submissions' }))).toEqual(['b', 'c', 'a', 'e', 'd'])
  })

  it('filters by owner, status and search text (title or owner)', () => {
    expect(ids(applyFormsView(forms, { owner: 'mine' }))).not.toContain('c')
    expect(ids(applyFormsView(forms, { status: 'draft' }))).toEqual(['b'])
    expect(ids(applyFormsView(forms, { q: 'ZEBRA' }))).toEqual(['a'])
    expect(ids(applyFormsView(forms, { q: 'ibrahim@' }))).toEqual(['c'])
    expect(ids(applyFormsView(forms, { q: 'naseer', owner: 'mine' }))).toEqual([])
  })

  it('does not change the input', () => {
    const before = ids(forms)
    applyFormsView(forms, { sort: 'name' })
    expect(ids(forms)).toEqual(before)
  })
})

describe('validateFormsSearch', () => {
  it('keeps known values and drops the rest', () => {
    expect(validateFormsSearch({ q: 'x', owner: 'mine', status: 'live', sort: 'name' })).toEqual({
      q: 'x',
      owner: 'mine',
      status: 'live',
      sort: 'name',
    })
    expect(validateFormsSearch({ q: '  ', owner: 'them', status: 'gone', sort: 'edited' })).toEqual({
      q: undefined,
      owner: undefined,
      status: undefined,
      sort: undefined,
    })
  })

  it('knows when a filter is on', () => {
    expect(isFiltered({ sort: 'name' })).toBe(false)
    expect(isFiltered({ status: 'live' })).toBe(true)
  })
})

describe('formatRelative', () => {
  const now = new Date('2026-10-25T12:00:00Z').getTime()
  it('reads like a person would say it', () => {
    expect(formatRelative('2026-10-25T11:59:40Z', now)).toBe('just now')
    expect(formatRelative('2026-10-25T11:55:00Z', now)).toBe('5 minutes ago')
    expect(formatRelative('2026-10-25T09:00:00Z', now)).toBe('3 hours ago')
    expect(formatRelative('2026-10-24T09:00:00Z', now)).toBe('yesterday')
    expect(formatRelative('2026-10-20T12:00:00Z', now)).toBe('5 days ago')
    expect(formatRelative('2026-08-01T12:00:00Z', now)).toBe('1 Aug 2026')
  })
})

describe('openPath', () => {
  it('opens submissions when there are any, else the editor; submissions viewers always submissions', () => {
    expect(openPath(listItem({ submissionCount: 3 }))).toBe('/forms/$formId/submissions')
    expect(openPath(listItem({ submissionCount: 0 }))).toBe('/forms/$formId/edit')
    expect(openPath(listItem({ submissionCount: 0, role: 'viewer' }))).toBe('/forms/$formId/submissions')
  })
})
