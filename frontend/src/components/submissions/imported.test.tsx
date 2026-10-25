// @vitest-environment happy-dom
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { ImportedFile, SubmissionDetail } from '@/lib/api'
import type { Form } from '@/schema'

import { ActivityList } from './activity'
import { Answers } from './answers'
import { ImportedNote } from './viewer-parts'

const form = {
  schemaVersion: '1',
  settings: { title: 'Volunteers', language: 'en' },
  pages: [
    {
      id: 'p1',
      elements: [
        { kind: 'field', id: 'name', type: 'short_text', label: 'Name' },
        { kind: 'field', id: 'portfolio', type: 'file', label: 'Portfolio' },
        { kind: 'field', id: 'sign', type: 'signature', label: 'Signature' },
      ],
    },
  ],
} as Form

const file = (fieldId: string, name: string, mime: string, kind: 'file' | 'signature' = 'file'): ImportedFile => ({
  fieldId,
  index: 0,
  kind,
  name,
  mime,
  size: 3_100_000,
  url: `/api/v1/submissions/s1/imported-files/${fieldId}/0`,
})

const FILES = [
  file('portfolio', 'PROFILE-PORTFOLIO-a-very-long-file-name-that-would-not-fit-on-a-phone.pdf', 'application/pdf'),
  file('sign', 'signature.png', 'image/png', 'signature'),
  file('removed_question', 'old.png', 'image/png'),
]

const html = (node: React.ReactNode) => renderToStaticMarkup(<TooltipProvider>{node}</TooltipProvider>)

describe('imported submissions', () => {
  it('shows copied files and signatures with their questions, as tap targets', () => {
    const out = html(<Answers form={form} data={{ name: 'Ali' }} importedFiles={FILES} />)
    // The PDF card is one link that downloads; the long name wraps instead of overflowing.
    expect(out).toMatch(/<a[^>]*href="\/api\/v1\/submissions\/s1\/imported-files\/portfolio\/0"[^>]*download=/)
    expect(out).toContain('break-all')
    expect(out).toContain('3.0 MB')
    // Images open a larger preview: the whole card is a button.
    expect(out).toMatch(/<button[^>]*aria-haspopup="dialog"/)
    expect(out).toContain('/api/v1/submissions/s1/imported-files/sign/0?preview=1')
    expect(out).toContain('Imported')
    expect(out).toContain('Image from Jotform, not captured by JustForms')
    // Both file questions show their copies instead of "No answer".
    expect(out).not.toContain('No answer')
  })

  it('wraps long Jotform ids and gives the import time as a detail', () => {
    const d = {
      id: 's1',
      seq: 3,
      source: 'jotform_import',
      externalId: '6630574767918824915663057476791882491566305747679188',
      createdAt: '2026-10-25T10:23:00Z',
      submittedAt: '2026-08-20T17:51:00Z',
      schema: form,
      data: {},
      importedFiles: FILES,
      importedLinks: { portfolio: ['https://files.example.org/uploads/form/6630574767918824915/still-there.docx'] },
    } as unknown as SubmissionDetail
    const out = html(<ImportedNote d={d} />)
    expect(out).toMatch(/<p class="[^"]*break-all[^"]*">Jotform submission/)
    expect(out).toContain('Imported <span class="tabular-nums">25 Oct 2026')
    expect(out).not.toContain('Originally submitted')
    // Files of questions no longer on the form are listed here; the others are on the sheet.
    expect(out).toContain('removed_question: old.png')
    expect(out).not.toContain('signature.png')
    expect(out).toContain('Not copied yet, still on Jotform:')
    expect(out).toMatch(/<li class="[^"]*break-all/)
  })

  it('says an imported row was imported, not submitted, in the activity', () => {
    const out = html(
      <ActivityList
        events={[{ seq: 1, type: 'created', actorName: null, payload: { imported: true }, createdAt: '2026-10-25T10:23:00Z' }]}
      />,
    )
    expect(out).toContain('Imported from Jotform')
  })
})
