// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'

import { ssoLoginUrl } from '@/lib/api'

import {
  ATTEMPT_WINDOW_MS,
  attemptCookie,
  autoSignInUrl,
  clearSignedOut,
  isSignedOut,
  loginTarget,
  markSignedOut,
  shouldAutoSignIn,
} from './sso-auto'

const on = { oidc: true, oidcAutoRedirect: true }

function memory() {
  const data = new Map<string, string>()
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  }
}

describe('automatic single sign-on', () => {
  it('goes straight to the IdP when OIDC and auto-redirect are on', () => {
    expect(shouldAutoSignIn({ features: on, storage: memory(), cookie: '' })).toBe(true)
  })

  it('stays on the page when OIDC or auto-redirect is off, or meta is unknown', () => {
    const storage = memory()
    expect(shouldAutoSignIn({ features: { oidc: true, oidcAutoRedirect: false }, storage, cookie: '' })).toBe(false)
    expect(shouldAutoSignIn({ features: { oidc: false, oidcAutoRedirect: true }, storage, cookie: '' })).toBe(false)
    expect(shouldAutoSignIn({ features: undefined, storage, cookie: '' })).toBe(false)
  })

  it('does not sign people straight back in after they sign out', () => {
    const storage = memory()
    markSignedOut(storage)
    expect(isSignedOut(storage)).toBe(true)
    expect(shouldAutoSignIn({ features: on, storage, cookie: '' })).toBe(false)
    // "Sign in again" (or a live session) ends the signed-out state.
    clearSignedOut(storage)
    expect(shouldAutoSignIn({ features: on, storage, cookie: '' })).toBe(true)
  })

  it('does not bounce again after a failed sign-in, or with ?manual=1', () => {
    expect(shouldAutoSignIn({ features: on, error: 'sso_failed', storage: memory(), cookie: '' })).toBe(false)
    expect(shouldAutoSignIn({ features: on, error: 'anything', storage: memory(), cookie: '' })).toBe(false)
    expect(shouldAutoSignIn({ features: on, manual: true, storage: memory(), cookie: '' })).toBe(false)
  })

  it('tries at most once within the attempt window', () => {
    const now = 1_800_000_000_000
    const cookie = `theme=x; justforms_sso_attempt=${now - 5_000}; other=1`
    expect(shouldAutoSignIn({ features: on, now, storage: memory(), cookie })).toBe(false)
    expect(
      shouldAutoSignIn({ features: on, now: now - 5_000 + ATTEMPT_WINDOW_MS, storage: memory(), cookie }),
    ).toBe(true)
  })

  it('records the attempt in a short-lived cookie (Clear-Site-Data "storage" keeps cookies)', () => {
    expect(attemptCookie(123, false)).toBe('justforms_sso_attempt=123; Max-Age=30; Path=/; SameSite=Lax')
    expect(attemptCookie(123, true)).toContain('; Secure')
  })

  it('keeps the return-to path through the round trip', () => {
    expect(autoSignInUrl({ features: on, next: '/forms/abc/edit?tab=logic', storage: memory(), cookie: '' })).toBe(
      ssoLoginUrl('/forms/abc/edit?tab=logic'),
    )
    expect(ssoLoginUrl('/forms/abc/edit?tab=logic')).toBe('/api/v1/auth/login?next=%2Fforms%2Fabc%2Fedit%3Ftab%3Dlogic')
    expect(autoSignInUrl({ features: on, error: 'sso_failed', next: '/forms', storage: memory(), cookie: '' })).toBeNull()
  })

  it('passes the invited address as a login hint', () => {
    expect(
      autoSignInUrl({ features: on, next: '/login/invite/tok', loginHint: 'a.b@example.org', storage: memory(), cookie: '' }),
    ).toBe('/api/v1/auth/login?next=%2Flogin%2Finvite%2Ftok&login_hint=a.b%40example.org')
  })

  it('lands on the studio home without a usable next, never "/"', () => {
    expect(loginTarget(undefined)).toBe('/forms')
    expect(loginTarget('')).toBe('/forms')
    expect(loginTarget('//evil.example')).toBe('/forms')
    expect(loginTarget('https://evil.example')).toBe('/forms')
    expect(loginTarget('/\\evil')).toBe('/forms')
    expect(loginTarget('/settings/people')).toBe('/settings/people')
  })
})
