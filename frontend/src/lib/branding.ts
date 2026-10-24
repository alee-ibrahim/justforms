/**
 * Organisation branding on the page (docs/ux/BRANDING-SCREENS.md, DESIGN 18.2). Shared by the
 * studio, the public form and the document pages, so it stays tiny: the colours arrive as a
 * same-origin stylesheet of CSS variables (no JS colour maths here), the logo and icon as
 * same-origin URLs.
 */
import { applyFormScheme } from './color-scheme'

/** A form theme's options that need markup (backend app/theme/resolve.py `options`). */
export interface ThemeOptions {
  colorScheme: 'light' | 'dark' | 'auto'
  buttonStyle: 'filled' | 'outline'
  buttonFullWidth: boolean
  inputStyle: 'outlined' | 'filled' | 'underlined'
  progressStyle: 'bar' | 'steps' | 'none'
  logoPlacement: 'start' | 'center' | 'end' | 'hidden'
  /** Logo height: small 24px, medium 32px, large 56px. */
  logoSize?: 's' | 'm' | 'l'
  /** Where the logo links to (http/https), or nothing. */
  logoLink?: string | null
  /** The logo this form shows: its own, else the organisation's (null: none). */
  logoUrl?: string | null
  logoDarkUrl?: string | null
  /** The form has its own logo (not the organisation's). */
  logoOwn?: boolean
  headerImageUrl: string | null
  backgroundImageUrl: string | null
}

const schemeKey = () => `justforms:scheme:${window.location.pathname.split('/').filter(Boolean)[0] ?? ''}`

function rememberFormScheme(scheme: ThemeOptions['colorScheme']): void {
  try {
    if (scheme === 'light') window.localStorage.removeItem(schemeKey())
    else window.localStorage.setItem(schemeKey(), scheme)
  } catch {
    // storage blocked
  }
}

/** The colour mode this form had last time (public form entry, before it loads). */
export function rememberedFormScheme(): ThemeOptions['colorScheme'] {
  try {
    const v = window.localStorage.getItem(schemeKey())
    return v === 'dark' || v === 'auto' ? v : 'light'
  } catch {
    return 'light'
  }
}

export interface Brand {
  name: string
  /** Anything set beyond JustForms' own identity. */
  custom: boolean
  logoUrl: string | null
  logoDarkUrl: string | null
  iconUrl: string | null
  supportUrl: string | null
  poweredBy: boolean
  themeUrl: string | null
  manifestUrl: string
  version: string
  /** On a form's public pages: its theme (`themeUrl` is then the form's theme stylesheet). */
  theme?: ThemeOptions
}

export const brandPath = (slug: string) => `/api/v1/public/branding/${encodeURIComponent(slug)}`

function link(rel: string, id: string): HTMLLinkElement {
  let el = document.getElementById(id) as HTMLLinkElement | null
  if (!el) {
    el = document.createElement('link')
    el.id = id
    el.rel = rel
    document.head.appendChild(el)
  }
  return el
}

/** Link a form's theme (colours, fonts, sizes) before the form loads, so it is there on first
 * paint; `applyBrand` later swaps in the versioned URL. */
export function preloadFormTheme(slug: string): void {
  link('stylesheet', 'df-theme').href = `/api/v1/public/forms/${encodeURIComponent(slug)}/theme.css`
}

/** Theme, favicon, manifest and tab title for `brand` (`null`: JustForms' own). On a form's
 * public pages (`brand.theme` set) also its colour mode, remembered per form so the next visit
 * starts in it. */
export function applyBrand(brand: Brand | null, title?: string): void {
  if (brand?.theme) {
    applyFormScheme(brand.theme.colorScheme)
    rememberFormScheme(brand.theme.colorScheme)
  }
  const theme = document.getElementById('df-theme')
  if (brand?.themeUrl) link('stylesheet', 'df-theme').href = brand.themeUrl
  else theme?.remove()
  for (const el of document.querySelectorAll<HTMLLinkElement>('link[rel=icon], link[rel=apple-touch-icon]')) {
    el.dataset.href ??= el.getAttribute('href') ?? ''
    el.dataset.type ??= el.type
    el.href = brand?.iconUrl ?? el.dataset.href
    el.type = brand?.iconUrl ? '' : el.dataset.type
  }
  const manifest = document.querySelector<HTMLLinkElement>('link[rel=manifest]')
  if (manifest && brand) manifest.href = brand.manifestUrl
  const name = brand?.custom ? brand.name : ''
  if (title !== undefined) document.title = title && name ? `${title} – ${name}` : title || name || 'JustForms'
}
