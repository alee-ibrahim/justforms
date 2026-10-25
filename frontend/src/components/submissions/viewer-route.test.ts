// @vitest-environment happy-dom
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'

import { createAppRouter } from '@/router'

const leaf = (path: string) => {
  const router = createAppRouter(new QueryClient(), createMemoryHistory({ initialEntries: ['/'] }))
  const matches = router.matchRoutes(path, {})
  return matches.at(-1)!
}

describe('submission view route', () => {
  it('is linkable by reference number, with the list view state', () => {
    const m = leaf('/forms/abc/submissions/47')
    expect(m.routeId).toBe('/authed/forms/$formId/submissions/$ref')
    expect(m.params).toMatchObject({ formId: 'abc', ref: '47' })
  })

  it('leaves the import page and the list alone', () => {
    expect(leaf('/forms/abc/submissions/import').routeId).toBe('/authed/forms/$formId/submissions/import')
    expect(leaf('/forms/abc/submissions').routeId).toBe('/authed/forms/$formId/submissions')
  })
})
