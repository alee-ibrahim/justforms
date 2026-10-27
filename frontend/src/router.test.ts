// @vitest-environment happy-dom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Meta } from '@/lib/api'

vi.mock('@/lib/sso-auto', async (importActual) => ({
  ...(await importActual<typeof import('@/lib/sso-auto')>()),
  startAutoSignIn: vi.fn(),
}))

const { startAutoSignIn, markSignedOut } = await import('@/lib/sso-auto')
const { createAppRouter } = await import('@/router')

function meta(oidcAutoRedirect = true): Meta {
  return {
    version: 'test',
    features: {
      ai: false,
      aiVision: false,
      oidc: true,
      oidcAutoRedirect,
      localLogin: false,
      demo: false,
      email: false,
      captcha: 'none',
      captchaBusyThreshold: 1000,
    },
    thaanaFontCssUrl: '',
  }
}

async function visit(path: string, autoRedirect = true) {
  const queryClient = new QueryClient()
  queryClient.setQueryData(['me'], null)
  queryClient.setQueryData(['meta'], meta(autoRedirect))
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }))
  await router.load()
  return router
}

beforeEach(() => {
  vi.mocked(startAutoSignIn).mockClear()
  window.sessionStorage.clear()
  document.cookie = 'justforms_sso_attempt=; Max-Age=0; Path=/'
})
afterEach(() => window.sessionStorage.clear())

describe('signed-out studio visits with OIDC', () => {
  it('go straight to the IdP, keeping the page as next', async () => {
    const router = await visit('/forms/abc/edit')
    expect(router.state.location.pathname).toBe('/login')
    expect(startAutoSignIn).toHaveBeenCalledWith('/api/v1/auth/login?next=%2Fforms%2Fabc%2Fedit')
    expect(router.state.matches.at(-1)?.context).toMatchObject({ autoSignIn: true })
  })

  it('the sign-in page itself defaults next to the studio home', async () => {
    await visit('/login')
    expect(startAutoSignIn).toHaveBeenCalledWith('/api/v1/auth/login?next=%2Fforms')
  })

  it('not after signing out', async () => {
    markSignedOut()
    const router = await visit('/forms')
    expect(startAutoSignIn).not.toHaveBeenCalled()
    expect(router.state.matches.at(-1)?.context).toMatchObject({ autoSignIn: false })
  })

  it('not after a failed sign-in, nor with ?manual=1', async () => {
    await visit('/login?error=sso_failed')
    await visit('/login?manual=1')
    expect(startAutoSignIn).not.toHaveBeenCalled()
  })

  it('not when auto-redirect is turned off', async () => {
    await visit('/forms', false)
    expect(startAutoSignIn).not.toHaveBeenCalled()
  })
})
