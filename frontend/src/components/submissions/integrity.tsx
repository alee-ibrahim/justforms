/** Integrity badge and signed-PDF button for the submission header (PHASE-3-SCREENS 1). */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckIcon, FileDownIcon, XIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { Spinner } from '@/components/ui/spinner'
import { api, type Integrity, type SubmissionDetail } from '@/lib/api'

export function IntegrityBadge({ result }: { result: Integrity }) {
  return (
    <HoverCard openDelay={200}>
      <HoverCardTrigger asChild>
        <Badge variant={result.ok ? 'outline' : 'destructive'} tabIndex={0}>
          {result.ok ? <CheckIcon data-icon="inline-start" /> : <XIcon data-icon="inline-start" />}
          {result.ok ? 'Integrity verified' : 'Integrity check failed'}
        </Badge>
      </HoverCardTrigger>
      <HoverCardContent className="text-sm">
        {result.ok
          ? 'The answers, files and signatures match the fingerprint taken when this was submitted, and the activity log is unbroken.'
          : 'Something changed this submission outside JustForms after it was submitted. Download the PDF and contact your administrator.'}
      </HoverCardContent>
    </HoverCard>
  )
}

export function PdfButton({ d }: { d: SubmissionDetail }) {
  const queryClient = useQueryClient()
  const asked = useRef(false)
  const create = useMutation({
    mutationFn: () => api.requestPdf(d.id),
    onSuccess: (res) => {
      asked.current = true
      queryClient.setQueryData<SubmissionDetail>(['submission', d.id], (old) => (old ? { ...old, pdfStatus: res.pdfStatus } : old))
    },
    onError: () => toast.error("Couldn't start the PDF. Try again."),
  })
  const status = d.pdfStatus
  const url = `/api/v1/submissions/${d.id}/pdf`
  const previous = useRef(status)
  useEffect(() => {
    if (previous.current === 'pending' && status === 'ready' && asked.current)
      toast('PDF ready', { action: { label: 'Download', onClick: () => window.location.assign(url) } })
    previous.current = status
  }, [status, url])

  if (status === 'ready')
    return (
      <Button variant="outline" size="sm" asChild>
        <a href={url} download>
          <FileDownIcon />
          Download PDF
        </a>
      </Button>
    )
  if (status === 'pending')
    return (
      <Button variant="outline" size="sm" disabled>
        <Spinner />
        Preparing PDF
      </Button>
    )
  return (
    <span className="inline-flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={() => create.mutate()} disabled={create.isPending}>
        <FileDownIcon />
        {status === 'failed' ? 'Create PDF again' : 'Create PDF'}
      </Button>
      {status === 'failed' && <span className="text-sm text-muted-foreground">Couldn't create the PDF.</span>}
    </span>
  )
}
