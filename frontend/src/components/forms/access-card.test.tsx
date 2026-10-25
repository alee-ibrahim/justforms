// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { AccessList } from '@/lib/api'
import { FORM_ROLE_DESCRIPTIONS, FORM_ROLE_LABELS } from '@/lib/labels'

import { AccessCard } from './access-card'

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
    })
    expect(html).toContain('Submissions viewer')
    expect(html).not.toMatch(/>Viewer</)
  })
})
