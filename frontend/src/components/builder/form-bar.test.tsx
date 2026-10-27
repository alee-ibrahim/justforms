// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { FormSummary } from '@/lib/api'
import type { Form } from '@/schema'

import { FormBar } from './form-bar'
import { BuilderContext, BuilderStore } from './store'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const schema: Form = { schemaVersion: '1', settings: { title: 'Intake' }, pages: [{ id: 'page_1', elements: [] }] }

const summary: FormSummary = {
  id: 'f1',
  orgId: 'o1',
  orgSlug: 'org',
  slug: 'intake',
  url: 'http://localhost/intake',
  title: 'Intake',
  status: 'live',
  accessMode: 'public',
  draftRevision: 3,
  currentVersion: 1,
  role: 'owner',
  embedOrigins: [],
  retentionDays: null,
  otpAllowedDomains: [],
  otpOneResponse: false,
  captcha: 'off',
  saveProgress: false,
  saveProgressDays: 7,
  submissionCount: 0,
  newCount: 0,
  createdAt: '2026-10-01T00:00:00Z',
  updatedAt: '2026-10-01T00:00:00Z',
}

let root: Root | undefined
let host: HTMLElement | undefined

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
})

async function render(path: string) {
  const store = new BuilderStore('f1', { schema, revision: 3, canUndo: true, canRedo: false })
  const rootRoute = createRootRoute({
    component: () => (
      <TooltipProvider>
        <BuilderContext.Provider value={store}>
          <FormBar form={summary} store={store} unpublished onPublish={() => {}} />
          <Outlet />
        </BuilderContext.Provider>
      </TooltipProvider>
    ),
  })
  const pages = ['edit', 'preview', 'share', 'submissions', 'submissions/$ref', 'settings', 'submissions/insights']
  const children = ['/forms', ...pages.map((p) => `/forms/$formId/${p}`)].map((p) =>
    createRoute({ getParentRoute: () => rootRoute, path: p }),
  )
  const router = createRouter({
    routeTree: rootRoute.addChildren(children),
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  await router.load()
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  await act(async () => {
    root!.render(
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )
  })
  return host
}

const historyButtons = (el: HTMLElement) => el.querySelectorAll('[aria-label="History"]')

describe('FormBar undo and redo', () => {
  it('shows them on the builder (Edit)', async () => {
    const el = await render('/forms/f1/edit')
    expect(historyButtons(el)).toHaveLength(1)
    expect(el.querySelector('button[aria-label^="Undo"]')).not.toBeNull()
    // Save state and Publish stay.
    expect(el.textContent).toContain('Saved')
    expect([...el.querySelectorAll('button')].some((b) => b.textContent === 'Publish')).toBe(true)
  })

  it.each(['preview', 'share', 'submissions', 'submissions/12', 'settings', 'submissions/insights'])(
    'hides them on %s',
    async (page) => {
      const el = await render(`/forms/f1/${page}`)
      expect(historyButtons(el)).toHaveLength(0)
      expect(el.querySelector('button[aria-label^="Undo"]')).toBeNull()
      expect(el.querySelector('button[aria-label^="Redo"]')).toBeNull()
    },
  )
})
