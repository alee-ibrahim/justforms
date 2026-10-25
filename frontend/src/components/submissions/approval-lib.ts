/** Helpers for deciding approval steps in the studio (APPROVALS-SCREENS 3.4). */
import { ApiError, type AlreadyDecided, type ApprovalStepInfo, type SubmissionDetail } from '@/lib/api'
import { formatDateTime } from '@/lib/format'

/** The step staff can decide now: the current one, while it waits for its approver. */
export function decidableStep(d: SubmissionDetail): ApprovalStepInfo | null {
  const a = d.approval
  if (!d.canEdit || !a || a.state !== 'pending' || !a.step) return null
  const s = a.steps.find((x) => x.step === a.step)
  return s && (s.state === 'pending' || s.state === 'no_approver') ? s : null
}

/** "Already approved by Aminath Ali on 25 Oct 2026 10:14." from a 409, or null. */
export function alreadyDecidedMessage(err: unknown): string | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null
  const d = err.detail as Partial<AlreadyDecided> | string | undefined
  if (typeof d !== 'object' || !d) return 'This step was already decided.'
  if (d.state === 'stopped') return 'This approval was stopped.'
  const what = d.state === 'rejected' ? 'rejected' : d.state === 'approved' ? 'approved' : 'decided'
  const who = d.decidedName ? ` by ${d.decidedName}` : ''
  const via = d.decidedVia === 'email' ? ' through the emailed link' : d.decidedVia === 'studio' ? ' in the studio' : ''
  const when = d.decidedAt ? ` on ${formatDateTime(d.decidedAt)}` : ''
  return `Already ${what}${who}${via}${when}.`
}
