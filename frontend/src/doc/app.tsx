import { lazy, Suspense } from 'react'

import { Page } from './page'
import { VerifyPage } from './verify'

const ApproverPage = lazy(() => import('./approver').then((m) => ({ default: m.ApproverPage })))

/** `/v/{token}` (verify) or `/a/{token}` (approver). */
function route(): { kind: 'verify' | 'approve'; token: string } {
  const [kind, token = ''] = window.location.pathname.split('/').filter(Boolean)
  return { kind: kind === 'a' ? 'approve' : 'verify', token: kind === 'a' || kind === 'v' ? token : '' }
}

export function DocApp() {
  const r = route()
  if (r.kind === 'approve')
    return (
      <Suspense fallback={<Page />}>
        <ApproverPage token={r.token} />
      </Suspense>
    )
  return <VerifyPage token={r.token} />
}
