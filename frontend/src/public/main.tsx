/**
 * Public form entry (`/{slug}`, `?embed=1`), separate from the studio so the
 * respondent bundle stays small.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '../index.css'

import { preloadFormTheme, rememberedFormScheme } from '@/lib/branding'
import { applyFormScheme } from '@/lib/color-scheme'

import { App } from './app'
import { formSlug } from './helpers'

if (formSlug) {
  preloadFormTheme(formSlug)
  applyFormScheme(rememberedFormScheme())
}


createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
