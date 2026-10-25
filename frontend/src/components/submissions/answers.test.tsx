// @vitest-environment happy-dom
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { SignatureInfo } from '@/lib/api'
import type { Form } from '@/schema'

import { Answers } from './answers'

const opts = (...values: string[]) => values.map((v) => ({ value: v, label: v[0].toUpperCase() + v.slice(1) }))

const form = (language: 'en' | 'dv' = 'en'): Form =>
  ({
    schemaVersion: '1',
    settings: { title: 'Application', language },
    pages: [
      {
        id: 'about',
        title: language === 'dv' ? 'ތަފްޞީލު' : 'About you',
        elements: [
          { kind: 'field', id: 'name', type: 'short_text', label: language === 'dv' ? 'ނަން' : 'Full name', width: 'half' },
          { kind: 'field', id: 'dob', type: 'date', label: 'Date of birth', width: 'half' },
          { kind: 'field', id: 'email', type: 'email', label: 'Email' },
          { kind: 'field', id: 'phone', type: 'phone', label: 'Phone' },
          { kind: 'field', id: 'nid', type: 'short_text', label: 'National ID', sensitive: true },
          { kind: 'field', id: 'track', type: 'single_choice', label: 'Track', options: opts('tech', 'arts'), allowOther: true },
          { kind: 'field', id: 'topics', type: 'multi_choice', label: 'Topics', options: opts('coding', 'design', 'law') },
          { kind: 'field', id: 'minor', type: 'yes_no', label: 'Under 18?' },
          { kind: 'field', id: 'guardian', type: 'short_text', label: 'Guardian', visibleIf: { field: 'minor', op: 'eq', value: true } },
          { kind: 'field', id: 'campaign', type: 'hidden', label: 'Campaign' },
          {
            kind: 'section',
            id: 'address',
            title: 'Where you live',
            elements: [{ kind: 'field', id: 'island', type: 'short_text', label: 'Island' }],
          },
        ],
      },
      {
        id: 'more',
        title: 'More',
        elements: [
          { kind: 'field', id: 'why', type: 'long_text', label: 'Why' },
          { kind: 'field', id: 'confidence', type: 'rating', label: 'Confidence', max: 5 },
          { kind: 'field', id: 'years', type: 'number', label: 'Years' },
          { kind: 'field', id: 'at', type: 'time', label: 'Time' },
          {
            kind: 'repeater',
            id: 'refs',
            label: 'References',
            addLabel: 'Add reference',
            elements: [{ kind: 'field', id: 'ref_name', type: 'short_text', label: 'Name' }],
          },
          { kind: 'field', id: 'docs', type: 'file', label: 'Documents' },
          { kind: 'field', id: 'sign', type: 'signature', label: 'Signature', attestation: 'It is true.' },
        ],
      },
    ],
  }) as Form

const SIG: SignatureInfo = {
  id: 'sig-1',
  fieldId: 'sign',
  signedAt: '2026-10-25T08:00:00Z',
  receivedAt: '2026-10-25T08:00:05Z',
  ip: '203.0.113.7',
  userAgent: 'Test browser',
  attestation: 'It is true.',
  strokesSha256: 'a'.repeat(64),
  imageUrl: '/api/v1/signatures/sig-1/image',
}

const DATA = {
  name: 'Aminath Ali',
  dob: '2004-02-03',
  email: 'a@example.org',
  phone: '+9607771234',
  nid: '••••567',
  track: 'Marine biology',
  topics: ['design', 'coding'],
  minor: false,
  campaign: 'spring',
  island: 'Example Island',
  why: 'First line\nSecond line',
  confidence: 4,
  years: 3,
  at: '15:30',
  refs: [{ ref_name: 'Ibrahim' }, { ref_name: 'Mariyam' }],
  docs: [
    { fileId: 'f1', name: 'id-front.png', size: 2048, mime: 'image/png' },
    { fileId: 'f2', name: 'cv.pdf', size: 5_000_000, mime: 'application/pdf' },
  ],
  sign: 'sig-1',
}

const render = (props: Partial<Parameters<typeof Answers>[0]> & { language?: 'en' | 'dv' } = {}) => {
  const { language, ...rest } = props
  return renderToStaticMarkup(
    <TooltipProvider>
      <Answers form={form(language)} data={DATA} signatures={[SIG]} {...rest} />
    </TooltipProvider>,
  )
}

describe('Answers (form view)', () => {
  it('stacks every page with its title and keeps sections and half-width pairs', () => {
    const html = render()
    expect(html).toContain('About you')
    expect(html).toContain('More')
    expect(html).toContain('Where you live')
    // Half-width questions pair on the sheet's grid, full-width ones span it.
    expect(html).toMatch(/@min-\[32rem\]:col-span-1"><dl[^>]*data-question="name"/)
    expect(html).toMatch(/@min-\[32rem\]:col-span-2"><dl[^>]*data-question="email"/)
  })

  it('formats each answer type', () => {
    const html = render()
    expect(html).toContain('3 Feb 2004')
    expect(html).toContain('href="mailto:a@example.org"')
    expect(html).toContain('+960 777 1234')
    expect(html).toContain('href="tel:+9607771234"')
    // Chosen options as chips in the form's order, then a typed "Other" answer.
    expect(html.indexOf('>Coding<')).toBeLessThan(html.indexOf('>Design<'))
    expect(html).not.toContain('>Law<')
    expect(html).toContain('Other:')
    expect(html).toContain('Marine biology')
    expect(html).toContain('>No<')
    expect(html).toContain('First line\nSecond line')
    expect(html).toContain('whitespace-pre-wrap')
    expect(html).toContain('4 out of 5')
    expect(html).toContain('15:30')
    expect(html).toContain('Reference 1')
    expect(html).toContain('Reference 2')
    expect(html).toContain('id-front.png')
    expect(html).toContain('/api/v1/files/f1?preview=1')
    expect(html).toContain('href="/api/v1/files/f2" download="cv.pdf"')
    expect(html).toContain('4.8 MB')
    expect(html).toContain('src="/api/v1/signatures/sig-1/image"')
    expect(html).toContain('It is true.')
  })

  it('masks sensitive answers, with Show only for people who may reveal them', () => {
    expect(render()).toContain('••••567')
    expect(render()).toContain('Sensitive')
    expect(render()).not.toContain('>Show<')
    expect(render({ reveal: async () => 'A111567' })).toContain('>Show<')
  })

  it('leaves out hidden values and questions the logic skipped, unless asked', () => {
    const html = render()
    expect(html).not.toContain('spring')
    expect(html).not.toContain('Guardian')
    const shown = render({ showSkipped: true })
    expect(shown).toContain('Guardian')
    expect(shown).toContain('Skipped (not shown to the respondent)')
  })

  it('renders a Dhivehi form with Thaana labels and Latin data isolated left to right', () => {
    const html = render({ language: 'dv' })
    expect(html).toContain('ނަން')
    expect(html).toContain('ތަފްޞީލު')
    expect(html).toMatch(/<bdi dir="ltr">\+960 777 1234<\/bdi>/)
    expect(html).toMatch(/<bdi dir="ltr">3 Feb 2004<\/bdi>/)
    // System words stay English runs inside the RTL sheet.
    expect(html).toMatch(/<bdi dir="ltr" lang="en">No<\/bdi>/)
    expect(html).toMatch(/<bdi dir="ltr" lang="en">Other:<\/bdi>/)
  })
})
