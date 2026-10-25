/**
 * Automatic single sign-on (JUSTFORMS_OIDC_AUTO_REDIRECT, DESIGN 8.1). With OIDC on, a signed-out
 * visit to the sign-in page (or any studio page) goes straight to the identity provider. Escape
 * hatches so it never loops: not right after signing out, not after a failed sign-in (`?error=`),
 * not with `?manual=1`, and not twice within ATTEMPT_WINDOW_MS in the same tab.
 *
 * The signed-out flag lives in sessionStorage: per tab, and it survives the round trip to the
 * IdP. The attempt time is a short-lived cookie instead, because a successful sign-in sends
 * Clear-Site-Data "storage" (which never clears cookies): if the session cookie then fails to
 * stick, the guard still stops a second bounce.
 */
import { ssoLoginUrl, type Meta } from '@/lib/api'

const SIGNED_OUT_KEY = 'justforms:signed-out'
const ATTEMPT_COOKIE = 'justforms_sso_attempt'
export const ATTEMPT_WINDOW_MS = 30_000

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function store(): Store | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

function read(key: string, s: Store | null = store()): string | null {
  try {
    return s?.getItem(key) ?? null
  } catch {
    return null
  }
}

function write(key: string, value: string | null, s: Store | null = store()) {
  try {
    if (value === null) s?.removeItem(key)
    else s?.setItem(key, value)
  } catch {
    // Storage blocked: auto sign-in still works, only the loop guard is lost.
  }
}

/** Call before signing out: the sign-in page then says "You're signed out" instead of
 * sending the person straight back to the IdP (which would sign them in again). */
export const markSignedOut = (s?: Store | null) => write(SIGNED_OUT_KEY, '1', s)
/** A deliberate "Sign in again" or a live session ends the signed-out state. */
export const clearSignedOut = (s?: Store | null) => write(SIGNED_OUT_KEY, null, s)
export const isSignedOut = (s?: Store | null) => read(SIGNED_OUT_KEY, s) === '1'

/** Where to land after signing in: a same-origin path, else the forms list. */
export const loginTarget = (next: string | undefined) =>
  next && next.startsWith('/') && !next.startsWith('//') && !next.includes('\\') ? next : '/forms'

export interface AutoSignInInput {
  features: Pick<Meta['features'], 'oidc' | 'oidcAutoRedirect'> | undefined
  /** `?error=` from a failed callback. */
  error?: string
  /** `?manual=1`: show the normal sign-in page. */
  manual?: boolean
  now?: number
  storage?: Store | null
  /** `document.cookie` (injectable for tests). */
  cookie?: string
}

function lastAttempt(cookie: string): number {
  const m = /(?:^|;\s*)justforms_sso_attempt=(\d+)/.exec(cookie)
  return m ? Number(m[1]) : 0
}

function readCookie(): string {
  try {
    return document.cookie
  } catch {
    return ''
  }
}

/** Whether this visit should go straight to the IdP. */
export function shouldAutoSignIn({
  features,
  error,
  manual,
  now = Date.now(),
  storage,
  cookie = readCookie(),
}: AutoSignInInput): boolean {
  if (!features?.oidc || !features.oidcAutoRedirect) return false
  if (error || manual) return false
  if (isSignedOut(storage === undefined ? store() : storage)) return false
  const last = lastAttempt(cookie)
  if (last && now - last >= 0 && now - last < ATTEMPT_WINDOW_MS) return false
  return true
}

/** The cookie that records an automatic attempt for ATTEMPT_WINDOW_MS. */
export function attemptCookie(now: number, secure = window.location.protocol === 'https:'): string {
  const maxAge = Math.ceil(ATTEMPT_WINDOW_MS / 1000)
  return `${ATTEMPT_COOKIE}=${now}; Max-Age=${maxAge}; Path=/; SameSite=Lax${secure ? '; Secure' : ''}`
}

/** The IdP round-trip URL for an automatic sign-in, or null when the page should render. */
export function autoSignInUrl(input: AutoSignInInput & { next: string; loginHint?: string | null }): string | null {
  return shouldAutoSignIn(input) ? ssoLoginUrl(input.next, input.loginHint) : null
}

/** Leave for the IdP, remembering the attempt (the loop guard). `replace` keeps the
 * bounce out of the history, so Back doesn't land on it again. */
export function startAutoSignIn(url: string, now = Date.now()) {
  try {
    document.cookie = attemptCookie(now)
  } catch {
    // Cookies blocked: then the session cookie can't work either; the IdP round trip shows it.
  }
  window.location.replace(url)
}
