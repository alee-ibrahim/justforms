import { CheckIcon, CircleDashedIcon, CircleIcon, XIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { SubmissionStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

import { STATUS_LABELS } from './labels'

/** Icon and word on every status (never colour alone); In review wears the marker. */
export function SubmissionStatusBadge({ status }: { status: SubmissionStatus }) {
  const Icon = { new: CircleIcon, in_review: CircleDashedIcon, approved: CheckIcon, rejected: XIcon }[status]
  return (
    <Badge
      variant={status === 'new' ? 'default' : status === 'rejected' ? 'destructive' : 'outline'}
      className={cn(status === 'in_review' && 'border-transparent bg-accent text-accent-foreground')}
    >
      <Icon data-icon="inline-start" className={cn(status === 'new' && 'fill-current')} />
      {STATUS_LABELS[status]}
    </Badge>
  )
}
