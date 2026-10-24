import { ApiError, type WebhookEvent } from '@/lib/api'

export const EVENT_LABELS: Record<WebhookEvent | 'test', string> = {
  'submission.created': 'New response',
  'submission.status_changed': 'Status changed',
  'submission.comment_added': 'Comment added',
  'submission.pdf_ready': 'Signed PDF ready',
  'submission.approval_step': 'Approval step',
  test: 'Test event',
}

export const EVENTS = Object.keys(EVENT_LABELS).filter((e) => e !== 'test') as WebhookEvent[]

/** Copy for a refused webhook URL (server codes from app/notifications/ssrf.py). */
export function urlError(err: unknown): string {
  const code = err instanceof ApiError ? err.detail : null
  if (code === 'https_required') return 'Use an https:// address.'
  if (code === 'private_address') return 'This address points to a private network. Ask an administrator to allow it.'
  if (code === 'too_many_webhooks') return 'A form can have up to 10 webhooks. Delete one to add another.'
  if (code === 'invalid_url' || (err instanceof ApiError && err.status === 422))
    return 'Enter a full address like https://hooks.example.org/justforms'
  return "Couldn't save the webhook. Try again."
}
