import { describe, expect, it } from 'vitest'

import { normalizeSlug, readableSlug } from '@/components/forms/slug'
import { loadSpecFile } from '@/logic/spec-files'

import { hasThaana, isGenericSlug, romanise, romaniseWord, titleSlug, TITLE_SLUG_LENGTH } from './latin'

type Pair = { thaana: string; latin: string }
const latin = loadSpecFile<{ words: Pair[]; texts: Pair[] }>('slugs/thaana-latin.json')
const slugs = loadSpecFile<{ cases: { title: string; slug: string }[] }>('slugs/slugs.json')

describe('romanise (shared vectors, spec/slugs)', () => {
  it.each(latin.words)('booklet example $latin', ({ thaana, latin: want }) => {
    expect(romaniseWord(thaana)).toBe(want)
  })

  it.each(latin.texts)('text $latin', ({ thaana, latin: want }) => {
    expect(romanise(thaana)).toBe(want)
  })

  it('passes Latin text through', () => {
    expect(hasThaana('Survey 2026')).toBe(false)
    expect(romanise('ފޯމު - Form')).toBe('Foamu - Form')
  })
})

describe('titleSlug (shared vectors, spec/slugs)', () => {
  it.each(slugs.cases)('$title -> $slug', ({ title, slug }) => {
    const got = titleSlug(title)
    expect(got).toBe(slug)
    expect(got.length).toBeLessThanOrEqual(TITLE_SLUG_LENGTH)
  })
})

describe('address helpers', () => {
  it('romanises Thaana typed into the address field', () => {
    expect(normalizeSlug('ކަނޑި')).toBe('kandi')
    expect(normalizeSlug('My Form')).toBe('my-form')
  })

  it('offers a readable address only to Dhivehi forms at a generic one', () => {
    expect(isGenericSlug('form-3')).toBe(true)
    expect(isGenericSlug('forms')).toBe(false)
    expect(readableSlug({ slug: 'form-3', title: 'ޢީދު މުބާރަކް' })).toBe('eedhu-mubaarak')
    expect(readableSlug({ slug: 'eid', title: 'ޢީދު މުބާރަކް' })).toBeNull()
    expect(readableSlug({ slug: 'form', title: 'Form' })).toBeNull()
    expect(readableSlug({ slug: 'form', title: '؟' })).toBeNull()
  })
})
