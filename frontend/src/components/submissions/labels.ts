import type { SubmissionStatus } from '@/lib/api'

export const STATUS_LABELS: Record<SubmissionStatus, string> = {
  new: 'New',
  in_review: 'In review',
  approved: 'Approved',
  rejected: 'Rejected',
}
