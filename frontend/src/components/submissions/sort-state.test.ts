import { describe, expect, it } from 'vitest'

import type { FieldElement } from '@/schema'

import { dirWords, fieldKind, isSortable, nextSort, normalise, sortedDir } from './sort-state'
import { validateSubmissionsSearch } from './search'

describe('submissions sort state', () => {
  it('is Submitted, newest first, when unset', () => {
    expect(sortedDir({}, '_submitted')).toBe('desc')
    expect(sortedDir({}, 'name')).toBeNull()
  })

  it('cycles a column and clears the URL back at newest first', () => {
    // An answer starts A to Z, then Z to A.
    expect(nextSort({}, 'name')).toEqual({ sort: 'name', dir: 'asc' })
    expect(nextSort({ sort: 'name', dir: 'asc' }, 'name')).toEqual({ sort: 'name', dir: 'desc' })
    // Submitted flips to oldest first, and back to the default (nothing in the URL).
    expect(nextSort({}, '_submitted')).toEqual({ sort: '_submitted', dir: 'asc' })
    expect(nextSort({ sort: '_submitted', dir: 'asc' }, '_submitted')).toEqual({ sort: undefined, dir: undefined })
    // The reference number starts newest first.
    expect(nextSort({}, '_seq')).toEqual({ sort: '_seq', dir: 'desc' })
    expect(normalise({ sort: 'age' })).toEqual({ sort: 'age', dir: 'desc' })
  })

  it('knows which answers sort and how they read', () => {
    const f = (type: string) => ({ kind: 'field', id: 'q', type, label: 'Q' }) as unknown as FieldElement
    expect(isSortable(f('file'))).toBe(false)
    expect(isSortable(f('signature'))).toBe(false)
    expect(isSortable(f('short_text'))).toBe(true)
    expect(fieldKind(f('phone'))).toBe('number')
    expect(fieldKind(f('date'))).toBe('date')
    expect(fieldKind(f('single_choice'))).toBe('choice')
    expect(dirWords('date', 'desc')).toBe('Newest first')
    expect(dirWords('text', 'asc')).toBe('A to Z')
  })

  it('keeps a valid sort and the Deleted tab from the URL, drops the rest', () => {
    expect(validateSubmissionsSearch({ sort: 'full_name', dir: 'asc', status: 'deleted' })).toMatchObject({
      sort: 'full_name',
      dir: 'asc',
      status: 'deleted',
    })
    const bad = validateSubmissionsSearch({ sort: 'Name; drop', dir: 'sideways' })
    expect(bad.sort).toBeUndefined()
    expect(bad.dir).toBeUndefined()
  })
})
