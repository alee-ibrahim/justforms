import { describe, expect, it } from 'vitest'

import { themeScope } from '@/lib/theme'
import type { ThemeReport } from '@/lib/api'

import { DEFAULT_THEME, themeAttrs } from './theme'

describe('form theme on the root', () => {
  it('defaults to filled buttons and outlined inputs', () => {
    expect(themeAttrs(null)).toEqual({ 'data-df-theme': '', 'data-df-button': 'filled', 'data-df-input': 'outlined' })
  })

  it('scopes the chosen mode with its tokens and options', () => {
    const report = {
      light: { '--primary': '#0F766E' },
      dark: { '--primary': '#7DD3C8' },
      fonts: [],
      options: { ...DEFAULT_THEME, buttonStyle: 'outline', inputStyle: 'underlined' },
    } as unknown as ThemeReport
    const scope = themeScope(report, 'dark')
    expect(scope.className).toBe('dark')
    expect(scope.style).toEqual({ '--primary': '#7DD3C8' })
    expect(scope['data-df-button']).toBe('outline')
    expect(scope['data-df-input']).toBe('underlined')
  })
})
