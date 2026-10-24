import { describe, expect, it } from 'vitest'

import type { Element, Form } from '@/schema'

import { blockPosition } from './problems'

const field = (id: string, type = 'short_text'): Element => ({ kind: 'field', id, type, label: '' }) as Element

const form: Form = {
  schemaVersion: '1',
  settings: { language: 'en', title: 'T' },
  pages: [
    {
      id: 'page_1',
      elements: [
        { kind: 'content', id: 'h1', contentType: 'heading', text: '' },
        field('a'),
        { kind: 'section', id: 's1', elements: [field('b', 'email')] },
        { kind: 'content', id: 'h2', contentType: 'heading', text: '' },
      ],
    },
    { id: 'page_2', elements: [field('c', 'phone')] },
  ],
}

describe('blockPosition', () => {
  it('numbers questions in reading order per page, with their type', () => {
    expect(blockPosition(form, 'a')).toBe('Page 1, question 1 (Short answer)')
    expect(blockPosition(form, 'b')).toBe('Page 1, question 2 (Email)')
    expect(blockPosition(form, 'c')).toBe('Page 2, question 1 (Phone)')
  })

  it('numbers other blocks by their own type', () => {
    expect(blockPosition(form, 'h2')).toBe('Page 1, heading 2')
    expect(blockPosition(form, 's1')).toBe('Page 1, section 1')
  })

  it('returns null for an unknown block', () => {
    expect(blockPosition(form, 'nope')).toBeNull()
  })
})
