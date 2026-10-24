/**
 * A signature in the submission detail (PHASE-3-SCREENS 1): the server-rendered image on
 * white paper (also in dark mode, so ink reads as ink), the statement shown to the signer,
 * and the audit data.
 */
import { Card, CardContent } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { SignatureInfo } from '@/lib/api'
import { formatDateTimeSeconds, shortHash } from '@/lib/format'
import type { FormLanguage } from '@/schema'
import { contentProps } from '@/schema/language'

export function SignatureBlock({ sig, language }: { sig: SignatureInfo; language: FormLanguage }) {
  const rows: [string, React.ReactNode][] = [
    ['Signed', sig.signedAt ? formatDateTimeSeconds(sig.signedAt) : 'Not reported'],
    ['Received', formatDateTimeSeconds(sig.receivedAt)],
    ['IP address', sig.ip ?? 'Not recorded'],
    [
      'Device',
      sig.userAgent ? (
        <Tooltip key="ua">
          <TooltipTrigger asChild>
            <span tabIndex={0} className="block truncate">
              {sig.userAgent}
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-sm break-all">{sig.userAgent}</TooltipContent>
        </Tooltip>
      ) : (
        'Not recorded'
      ),
    ],
    [
      'Strokes',
      <Tooltip key="h">
        <TooltipTrigger asChild>
          <span tabIndex={0} className="font-mono">
            sha256 {shortHash(sig.strokesSha256)}
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-sm font-mono break-all">{sig.strokesSha256}</TooltipContent>
      </Tooltip>,
    ],
  ]
  return (
    <figure className="flex max-w-md flex-col gap-2">
      <Card className="gap-0 overflow-hidden border-input bg-paper py-0">
        <CardContent className="relative p-0">
          <img src={sig.imageUrl} alt="Signature" className="block w-full" />
          <div className="pointer-events-none absolute inset-x-6 top-[70%] border-t border-paper-ink/25" />
        </CardContent>
      </Card>
      {sig.attestation && (
        <figcaption {...contentProps(language)} className="text-sm">
          {sig.attestation}
        </figcaption>
      )}
      <dl lang="en" dir="ltr" className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="min-w-0 tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </figure>
  )
}
