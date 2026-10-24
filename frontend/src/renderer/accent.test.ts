import { describe, expect, it } from 'vitest'

import { contrastWithWhite, legibleAccent } from './accent'

const rgb = (hex: string) =>
  [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255) as [number, number, number]

describe('legibleAccent', () => {
  it('keeps a dark enough accent', () => {
    expect(legibleAccent('#0f766e')).toBe('#0f766e')
  })
  it('darkens a pale accent until it passes 4.5:1 on white', () => {
    const out = legibleAccent('#ffe45c')!
    expect(contrastWithWhite(rgb(out))).toBeGreaterThanOrEqual(4.5)
  })
  it('ignores missing or malformed values', () => {
    expect(legibleAccent(null)).toBeNull()
    expect(legibleAccent('teal')).toBeNull()
  })
})
