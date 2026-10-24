/**
 * Loads the configured Thaana font stylesheet (JUSTFORMS_THAANA_FONT_CSS_URL, Faruma by default)
 * once. Faruma files are never bundled; Noto Sans Thaana is the bundled fallback.
 */
export function loadThaanaFont(url: string | null | undefined): void {
  if (!url || document.getElementById('justforms-thaana-font')) return
  const link = document.createElement('link')
  link.id = 'justforms-thaana-font'
  link.rel = 'stylesheet'
  link.href = url
  link.crossOrigin = 'anonymous'
  document.head.appendChild(link)
}
