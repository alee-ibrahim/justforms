import { describe, expect, it } from 'vitest'

import { BuilderStore } from '@/components/builder/store'
import type { Form } from '@/schema'

import { parseSse, type Proposal } from './api'
import { changedIds, errorText } from './controller'
import { fileProblem } from './files'

const form: Form = {
  schemaVersion: '1',
  settings: { language: 'en', title: 'T' },
  pages: [{ id: 'page_1', elements: [{ kind: 'field', id: 'a', type: 'short_text', label: 'A' }] }],
} as Form

describe('parseSse', () => {
  it('splits complete events and keeps the rest', () => {
    const { events, rest } = parseSse(
      ': started\n\nevent: tool.applied\ndata: {"tool":"add_field","ok":true}\n\nevent: done\ndata: {"usa',
    )
    expect(events).toEqual([{ event: 'tool.applied', data: { tool: 'add_field', ok: true } }])
    expect(rest).toBe('event: done\ndata: {"usa')
  })

  it('handles CRLF and skips malformed events', () => {
    const { events } = parseSse('event: error\r\ndata: {"code":"timeout"}\r\n\r\nevent: x\ndata: {bad\n\n')
    expect(events).toEqual([{ event: 'error', data: { code: 'timeout' } }])
  })
})

describe('messages', () => {
  it('explains every error with a next step', () => {
    for (const code of ['provider_unavailable', 'ai_budget_exceeded', 'tool_limit', 'form_too_large', 'unknown'])
      expect(errorText({ code })).toMatch(/\.$/)
    expect(errorText({ code: 'ai_budget_exceeded' })).toContain('resets tomorrow')
  })

  it('checks paper files', () => {
    expect(fileProblem(new File(['x'], 'form.pdf', { type: 'application/pdf' }))).toBeNull()
    expect(fileProblem(new File(['x'], 'notes.docx', { type: 'application/msword' }))).toContain('PDF, JPG')
  })

  it('washes added, changed and moved questions only', () => {
    const p = {
      changes: [
        { kind: 'element', id: 'a', change: 'added' },
        { kind: 'element', id: 'b', change: 'removed' },
        { kind: 'element', id: 'c', change: 'moved' },
        { kind: 'page', id: 'page_2', change: 'added' },
      ],
    } as Proposal
    expect(changedIds(p)).toEqual(['a', 'c'])
  })
})

describe('builder store with a suggestion', () => {
  const draft = { schema: form, revision: 3, canUndo: true, canRedo: false }

  it('ignores edits in a read-only preview store', () => {
    const store = new BuilderStore('f', draft, { readOnly: true })
    store.edit((f) => ({ ...f, settings: { ...f.settings, title: 'X' } }))
    expect(store.get().schema.settings.title).toBe('T')
    expect(store.canUndo).toBe(false)
  })

  it('locks the draft while a suggestion is shown and loads the applied draft', () => {
    const store = new BuilderStore('f', draft)
    store.setLocked(true)
    store.edit((f) => ({ ...f, settings: { ...f.settings, title: 'X' } }))
    expect(store.get().schema.settings.title).toBe('T')
    expect(store.canUndo).toBe(false)
    store.setLocked(false)
    store.loadDraft({ schema: { ...form, settings: { ...form.settings, title: 'AI' } }, revision: 4, canUndo: true, canRedo: false })
    expect(store.get().saved.revision).toBe(4)
    expect(store.canUndo).toBe(true)
    store.flash(['a'])
    expect(store.get().highlight.has('a')).toBe(true)
    store.select({ type: 'form' })
    expect(store.get().highlight.size).toBe(0)
  })
})
