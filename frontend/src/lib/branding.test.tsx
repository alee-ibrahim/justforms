// @vitest-environment happy-dom
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it } from 'vitest'

import { BrandFooter, BrandLogo } from '@/components/brand/brand-parts'

import { applyBrand, preloadFormTheme, type Brand } from './branding'

const brand: Brand = {
  name: 'Example Youth Office',
  custom: true,
  logoUrl: '/api/v1/public/branding/example/logo?v=1',
  logoDarkUrl: null,
  iconUrl: '/api/v1/public/branding/example/icon?v=2',
  supportUrl: 'https://example.org/help',
  poweredBy: true,
  themeUrl: '/api/v1/public/branding/example/theme.css?v=3',
  manifestUrl: '/api/v1/public/branding/example/manifest.webmanifest?v=3',
  version: '3',
}

beforeEach(() => {
  document.head.innerHTML =
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg"><link rel="apple-touch-icon" href="/apple-touch-icon.png"><link rel="manifest" href="/manifest.webmanifest">'
  document.title = 'JustForms'
})

describe('applyBrand', () => {
  it('links the theme, swaps the icons and manifest and titles the tab', () => {
    applyBrand(brand, 'Application form')
    expect(document.querySelector<HTMLLinkElement>('#df-theme')?.getAttribute('href')).toBe(brand.themeUrl)
    const icon = document.querySelector<HTMLLinkElement>('link[rel=icon]')!
    expect(icon.getAttribute('href')).toBe(brand.iconUrl)
    expect(icon.getAttribute('type')).toBe('')
    expect(document.querySelector('link[rel=manifest]')?.getAttribute('href')).toBe(brand.manifestUrl)
    expect(document.title).toBe('Application form – Example Youth Office')
  })

  it("falls back to JustForms' own identity", () => {
    applyBrand(brand, '')
    applyBrand(null, '')
    expect(document.querySelector('#df-theme')).toBeNull()
    const icon = document.querySelector<HTMLLinkElement>('link[rel=icon]')!
    expect(icon.getAttribute('href')).toBe('/favicon.svg')
    expect(icon.getAttribute('type')).toBe('image/svg+xml')
    expect(document.title).toBe('JustForms')
  })

  it('keeps JustForms in the title when nothing is branded', () => {
    applyBrand({ ...brand, custom: false, themeUrl: null, iconUrl: null }, 'Form')
    expect(document.title).toBe('Form')
    expect(document.querySelector('#df-theme')).toBeNull()
  })

  it("preloads the form's theme from its address", () => {
    preloadFormTheme('youth-app')
    expect(document.querySelector('#df-theme')?.getAttribute('href')).toBe('/api/v1/public/forms/youth-app/theme.css')
  })
})

describe('brand parts', () => {
  const html = (el: ReactElement) => renderToStaticMarkup(el)

  it('shows the logo with the name as its text alternative', () => {
    expect(html(<BrandLogo brand={brand} />)).toContain('alt="Example Youth Office"')
    expect(html(<BrandLogo brand={{ ...brand, logoUrl: null }} />)).toBe('')
  })

  it('shows "Made with JustForms" by default and "Powered by JustForms" for a brand', () => {
    expect(html(<BrandFooter brand={null} madeWith="Made with JustForms" />)).toContain('Made with JustForms')
    const branded = html(<BrandFooter brand={brand} madeWith="Made with JustForms" />)
    expect(branded).toContain('Powered by JustForms')
    expect(branded).toContain('href="https://example.org/help"')
    expect(html(<BrandFooter brand={{ ...brand, poweredBy: false, supportUrl: null }} madeWith="x" />)).toBe('')
  })
})
