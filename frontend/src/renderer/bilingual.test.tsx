// @vitest-environment happy-dom
// One form holding English and Dhivehi: every block takes its own direction and alignment.
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { Form } from '@/schema'

import { RendererContext, type RendererContextValue } from './context'
import { FillElements } from './elements'
import { placement } from './util'

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

describe('placement', () => {
  it('moves width-capped blocks with physical margins only for explicit sides', () => {
    expect(placement('Help', 'right', null).block).toEqual({ textAlign: 'right', marginLeft: 'auto' })
    expect(placement('Help', 'center', null).block).toEqual({ textAlign: 'center', marginInline: 'auto' })
    expect(placement('ނަން', null, 'auto').block).toEqual({ textAlign: 'start' })
  })
})

describe('requirement marker', () => {
  const label = (host: HTMLElement, id: string) => host.querySelector<HTMLElement>(`#q-${id}-label`)!

  it('isolates a mixed label and puts the marker right after it, at the logical end', () => {
    const right = { ...form, settings: { ...form.settings, align: 'right' as const } }
    for (const host of [render(), render(right)]) {
      const el = label(host, 'island')
      const [name, mark] = [...el.children] as HTMLElement[]
      expect(name.tagName).toBe('BDI')
      expect(name.getAttribute('dir')).toBe('ltr')
      expect(name.textContent).toBe('Island / ރަށް')
      expect(mark.dataset.slot).toBe('requirement-mark')
      expect(mark.textContent).toBe(' (optional)')
      // The marker is an English run isolated from the label's Thaana run.
      expect(mark.querySelector('bdi')?.getAttribute('dir')).toBe('ltr')
      expect(mark.querySelector('bdi')?.getAttribute('lang')).toBe('en')
      expect(el.textContent).toBe('Island / ރަށް (optional)')
    }
  })

  it('isolates a Thaana-first label in its own direction (the marker then sits on the left)', () => {
    const el = label(render(), 'full_name')
    const name = el.firstElementChild as HTMLElement
    expect(name.tagName).toBe('BDI')
    expect(name.getAttribute('dir')).toBe('rtl')
    expect(el.lastElementChild?.getAttribute('data-slot')).toBe('requirement-mark')
  })

  it('marks required questions the same way', () => {
    const f: Form = { ...form, pages: [{ ...form.pages[0] }] }
    const host = document.createElement('div')
    host.innerHTML = renderToStaticMarkup(
      <RendererContext.Provider value={{ ...ctx(f), convention: 'required', isRequired: () => true }}>
        <FillElements elements={f.pages[0].elements ?? []} />
      </RendererContext.Provider>,
    )
    const el = label(host, 'island')
    expect(el.firstElementChild?.tagName).toBe('BDI')
    expect(el.lastElementChild?.textContent).toBe(' (required)')
    // Choice questions (legend) too.
    const track = label(host, 'track')
    expect(track.firstElementChild?.getAttribute('dir')).toBe('rtl')
    expect(track.lastElementChild?.textContent).toBe(' (required)')
  })
})

describe('multi-paragraph text (per-line direction)', () => {
  const text = 'Please read the notes below.\n\nމި ފޯމު ފުރިހަމަ ކުރައްވާ.\nސުވާލުތަކަށް ޖަވާބު ދެއްވާ.\nEnglish again'
  const withParagraph = (align?: 'left' | 'center' | 'right'): Form => ({
    ...form,
    pages: [{ id: 'page_1', elements: [{ kind: 'content', id: 'p', contentType: 'paragraph', text, align }] }],
  })

  it('gives each line break-separated paragraph its own direction and start alignment (auto)', () => {
    const ps = [...render(withParagraph()).querySelectorAll<HTMLElement>('p')]
    expect(ps.map((p) => p.getAttribute('dir'))).toEqual(['ltr', 'rtl', 'ltr'])
    expect(ps.map((p) => p.getAttribute('lang'))).toEqual(['en', 'dv', 'en'])
    expect(ps[1].textContent).toBe('މި ފޯމު ފުރިހަމަ ކުރައްވާ.ސުވާލުތަކަށް ޖަވާބު ދެއްވާ.')
    for (const p of ps) {
      expect(p.style.textAlign).toBe('start')
      expect(p.className).toContain('max-w-[36em]')
    }
  })

  it('applies an explicit alignment to every paragraph', () => {
    const ps = [...render(withParagraph('right')).querySelectorAll<HTMLElement>('p')]
    expect(ps.map((p) => p.getAttribute('dir'))).toEqual(['ltr', 'rtl', 'ltr'])
    for (const p of ps) expect(p.style.textAlign).toBe('right')
  })
})

describe('justify', () => {
  const text = 'The grant supports small projects.\nމި ގްރާންޓް ދެވެނީ ކުދި މަޝްރޫޢުތަކަށް.'
  const justified: Form = {
    ...form,
    pages: [
      {
        id: 'page_1',
        elements: [
          { kind: 'content', id: 'p', contentType: 'paragraph', text, align: 'justify' },
          { kind: 'field', id: 'q', type: 'short_text', label: 'ނަން', align: 'justify' },
        ],
      },
    ],
  }

  it('justifies each paragraph in its own direction, the last line at its start edge', () => {
    const ps = [...render(justified).querySelectorAll<HTMLElement>('p')]
    expect(ps.map((p) => p.getAttribute('dir'))).toEqual(['ltr', 'rtl'])
    for (const p of ps) {
      expect(p.style.textAlign).toBe('justify')
      expect(p.style.textAlignLast).toBe('start')
    }
  })

  it('keeps one-line labels at their start edge', () => {
    expect(block(render(justified), 'q')?.style.textAlign).toBe('start')
    expect(placement('ނަން', 'justify', null).align).toBe('justify')
    expect(placement('ނަން', 'justify', null).text).toEqual({ textAlign: 'start' })
  })
})

describe('punctuation and the dominant script', () => {
  it('reads a Dhivehi heading that starts with a Latin acronym right to left, the acronym isolated', () => {
    const f: Form = {
      ...form,
      pages: [{ id: 'page_1', elements: [{ kind: 'content', id: 'h', contentType: 'heading', text: 'ބައިވެރިވުމަށް (PPY) ފޯމު ފުރުއްވާ.' }] }],
    }
    const h3 = render(f).querySelector('h3')!
    expect(h3.getAttribute('dir')).toBe('rtl')
    expect(h3.style.textAlign).toBe('start')
    expect(h3.innerHTML).toBe('ބައިވެރިވުމަށް (<span lang="en" dir="ltr">PPY</span>) ފޯމު ފުރުއްވާ.')
  })

  it('isolates Latin runs inside Dhivehi paragraphs (Markdown)', () => {
    const f: Form = {
      ...form,
      pages: [{ id: 'page_1', elements: [{ kind: 'content', id: 'p', contentType: 'paragraph', text: 'PPY ގެ ބައިވެރިން ކޮބާ؟' }] }],
    }
    const p = render(f).querySelector('p')!
    expect(p.getAttribute('dir')).toBe('rtl')
    expect(p.querySelector('span[dir="ltr"]')?.textContent).toBe('PPY')
  })
})
