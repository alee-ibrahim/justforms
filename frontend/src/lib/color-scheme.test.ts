// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest'

import { applyAppearance, applyFormScheme, rememberAppearance, storedAppearance } from './color-scheme'

const dark = () => document.documentElement.classList.contains('dark')

describe('appearance', () => {
  afterEach(() => {
    window.localStorage.clear()
    applyAppearance('light')
  })

  it('defaults to light when nothing is stored', () => {
    expect(storedAppearance()).toBe('light')
    applyAppearance(storedAppearance())
    expect(dark()).toBe(false)
  })

  it('remembers the choice and applies dark', () => {
    rememberAppearance('dark')
    expect(storedAppearance()).toBe('dark')
    applyAppearance('dark')
    expect(dark()).toBe(true)
    window.localStorage.setItem('justforms:appearance', 'sepia')
    expect(storedAppearance()).toBe('light')
  })

  it('maps a form colour mode: light unless dark or auto', () => {
    applyFormScheme('dark')
    expect(dark()).toBe(true)
    applyFormScheme(null)
    expect(dark()).toBe(false)
    applyFormScheme('auto') // follows the device; happy-dom reports light
    expect(dark()).toBe(false)
  })
})
