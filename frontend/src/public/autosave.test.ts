// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Form } from '@/schema'

import type { LiveForm } from './api'
import { ago, openProgress, progressKey, restoredText, SAVE_DELAY } from './autosave'

const form = (nameType = 'short_text'): Form =>
  ({
    schemaVersion: '1',
    settings: { title: 'Membership', language: 'en' },
    pages: [
      {
        id: 'page_1',
        elements: [
          { kind: 'field', id: 'name', type: nameType, label: 'Name' },
          { kind: 'field', id: 'id_number', type: 'short_text', label: 'ID number', sensitive: true },
          { kind: 'field', id: 'source', type: 'hidden', label: 'Source' },
          {
            kind: 'repeater',
            id: 'children',
            label: 'Children',
            elements: [
              { kind: 'field', id: 'child_name', type: 'short_text', label: 'Child name' },
              { kind: 'field', id: 'child_doc', type: 'file', label: 'Birth certificate' },
            ],
          },
        ],
      },
      {
        id: 'page_2',
        elements: [
          { kind: 'field', id: 'cv', type: 'file', label: 'CV' },
          { kind: 'field', id: 'sign', type: 'signature', label: 'Signature' },
          { kind: 'field', id: 'note', type: 'long_text', label: 'Note' },
        ],
      },
    ],
  }) as unknown as Form

const live = (over: Partial<LiveForm> = {}): LiveForm =>
  ({
    formId: 'f1',
    versionId: 'v1',
    version: 1,
    accessMode: 'public',
    respondentEmail: null,
    schema: form(),
    saveProgress: { days: 7 },
    ...over,
  }) as LiveForm

const answers = {
  name: 'ޢަލީ މުޙައްމަދު',
  id_number: 'A123456',
  source: 'newsletter',
  children: [{ child_name: 'Sara', child_doc: [{ fileId: 'x' }] }],
  cv: [{ fileId: 'y', name: 'cv.pdf' }],
  sign: { fileId: 'z' },
  note: 'Hello',
}

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

function saveAndReopen(first: LiveForm, then: LiveForm = first, page = 'page_2') {
  const p = openProgress(first)!
  p.save(answers, 'page_1')
  p.save(answers, page)
  vi.advanceTimersByTime(SAVE_DELAY)
  return openProgress(then)
}

describe('saved progress', () => {
  it('saves after a pause and restores answers and page', () => {
    const p = openProgress(live())!
    expect(p.restored).toBeNull()
    p.save({ name: 'Ali' }, 'page_1')
    expect(localStorage.length).toBe(1) // first save of a page is straight away
    p.save({ name: 'Ali Mohamed' }, 'page_1')
    vi.advanceTimersByTime(SAVE_DELAY - 1)
    expect(JSON.parse(localStorage.getItem(progressKey(live()))!).answers.name).toBe('Ali')
    vi.advanceTimersByTime(1)
    const again = openProgress(live())!
    expect(again.restored).toMatchObject({ answers: { name: 'Ali Mohamed' }, page: 'page_1', changed: false, dropped: false })
  })

  it('never stores sensitive answers, files, signatures or hidden values; Thaana stays intact', () => {
    const r = saveAndReopen(live())!.restored!
    expect(r.answers).toEqual({ name: 'ޢަލީ މުޙައްމަދު', children: [{ child_name: 'Sara' }], note: 'Hello' })
    expect(r.skipped).toEqual(['files', 'private', 'signatures'])
    const raw = localStorage.getItem(progressKey(live()))!
    for (const secret of ['A123456', 'newsletter', 'cv.pdf', '"z"']) expect(raw).not.toContain(secret)
    expect(restoredText(r, r.savedAt)).toEqual([
      'We restored your progress from a moment ago.',
      "Files, private answers and signatures aren't saved on this device, so add them again.",
    ])
  })

  it('flushes when the page is hidden', () => {
    const p = openProgress(live())!
    p.save({ name: 'Ali' }, 'page_1')
    p.save({ name: 'Ali M' }, 'page_1')
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    expect(JSON.parse(localStorage.getItem(progressKey(live()))!).answers.name).toBe('Ali M')
  })

  it('after a new version keeps only answers whose question and type still exist', () => {
    const next = live({ version: 2, schema: form('email') })
    const r = saveAndReopen(live(), next)!.restored!
    expect(r.answers).toEqual({ children: [{ child_name: 'Sara' }], note: 'Hello' })
    expect(r).toMatchObject({ changed: true, dropped: true, page: undefined })
    expect(restoredText(r, r.savedAt)[1]).toBe('The form has changed since, and some answers no longer apply.')
  })

  it('clears on submit or start over', () => {
    const p = saveAndReopen(live())!
    p.save({ name: 'Ali' }, 'page_1')
    p.clear()
    vi.advanceTimersByTime(SAVE_DELAY)
    expect(localStorage.length).toBe(0)
    expect(openProgress(live())!.restored).toBeNull()
  })

  it('expires', () => {
    saveAndReopen(live())
    expect(openProgress(live(), Date.now() + 8 * 86_400_000)!.restored).toBeNull()
    expect(localStorage.length).toBe(0)
  })

  it('is off when the owner turned it off, and removes what was saved', () => {
    saveAndReopen(live())
    expect(openProgress(live({ saveProgress: null }))).toBeNull()
    expect(localStorage.length).toBe(0)
  })

  it('keeps respondents of email-code forms apart', () => {
    const ali = live({ accessMode: 'otp', respondentEmail: 'ali@example.org' })
    const sara = live({ accessMode: 'otp', respondentEmail: 'sara@example.org' })
    expect(progressKey(ali)).not.toBe(progressKey(sara))
    expect(progressKey(ali)).not.toContain('example.org')
    saveAndReopen(ali)
    expect(openProgress(sara)!.restored).toBeNull()
    expect(openProgress(ali)!.restored).not.toBeNull()
  })

  it('fails quietly without storage', () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    expect(openProgress(live())).toBeNull()
  })

  it('fails quietly when storage is full', () => {
    const p = openProgress(live())!
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(() => {
      p.save({ name: 'Ali' }, 'page_1')
      p.flush()
    }).not.toThrow()
  })

  it('ignores a broken record', () => {
    localStorage.setItem(progressKey(live()), '{not json')
    expect(openProgress(live())!.restored).toBeNull()
  })

  it('says when progress was saved', () => {
    const now = Date.UTC(2026, 9, 25, 12)
    expect(ago(now - 20_000, now)).toBe('a moment ago')
    expect(ago(now - 5 * 60_000, now)).toBe('5 minutes ago')
    expect(ago(now - 2 * 3_600_000, now)).toBe('2 hours ago')
    expect(ago(now - 86_400_000, now)).toBe('yesterday')
  })
})
