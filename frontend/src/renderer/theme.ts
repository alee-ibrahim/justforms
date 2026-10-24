/**
 * A form theme on the form root (docs/ux/FORM-THEME-SCREENS.md 3.5): `data-df-*` attributes that
 * index.css styles. The variables themselves arrive as a stylesheet (public pages) or inline
 * (studio canvas and previews).
 */
import type { ThemeOptions } from '@/lib/branding'

export const DEFAULT_THEME: ThemeOptions = {
  colorScheme: 'light',
  buttonStyle: 'filled',
  buttonFullWidth: true,
  inputStyle: 'outlined',
  progressStyle: 'bar',
  logoPlacement: 'start',
  headerImageUrl: null,
  backgroundImageUrl: null,
}

export interface ThemeAttrs {
  'data-df-theme': ''
  'data-df-button': ThemeOptions['buttonStyle']
  'data-df-input': ThemeOptions['inputStyle']
}

export function themeAttrs(theme: ThemeOptions | null | undefined): ThemeAttrs {
  const t = theme ?? DEFAULT_THEME
  return {
    'data-df-theme': '',
    'data-df-button': t.buttonStyle,
    'data-df-input': t.inputStyle,
  }
}
