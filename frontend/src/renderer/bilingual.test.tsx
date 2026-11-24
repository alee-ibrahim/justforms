// @vitest-environment happy-dom
// One form holding English and Dhivehi: every block takes its own direction and alignment.
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { Form, ShortTextField } from '@/schema'

import { RendererContext, type RendererContextValue } from './context'
import { FillElements } from './elements'
import { placement, thaanaKeyboard } from './util'

const form: Form = {
  schemaVersion: '2',
  settings: { title: 'Application / ހުށަހެޅުން' },
  pages: [
    {
      id: 'page_1',
      elements: [
        { kind: 'field', id: 'full_name', type: 'short_text', label: 'ފުރިހަމަ ނަން' },
        { kind: 'field', id: 'email', type: 'email', label: 'Email' },
        { kind: 'field', id: 'island', type: 'short_text', label: 'Island / ރަށް', align: 'center' },
        {
          kind: 'field',
          id: 'track',
          type: 'single_choice',
          label: 'ޕްރޮގްރާމް',
          options: [
            { value: 'law', label: 'ގާނޫނު' },
            { value: 'it', label: 'IT' },
          ],
        },
        { kind: 'content', id: 'note', contentType: 'heading', text: 'Declaration', align: 'right' },
      ],
    },
  ],
}

function ctx(f: Form): RendererContextValue {
  return {
    form: f,
    dir: 'ltr',
    mode: 'fill',
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

function render(f: Form = form): HTMLElement {
  const host = document.createElement('div')
  host.innerHTML = renderToStaticMarkup(
    <RendererContext.Provider value={ctx(f)}>
      <FillElements elements={f.pages[0].elements ?? []} />
    </RendererContext.Provider>,
  )
  return host
}

const block = (host: HTMLElement, id: string) =>
  host.querySelector<HTMLElement>(`#q-${id}-label`)?.closest<HTMLElement>('[data-slot="field"], [data-slot="field-set"]')

describe('bilingual form', () => {
  it('gives each question the direction of its own label', () => {
    const host = render()
    expect(block(host, 'full_name')?.getAttribute('dir')).toBe('rtl')
    expect(block(host, 'full_name')?.getAttribute('lang')).toBe('dv')
    expect(block(host, 'email')?.getAttribute('dir')).toBe('ltr')
    expect(block(host, 'island')?.getAttribute('dir')).toBe('ltr')
    expect(block(host, 'track')?.getAttribute('dir')).toBe('rtl')
  })

  it('aligns by the element override, else auto (start)', () => {
    const host = render()
    expect(block(host, 'island')?.style.textAlign).toBe('center')
    expect(block(host, 'full_name')?.style.textAlign).toBe('start')
    expect(host.querySelector('h3')?.style.textAlign).toBe('right')
  })

  it('follows the form default when an element has none', () => {
    const host = render({ ...form, settings: { ...form.settings, align: 'right' } })
    expect(block(host, 'email')?.style.textAlign).toBe('right')
    expect(block(host, 'island')?.style.textAlign).toBe('center')
  })

  it('isolates each option in its own direction', () => {
    const host = render()
    const bdis = [...(block(host, 'track')?.querySelectorAll('[role="radiogroup"] bdi') ?? [])]
    expect(bdis.map((b) => b.getAttribute('dir'))).toEqual(['rtl', 'ltr'])
  })

  it('answer boxes start on the side of their question', () => {
    const host = render()
    expect(host.querySelector('#q-full_name')?.getAttribute('dir')).toBe('rtl')
    expect(host.querySelector('#q-island')?.getAttribute('dir')).toBe('ltr')
  })
})

describe('thaanaKeyboard', () => {
  const field = (label: string, inputScript?: ShortTextField['inputScript']): ShortTextField => ({
    kind: 'field',
    id: 'x',
    type: 'short_text',
    label,
    inputScript,
  })
  it('is on for Thaana labels, offered for mixed ones, absent for English', () => {
    expect(thaanaKeyboard(field('ނަން'))).toBe('on')
    expect(thaanaKeyboard(field('Name / ނަން'))).toBe('off')
    expect(thaanaKeyboard(field('Name'))).toBe('none')
    expect(thaanaKeyboard(field('Name', 'thaana'))).toBe('on')
    expect(thaanaKeyboard(field('ނަން', 'latin'))).toBe('none')
  })
})

describe('placement', () => {
  it('moves width-capped blocks with physical margins only for explicit sides', () => {
    expect(placement('Help', 'right', null).block).toEqual({ textAlign: 'right', marginLeft: 'auto' })
    expect(placement('Help', 'center', null).block).toEqual({ textAlign: 'center', marginInline: 'auto' })
    expect(placement('ނަން', null, 'auto').block).toEqual({ textAlign: 'start' })
  })
})
