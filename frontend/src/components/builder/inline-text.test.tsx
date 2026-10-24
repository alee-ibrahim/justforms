// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import { RendererContext, type RendererContextValue } from '@/renderer/context'
import type { Form } from '@/schema'

import { OptionList } from './canvas-text'
import { setElementText, textKey } from './inline-edit'
import { InlineText } from './inline-text'
import { BuilderContext, BuilderStore } from './store'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const makeForm = (language: 'en' | 'dv' = 'en'): Form => ({
  schemaVersion: '1',
  settings: { title: 'Registration', language },
  pages: [
    {
      id: 'page_1',
      elements: [
        { kind: 'field', id: 'full_name', type: 'short_text', label: language === 'dv' ? 'ފުރިހަމަ ނަން' : 'Full name' },
        {
          kind: 'field',
          id: 'colour',
          type: 'single_choice',
          label: 'Colour',
          options: [
            { value: 'red', label: 'Red' },
            { value: 'green', label: 'Green' },
          ],
        },
      ],
    },
  ],
})

let root: Root
let host: HTMLDivElement
let store: BuilderStore

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  store?.dispose()
  vi.useRealTimers()
})

function ctx(form: Form): RendererContextValue {
  return {
    form,
    language: form.settings.language ?? 'en',
    mode: 'canvas',
    convention: 'optional',
    getValue: () => undefined,
    setValue: () => {},
    blur: () => {},
    errorFor: () => null,
    isVisible: () => true,
    isRequired: () => false,
    highlighted: new Set(),
    uploader: () => Promise.reject(new Error('test')),
    setUploading: () => {},
    rowCount: () => 1,
    addRow: () => {},
    removeRow: () => {},
  }
}

function Label() {
  const form = store.get().schema
  const el = form.pages[0].elements![0]
  if (el.kind !== 'field') return null
  return (
    <InlineText
      editKey={textKey.element('full_name', 'label')}
      value={el.label}
      name="question label"
      language={form.settings.language ?? 'en'}
      empty="Untitled question"
      onCommit={(t) => store.edit((f) => setElementText(f, 'full_name', 'label', t).form)}
    />
  )
}

function Choices() {
  const form = store.get().schema
  const el = form.pages[0].elements![1]
  if (el.kind !== 'field' || el.type !== 'single_choice') return null
  return (
    <RendererContext.Provider value={ctx(form)}>
      <OptionList field={el} active />
    </RendererContext.Provider>
  )
}

function mount(node: () => React.ReactNode, form = makeForm()) {
  store = new BuilderStore('form-1', { schema: form, revision: 1, canUndo: false, canRedo: false })
  const render = () =>
    root.render(
      <BuilderContext.Provider value={store}>
        <TooltipProvider>{node()}</TooltipProvider>
      </BuilderContext.Provider>,
    )
  store.subscribe(() => act(render))
  act(render)
}

const input = () => host.querySelector<HTMLInputElement>('input')!
const idle = (key: string) => host.querySelector<HTMLElement>(`[data-inline-text="${key}"]`)!

function type(el: HTMLInputElement, value: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setter.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function key(el: HTMLElement, k: string, init: KeyboardEventInit = {}) {
  act(() => {
    el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init }))
  })
}

const label = () => {
  const el = store.get().schema.pages[0].elements![0]
  return el.kind === 'field' ? el.label : ''
}
const options = () => {
  const el = store.get().schema.pages[0].elements![1]
  return el.kind === 'field' && el.type === 'single_choice' ? el.options.map((o) => o.label) : []
}

describe('InlineText', () => {
  it('names the text it edits and starts editing on click', () => {
    mount(() => <Label />)
    const text = idle(textKey.element('full_name', 'label'))
    expect(text.getAttribute('role')).toBe('button')
    expect(text.getAttribute('aria-label')).toBe('Edit question label: Full name')
    act(() => text.click())
    expect(input().value).toBe('Full name')
    expect(input().getAttribute('aria-label')).toBe('Edit question label')
    expect(document.activeElement).toBe(input())
  })

  it('commits once on Enter: one undo step, nothing saved per keystroke', () => {
    mount(() => <Label />)
    act(() => idle(textKey.element('full_name', 'label')).click())
    type(input(), 'Full nam')
    type(input(), 'Full name as on ID')
    expect(label()).toBe('Full name')
    key(input(), 'Enter')
    expect(label()).toBe('Full name as on ID')
    expect(store.get().undoStack).toHaveLength(1)
    expect(store.get().editing).toBeNull()
    act(() => void store.undo())
    expect(label()).toBe('Full name')
  })

  it('cancels on Escape', () => {
    mount(() => <Label />)
    act(() => idle(textKey.element('full_name', 'label')).click())
    type(input(), 'Something else')
    key(input(), 'Escape')
    expect(label()).toBe('Full name')
    expect(store.get().undoStack).toHaveLength(0)
    expect(host.querySelector('input')).toBeNull()
  })

  it('commits on blur and ignores an unchanged commit', () => {
    mount(() => <Label />)
    act(() => idle(textKey.element('full_name', 'label')).click())
    act(() => input().dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
    expect(store.get().undoStack).toHaveLength(0)
    act(() => idle(textKey.element('full_name', 'label')).click())
    type(input(), 'Name')
    act(() => input().dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
    expect(label()).toBe('Name')
  })

  it('starts editing with Enter on the focused text', () => {
    mount(() => <Label />)
    key(idle(textKey.element('full_name', 'label')), 'Enter')
    expect(input().value).toBe('Full name')
  })

  it('types a Dhivehi form right to left with the Thaana keyboard toggle', () => {
    mount(() => <Label />, makeForm('dv'))
    act(() => idle(textKey.element('full_name', 'label')).click())
    expect(input().getAttribute('dir')).toBe('rtl')
    expect(input().getAttribute('lang')).toBe('dv')
    expect(host.querySelector('[aria-label="Thaana keyboard"]')).not.toBeNull()
  })
})

describe('OptionList', () => {
  it('Enter adds the next option below, typed and committed as one change', () => {
    mount(() => <Choices />)
    act(() => idle(textKey.option('colour', 'red')).click())
    key(input(), 'Enter')
    expect(store.get().editing).toBe(textKey.newOption('colour', 0))
    type(input(), 'Blue')
    key(input(), 'Enter')
    expect(options()).toEqual(['Red', 'Blue', 'Green'])
    // The next new option is open; leaving it empty adds nothing.
    expect(store.get().editing).toBe(textKey.newOption('colour', 1))
    key(input(), 'Enter')
    expect(options()).toEqual(['Red', 'Blue', 'Green'])
  })

  it('Backspace in an empty option removes it and edits the one above', () => {
    mount(() => <Choices />)
    act(() => idle(textKey.option('colour', 'green')).click())
    type(input(), '')
    key(input(), 'Backspace')
    expect(options()).toEqual(['Red'])
    expect(store.get().editing).toBe(textKey.option('colour', 'red'))
  })

  it('Alt+ArrowUp moves an option', () => {
    mount(() => <Choices />)
    key(idle(textKey.option('colour', 'green')), 'ArrowUp', { altKey: true })
    expect(options()).toEqual(['Green', 'Red'])
  })

  it('adds and removes "Other"', () => {
    mount(() => <Choices />)
    const add = [...host.querySelectorAll('button')].find((b) => b.textContent?.includes('Other'))!
    act(() => add.click())
    const el = store.get().schema.pages[0].elements![1]
    expect(el.kind === 'field' && el.type === 'single_choice' && el.allowOther).toBe(true)
    act(() => host.querySelector<HTMLButtonElement>('[aria-label="Remove “Other”"]')!.click())
    const after = store.get().schema.pages[0].elements![1]
    expect(after).not.toHaveProperty('allowOther')
  })
})
