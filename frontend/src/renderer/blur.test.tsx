// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { Form } from '@/schema'

import type { Uploader } from './context'

import { FormRenderer } from './form-view'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const form = {
  schemaVersion: '1',
  settings: { language: 'en', title: 'Sign-up' },
  pages: [
    {
      id: 'page_1',
      elements: [
        { kind: 'field', id: 'name', type: 'short_text', label: 'Name', required: true },
        { kind: 'field', id: 'town', type: 'short_text', label: 'Town', required: true },
      ],
    },
    { id: 'page_2', elements: [{ kind: 'field', id: 'note', type: 'short_text', label: 'Note' }] },
  ],
} as unknown as Form

const uploader: Uploader = async (file) => ({ fileId: 'f', name: file.name, size: file.size, mime: file.type })

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

const input = (id: string) => host.querySelector<HTMLInputElement>(`#q-${id}`)!
const errorOf = (id: string) => host.querySelector(`#q-${id}-err`)?.textContent ?? null

function type(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  setter.call(el, value)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('validation on blur', () => {
  it('leaves an untouched question alone and checks one the respondent changed', async () => {
    await act(async () => {
      root.render(<FormRenderer form={form} mode="preview" uploader={uploader} onSubmit={async () => ({ ok: true, reference: 'x' })} />)
    })
    const name = input('name')
    await act(async () => {
      name.focus()
      name.blur()
    })
    expect(errorOf('name')).toBeNull()

    await act(async () => {
      name.focus()
      type(name, 'A')
    })
    await act(async () => {
      type(name, '')
    })
    await act(async () => {
      name.blur()
    })
    expect(errorOf('name')).not.toBeNull()

    // Next still checks every question on the page.
    const next = [...host.querySelectorAll('button')].find((b) => b.textContent?.includes('Next'))!
    await act(async () => {
      next.click()
    })
    expect(errorOf('town')).not.toBeNull()
  })
})
