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

describe('BulkBar delete', () => {
  it('deletes to Deleted and offers Undo, which restores the same submissions', async () => {
    const bulk = vi.spyOn(api, 'bulk').mockResolvedValue({ changed: 2 })
    const client = new QueryClient()
    client.setQueryData(['meta'], { trashDays: 30 })
    host = document.createElement('div')
    document.body.append(host)
    root = createRoot(host)
    await act(async () =>
      root!.render(
        <QueryClientProvider client={client}>
          <BulkBar formId="f1" ids={['a', 'b']} canDelete onClear={() => {}} onExport={() => {}} />
        </QueryClientProvider>,
      ),
    )
    // Reversible, so no confirmation: straight to Deleted.
    await click(button('Delete'))
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
