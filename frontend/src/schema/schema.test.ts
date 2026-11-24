import { expect, it } from 'vitest'

import { loadSpecFile } from '@/logic/spec-files'

import { formDirection, parseForm, type Form } from '.'

const example = loadSpecFile<Form>('examples/youth-programme.json')

it('accepts the design example', () => {
  expect(parseForm(example).ok).toBe(true)
})

it('rejects unknown field types and operators', () => {
  const bad = structuredClone(example) as unknown as {
    pages: { elements: Record<string, unknown>[] }[]
  }
  bad.pages[0].elements[0].type = 'nope'
  expect(parseForm(bad).ok).toBe(false)
  const bad2 = structuredClone(example) as unknown as typeof bad
  bad2.pages[0].elements[0].visibleIf = { field: 'age', op: 'matches', value: 'x' }
  expect(parseForm(bad2).ok).toBe(false)
})

it('rejects extra keys', () => {
  const bad = structuredClone(example) as unknown as Record<string, unknown>
  bad.colour = 'red'
  expect(parseForm(bad).ok).toBe(false)
})

it('rejects bilingual text objects and the removed form language', () => {
  const bad = structuredClone(example) as unknown as { settings: Record<string, unknown> }
  bad.settings.title = { en: 'Title', dv: 'ފޯމު' }
  expect(parseForm(bad).ok).toBe(false)
  const bad2 = structuredClone(example) as unknown as typeof bad
  bad2.settings.language = 'fr'
  expect(parseForm(bad2).ok).toBe(false)
})

it('lays the example (a Dhivehi form) out right to left from its title', () => {
  expect(formDirection(example)).toBe('rtl')
})
