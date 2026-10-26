/**
 * Form themes in the studio (docs/ux/FORM-THEME-SCREENS.md 3.4-3.5): the canvas and the live
 * previews get the theme's variables inline from the API's report (light or dark set), plus its
 * font stylesheets as links. Public pages use the stylesheet instead.
 */
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState, type CSSProperties } from 'react'

import { api, type FormTheme, type ResolvedTheme, type ThemeColors, type ThemeReport } from '@/lib/api'
import { themeAttrs } from '@/renderer/theme'

/** Link each font stylesheet once (Latin theme fonts are same-origin, Thaana from the font
 * service the CSP already allows). */
export function useFontLinks(urls: readonly string[] | undefined): void {
  const key = (urls ?? []).join('|')
  useEffect(() => {
    for (const url of key ? key.split('|') : []) {
      if (document.querySelector(`link[data-df-font="${CSS.escape(url)}"]`)) continue
      const el = document.createElement('link')
      el.rel = 'stylesheet'
      el.href = url
      el.dataset.dfFont = url
      if (/^https?:/.test(url)) el.crossOrigin = 'anonymous'
      document.head.appendChild(el)
    }
  }, [key])
}

export type ThemeMode = 'light' | 'dark'

/** Props for a themed container: the mode class (which also stops the studio's own dark mode
 * leaking in), the variables and the `data-df-*` options. */
export function themeScope(report: ThemeReport | undefined, mode: ThemeMode) {
  return {
    className: mode,
    style: (report ? report[mode] : undefined) as CSSProperties | undefined,
    ...themeAttrs(report?.options),
  }
}

function useDebounced<T>(value: T, ms: number): T {
  const [out, setOut] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setOut(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return out
}

/** The report for unsaved values, refreshed ~250 ms after the last change. */
export function useThemePreview(
  orgId: string | undefined,
  organisation: FormTheme | undefined,
  form: FormTheme | undefined,
  initial: ThemeReport | undefined,
  formId?: string,
) {
  const body = useDebounced(JSON.stringify({ orgId, organisation, form, formId }), 250)
  const query = useQuery({
    queryKey: ['theme-preview', body],
    queryFn: () => api.previewTheme(JSON.parse(body) as Parameters<typeof api.previewTheme>[0]),
    enabled: !!orgId,
    placeholderData: (prev) => prev ?? initial,
    staleTime: 60_000,
  })
  return query.data ?? initial
}

/** The canvas mode for a form: its own colour mode, or the studio's for "match device". */
export function canvasMode(report: ThemeReport | undefined): ThemeMode {
  const scheme = report?.options.colorScheme ?? 'light'
  if (scheme === 'auto') return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
  return scheme
}

export interface ThemeBase {
  /** Inherited values (organisation's, or JustForms' defaults). */
  resolved: ResolvedTheme
  colors: ThemeColors
}

export const JUSTFORMS_DEFAULTS: ThemeBase = {
  resolved: {
    latinFont: 'inter',
    thaanaFont: 'faruma',
    textSize: 'm',
    headingScale: 'standard',
    radius: 'medium',
    density: 'comfortable',
    pageWidth: 'standard',
    buttonStyle: 'filled',
    buttonFullWidth: true,
    inputStyle: 'outlined',
    progressStyle: 'bar',
    colorScheme: 'light',
    logoPlacement: 'start',
    logoSize: 'm',
    logoLink: null,
    headerImage: null,
    backgroundImage: null,
  },
  colors: {},
}

