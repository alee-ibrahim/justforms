import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { FormLines, FormText } from './form-text'
import { isMixed, scriptRuns } from './runs'

describe('scriptRuns', () => {
  it('splits a bilingual label into script runs, neutrals between them on their own', () => {
    expect(scriptRuns('Name / ނަން')).toEqual([
      { text: 'Name', script: 'latin' },
      { text: ' / ', script: 'neutral' },
      { text: 'ނަން', script: 'thaana' },
    ])
  })

  it('keeps spaces and digits inside a run of one script', () => {
    expect(scriptRuns('ފުރިހަމަ ނަން')).toEqual([{ text: 'ފުރިހަމަ ނަން', script: 'thaana' }])
    expect(isMixed('Full name 2')).toBe(false)
    expect(isMixed('ނަން (Name)')).toBe(true)
  })
})

describe('FormText', () => {
  it('leaves single-script text alone', () => {
    expect(renderToStaticMarkup(<FormText text="Full name" />)).toBe('Full name')
  })

  it('marks the Thaana run inside English text', () => {
    expect(renderToStaticMarkup(<FormText text="Name / ނަން" />)).toBe(
      'Name / <span lang="dv" dir="rtl" class="df-run">ނަން</span>',
    )
  })

  it('marks the Latin run inside Dhivehi text', () => {
    expect(renderToStaticMarkup(<FormText text="ނަން / Name" />)).toBe('ނަން / <span lang="en" dir="ltr">Name</span>')
  })
})

describe('FormLines', () => {
  it('renders each line in its own direction', () => {
    const html = renderToStaticMarkup(<FormLines text={'Hello\nހެލޯ\n\n123'} align="auto" />)
    expect(html).toBe(
      '<span class="block" dir="ltr" lang="en" style="text-align:start">Hello</span>' +
        '<span class="block" dir="rtl" lang="dv" style="text-align:start">ހެލޯ</span>' +
        '<span class="block" dir="ltr" lang="en" style="text-align:start"><br/></span>' +
        '<span class="block" dir="ltr" lang="en" style="text-align:start">123</span>',
    )
  })

  it('leaves single-line text to FormText', () => {
    expect(renderToStaticMarkup(<FormLines text="Full name" />)).toBe('Full name')
  })
})

describe('FormText split', () => {
  it('shows a bilingual label as one row: English left, Dhivehi right', () => {
    const html = renderToStaticMarkup(<FormText text="Full name: ފުރިހަމަ ނަން" split />)
    expect(html).toBe(
      '<span dir="ltr" data-slot="bilingual" class="flex w-full flex-wrap items-baseline gap-x-6">' +
        '<span lang="en" dir="ltr" class="text-start" data-part="ltr">Full name:</span>' +
        '<span lang="dv" dir="rtl" class="me-auto text-start" data-part="rtl">ފުރިހަމަ ނަން</span></span>',
    )
  })

  it('puts the English part first even when the text starts in Dhivehi, brackets paired', () => {
    const html = renderToStaticMarkup(
      <FormText text="ޕްރެކްޓިސް ޕާލިމެންޓް ފޮރ ޔޫތު (ޕީ.ޕީ.ވައި) (Practice Parliament for Youth (PPY))" split />,
    )
    expect(html).toContain('data-part="ltr">(Practice Parliament for Youth (PPY))</span>')
    expect(html).toContain('data-part="rtl">ޕްރެކްޓިސް ޕާލިމެންޓް ފޮރ ޔޫތު (ޕީ.ޕީ.ވައި)</span>')
    expect(html.indexOf('data-part="ltr"')).toBeLessThan(html.indexOf('data-part="rtl"'))
  })

  it('keeps text with an embedded run whole, and does not split without `split`', () => {
    expect(renderToStaticMarkup(<FormText text="PPY ގެ ބައިވެރިން ކޮބާ؟" split />)).not.toContain('bilingual')
    expect(renderToStaticMarkup(<FormText text="Full name: ފުރިހަމަ ނަން" />)).not.toContain('bilingual')
  })

  it('isolates a bracketed English run inside Dhivehi with its brackets', () => {
    expect(renderToStaticMarkup(<FormText text="ބައިވެރިވުމަށް (PPY) ފޯމު ފުރުއްވާ." />)).toBe(
      'ބައިވެރިވުމަށް <span lang="en" dir="ltr">(PPY)</span> ފޯމު ފުރުއްވާ.',
    )
  })
})
