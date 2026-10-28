// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createFrictionReporter } from './friction'

afterEach(() => {
  vi.useRealTimers()
  sessionStorage.clear()
})

describe('friction reporter', () => {
  it('batches, de-duplicates and sends only keys, codes and a visit id', () => {
    vi.useFakeTimers()
    const sent: { url: string; body: Record<string, unknown> }[] = []
    const r = createFrictionReporter({
      slug: 'apply',
      formId: 'f1',
      versionId: 'v1',
      send: (url, body) => sent.push({ url, body: JSON.parse(body) }),
    })
    r.report({ type: 'page', page: 'about' })
    r.report({ type: 'start' })
    r.report({ type: 'error', field: 'nid', code: 'pattern' })
    r.report({ type: 'error', field: 'nid', code: 'pattern' })
    expect(sent).toEqual([])
    vi.advanceTimersByTime(3000)
    expect(sent).toHaveLength(1)
    expect(sent[0].url).toBe('/api/v1/public/forms/apply/friction')
    expect(sent[0].body.versionId).toBe('v1')
    expect(String(sent[0].body.visit)).toMatch(/^[A-Za-z0-9_-]{16,64}$/)
    expect(sent[0].body.events).toEqual([
      { type: 'page', page: 'about' },
      { type: 'start' },
      { type: 'error', field: 'nid', code: 'pattern' },
    ])
    r.stop()
  })

  it('keeps one visit id per tab and form, and sends on page hide', () => {
    const bodies: string[] = []
    const send = (_: string, body: string) => bodies.push(body)
    const a = createFrictionReporter({ slug: 's', formId: 'f1', versionId: 'v1', send })
    a.report({ type: 'start' })
    window.dispatchEvent(new Event('pagehide'))
    expect(bodies).toHaveLength(1)
    a.stop()
    const b = createFrictionReporter({ slug: 's', formId: 'f1', versionId: 'v1', send })
    b.report({ type: 'start' })
    b.flush()
    expect(JSON.parse(bodies[1]).visit).toBe(JSON.parse(bodies[0]).visit)
    b.stop()
    expect(document.cookie).toBe('')
  })
})
