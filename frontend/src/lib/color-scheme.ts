/**
 * Light or dark: toggles `.dark` on <html>; shadcn components read the `.dark` variables from
 * index.css (docs/ux/FORM-THEME-SCREENS.md section 2).
 *
 * - The studio is light unless the person chose dark or "match device" (`users.appearance`,
 *   cached in localStorage and applied before the first paint by /appearance.js).
 * - Public form, approver and verify pages are light unless the form's theme says dark or
 *   "match device"; they never read the studio preference.
 */
export type Appearance = 'light' | 'dark' | 'system'

const KEY = 'justforms:appearance'
let unfollow: (() => void) | null = null

export function applyAppearance(pref: Appearance): void {
  unfollow?.()
  unfollow = null
  const root = document.documentElement
  if (pref !== 'system') {
    root.classList.toggle('dark', pref === 'dark')
    return
  }
  const query = window.matchMedia('(prefers-color-scheme: dark)')
  const apply = () => root.classList.toggle('dark', query.matches)
  apply()
  query.addEventListener('change', apply)
  unfollow = () => query.removeEventListener('change', apply)
}

export function storedAppearance(): Appearance {
  try {
    const v = window.localStorage.getItem(KEY)
    return v === 'dark' || v === 'system' ? v : 'light'
  } catch {
    return 'light'
  }
}

export function rememberAppearance(pref: Appearance): void {
  try {
    window.localStorage.setItem(KEY, pref)
  } catch {
    // private mode: applies to this page only
  }
}

/** A form's colour mode for the people filling it in (`auto` follows the device). */
export function applyFormScheme(scheme: 'light' | 'dark' | 'auto' | null | undefined): void {
  applyAppearance(scheme === 'dark' ? 'dark' : scheme === 'auto' ? 'system' : 'light')
}
