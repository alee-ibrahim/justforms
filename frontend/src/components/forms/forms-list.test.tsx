// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { FormListItem } from '@/lib/api'

import { FormsList } from './forms-list'
import type { FormsSort } from './forms-view'
import { listItem } from './list-item.fixture'

// React needs this to run `act` outside a test renderer.
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const NOW = new Date('2026-10-25T12:00:00Z').getTime()
let root: Root | undefined
let current: { state: { location: { pathname: string } } } | undefined
let host: HTMLElement | undefined

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
})

async function render(forms: FormListItem[], sort: FormsSort = 'edited') {
  const rootRoute = createRootRoute({
    component: () => (
      <TooltipProvider>
        <FormsList forms={forms} orgId="o1" meId="me" canCreate sort={sort} now={NOW} />
      </TooltipProvider>
    ),
  })
  const children = ['/forms', '/forms/$formId/edit', '/forms/$formId/submissions', '/forms/$formId/share'].map(
    (path) => createRoute({ getParentRoute: () => rootRoute, path }),
  )
  const router = createRouter({
    routeTree: rootRoute.addChildren(children),
    history: createMemoryHistory({ initialEntries: ['/forms'] }),
  })
  await router.load()
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  current = router
  await act(async () => {
    root!.render(
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )
  })
  return host
}

const rowsOf = (el: HTMLElement, part: 'table' | 'cards') =>
  [...el.querySelectorAll(`[data-testid=forms-${part}] [data-form]`)] as HTMLElement[]

describe('FormsList', () => {
  it('shows owner, status, counts, activity and markers in a table row', async () => {
    const el = await render([
      listItem({
        id: 'grant',
        title: 'Youth grant',
        owner: { id: 'u2', name: 'Ibrahim Naseer', email: 'ibrahim@example.org' },
        ownerCount: 3,
        hasUnpublishedChanges: true,
        submissionCount: 128,
        newCount: 3,
        recentCount: 5,
        approvalsOn: true,
        pendingApprovalCount: 2,
        lastSubmissionAt: '2026-10-25T10:00:00Z',
        lastEditedAt: '2026-10-24T09:00:00Z',
        lastEditedBy: { id: 'me', name: 'Me', email: 'me@example.org' },
        accessMode: 'otp',
        importedFrom: 'jotform',
      }),
    ])
    const [row] = rowsOf(el, 'table')
    const text = row!.textContent ?? ''
    expect(text).toContain('Youth grant')
    expect(text).toContain('IN') // avatar initials
    expect(text).toContain('Ibrahim Naseer')
    expect(text).toContain('+2')
    expect(text).toContain('and 2 other owners')
    expect(text).toContain('Live')
    expect(text).toContain('Unpublished changes')
    expect(text).toContain('Email code')
    expect(text).toContain('Imported from Jotform')
    expect(text).toContain('128')
    expect(text).toContain('3 new')
    expect(text).toContain('5 in last 7 days')
    expect(text).toContain('2 awaiting approval')
    expect(text).toContain('2 hours ago')
    expect(text).toContain('yesterday')
    expect(text).toContain('by you')
    expect(text).not.toContain('Dhivehi')
    // With submissions, the title opens them; Edit stays in the menu.
    expect(row!.querySelector('a[href="/forms/grant/submissions"]')).not.toBeNull()
    expect(row!.querySelector('a[href="/forms/grant/edit"]')).toBeNull()
    expect(row!.querySelector('a[aria-label][href="/forms/grant/submissions"]')?.getAttribute('aria-label')).toBe(
      '128 submissions, 3 new, 5 in the last 7 days, 2 awaiting approval',
    )
  })

  it('says "You" for the viewer, marks Dhivehi titles and hides approvals when off', async () => {
    const el = await render([
      listItem({
        id: 'dv',
        title: 'ފޯމު',
        language: 'dv',
        owner: { id: 'me', name: 'Me Myself', email: 'me@example.org' },
        approvalsOn: false,
        pendingApprovalCount: 4,
        currentVersion: null,
        status: 'draft',
      }),
    ])
    const [row] = rowsOf(el, 'table')
    const text = row!.textContent ?? ''
    expect(text).toContain('You')
    expect(text).not.toContain('Me Myself')
    expect(text).toContain('Dhivehi')
    expect(text).toContain('Draft')
    expect(text).not.toContain('awaiting approval')
    expect(row!.querySelector('bdi[lang=dv]')?.textContent).toBe('ފޯމު')
    // Never published: no link into submissions, a dash instead.
    expect(row!.querySelector('a[href="/forms/dv/submissions"]')).toBeNull()
  })

  it('renders phone cards with the key facts, in the given order', async () => {
    const el = await render(
      [
        listItem({ id: 'one', title: 'First', submissionCount: 1, newCount: 1, lastSubmissionAt: '2026-10-25T11:55:00Z' }),
        listItem({ id: 'two', title: 'Second', status: 'closed' }),
      ],
      'name',
    )
    const cards = rowsOf(el, 'cards')
    expect(cards.map((c) => c.dataset.form)).toEqual(['one', 'two'])
    const first = cards[0]!.textContent ?? ''
    expect(first).toContain('Live')
    expect(first).toContain('1 new')
    expect(first).toContain('1 submission')
    expect(first).toContain('Aminath Ali')
    expect(first).toContain('Last submission 5 minutes ago')
    expect(cards[1]!.textContent).toContain('Closed')
    // The sorted column is announced.
    const sorted = el.querySelector('[data-testid=forms-table] th[aria-sort]')
    expect(sorted?.textContent).toBe('Form')
    expect(sorted?.getAttribute('aria-sort')).toBe('ascending')
  })

  it('opens submissions or the editor when a row or card is clicked', async () => {
    const el = await render([
      listItem({ id: 'busy', title: 'Busy', submissionCount: 2 }),
      listItem({ id: 'quiet', title: 'Quiet', submissionCount: 0, currentVersion: null, status: 'draft' }),
    ])
    const [busy, quiet] = rowsOf(el, 'table')
    expect(quiet!.querySelector('a[href="/forms/quiet/edit"]')).not.toBeNull()
    await act(async () => busy!.querySelectorAll('td')[2]!.click())
    expect(current!.state.location.pathname).toBe('/forms/busy/submissions')
    const [, quietCard] = rowsOf(el, 'cards')
    await act(async () => quietCard!.click())
    expect(current!.state.location.pathname).toBe('/forms/quiet/edit')
  })
})
