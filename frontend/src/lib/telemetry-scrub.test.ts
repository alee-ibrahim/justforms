import { describe, expect, it } from 'vitest'

import { loadSpecFile } from '@/logic/spec-files'

import { scrubEvent, scrubText, scrubUrl } from './telemetry-scrub'

interface Case<T> {
  name: string
  input: T
  output: T
}

const spec = loadSpecFile<{ text: Case<string>[]; url: Case<string>[]; events: Case<object>[] }>(
  'telemetry/scrub.json',
)

describe('shared scrub cases (spec/telemetry/scrub.json, also run by pytest)', () => {
  it.each(spec.text.map((c) => [c.name, c] as const))('text: %s', (_, c) => {
    expect(scrubText(c.input)).toBe(c.output)
  })
  it.each(spec.url.map((c) => [c.name, c] as const))('url: %s', (_, c) => {
    expect(scrubUrl(c.input)).toBe(c.output)
  })
  it.each(spec.events.map((c) => [c.name, c] as const))('event: %s', (_, c) => {
    expect(scrubEvent(c.input)).toEqual(c.output)
  })
})

describe('no answer value survives', () => {
  it('drops user, extra, breadcrumbs, request data and frame variables', () => {
    const answers = ['Aminath Ali', 'aminath@example.org', '+9607771234', 'A123456', 'Hulhumale']
    const event = {
      message: 'failed for aminath@example.org',
      user: { email: 'aminath@example.org' },
      extra: { answers: { name: 'Aminath Ali', island: 'Hulhumale' } },
      breadcrumbs: [{ category: 'ui.input', message: 'Aminath Ali' }],
      request: { url: 'https://f.example/x?island=Hulhumale', headers: { Cookie: 'a=b' } },
      exception: {
        values: [
          {
            type: 'Error',
            value: 'bad A123456 +9607771234',
            stacktrace: { frames: [{ function: 'f', vars: { v: 'Aminath Ali', w: 'Hulhumale' } }] },
          },
        ],
      },
    }
    const out = JSON.stringify(scrubEvent(event))
    for (const value of answers) expect(out).not.toContain(value)
    expect(out).toContain('"type":"Error"')
  })
})
