// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn(), warning: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

const { api } = await import('@/lib/api')
const { BulkBar } = await import('./bulk-bar')

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | undefined
let host: HTMLElement | undefined

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  vi.restoreAllMocks()
  toast.mockReset()
})

const click = async (el: Element | null | undefined) => {
  expect(el).toBeTruthy()
  await act(async () => (el as HTMLElement).click())
}
const button = (text: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)

const dialog = () => document.querySelector('[role=alertdialog]')

async function renderBar(props: { ids: string[]; seq?: number }) {
  const client = new QueryClient()
  client.setQueryData(['meta'], { trashDays: 30 })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  await act(async () =>
    root!.render(
      <QueryClientProvider client={client}>
        <BulkBar formId="f1" {...props} canDelete onClear={() => {}} onExport={() => {}} />
      </QueryClientProvider>,
    ),
  )
}

describe('BulkBar delete', () => {
  it('asks first, with Cancel focused and a destructive confirm', async () => {
    const bulk = vi.spyOn(api, 'bulk').mockResolvedValue({ changed: 5 })
    await renderBar({ ids: ['a', 'b', 'c', 'd', 'e'] })
    await click(button('Delete…'))
    expect(dialog()?.textContent).toContain('Delete 5 submissions?')
    expect(dialog()?.textContent).toContain('They move to Deleted for 30 days.')
    expect(document.activeElement?.textContent?.trim()).toBe('Cancel')
    expect(button('Delete 5')?.getAttribute('data-variant')).toBe('destructive')
    expect(bulk).not.toHaveBeenCalled()
  })

  it('names the submission when one is selected', async () => {
    vi.spyOn(api, 'bulk').mockResolvedValue({ changed: 1 })
    await renderBar({ ids: ['a'], seq: 12 })
    await click(button('Delete…'))
    expect(dialog()?.textContent).toContain('Delete #0012?')
    expect(dialog()?.textContent).toContain('It moves to Deleted for 30 days.')
    expect(button('Delete submission')).toBeTruthy()
  })

  it('does nothing on Cancel or Esc', async () => {
    const bulk = vi.spyOn(api, 'bulk').mockResolvedValue({ changed: 2 })
    await renderBar({ ids: ['a', 'b'] })
    await click(button('Delete…'))
    await click(button('Cancel'))
    expect(dialog()).toBeNull()
    await click(button('Delete…'))
    await act(async () =>
      document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })),
    )
    expect(dialog()).toBeNull()
    expect(bulk).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it('deletes to Deleted on confirm and offers Undo, which restores the same submissions', async () => {
    const bulk = vi.spyOn(api, 'bulk').mockResolvedValue({ changed: 2 })
    await renderBar({ ids: ['a', 'b'] })
    await click(button('Delete…'))
    await click(button('Delete 2'))
    expect(dialog()).toBeNull()
    expect(bulk).toHaveBeenCalledWith('f1', { ids: ['a', 'b'], action: 'delete' })
    const [message, options] = toast.mock.calls.at(-1)!
    expect(message).toBe('Deleted 2 submissions')
    expect(options.action.label).toBe('Undo')
    expect(options.description).toBe('In Deleted for 30 days.')
    await act(async () => options.action.onClick())
    expect(bulk).toHaveBeenLastCalledWith('f1', { ids: ['a', 'b'], action: 'restore' })
    expect(toast).toHaveBeenLastCalledWith('Restored 2 submissions')
  })
})
