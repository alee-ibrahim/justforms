import { describe, expect, it } from 'vitest'

import type { Form } from '@/schema'

import {
  insertOption,
  moveOption,
  nextOptionValue,
  removeOption,
  renameOption,
  setAllowOther,
  setElementText,
  setPageText,
  setSettingsText,
} from './inline-edit'

const form = (): Form => ({
  schemaVersion: '1',
  settings: { title: 'Registration', language: 'en' },
  pages: [
    {
      id: 'page_1',
      title: 'About you',
      elements: [
        { kind: 'field', id: 'short_text_1', type: 'short_text', label: '' },
        { kind: 'field', id: 'full_name', type: 'short_text', label: 'Full name', description: 'As on your ID card' },
        {
          kind: 'field',
          id: 'colour',
          type: 'single_choice',
          label: 'Favourite colour',
          options: [
            { value: 'red', label: 'Red' },
            { value: 'green', label: 'Green' },
          ],
        },
      ],
    },
  ],
})

const colour = (f: Form) => {
  const el = f.pages[0].elements![2]
  if (el.kind !== 'field' || el.type !== 'single_choice') throw new Error('not a choice')
  return el
}

describe('setElementText', () => {
  it('names an automatic key from a Latin label in the same change', () => {
    const out = setElementText(form(), 'short_text_1', 'label', 'Phone number')
    expect(out.id).toBe('phone_number')
    expect(out.form.pages[0].elements![0]).toMatchObject({ id: 'phone_number', label: 'Phone number' })
  })

  it('keeps a key the builder chose', () => {
    const out = setElementText(form(), 'full_name', 'label', 'Your name')
    expect(out.id).toBe('full_name')
  })

  it('removes optional text left empty, keeps a required label even when empty', () => {
    let f = setElementText(form(), 'full_name', 'description', '  ').form
    expect(f.pages[0].elements![1]).not.toHaveProperty('description')
    f = setElementText(f, 'full_name', 'label', '').form
    expect(f.pages[0].elements![1]).toHaveProperty('label', '')
  })
})

describe('form and page texts', () => {
  it('sets and clears settings texts', () => {
    let f = setSettingsText(form(), 'nextLabel', 'Continue')
    expect(f.settings.nextLabel).toBe('Continue')
    f = setSettingsText(f, 'nextLabel', '')
    expect(f.settings).not.toHaveProperty('nextLabel')
    expect(setSettingsText(f, 'title', '').settings.title).toBe('')
  })

  it('sets a page title and drops an empty description', () => {
    let f = setPageText(form(), 'page_1', 'description', 'Tell us about yourself')
    expect(f.pages[0].description).toBe('Tell us about yourself')
    f = setPageText(f, 'page_1', 'description', '')
    expect(f.pages[0]).not.toHaveProperty('description')
  })
})

describe('options', () => {
  it('renames by value without touching the value', () => {
    const f = renameOption(form(), 'colour', 'green', 'Leaf green')
    expect(colour(f).options[1]).toEqual({ value: 'green', label: 'Leaf green' })
  })

  it('inserts after a position with a fresh value', () => {
    const { form: f, value } = insertOption(form(), 'colour', 0, 'Blue')
    expect(value).toBe('option_3')
    expect(colour(f).options.map((o) => o.label)).toEqual(['Red', 'Blue', 'Green'])
    expect(colour(insertOption(f, 'colour', -1, 'First').form).options[0].label).toBe('First')
  })

  it('never removes the last option', () => {
    const one = removeOption(form(), 'colour', 'red')
    expect(colour(one).options).toHaveLength(1)
    expect(removeOption(one, 'colour', 'green')).toBe(one)
  })

  it('moves an option and refuses to move past the ends', () => {
    const f = moveOption(form(), 'colour', 'green', -1)
    expect(colour(f).options.map((o) => o.value)).toEqual(['green', 'red'])
    const same = form()
    expect(moveOption(same, 'colour', 'red', -1)).toBe(same)
  })

  it('turns "Other" on and off', () => {
    const on = setAllowOther(form(), 'colour', true)
    expect(colour(on).allowOther).toBe(true)
    expect(colour(setAllowOther(on, 'colour', false))).not.toHaveProperty('allowOther')
  })

  it('picks unused values', () => {
    expect(nextOptionValue([{ value: 'option_2', label: '' }, { value: 'x', label: '' }])).toBe('option_3')
  })
})
