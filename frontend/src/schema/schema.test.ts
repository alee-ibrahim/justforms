import { expect, it } from 'vitest'

import { loadSpecFile } from '@/logic/spec-files'

import { contentProps, formLanguage, parseForm, type Form } from '.'

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

it('rejects bilingual text objects and unknown languages', () => {
  const bad = structuredClone(example) as unknown as { settings: Record<string, unknown> }
  bad.settings.title = { en: 'Title', dv: 'ފޯމު' }
  expect(parseForm(bad).ok).toBe(false)
  const bad2 = structuredClone(example) as unknown as typeof bad
  bad2.settings.language = 'fr'
  expect(parseForm(bad2).ok).toBe(false)
})

it('derives lang and direction from the form language', () => {
  expect(formLanguage(example)).toBe('dv')
  expect(contentProps(formLanguage(example))).toEqual({ lang: 'dv', dir: 'rtl' })
  const en = { ...example, settings: { title: 'T' } }
  expect(formLanguage(en)).toBe('en')
  expect(contentProps('en')).toEqual({ lang: 'en', dir: 'ltr' })
})
