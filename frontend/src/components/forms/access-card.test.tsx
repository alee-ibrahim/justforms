// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { AccessList } from '@/lib/api'
import { FORM_ROLE_DESCRIPTIONS, FORM_ROLE_LABELS } from '@/lib/labels'

import { AccessCard } from './access-card'
import { notifyBody } from './share-notify-lib'

function render(list: AccessList) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  client.setQueryData(['access', 'f1'], list)
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <AccessCard formId="f1" myEmail="owner@example.org" />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('form roles', () => {
  it('calls the viewer role "Submissions viewer" and says what it can do', () => {
    expect(FORM_ROLE_LABELS.viewer).toBe('Submissions viewer')
    expect(FORM_ROLE_DESCRIPTIONS.viewer).toBe("Can view and export submissions, can't edit the form.")
  })

  it('shows the label in the access list', () => {
    const html = render({
      entries: [
        { userId: 'u1', email: 'owner@example.org', displayName: 'Aminath Ali', role: 'owner', orgAdmin: false },
        { userId: 'u2', email: 'viewer@example.org', displayName: 'Ibrahim Naseer', role: 'viewer', orgAdmin: false },
      ],
      pending: [{ invitationId: 'i1', email: 'new@example.org', role: 'viewer', expired: false }],
      canManage: false,
      canInvite: false,
      orgName: 'Example',
      smtpEnabled: false,
    })
    expect(html).toContain('Submissions viewer')
    expect(html).not.toMatch(/>Viewer</)
  })
})

describe('notify by email', () => {
  const owner = { userId: 'u1', email: 'owner@example.org', displayName: 'Aminath Ali', role: 'owner' as const, orgAdmin: false }
  const base = { entries: [owner], pending: [], canManage: true, canInvite: false, orgName: 'Example' }

  it('is ticked by default with an optional message when email is set up', () => {
    const html = render({ ...base, smtpEnabled: true })
    expect(html).toContain('Notify by email')
    expect(html).toMatch(/id="access-notify"[^>]*aria-checked="true"|aria-checked="true"[^>]*id="access-notify"/)
    expect(html).toContain('Message (optional)')
    expect(html).toContain('maxLength="500"')
    expect(html).not.toContain('Email is not set up on this server.')
  })

  it('is turned off and explained when email is not set up', () => {
    const html = render({ ...base, smtpEnabled: false })
    expect(html).toContain('Email is not set up on this server.')
    expect(html).toMatch(/id="access-notify"[^>]*disabled=""|disabled=""[^>]*id="access-notify"/)
    expect(html).not.toContain('Message (optional)')
  })

  it('sends notify and a trimmed message only when it can email', () => {
    expect(notifyBody({ notify: true, message: '  Hi  ' }, true)).toEqual({ notify: true, message: 'Hi' })
    expect(notifyBody({ notify: true, message: '   ' }, true)).toEqual({ notify: true })
    expect(notifyBody({ notify: false, message: 'Hi' }, true)).toEqual({ notify: false })
    expect(notifyBody({ notify: true, message: 'Hi' }, false)).toEqual({ notify: false })
  })
})
