import { describe, expect, it } from 'vitest'

import { parseForm, type Element, type Form } from '@/schema'

import {
  addPage,
  dropRulesReading,
  duplicateElement,
  duplicatePage,
  findElement,
  insertElement,
  keyFromLabel,
  moveElement,
  movePage,
  newElement,
  nudgeElement,
  placementProblem,
  removePage,
  renameId,
  rulesReading,
  uniqueId,
  wrapInSection,
} from './tree'

const field = (id: string, extra: object = {}): Element =>
  ({ kind: 'field', id, type: 'short_text', label: id, ...extra }) as Element

const base: Form = {
  schemaVersion: '1',
  settings: { language: 'en', title: 'T' },
  pages: [
    {
      id: 'page_1',
      elements: [
        field('a'),
        field('b', { visibleIf: { field: 'a', op: 'not_empty' } }),
        { kind: 'section', id: 's1', elements: [field('c')] },
        { kind: 'repeater', id: 'r1', label: 'R', elements: [field('d')] },
      ],
    },
    { id: 'page_2', elements: [field('e')] },
  ],
}

const ids = (form: Form, page = 0) => (form.pages[page].elements ?? []).map((e) => e.id)

describe('tree edits', () => {
  it('inserts, moves and nudges', () => {
    let f = insertElement(base, field('x'), { pageIndex: 0, parentId: null, index: 1 })
    expect(ids(f)).toEqual(['a', 'x', 'b', 's1', 'r1'])
    f = moveElement(f, 'x', { pageIndex: 0, parentId: null, index: 4 })
    expect(ids(f)).toEqual(['a', 'b', 's1', 'x', 'r1'])
    f = nudgeElement(f, 'x', -1)
    expect(ids(f)).toEqual(['a', 'b', 'x', 's1', 'r1'])
    f = nudgeElement(f, 'a', -1)
    expect(ids(f)[0]).toBe('a')
    f = moveElement(f, 'x', { pageIndex: 0, parentId: 's1', index: 0 })
    expect(findElement(f, 'x')?.loc).toEqual({ pageIndex: 0, parentId: 's1', index: 0 })
    f = moveElement(f, 'x', { pageIndex: 1, parentId: null, index: 1 })
    expect(ids(f, 1)).toEqual(['e', 'x'])
    expect(parseForm(f).ok).toBe(true)
  })

  it('refuses nested repeaters, signatures in repeaters and a third section level', () => {
    const rep = newElement(base, 'repeater')
    expect(placementProblem(base, rep, { pageIndex: 0, parentId: 'r1' })).toMatch(/Repeaters/)
    const sig = newElement(base, 'signature')
    expect(placementProblem(base, sig, { pageIndex: 0, parentId: 'r1' })).toMatch(/Signatures/)
    const nested: Element = { kind: 'section', id: 's2', elements: [{ kind: 'section', id: 's3', elements: [] }] }
    expect(placementProblem(base, nested, { pageIndex: 0, parentId: 's1' })).toMatch(/two levels/)
    expect(placementProblem(base, field('y'), { pageIndex: 0, parentId: 's1' })).toBeNull()
    expect(placementProblem(base, base.pages[0].elements![2], { pageIndex: 0, parentId: 's1' })).toMatch(/itself/)
  })

  it('makes keys from labels and keeps them unique', () => {
    expect(keyFromLabel('Full name')).toBe('full_name')
    expect(keyFromLabel("Guardian's phone number (mobile)")).toBe('guardian_s_phone_number_mobile')
    expect(keyFromLabel('ފުރިހަމަ ނަން')).toBeNull()
    expect(uniqueId(base, 'a')).toBe('a_1')
    expect(uniqueId(base, 'full_name')).toBe('full_name')
    expect(uniqueId(base, 'short_text')).toBe('short_text_1')
    expect(newElement(base, 'single_choice')).toMatchObject({ options: [{ value: 'option_1' }, { value: 'option_2' }] })
  })

  it('duplicates with fresh ids and renames references', () => {
    const { form, id } = duplicateElement(base, 's1')
    expect(id).not.toBe('s1')
    expect(ids(form)).toEqual(['a', 'b', 's1', id, 'r1'])
    expect(parseForm(form).ok).toBe(true)
    const renamed = renameId(base, 'a', 'full_name')
    expect(findElement(renamed, 'b')?.el.visibleIf).toEqual({ field: 'full_name', op: 'not_empty' })
  })

  it('finds and drops rules that read deleted questions', () => {
    expect(rulesReading(base, new Set(['a']))).toEqual([{ ownerId: 'b', kind: 'visibleIf' }])
    const f = dropRulesReading(base, new Set(['a']))
    expect(findElement(f, 'b')?.el.visibleIf).toBeUndefined()
  })

  it('wraps in a section', () => {
    const { form, id } = wrapInSection(base, 'a')
    expect(ids(form)[0]).toBe(id)
    expect(findElement(form, 'a')?.loc.parentId).toBe(id)
  })

  it('adds, moves, duplicates and removes pages', () => {
    let { form } = addPage(base)
    expect(form.pages.map((p) => p.title)).toEqual([undefined, undefined, 'Page 3'])
    const jumped: Form = {
      ...form,
      pages: [{ ...form.pages[0], next: [{ if: { field: 'a', op: 'empty' }, goto: 'page_2' }] }, ...form.pages.slice(1)] as Form['pages'],
    }
    form = movePage(jumped, 1, 0)
    expect(form.pages[1].next).toEqual([]) // a jump may not point backwards
    const dup = duplicatePage(base, 1)
    expect(dup.form.pages).toHaveLength(3)
    expect(parseForm(dup.form).ok).toBe(true)
    const removed = removePage(base, 0)
    expect(removed.pages.map((p) => p.id)).toEqual(['page_2'])
  })
})
