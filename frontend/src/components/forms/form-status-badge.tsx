import { ArchiveIcon, CircleDotIcon, CircleSlashIcon, PencilLineIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { FormStatus } from '@/lib/api'
import { FORM_STATUS_LABELS } from '@/lib/labels'

const ICONS = {
  draft: PencilLineIcon,
  live: CircleDotIcon,
  closed: CircleSlashIcon,
  archived: ArchiveIcon,
} as const

/** Status is never colour alone: every badge has an icon and a word. */
export function FormStatusBadge({ status }: { status: FormStatus }) {
  const Icon = ICONS[status]
  return (
    <Badge variant={status === 'live' ? 'default' : status === 'draft' ? 'secondary' : 'outline'}>
      <Icon data-icon="inline-start" />
      {FORM_STATUS_LABELS[status]}
    </Badge>
  )
}
