// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import { api, ApiError, type ApprovalDetail, type SubmissionDetail } from '@/lib/api'
import type { Form } from '@/schema'

import { ApprovalBlock, ApprovalDecision } from './approval-block'
import { alreadyDecidedMessage, decidableStep } from './approval-lib'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const schema = {
  schemaVersion: '1',
  settings: { title: 'Registration', language: 'en' },
  pages: [{ id: 'p1', elements: [{ kind: 'field', id: 'name', type: 'short_text', label: 'Name' }] }],
} as Form

const pending: ApprovalDetail = {
  state: 'pending',
  step: 1,
  total: 1,
  outcomeTo: 'applicant@example.org',
  steps: [
    {
      step: 1,
      name: 'Review',
      state: 'pending',
      source: 'fixed',
      fieldId: null,
      approverEmail: 'approver@example.org',
      requestedAt: '2026-10-25T08:00:00Z',
      decidedAt: null,
      decidedName: null,
      comment: null,
    },
  ],
}

function detail(over: Partial<SubmissionDetail> = {}): SubmissionDetail {
  return {
    id: 's1',
    formId: 'f1',
    seq: 7,
    status: 'in_review',
    language: 'en',
    version: 1,
    createdAt: '2026-10-25T08:00:00Z',
    submittedAt: '2026-10-25T08:00:00Z',
    respondentEmail: null,
    data: { name: 'Example Society' },
    approval: pending,
    schema,
    canEdit: true,
    canDelete: false,
    contentHash: null,
    pdfStatus: 'none',
    signatures: [],
    events: [],
    pdfSha256: null,
    schemaHash: null,
    chainHead: null,
    ...over,
  }
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})

async function render(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <TooltipProvider>{node}</TooltipProvider>
      </QueryClientProvider>,
    )
  })
}

const buttons = () => [...document.querySelectorAll('button')].map((b) => b.textContent?.trim())
const button = (text: string) => [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)!

describe('deciding an approval step in the studio', () => {
  it('shows Approve and Reject… to editors on the waiting step', async () => {
    await render(<ApprovalDecision d={detail()} />)
    expect(buttons()).toEqual(expect.arrayContaining(['Approve', 'Reject…']))
    expect(host.textContent).toContain('waiting for approver@example.org')
  })

  it('shows no decision buttons to viewers or once the approval is finished', async () => {
    expect(decidableStep(detail({ canEdit: false }))).toBeNull()
    await render(
      <>
        <ApprovalDecision d={detail({ canEdit: false })} />
        <ApprovalBlock d={detail({ canEdit: false })} />
      </>,
    )
    expect(buttons()).not.toContain('Approve')
    expect(buttons()).not.toContain('Reject…')

    const done = detail({
      status: 'approved',
      approval: {
        ...pending,
        state: 'approved',
        step: null,
        steps: [
          {
            ...pending.steps[0],
            state: 'approved',
            decidedAt: '2026-10-25T09:00:00Z',
            decidedName: 'Aminath Ali',
            decidedEmail: 'aminath@example.org',
            decidedVia: 'studio',
          },
        ],
      },
    })
    expect(decidableStep(done)).toBeNull()
    await render(<ApprovalBlock d={done} />)
    expect(buttons()).not.toContain('Approve')
    expect(host.textContent).toContain('Approved by Aminath Ali (aminath@example.org) in the studio')
  })

  it('needs a comment to reject', async () => {
    const decide = vi.spyOn(api, 'decideApproval').mockResolvedValue({ state: 'rejected', status: 'rejected', approval: null })
    await render(<ApprovalDecision d={detail()} />)
    await act(async () => button('Reject…').click())
    expect(document.body.textContent).toContain('Reject this response?')
    await act(async () => button('Reject').click())
    expect(document.body.textContent).toContain("Write why you're rejecting it")
    expect(decide).not.toHaveBeenCalled()

    const box = document.querySelector<HTMLTextAreaElement>('#decide-comment')!
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
      setter.call(box, 'Missing documents')
      box.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => button('Reject').click())
    expect(decide).toHaveBeenCalledWith('s1', { step: 1, decision: 'reject', comment: 'Missing documents' })
  })

  it('approves the step it shows, with no comment needed', async () => {
    const decide = vi.spyOn(api, 'decideApproval').mockResolvedValue({ state: 'approved', status: 'approved', approval: null })
    await render(<ApprovalDecision d={detail()} />)
    await act(async () => button('Approve').click())
    expect(document.body.textContent).toContain('This is the last step, so the response is Approved.')
    const confirm = [...document.querySelectorAll('[role="alertdialog"] button')].find((b) => b.textContent?.trim() === 'Approve')!
    await act(async () => (confirm as HTMLButtonElement).click())
    expect(decide).toHaveBeenCalledWith('s1', { step: 1, decision: 'approve', comment: '' })
  })

  it('says who decided first when someone else got there', () => {
    const err = new ApiError(409, {
      detail: { code: 'approval_done', state: 'approved', decidedName: 'Hassan', decidedAt: '2026-10-25T09:00:00Z', decidedVia: 'email' },
    })
    expect(alreadyDecidedMessage(err)).toMatch(/^Already approved by Hassan through the emailed link on /)
    expect(alreadyDecidedMessage(new ApiError(500, null))).toBeNull()
  })

  it('says a studio-only step waits for someone with edit access, with no approver link', async () => {
    const studio = detail({
      approval: {
        ...pending,
        steps: [{ ...pending.steps[0], source: 'editors', approverEmail: null, notifyTo: ['team@example.org'] }],
      },
    })
    expect(decidableStep(studio)?.step).toBe(1)
    await render(
      <>
        <ApprovalDecision d={studio} />
        <ApprovalBlock d={studio} />
      </>,
    )
    expect(host.textContent).toContain('Waiting for a decision by someone with edit access')
    expect(host.textContent).toContain('waiting for a decision by someone with edit access. You can decide it here.')
    expect(buttons()).toEqual(expect.arrayContaining(['Approve', 'Reject…', 'Send the notification again']))
    expect(buttons()).not.toContain('Send the email again')
    await act(async () => button('Reject…').click())
    expect(document.body.textContent).not.toContain('The emailed link')

    // Nobody to notify: no "send again".
    await render(
      <ApprovalBlock
        d={detail({ approval: { ...pending, steps: [{ ...pending.steps[0], source: 'editors', approverEmail: null, notifyTo: [] }] } })}
      />,
    )
    expect(buttons().some((b) => b?.startsWith('Send the'))).toBe(false)
  })
})
