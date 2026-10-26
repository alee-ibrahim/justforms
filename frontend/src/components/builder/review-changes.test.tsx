// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type Draft, type DraftChanges } from '@/lib/api'
import type { Form } from '@/schema'

import { ChangeList } from './review-changes'
import { BuilderStore } from './store'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const w = (text: string) => ({ text, content: false })
const c = (text: string) => ({ text, content: true })

const changes = (language: 'en' | 'dv'): DraftChanges => ({
  baseVersion: 2,
  revision: 9,
  hasChanges: true,
  summary: '1 page added, 1 question added, 1 question removed, 1 question changed, 1 form setting changed',
  counts: { added: 2, removed: 1, changed: 2, moved: 0 },
  language,
  settings: [
    { property: 'title', name: 'Form title', kind: 'text', before: [c('Old')], after: [c('New')], summary: 'Form title changed' },
  ],
  pages: [
    {
      pageId: 'page_1',
      number: 1,
      title: '',
      status: null,
      summary: '',
      movedFrom: null,
      changes: [],
      elements: [
        {
          id: 'name',
          kind: 'field',
          type: 'short_text',
          typeName: 'Short answer',
          label: 'ނަން',
          within: ['ބައި'],
          status: 'changed',
          summary: 'Label changed',
          movedFrom: null,
          changes: [
            { property: 'label', name: 'Label', kind: 'text', before: [c('ނަމް')], after: [c('ނަން')], summary: 'Label changed' },
            {
              property: 'visibleIf',
              name: 'Shown when',
              kind: 'logic',
              before: null,
              after: [c('ޢުމުރު'), w(' is at least'), w(' 18')],
              summary: 'Show rule added',
            },
            {
              property: 'options',
              name: 'Options',
              kind: 'options',
              before: null,
              after: null,
              summary: '1 option added',
              options: { added: [{ value: 'y', label: 'Yellow' }], removed: [], renamed: [], reordered: false },
            },
          ],
        },
        {
          id: 'old',
          kind: 'field',
          type: 'email',
          typeName: 'Email',
          label: 'Email',
          within: [],
          status: 'removed',
          summary: 'Email removed',
          movedFrom: null,
          changes: [],
        },
      ],
    },
    {
      pageId: 'page_2',
      number: 2,
      title: 'Page 2',
      status: 'added',
      summary: 'Page added',
      movedFrom: null,
      changes: [],
      elements: [],
    },
  ],
})

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.restoreAllMocks()
})

describe('ChangeList', () => {
  it('groups by page with status badges and before/after values', () => {
    act(() => root.render(<ChangeList changes={changes('en')} />))
    const text = container.textContent ?? ''
    expect(text).toContain('Form settings')
    expect(text).toContain('Page 1')
    expect(text).toContain('Page 2')
    expect(text).toContain('An empty page.')
    for (const label of ['Changed', 'Removed', 'Added']) expect(text).toContain(label)
    expect(text).toContain('Before:')
    expect(text).toContain('After:')
    expect(text).toContain('Added option:')
    // "Page 2" is the default title: not repeated after the number.
    expect(text).not.toContain('Page 2, Page 2')
  })

  it('shows Dhivehi content right-to-left and English words left-to-right', () => {
    act(() => root.render(<ChangeList changes={changes('dv')} />))
    const label = [...container.querySelectorAll('bdi')].find((b) => b.textContent === 'ނަން')!
    expect(label.getAttribute('dir')).toBe('rtl')
    expect(label.getAttribute('lang')).toBe('dv')
    // A plain content value is a whole right-to-left paragraph.
    const value = [...container.querySelectorAll('p')].find((p) => p.textContent === 'ނަމް')!
    expect(value.getAttribute('dir')).toBe('rtl')
    // A rule mixes both: the sentence stays left-to-right, the label inside is isolated.
    const rule = [...container.querySelectorAll('p')].find((p) => p.textContent?.includes('is at least'))!
    expect(rule.getAttribute('dir')).toBeNull()
    expect(rule.querySelector('bdi')?.getAttribute('dir')).toBe('rtl')
  })

  it('compact: one line per change, no before/after', () => {
    act(() => root.render(<ChangeList changes={changes('en')} compact />))
    const text = container.textContent ?? ''
    expect(text).toContain('Label changed')
    expect(text).not.toContain('Before:')
    expect(text).toContain('Form title changed')
  })

  it('clamps long text with Show all', () => {
    const long = changes('en')
    long.settings[0].after = [c('x'.repeat(300))]
    act(() => root.render(<ChangeList changes={long} />))
    const button = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Show all')!
    expect(button).toBeTruthy()
    act(() => button.click())
    expect(container.textContent).toContain('Show less')
  })
})

const form = (title: string): Form => ({
  schemaVersion: '1',
  settings: { title },
  pages: [{ id: 'page_1', elements: [] }],
})

describe('BuilderStore.discard', () => {
  it('saves pending edits, then loads the discarded draft with Undo available', async () => {
    const store = new BuilderStore('f1', { schema: form('Live'), revision: 3, canUndo: true, canRedo: false })
    const patch = vi.spyOn(api, 'patchDraft').mockResolvedValue({
      schema: form('Edited'),
      revision: 4,
      canUndo: true,
      canRedo: false,
    } satisfies Draft)
    const discard = vi
      .spyOn(api, 'discardDraft')
      .mockResolvedValue({ schema: form('Live'), revision: 5, canUndo: true, canRedo: false } satisfies Draft)
    store.edit((f) => ({ ...f, settings: { ...f.settings, title: 'Edited' } }))
    expect(await store.discard()).toBe(true)
    expect(patch).toHaveBeenCalledOnce()
    expect(discard).toHaveBeenCalledWith('f1', 4)
    const state = store.get()
    expect(state.schema.settings.title).toBe('Live')
    expect(state.saved.revision).toBe(5)
    expect(state.undoStack).toEqual([])
    expect(store.canUndo).toBe(true)
  })
})
