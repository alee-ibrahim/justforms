import { describe, expect, it } from 'vitest'

import { importOutcome, jotformTypeName } from './type-names'

describe('import type names', () => {
  it('names Jotform types in plain words', () => {
    expect(jotformTypeName('control_fullname')).toBe('Full name')
    expect(jotformTypeName('control_some_new_thing')).toBe('Some new thing')
  })

  it('says what each item became', () => {
    expect(importOutcome('control_fullname', 'section')).toBe('Full name became a section')
    expect(importOutcome('control_email', 'email')).toBe('Email became an email question')
    expect(importOutcome('control_radio', 'yes_no')).toBe('Single choice became a yes / no question')
    expect(importOutcome('control_head', 'form title')).toBe('Heading became the form title')
    expect(importOutcome('control_matrix', null)).toBe('Matrix wasn’t imported')
  })
})
