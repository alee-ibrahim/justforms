// @vitest-environment happy-dom
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { Brand } from '@/lib/branding'
import type { Form } from '@/schema'

import { FormHeader } from './form-view'
import { DEFAULT_THEME } from './theme'

const form = (language: 'en' | 'dv' = 'en'): Form => ({
  schemaVersion: '1',
  settings: { title: 'Youth programme', language },
  pages: [{ id: 'page_1', elements: [] }],
})

const brand = { name: 'Example Youth Office', logoUrl: '/org-logo.png', logoDarkUrl: '/org-logo-dark.png' } as Brand

describe('FormHeader logo', () => {
  it("shows the organisation's logo when the form has none", () => {
    const html = renderToStaticMarkup(<FormHeader form={form()} brand={brand} />)
    expect(html).toContain('src="/org-logo.png"')
    expect(html).toContain('alt="Example Youth Office"')
  })

  it("shows the form's own logo at its size and position, linked", () => {
    const html = renderToStaticMarkup(
      <FormHeader
        form={form()}
        brand={brand}
        theme={{
          ...DEFAULT_THEME,
          logoUrl: '/api/v1/public/form-logos/f/abc.png',
          logoDarkUrl: null,
          logoOwn: true,
          logoSize: 'l',
          logoPlacement: 'end',
          logoLink: 'https://example.org',
        }}
      />,
    )
    expect(html).toContain('src="/api/v1/public/form-logos/f/abc.png"')
    expect(html).not.toContain('org-logo')
    expect(html).toContain('h-14')
    expect(html).toContain('justify-end')
    expect(html).toContain('href="https://example.org"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('aria-label="Youth programme, opens in a new tab"')
  })

  it('hides the logo when the position is hidden', () => {
    const html = renderToStaticMarkup(
      <FormHeader form={form()} brand={brand} theme={{ ...DEFAULT_THEME, logoPlacement: 'hidden' }} />,
    )
    expect(html).not.toContain('<img')
  })

  it('uses logical alignment, so start is on the right in a Dhivehi form', () => {
    const html = renderToStaticMarkup(
      <FormHeader form={form('dv')} brand={brand} theme={{ ...DEFAULT_THEME, logoPlacement: 'start' }} />,
    )
    expect(html).toContain('justify-start')
    expect(html).not.toMatch(/\b(left|right)-/)
  })
})
