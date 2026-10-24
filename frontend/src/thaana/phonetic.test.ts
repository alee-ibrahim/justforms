import { describe, expect, it } from 'vitest'

import { KEYMAP, transliterate } from '@yashau/thaana-react'

const mapKey = (k: string) => transliterate(k)

// Keystroke -> output table (DESIGN 16).
const TABLE: [string, string][] = [
  ['h', 'ހ'],
  ['S', 'ށ'],
  ['n', 'ނ'],
  ['r', 'ރ'],
  ['b', 'ބ'],
  ['L', 'ޅ'],
  ['k', 'ކ'],
  ['a', 'ަ'],
  ['A', 'ާ'],
  ['i', 'ި'],
  ['I', 'ީ'],
  ['u', 'ު'],
  ['U', 'ޫ'],
  ['e', 'ެ'],
  ['E', 'ޭ'],
  ['o', 'ޮ'],
  ['O', 'ޯ'],
  ['q', 'ް'],
  ['w', 'އ'],
  [',', '،'],
  [';', '؛'],
  ['?', '؟'],
]

describe('phonetic layout', () => {
  it.each(TABLE)('%s -> %s', (key, out) => {
    expect(mapKey(key)).toBe(out)
  })

  it('passes digits, spaces and unmapped symbols through', () => {
    for (const ch of '0123456789 .-/') expect(mapKey(ch)).toBe(ch)
  })

  it('transliterates words', () => {
    expect(transliterate('divehi')).toBe('ދިވެހި')
    expect(transliterate('fOmu')).toBe('ފޯމު')
    expect(transliterate('nan')).toBe('ނަނ')
    expect(transliterate('A123456')).toBe('ާ123456')
  })

  it('maps every letter key', () => {
    for (const key of 'abcdefghijklmnopqrstuvwxyz') expect(KEYMAP[key]).toBeTruthy()
  })
})
