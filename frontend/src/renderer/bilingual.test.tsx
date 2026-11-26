// @vitest-environment happy-dom
// One form holding English and Dhivehi: every block takes its own direction and alignment.
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { FieldElement, Form } from '@/schema'

import { RendererContext, type RendererContextValue } from './context'
import { FillElements, QuestionView } from './elements'
import { placement } from './util'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

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

function render(f: Form = form, required = false): HTMLElement {
  const host = document.createElement('div')
  host.innerHTML = renderToStaticMarkup(
    <RendererContext.Provider value={{ ...ctx(f), isRequired: () => required }}>
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

describe('required marker', () => {
  const label = (host: HTMLElement, id: string) => host.querySelector<HTMLElement>(`#q-${id}-label`)!
  const mark = (el: HTMLElement) => el.querySelector<HTMLElement>('[data-slot="required-mark"]')

  it('marks nothing on optional questions', () => {
    const host = render()
    expect(host.querySelector('[data-slot="required-mark"]')).toBeNull()
    expect(host.querySelector('[aria-required]')).toBeNull()
    expect(label(host, 'island').textContent).toBe('Island / ރަށް')
  })

  it('isolates a mixed label and puts a decorative "*" right after it, at the logical end', () => {
    const right = { ...form, settings: { ...form.settings, align: 'right' as const } }
    for (const host of [render(form, true), render(right, true)]) {
      const el = label(host, 'island')
      const [name, star] = [...el.children] as HTMLElement[]
      expect(name.tagName).toBe('BDI')
      expect(name.getAttribute('dir')).toBe('ltr')
      expect(name.textContent).toBe('Island / ރަށް')
      expect(star.dataset.slot).toBe('required-mark')
      expect(star.textContent).toBe(' *')
      expect(star.getAttribute('aria-hidden')).toBe('true')
      expect(star.className).toContain('text-destructive')
      expect(el.textContent).toBe('Island / ރަށް *')
      // The required state is on the control, not in the "*".
      expect(host.querySelector('#q-island')?.getAttribute('aria-required')).toBe('true')
    }
  })

  it('puts the "*" at the end of a Thaana label, on the left of its right-to-left block', () => {
    const host = render(form, true)
    const el = label(host, 'full_name')
    expect(el.firstElementChild?.getAttribute('dir')).toBe('rtl')
    expect(el.lastElementChild?.getAttribute('data-slot')).toBe('required-mark')
    expect(block(host, 'full_name')?.getAttribute('dir')).toBe('rtl')
  })

  it('marks choice questions in their legend and the radio group as required', () => {
    const host = render(form, true)
    const track = label(host, 'track')
    expect(track.tagName).toBe('LEGEND')
    expect(track.lastElementChild?.getAttribute('data-slot')).toBe('required-mark')
    expect(block(host, 'track')?.querySelector('[role="radiogroup"]')?.getAttribute('aria-required')).toBe('true')
  })

  it('does not add a second "*" to a label that already ends with one', () => {
    const typed: Form = {
      ...form,
      pages: [{ id: 'page_1', elements: [{ kind: 'field', id: 'email', type: 'email', label: 'Email *' }] }],
    }
    const host = render(typed, true)
    expect(mark(label(host, 'email'))).toBeNull()
    expect(label(host, 'email').textContent).toBe('Email *')
    expect(host.querySelector('#q-email')?.getAttribute('aria-required')).toBe('true')
  })

  it('says "required" in the label where the control has no role that takes aria-required', () => {
    const groups: Form = {
      ...form,
      pages: [
        {
          id: 'page_1',
          elements: [
            {
              kind: 'field',
              id: 'topics',
              type: 'multi_choice',
              label: 'Topics',
              options: [{ value: 'a', label: 'A' }],
            },
            { kind: 'field', id: 'id_card', type: 'file', label: 'ID card' },
            { kind: 'field', id: 'sign', type: 'signature', label: 'ސޮއި' },
          ],
        },
      ],
    }
    const host = render(groups, true)
    for (const id of ['topics', 'id_card', 'sign']) {
      const el = label(host, id)
      expect(mark(el)?.textContent).toBe(' *')
      const sr = el.querySelector('.sr-only')!
      expect(sr.textContent).toBe(' required')
      expect(sr.getAttribute('lang')).toBe('en')
    }
    expect(host.querySelector('[aria-required]')).toBeNull()
    expect(render(groups).querySelector('.sr-only')).toBeNull()
  })

  it('follows the required state as it changes (builder canvas)', () => {
    const field = form.pages[0].elements![2] as FieldElement
    const host = document.createElement('div')
    const root = createRoot(host)
    const show = (required: boolean) =>
      act(() =>
        root.render(
          <RendererContext.Provider value={{ ...ctx(form), mode: 'canvas' }}>
            <QuestionView field={field} path={{ id: field.id }} required={required} label={<span>{field.label}</span>} />
          </RendererContext.Provider>,
        ),
      )
    show(false)
    expect(mark(host)).toBeNull()
    show(true)
    expect(mark(host)?.textContent).toBe(' *')
    show(false)
    expect(mark(host)).toBeNull()
    act(() => root.unmount())
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
    // Not a two-block bilingual text (an acronym inside a sentence): one piece, the bracket
    // pair isolated with the run it encloses.
    expect(h3.innerHTML).toBe('ބައިވެރިވުމަށް <span lang="en" dir="ltr">(PPY)</span> ފޯމު ފުރުއްވާ.')
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

describe('bilingual one-line texts (auto alignment)', () => {
  const PPY = 'ޕްރެކްޓިސް ޕާލިމެންޓް ފޮރ ޔޫތު (ޕީ.ޕީ.ވައި) (Practice Parliament for Youth (PPY))'
  const split: Form = {
    ...form,
    pages: [
      {
        id: 'page_1',
        elements: [
          { kind: 'field', id: 'name', type: 'short_text', label: 'Full name: ފުރިހަމަ ނަން' },
          {
            kind: 'field',
            id: 'program',
            type: 'single_choice',
            label: 'Which program did you participate in? ބައިވެރިވި ޕްރޮގްރާމަކީ:',
            options: [{ value: 'ppy', label: PPY }],
          },
        ],
      },
    ],
  }

  it('shows the English part at the left and the Dhivehi part at the right, the "*" after English', () => {
    const host = render(split, true)
    const row = host.querySelector('label [data-slot="bilingual"]')!
    expect(row.getAttribute('dir')).toBe('ltr')
    const en = row.querySelector('[data-part="ltr"]')!
    const dv = row.querySelector('[data-part="rtl"]')!
    expect(en.textContent).toBe('Full name: *')
    expect(en.querySelector('[data-slot="required-mark"]')).not.toBeNull()
    expect(dv.querySelector('[data-slot="required-mark"]')).toBeNull()
    expect(dv.textContent).toBe('ފުރިހަމަ ނަން')
    expect(dv.getAttribute('dir')).toBe('rtl')
    expect(dv.className).toContain('me-auto')
  })

  it('splits question labels with trailing punctuation and options with brackets', () => {
    const host = render(split)
    const legend = host.querySelectorAll('[data-slot="bilingual"]')[1]
    expect(legend.querySelector('[data-part="ltr"]')!.textContent).toBe('Which program did you participate in?')
    expect(legend.querySelector('[data-part="rtl"]')!.textContent).toBe('ބައިވެރިވި ޕްރޮގްރާމަކީ:')
    const option = host.querySelectorAll('[data-slot="bilingual"]')[2]
    expect(option.querySelector('[data-part="ltr"]')!.textContent).toBe('(Practice Parliament for Youth (PPY))')
    expect(option.querySelector('[data-part="rtl"]')!.textContent).toBe('ޕްރެކްޓިސް ޕާލިމެންޓް ފޮރ ޔޫތު (ޕީ.ޕީ.ވައި)')
  })

  it('keeps the text whole with an explicit alignment (left/center/right/justify)', () => {
    for (const align of ['left', 'center', 'right', 'justify'] as const) {
      const host = render({ ...split, settings: { ...split.settings, align } })
      expect(host.querySelector('[data-slot="bilingual"]')).toBeNull()
    }
  })
})
