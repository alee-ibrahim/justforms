// @vitest-environment happy-dom
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { Form } from '@/schema'

import { Answers } from './answers'

const form: Form = {
  schemaVersion: '1',
  settings: { title: 'T', language: 'en' },
  pages: [
    {
      id: 'page_1',
      elements: [
        { kind: 'field', id: 'has_guardian', type: 'yes_no', label: 'Guardian?' },
        { kind: 'field', id: 'guardian', type: 'short_text', label: 'Guardian name', visibleIf: { field: 'has_guardian', op: 'eq', value: true } },
        { kind: 'field', id: 'notes', type: 'short_text', label: 'Notes' },
      ],
    },
  ],
} as Form

const render = (data: Record<string, unknown>) =>
  renderToStaticMarkup(
    <TooltipProvider>
      <Answers form={form} data={data} />
    </TooltipProvider>,
  )

describe('Answers', () => {
  it('says a question hidden by logic was skipped, not unanswered', () => {
    const html = render({ has_guardian: false })
    expect(html).toContain('Skipped (not shown to the respondent)')
    // "Notes" was shown and left empty.
    expect(html).toContain('No answer')
  })

  it('shows "No answer" when the question was shown', () => {
    const html = render({ has_guardian: true })
    expect(html).not.toContain('Skipped')
  })
})
