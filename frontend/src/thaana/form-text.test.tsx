import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { FormText } from './form-text'
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
