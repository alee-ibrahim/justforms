import { describe, expect, it } from 'vitest'

import { evaluate } from '@/logic/engine'
import { buildIndex } from '@/logic/form-index'
import type { Form } from '@/schema'

import { padToMinRows } from './util'

const form = {
  schemaVersion: '1',
  settings: { language: 'en', title: 'Board' },
  pages: [
    {
      id: 'page_1',
      elements: [
        {
          kind: 'repeater',
          id: 'members',
          label: 'Members',
          minRows: 2,
          elements: [{ kind: 'field', id: 'member_name', type: 'short_text', label: 'Name', required: true }],
        },
        { kind: 'repeater', id: 'extras', label: 'Extras', elements: [{ kind: 'field', id: 'extra', type: 'short_text', label: 'Extra' }] },
      ],
    },
  ],
} as unknown as Form

describe('padToMinRows', () => {
  const elements = () => buildIndex(form).elements.values()

  it('adds the empty rows the renderer shows, so their required questions count', () => {
    const padded = padToMinRows(elements(), {})
    expect(padded).toEqual({ members: [{}, {}] })
    const ev = evaluate(form, padded)
    expect(ev.rows.members.map((r) => r.required)).toEqual([['member_name'], ['member_name']])
    // Without padding there are no rows to check (the bug: Next went on).
    expect(evaluate(form, {}).rows.members ?? []).toEqual([])
  })

  it('keeps answers that already have enough rows, and fills up short ones', () => {
    const full = { members: [{ member_name: 'A' }, {}, {}] }
    expect(padToMinRows(elements(), full)).toBe(full)
    expect(padToMinRows(elements(), { members: [{ member_name: 'A' }] })).toEqual({
      members: [{ member_name: 'A' }, {}],
    })
  })
})
