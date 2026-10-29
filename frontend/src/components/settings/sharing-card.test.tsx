// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { FormSummary, SharingOut } from '@/lib/api'
import { listItem } from '@/components/forms/list-item.fixture'

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

const { api } = await import('@/lib/api')
const { sharingQuery } = await import('@/lib/queries')
const { SharingCard } = await import('./sharing-card')

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | undefined
let host: HTMLElement | undefined
afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  vi.restoreAllMocks()
})

const data: SharingOut = {
  title: null,
  description: null,
  effectiveTitle: 'Volunteer sign-up',
  effectiveDescription: '',
  defaultTitle: 'Volunteer sign-up',
  defaultDescription: '',
  siteName: 'Forms',
  url: 'https://forms.example.org/volunteer',
  language: 'en',
  imageUrl: '/preview.png',
  customImage: { width: 1200, height: 630 },
  published: true,
  canEdit: true,
}
const button = (text: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === text) as HTMLElement

describe('Sharing image', () => {
  it('asks before deleting the uploaded image', async () => {
    const reset = vi.spyOn(api, 'deleteSharingImage').mockResolvedValue({ ...data, customImage: null })
    const form = listItem() as FormSummary
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    client.setQueryData(sharingQuery(form.id).queryKey, data)
    host = document.createElement('div')
    document.body.append(host)
    root = createRoot(host)
    await act(async () =>
      root!.render(
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <SharingCard form={form} />
          </TooltipProvider>
        </QueryClientProvider>,
      ),
    )
    await act(async () => button('Use generated image').click())
    expect(document.querySelector('[role=alertdialog]')?.textContent).toContain('Remove the uploaded image?')
    await act(async () => button('Cancel').click())
    expect(reset).not.toHaveBeenCalled()
    await act(async () => button('Use generated image').click())
    await act(async () => button('Remove image').click())
    expect(reset).toHaveBeenCalledWith(form.id)
  })
})
