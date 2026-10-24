/**
 * "Audit details" (APPROVALS-SCREENS 3.3): the hashes the respondent's PDF no longer prints,
 * kept in the studio. Signature IP, device and stroke hash stay with each signature.
 */
import { ChevronDownIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { SubmissionDetail } from '@/lib/api'
import { shortHash } from '@/lib/format'

function Hash({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted-foreground">None yet</span>
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="font-mono">
          sha256 {shortHash(value)}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm font-mono break-all">{value}</TooltipContent>
    </Tooltip>
  )
}

export function AuditDetails({ d }: { d: SubmissionDetail }) {
  const rows: [string, string | null][] = [
    ['Content', d.contentHash],
    ['Form version', d.schemaHash],
    ['Activity log head', d.chainHead],
    ['Signed PDF', d.pdfSha256],
  ]
  return (
    <Collapsible className="flex flex-col gap-2 border-t pt-4">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="group self-start px-0">
          Audit details
          <ChevronDownIcon className="transition-transform group-data-[state=open]:rotate-180 motion-reduce:transition-none" />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p className="pb-2 text-sm text-muted-foreground">
          Fingerprints of this submission. They are in the signed PDF's metadata, not printed on it.
        </p>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs">
          {rows.map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="min-w-0">
                <Hash value={value} />
              </dd>
            </div>
          ))}
        </dl>
      </CollapsibleContent>
    </Collapsible>
  )
}
