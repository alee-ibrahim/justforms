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
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { FormListItem } from '@/lib/api'

import { listItem } from './list-item.fixture'

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn(), warning: vi.fn(), success: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

const { api } = await import('@/lib/api')
const { RowMenu } = await import('./forms-list')

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | undefined
let host: HTMLElement | undefined

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  vi.restoreAllMocks()
  toast.mockReset()
})

async function render(form: FormListItem) {
  const rootRoute = createRootRoute({
    component: () => (
      <TooltipProvider>
        <RowMenu form={form} orgId="o1" canCreate />
      </TooltipProvider>
    ),
  })
  const children = ['/forms', '/forms/trash', '/forms/$formId/edit', '/forms/$formId/submissions', '/forms/$formId/share'].map(
    (path) => createRoute({ getParentRoute: () => rootRoute, path }),
  )
  const router = createRouter({
    routeTree: rootRoute.addChildren(children),
    history: createMemoryHistory({ initialEntries: ['/forms'] }),
  })
  await router.load()
  const client = new QueryClient()
  client.setQueryData(['meta'], { trashDays: 30 })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  await act(async () =>
    root!.render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    ),
  )
}

const button = (text: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)
const dialog = () => document.querySelector('[role=alertdialog]')

/** Opens the row menu from the keyboard and picks Delete…, which only asks. */
async function chooseDelete() {
  const trigger = document.querySelector('[aria-label="Form actions"]') as HTMLElement
  await act(async () => {
    trigger.focus()
    trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  })
  const item = [...document.querySelectorAll('[role=menuitem]')].find((m) => m.textContent?.trim() === 'Delete…')
  expect(item).toBeTruthy()
  await act(async () => (item as HTMLElement).click())
}

describe('RowMenu delete', () => {
  const form = listItem({ id: 'f9', title: 'Volunteer sign-up', submissionCount: 12 })

  it('asks first, naming the form and its submissions, with Cancel focused', async () => {
    const remove = vi.spyOn(api, 'deleteForm').mockResolvedValue()
    await render(form)
    await chooseDelete()
    expect(dialog()?.textContent).toContain('Delete Volunteer sign-up?')
    expect(dialog()?.textContent).toContain(
      'It moves to Trash for 30 days, with its 12 submissions. You can restore it from Trash.',
    )
    expect(document.activeElement?.textContent?.trim()).toBe('Cancel')
    expect(button('Delete form')?.getAttribute('data-variant')).toBe('destructive')
    expect(remove).not.toHaveBeenCalled()
  })

  it('does nothing on Cancel', async () => {
    const remove = vi.spyOn(api, 'deleteForm').mockResolvedValue()
    await render(form)
    await chooseDelete()
    await act(async () => button('Cancel')!.click())
    expect(dialog()).toBeNull()
    expect(remove).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it('does nothing on Esc', async () => {
    const remove = vi.spyOn(api, 'deleteForm').mockResolvedValue()
    await render(form)
    await chooseDelete()
    await act(async () =>
      document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })),
    )
    expect(dialog()).toBeNull()
    expect(remove).not.toHaveBeenCalled()
  })

  it('moves it to Trash on confirm, and Undo restores it', async () => {
    const remove = vi.spyOn(api, 'deleteForm').mockResolvedValue()
    const restore = vi.spyOn(api, 'restoreForm').mockResolvedValue(form)
    await render(form)
    await chooseDelete()
    await act(async () => button('Delete form')!.click())
    expect(remove).toHaveBeenCalledWith('f9')
    const [message, options] = toast.mock.calls.at(-1)!
    expect(message).toBe('Moved the form to Trash')
    expect(options.action.label).toBe('Undo')
    await act(async () => options.action.onClick())
    expect(restore).toHaveBeenCalledWith('f9', undefined)
    expect(toast).toHaveBeenLastCalledWith('Restored the form')
  })

  it('leaves out the count for a form without submissions', async () => {
    vi.spyOn(api, 'deleteForm').mockResolvedValue()
    await render(listItem({ title: 'Draft form', submissionCount: 0 }))
    await chooseDelete()
    expect(dialog()?.textContent).toContain('It moves to Trash for 30 days. You can restore it from Trash.')
  })
})
